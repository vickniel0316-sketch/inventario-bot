import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN DE APIS
# =========================

TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS),
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# CONTADORES EN MEMORIA
# =========================

stock_rows = len(stock.col_values(1))
mov_rows = len(mov.col_values(1))

# =========================
# KEEP ALIVE (SERVIDOR)
# =========================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"VICKNIEL SYSTEM ONLINE")

def web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# MOTOR DEL BOT Y SEGURIDAD
# =========================

bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()
cache_lock = threading.Lock()

def ok(m):
    return (
        m.from_user.id == CHAT_ID and
        m.chat.id == CHAT_ID
    )

def num(x):
    if x is None: return None
    try:
        x = str(x).replace(',', '.').replace(' ', '').strip()
        if x == '' or x.lower() == 'none': return None
        return float(x)
    except (ValueError, TypeError):
        return None

# =========================
# BÚSQUEDA INTELIGENTE PRO
# =========================

indice, data_cache, last_update = {}, {}, 0
CACHE_TTL = 60

def invalidar_indice():
    global last_update
    last_update = 0

def normalizar(texto):
    texto = str(texto).lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}

    for k, v in reemplazos.items():
        texto = texto.replace(k, v)

    return texto

def tokenizar(texto):
    texto = normalizar(texto)
    palabras = texto.split()
    tokens = set()

    for p in palabras:
        tokens.add(p)

        if len(p) > 4:
            tokens.add(p[:4])

        if any(c.isdigit() for c in p):
            tokens.add(''.join(filter(str.isdigit, p)))

    return tokens

def construir_indice():
    global indice, last_update, data_cache

    try:
        data = stock.get_all_values()
        nuevo_indice, nuevo_cache = {}, {}

        for i in range(1, len(data)):
            fila_num = i + 1
            fila_contenido = data[i]

            if len(fila_contenido) >= 12 and str(fila_contenido[11]).lower() == "inactivo":
                continue

            nuevo_cache[fila_num] = fila_contenido
            tokens = tokenizar(fila_contenido[0])

            for t in tokens:
                if t not in nuevo_indice:
                    nuevo_indice[t] = set()

                nuevo_indice[t].add(fila_num)

        indice, data_cache, last_update = nuevo_indice, nuevo_cache, time.time()

    except Exception as e:
        print(f"Error índice: {e}")

def obtener_indice():
    with cache_lock:
        if time.time() - last_update > CACHE_TTL:
            construir_indice()

    return indice

def buscar_producto_inteligente(query):
    idx = obtener_indice()
    palabras = tokenizar(query)
    resultados = None

    for p in palabras:
        if p in idx:
            if resultados is None:
                resultados = idx[p].copy()
            else:
                resultados &= idx[p]

    if not resultados:
        return None

    resultados = list(resultados)

    return resultados[0] if len(resultados) == 1 else resultados[:5]

# =========================
# COMANDOS PRINCIPALES
# =========================

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "cancelar")
def cmd_cancelar(m):
    with lock:
        estado.pop(m.chat.id, None)
        opciones_temp.pop(m.chat.id, None)

    bot.reply_to(m, "❌ Operación cancelada.")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def cmd_nuevo(m):
    with lock:
        estado[m.chat.id] = {"modo": "nuevo", "paso": "nombre"}

    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("ver "))
