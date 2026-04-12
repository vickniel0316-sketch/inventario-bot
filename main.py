import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS),
    ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
)

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# KEEP ALIVE
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# BOT
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try:
        return float(str(x).replace(',', '.').strip())
    except:
        return 0

# =========================
# BUSQUEDA INTELIGENTE
# =========================
indice = {}
last_update = 0
CACHE_TTL = 60

def invalidar_indice():
    global last_update
    last_update = 0

def normalizar(texto):
    texto = str(texto).lower().strip()
    reemplazos = {
        "acción": "accion",
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"
    }
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    return texto

def tokenizar(texto):
    texto = normalizar(texto)
    palabras = texto.split()
    tokens = set()

    for p in palabras:
        tokens.add(p)
        tokens.add(p[:3])
        if any(c.isdigit() for c in p):
            tokens.add(''.join(filter(str.isdigit, p)))

    return tokens

def construir_indice():
    global indice, last_update
    data = stock.get_all_values()
    indice = {}

    for i in range(1, len(data)):
        nombre = data[i][0]
        tokens = tokenizar(nombre)

        for t in tokens:
            if t not in indice:
                indice[t] = set()
            indice[t].add(i + 1)

    last_update = time.time()

def obtener_indice():
    global last_update
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

    if len(resultados) == 1:
        return resultados[0]

    return resultados[:5]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def movimientos(m):
    try:
        p = m.text.split()
        tipo = p[0].lower()
        cant = num(p[-1])
        prod = " ".join(p[1:-1]).strip()

        resultado = buscar_producto_inteligente(prod)

        if resultado is None:
            bot.reply_to(m, f"❌ El producto '{prod}' no existe.")
            return

        if isinstance(resultado, list):
            with lock:
                opciones_temp[m.chat.id] = {"opciones": resultado[:5], "tipo": tipo, "cantidad": cant}

            texto = "⚠️ Varias coincidencias:\n\n"
            for i, f in enumerate(resultado[:5], 1):
                nombre = stock.cell(f, 1).value
                texto += f"{i}. {nombre}\n"
            texto += "\nResponde con el número."
            bot.reply_to(m, texto)
            return

        ejecutar_movimiento(m, resultado, tipo, cant)

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error")

def ejecutar_movimiento(m, fila, tipo, cant):
    prod_real = stock.cell(fila, 1).value

    if tipo == "entrada":
        valor = cant
        tipo_txt = "Entrada"
    elif tipo == "salida":
        valor = -abs(cant)
        tipo_txt = "Salida"
    elif tipo == "ajuste":
        stock_actual = num(stock.cell(fila, 2).value)
        valor = cant - stock_actual
        tipo_txt = "Ajuste"

    mov.append_row([
        datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
        prod_real.lower(),
        tipo_txt,
        float(valor),
        m.from_user.first_name
    ], value_input_option="RAW")

    invalidar_indice()
    bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod_real}*.", parse_mode="Markdown")

# =========================
# 📦 PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_values()

    if not data or len(data) < 2:
        bot.reply_to(m, "❌ No hay datos en Stock")
        return

    headers = data[0]

    def col(name):
        name = name.strip().lower()
        for i, h in enumerate(headers):
            if h.strip().lower() == name:
                return i
        return -1

    i_stock = col("Stock_Actual")
    i_cons = col("Consumo_dia")
    i_tiempo = col("Tiempo_entrega")
    i_caja = col("Unidades_Caja")
    i_dias = col("Dias")

    txt = "📦 *PEDIDOS*\n\n"
    hay = False

    for i in range(1, len(data)):
        row = data[i]

        def get(idx):
            if idx == -1 or idx >= len(row):
                return 0
            return num(row[idx])

        s = get(i_stock)
        c = get(i_cons)
        t = get(i_tiempo)
        u = get(i_caja)
        d = get(i_dias)

        producto = row[0]

        if u <= 0: u = 1
        if d <= 0: d = 999

        if d <= 3:
            if s < 5:
                cajas = math.ceil((5 - s) / u)
                txt += f"🆕 {producto} → {cajas} cajas\n"
                hay = True
            continue

        if c <= 0: continue

        punto = (c * t) + (c * 2)

        if s <= punto:
            objetivo = (c * t) + (c * 2) + (c * 5)
            cajas = math.ceil((objetivo - s) / u)
            if cajas < 1: cajas = 1
            estado_txt = "🚨 URGENTE" if s <= c * (t + 1) else "⚠️ PRONTO"
            txt += f"{estado_txt} {producto} → {cajas} cajas\n"
            hay = True

    bot.reply_to(m, txt if hay else "✅ Sin reposición", parse_mode="Markdown")