def cmd_ver(m):
    res = buscar_producto_inteligente(m.text[4:].strip())

    if not res:
        bot.reply_to(m, "❌ No encontrado.")

    elif isinstance(res, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": res, "modo": "ver"}

        msg = "🔍 Selecciona:\n" + "\n".join([
            f"{i+1}. {data_cache.get(f, ['???'])[0]}"
            for i, f in enumerate(res)
        ])

        bot.reply_to(m, msg)

    else:
        mostrar_detalles(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("editar "))
def cmd_editar(m):
    res = buscar_producto_inteligente(m.text[7:].strip())

    if not res:
        bot.reply_to(m, "❌ No encontrado.")

    elif isinstance(res, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": res, "modo": "editar"}

        msg = "📝 Selecciona para editar:\n" + "\n".join([
            f"{i+1}. {data_cache.get(f, ['???'])[0]}"
            for i, f in enumerate(res)
        ])

        bot.reply_to(m, msg)

    else:
        iniciar_edicion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("eliminar "))
def cmd_eliminar(m):
    res = buscar_producto_inteligente(m.text[9:].strip())

    if not res:
        bot.reply_to(m, "❌ No encontrado.")

    elif isinstance(res, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": res, "modo": "eliminar"}

        msg = "🗑️ Selecciona para ELIMINAR:\n" + "\n".join([
            f"{i+1}. {data_cache.get(f, ['???'])[0]}"
            for i, f in enumerate(res)
        ])

        bot.reply_to(m, msg)

    else:
        with lock:
            opciones_temp[m.chat.id] = {"opciones": [res], "modo": "eliminar"}

        bot.reply_to(
            m,
            f"⚠️ Confirmar eliminar {data_cache.get(res, ['???'])[0]}? (Escribe 1)"
        )

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "pedidos")
def cmd_pedidos(m):
    try:
        obtener_indice()

        txt, hay = "📦 *PEDIDOS*\n\n", False

        for row in data_cache.values():

            if len(row) < 11:
                continue

            st = num(row[1]) or 0
            cons = num(row[8]) or 0
            t = num(row[9]) or 0
            u = num(row[10]) or 1
            dias = num(row[7]) or 0

            inc, cajas = False, 0

            if dias <= 3:
                if (st/u) < 5:
                    cajas, inc = math.ceil(5 - (st/u)), True

            elif cons > 0:
                reorden = (cons * t) + (cons * 2)

                if st <= reorden:
                    cajas = max(
                        1,
                        math.ceil(((reorden + cons*5) - st) / u)
                    )

                    inc = True

            if inc:
                txt += f"{'🚨' if dias <= 3 else '⚠️'} {row[0]} → {cajas} cajas\n"
                hay = True

        bot.reply_to(
            m,
            txt if hay else "✅ Todo al día",
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.reply_to(m, f"❌ Error en Pedidos: {e}")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def cmd_movimientos(m):
    try:
        p = m.text.split()

        if len(p) < 3:
            return

        tipo, cant, prod = p[0].lower(), num(p[-1]), " ".join(p[1:-1]).strip()

        if cant is None:
            bot.reply_to(m, "❌ Cantidad inválida.")
            return

        res = buscar_producto_inteligente(prod)

        if not res:
            bot.reply_to(m, "❌ No existe.")

        elif isinstance(res, list):
            with lock:
                opciones_temp[m.chat.id] = {
                    "opciones": res,
                    "tipo": tipo,
                    "cantidad": cant
                }

            msg = "⚠️ Selecciona:\n" + "\n".join([
                f"{i+1}. {data_cache.get(f, ['???'])[0]}"
                for i, f in enumerate(res)
            ])

            bot.reply_to(m, msg)

        else:
            ejecutar_mov(m, res, tipo, cant)

    except Exception as e:
        bot.reply_to(m, f"❌ Error en comando: {e}")

# =========================
# LÓGICA DE APOYO
# =========================

def mostrar_detalles(m, fila):
    try:
        f = data_cache.get(fila)

        msg = (
            f"📦 *PRODUCTO:* {f[0].upper()}\n"
            f"📊 *Stock:* {f[1]}\n"
            f"📍 *Ub:* P{f[3]}|L{f[4]}|S{f[5]}|N{f[2]}\n"
            f"📉 *Consumo:* {f[8]}"
        )

        bot.reply_to(m, msg, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(m, f"❌ Error detalles: {e}")

def iniciar_edicion(m, fila):
    nombre = data_cache.get(fila, ["???"])[0]

    with lock:
        estado[m.chat.id] = {
            "modo": "editar",
            "fila": fila,
            "paso": "menu"
        }

    bot.reply_to(
        m,
        f"🛠 *Editando:* {nombre}\n1. Ubicación\n2. Email\n3. Tiempo entrega"
    )

def ejecutar_mov(m, fila, tipo, cant):
    try:
        global mov_rows

        f_data = data_cache.get(fila)

        nombre = f_data[0]

        val = (
            abs(cant)
            if tipo == "entrada"
            else -abs(cant)
            if tipo == "salida"
            else cant - (num(f_data[1]) or 0)
        )

        ahora = datetime.now(
            ZoneInfo("America/Santo_Domingo")
        ).strftime("%Y-%m-%d %H:%M:%S")

        mov_rows += 1
        fila_mov = mov_rows

        mov.batch_update([{
            "range": f"A{fila_mov}:E{fila_mov}",
            "values": [[
                ahora,
                nombre.lower(),
                tipo.capitalize(),
                float(val),
                m.from_user.first_name
            ]]
        }], value_input_option="USER_ENTERED")

        bot.reply_to(
            m,
            f"✅ {tipo.capitalize()} de *{nombre}* registrada."
        )

        invalidar_indice()

    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

# =========================
# MANEJADOR DE PASOS
# =========================

@bot.message_handler(func=lambda m: ok(m))
def manejador_pasos(m):
    cid = m.chat.id

    if cid in opciones_temp and m.text.isdigit():
        data = opciones_temp.pop(cid)
        idx = int(m.text) - 1

        if 0 <= idx < len(data["opciones"]):
            fila = data["opciones"][idx]

            if data.get("modo") == "ver":
                mostrar_detalles(m, fila)

            elif data.get("modo") == "editar":
                iniciar_edicion(m, fila)

            elif data.get("modo") == "eliminar":
                stock.update_acell(f"L{fila}", "Inactivo")
                invalidar_indice()
                bot.reply_to(m, "🗑️ Producto marcado como inactivo.")

            else:
                ejecutar_mov(
                    m,
                    fila,
                    data["tipo"],
                    data["cantidad"]
                )

        return

    if cid in estado:
        d = estado[cid]

        if d["modo"] == "editar":
            p = d["paso"]

            if p == "menu":

                if m.text == "1":
                    d["paso"] = "nivel"
                    bot.reply_to(m, "📌 Nuevo Nivel:")

                elif m.text == "2":
                    d["paso"] = "solo_email"
                    bot.reply_to(m, "📧 Nuevo Correo:")

                elif m.text == "3":
                    d["paso"] = "solo_tiempo"
                    bot.reply_to(m, "🚚 Nuevo Tiempo:")

                return

            rutas = {
                "nivel": ("C", "pasillo", "➡️ Pasillo:"),
                "pasillo": ("D", "lado", "↔️ Lado:"),
                "lado": ("E", "seccion", "🔢 Sección:"),
                "seccion": ("F", "fin", "✅ Ubicación ok"),
                "solo_email": ("G", "fin", "✅ Correo ok"),
                "solo_tiempo": ("J", "fin", "✅ Tiempo ok")
            }

            if p in rutas:
                col, sig, msg = rutas[p]

                try:
                    stock.update_acell(
                        f"{col}{d['fila']}",
                        m.text.strip()
                    )

                    if sig == "fin":
                        estado.pop(cid)
                        invalidar_indice()
                        bot.reply_to(m, msg)

                    else:
                        d["paso"] = sig
                        bot.reply_to(m, msg)

                except Exception as e:
                    bot.reply_to(m, f"❌ Error API: {e}")

        elif d["modo"] == "nuevo":
            p = d["paso"]

            if p == "nombre":
                d["n"], d["paso"] = m.text.strip(), "stock"
                bot.reply_to(m, "📦 Stock:")

            elif p == "stock":
                val = num(m.text)

                if val is None:
                    bot.reply_to(m, "❌ Número requerido:")
                    return

                d["s"], d["paso"] = val, "nivel"
                bot.reply_to(m, "📌 Nivel:")

            elif p == "nivel":
                d["ni"], d["paso"] = m.text.strip(), "pasillo"
                bot.reply_to(m, "➡️ Pasillo:")

            elif p == "pasillo":
                d["pa"], d["paso"] = m.text.strip(), "lado"
                bot.reply_to(m, "↔️ Lado:")

            elif p == "lado":
                d["la"], d["paso"] = m.text.strip(), "seccion"
                bot.reply_to(m, "🔢 Sección:")

            elif p == "seccion":
                d["se"], d["paso"] = m.text.strip(), "t"
                bot.reply_to(m, "🚚 Tiempo:")

            elif p == "t":
                val = num(m.text)

                if val is None:
                    bot.reply_to(m, "❌ Número requerido:")
                    return

                d["t"], d["paso"] = val, "u"
                bot.reply_to(m, "📦 Unidades/Caja:")

            elif p == "u":
                val = num(m.text)

                if val is None:
                    bot.reply_to(m, "❌ Número requerido:")
                    return

                d["u"], d["paso"] = val, "e"
                bot.reply_to(m, "📧 Email:")

            elif p == "e":
                try:
                    global stock_rows, mov_rows

                    stock_rows += 1
                    fila = stock_rows

                    f_st = f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)'

                    f_di = (
                        f'=SI.ERROR(MIN(6, ENTERO(HOY()) - '
                        f'ENTERO(MIN(FILTER(Movimientos!A:A, '
                        f'Movimientos!B:B = A{fila})))), 0)'
                    )

                    f_co = (
                        f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO('
                        f'Movimientos!D:D, '
                        f'Movimientos!B:B, LOWER(A{fila}), '
                        f'Movimientos!C:C, "Salida")) / H{fila}, 0)'
                    )

                    stock.batch_update([{
                        "range": f"A{fila}:K{fila}",
                        "values": [[
                            d['n'],
                            f_st,
                            d['ni'],
                            d['pa'],
                            d['la'],
                            d['se'],
                            m.text.strip(),
                            f_di,
                            f_co,
                            d['t'],
                            d['u']
                        ]]
                    }], value_input_option="USER_ENTERED")

                    ahora = datetime.now(
                        ZoneInfo("America/Santo_Domingo")
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    mov_rows += 1
                    fila_mov = mov_rows

                    mov.batch_update([{
                        "range": f"A{fila_mov}:E{fila_mov}",
                        "values": [[
                            ahora,
                            d['n'].lower(),
                            "Entrada",
                            float(abs(d['s'])),
                            f"Sist ({m.from_user.first_name})"
                        ]]
                    }], value_input_option="USER_ENTERED")

                    estado.pop(cid)
                    invalidar_indice()

                    bot.reply_to(m, "✅ Creado.")

                except Exception as ex:
                    bot.reply_to(m, f"❌ Error: {ex}")

# =========================
# LANZAMIENTO
# =========================

bot.remove_webhook()

while True:
    try:
        bot.polling(
            none_stop=True,
            interval=1,
            timeout=60
        )

    except Exception as e:
        print(f"Polling error: {e}")
        time.sleep(10)