# =========================
# EDITAR PRODUCTO (NUEVO)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("editar "))
def editar(m):
    nombre = m.text.replace("editar", "").strip()
    resultado = buscar_producto_inteligente(nombre)

    if resultado is None:
        bot.reply_to(m, "❌ No encontrado")
        return

    if isinstance(resultado, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": resultado[:5], "modo": "editar"}
        
        texto = "📝 Selecciona producto para EDITAR:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            nombre_prod = stock.cell(f, 1).value
            texto += f"{i}. {nombre_prod}\n"
        bot.reply_to(m, texto)
        return

    # Si es uno solo, iniciar flujo
    with lock:
        estado[m.chat.id] = {"modo": "editar", "fila": resultado, "paso": "nivel"}
    bot.reply_to(m, f"🛠 Editando: *{stock.cell(resultado, 1).value}*\n📌 Ingrese nuevo Nivel:")

# =========================
# SELECCION MULTIUSO
# =========================
@bot.message_handler(func=lambda m: m.chat.id in opciones_temp and ok(m) and m.text.isdigit())
def seleccionar(m):
    try:
        data = opciones_temp[m.chat.id]
        idx = int(m.text.strip()) - 1

        if idx < 0 or idx >= len(data["opciones"]):
            bot.reply_to(m, "❌ Opción inválida")
            return

        fila = data["opciones"][idx]
        modo = data.get("modo")

        if modo == "editar":
            with lock:
                estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "nivel"}
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "📌 Ingrese nuevo Nivel:")
            return

        if modo == "eliminar":
            stock.delete_rows(fila)
            invalidar_indice()
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "🗑️ Eliminado")
            return

        # Es un movimiento (entrada/salida/ajuste)
        ejecutar_movimiento(m, fila, data["tipo"], data["cantidad"])
        del opciones_temp[m.chat.id]

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error selección")

# =========================
# FLUJOS (NUEVO Y EDITAR)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado)
def manejador_flujos(m):
    chat_id = m.chat.id
    data = estado.get(chat_id)
    modo = data.get("modo", "nuevo")

    if modo == "editar":
        flujo_editar_logica(m, chat_id, data)
    else:
        flujo_nuevo_logica(m, chat_id, data)

def flujo_editar_logica(m, chat_id, data):
    paso = data.get("paso")
    fila = data.get("fila")

    pasos = {
        "nivel": ("C", "pasillo", "➡️ Ingrese nuevo Pasillo:"),
        "pasillo": ("D", "lado", "↔️ Ingrese nuevo Lado:"),
        "lado": ("E", "seccion", "🔢 Ingrese nueva Sección:"),
        "seccion": ("F", "fin", "✅ Producto editado correctamente.")
    }

    if paso in pasos:
        col, siguiente, mensaje = pasos[paso]
        try:
            stock.update_acell(f"{col}{fila}", m.text.strip())
            if siguiente == "fin":
                bot.reply_to(m, mensaje)
                invalidar_indice()
                estado.pop(chat_id, None)
            else:
                data["paso"] = siguiente
                bot.reply_to(m, mensaje)
        except Exception as e:
            bot.reply_to(m, "❌ Error al editar.")
            estado.pop(chat_id, None)

def flujo_nuevo_logica(m, chat_id, data):
    paso = data.get("paso")

    if paso == "nombre":
        data["nombre"] = m.text.strip()
        data["paso"] = "stock"
        bot.reply_to(m, "📦 Stock inicial:")
    elif paso == "stock":
        data["stock"] = safe_num(m.text)
        data["paso"] = "nivel"
        bot.reply_to(m, "📌 Nivel:")
    elif paso == "nivel":
        data["nivel"] = m.text.strip()
        data["paso"] = "pasillo"
        bot.reply_to(m, "➡️ Pasillo:")
    elif paso == "pasillo":
        data["pasillo"] = m.text.strip()
        data["paso"] = "lado"
        bot.reply_to(m, "↔️ Lado:")
    elif paso == "lado":
        data["lado"] = m.text.strip()
        data["paso"] = "seccion"
        bot.reply_to(m, "🔢 Sección:")
    elif paso == "seccion":
        data["seccion"] = m.text.strip()
        data["paso"] = "tiempo_entrega"
        bot.reply_to(m, "🚚 Tiempo entrega:")
    elif paso == "tiempo_entrega":
        data["tiempo_entrega"] = safe_num(m.text)
        data["paso"] = "unidades_caja"
        bot.reply_to(m, "📦 Unidades por caja:")
    elif paso == "unidades_caja":
        data["unidades_caja"] = safe_num(m.text)
        data["paso"] = "email"
        bot.reply_to(m, "📧 Email:")
    elif paso == "email":
        data["email"] = m.text.strip()
        fila = len(stock.get_all_values()) + 1
        try:
            stock.update(f"A{fila}:K{fila}", [[
                data.get("nombre", ""),
                f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)',
                data.get("nivel", ""),
                data.get("pasillo", ""),
                data.get("lado", ""),
                data.get("seccion", ""),
                data.get("email", ""),
                f'=SI.ERROR(MIN(6, HOY() - MIN(FILTRAR(Movimientos!A:A, Movimientos!B:B = A{fila}))), 0)',
                f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D,Movimientos!B:B,A{fila},Movimientos!C:C,"Salida"))/H{fila},0)',
                data.get("tiempo_entrega", 0),
                data.get("unidades_caja", 0)
            ]], value_input_option="USER_ENTERED")
            invalidar_indice()
            estado.pop(chat_id, None)
            bot.reply_to(m, "✅ Producto creado correctamente")
        except Exception as e:
            bot.reply_to(m, f"❌ Error: {e}")

# =========================
# ELIMINAR
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("eliminar "))
def eliminar(m):
    nombre = m.text.replace("eliminar", "").strip()
    resultado = buscar_producto_inteligente(nombre)

    if resultado is None:
        bot.reply_to(m, "❌ No encontrado")
        return

    if isinstance(resultado, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": resultado[:5], "modo": "eliminar"}
        texto = "⚠️ Varias coincidencias:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            nombre = stock.cell(f, 1).value
            texto += f"{i}. {nombre}\n"
        bot.reply_to(m, texto + "\nResponde con el número.")
        return

    stock.delete_rows(resultado)
    invalidar_indice()
    bot.reply_to(m, "🗑️ Eliminado")

def safe_num(text):
    try: return float(text)
    except: return 0

# =========================
# START
# =========================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
