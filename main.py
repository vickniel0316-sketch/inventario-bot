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
    ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
)

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# KEEP ALIVE (SERVIDOR)
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
# MOTOR DEL BOT Y SEGURIDAD
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    if x is None: return None
    try:
        x = str(x).replace(',', '.').replace(' ', '').strip()
        if x == '' or x.lower() == 'none': return None
        return float(x)
    except (ValueError, TypeError): 
        return None

# =========================
# BÚSQUEDA INTELIGENTE PRO (MEJORADA)
# =========================
indice = {}
data_cache = {}  # CACHÉ DE FILAS COMPLETAS
last_update = 0
CACHE_TTL = 60

def invalidar_indice():
    global last_update
    last_update = 0

def normalizar(texto):
    texto = str(texto).lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "acción": "accion"}
    for k, v in reemplazos.items(): texto = texto.replace(k, v)
    return texto

def tokenizar(texto):
    texto = normalizar(texto)
    palabras = texto.split()
    tokens = set()
    for p in palabras:
        tokens.add(p)
        if len(p) > 2: tokens.add(p[:3])
        if any(c.isdigit() for c in p): tokens.add(''.join(filter(str.isdigit, p)))
    return tokens

def construir_indice():
    global indice, last_update, data_cache
    try:
        data = stock.get_all_values()
        nuevo_indice = {}
        nuevo_cache = {}
        for i in range(1, len(data)):
            fila_num = i + 1
            fila_contenido = data[i]
            nuevo_cache[fila_num] = fila_contenido # Guardamos la fila entera
            nombre = fila_contenido[0]
            tokens = tokenizar(nombre)
            for t in tokens:
                if t not in nuevo_indice: nuevo_indice[t] = set()
                nuevo_indice[t].add(fila_num)
        indice = nuevo_indice
        data_cache = nuevo_cache
        last_update = time.time()
    except Exception as e:
        print(f"Error índice: {e}")

def obtener_indice():
    global last_update
    if time.time() - last_update > CACHE_TTL: construir_indice()
    return indice

def buscar_producto_inteligente(query):
    idx = obtener_indice()
    palabras = tokenizar(query)
    resultados = None
    for p in palabras:
        if p in idx:
            if resultados is None: resultados = idx[p].copy()
            else: resultados &= idx[p]
    if not resultados: return None
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
    with lock: estado[m.chat.id] = {"modo": "nuevo", "paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("ver "))
def cmd_ver(m):
    prod = m.text[4:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "ver"}
        msg = "🔍 Selecciona:\n"
        for i, f in enumerate(res):
            nombre = data_cache.get(f, ["???"])[0]
            msg += f"{i+1}. {nombre}\n"
        bot.reply_to(m, msg)
    else: mostrar_detalles(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("editar "))
def cmd_editar(m):
    prod = m.text[7:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "editar"}
        msg = "📝 Selecciona para editar:\n"
        for i, f in enumerate(res):
            nombre = data_cache.get(f, ["???"])[0]
            msg += f"{i+1}. {nombre}\n"
        bot.reply_to(m, msg)
    else: iniciar_edicion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("eliminar "))
def cmd_eliminar(m):
    prod = m.text[9:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "eliminar"}
        msg = "🗑️ Selecciona para ELIMINAR:\n"
        for i, f in enumerate(res):
            nombre = data_cache.get(f, ["???"])[0]
            msg += f"{i+1}. {nombre}\n"
        bot.reply_to(m, msg)
    else: ejecutar_eliminacion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "pedidos")
def cmd_pedidos(m):
    try:
        # Usar obtener_indice para asegurar que el caché esté fresco
        obtener_indice()
        if not data_cache: return
        
        # Obtenemos los headers de la primera fila del caché real si es posible, 
        # o asumimos el orden estándar para mayor velocidad.
        txt, hay = "📦 *PEDIDOS*\n\n", False
        for row in data_cache.values():
            if len(row) < 11: continue
            # Indices: Stock(1), Consumo(8), Tiempo(9), Unidades(10), Dias(7)
            s, c, t, u, d = [num(row[i]) or 0 for i in [1, 8, 9, 10, 7]]
            if (d <= 3 and s < 5) or (c > 0 and s <= (c*t + c*2)):
                cajas = math.ceil(((c*t + c*2 + c*5 if c>0 else 5) - s) / (u if u>0 else 1))
                txt += f"{'🚨' if (c>0 and s <= c*(t+1)) else '⚠️'} {row[0]} → {max(1, cajas)} cajas\n"
                hay = True
        bot.reply_to(m, txt if hay else "✅ Todo al día", parse_mode="Markdown")
    except Exception as e: 
        bot.reply_to(m, f"❌ Error en Pedidos: {e}")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def cmd_movimientos(m):
    try:
        p = m.text.split()
        if len(p) < 3:
            bot.reply_to(m, "❌ Formato: `[tipo] [producto] [cantidad]`")
            return
            
        tipo, cant_str, prod = p[0].lower(), p[-1], " ".join(p[1:-1]).strip()
        cant_val = num(cant_str)
        
        if cant_val is None: 
            bot.reply_to(m, "❌ Cantidad inválida.")
            return
            
        res = buscar_producto_inteligente(prod)
        if not res: bot.reply_to(m, "❌ No existe.")
        elif isinstance(res, list):
            with lock: opciones_temp[m.chat.id] = {"opciones": res, "tipo": tipo, "cantidad": cant_val}
            msg = "⚠️ Selecciona:\n"
            for i, f in enumerate(res):
                nombre = data_cache.get(f, ["???"])[0]
                msg += f"{i+1}. {nombre}\n"
            bot.reply_to(m, msg)
        else: ejecutar_mov(m, res, tipo, cant_val)
    except Exception as e: 
        bot.reply_to(m, "❌ Error en comando.")

# =========================
# LÓGICA DE APOYO
# =========================

def mostrar_detalles(m, fila):
    try:
        # MEJORA: Usar data_cache en lugar de llamar a Google Sheets
        f = data_cache.get(fila)
        if not f: 
            bot.reply_to(m, "❌ Error: Datos no encontrados en caché.")
            return
        msg = f"📦 *PRODUCTO:* {f[0].upper()}\n📊 *Stock:* {f[1]}\n📍 *Ub:* P{f[3]}|L{f[4]}|S{f[5]}|N{f[2]}\n📉 *Consumo:* {f[8] if len(f)>8 else '0'}"
        bot.reply_to(m, msg, parse_mode="Markdown")
    except: bot.reply_to(m, "❌ Error detalles.")

def iniciar_edicion(m, fila):
    try:
        # MEJORA: Usar data_cache
        nombre = data_cache.get(fila, ["???"])[0]
        with lock: 
            estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "menu"}
        
        msg = (f"🛠 *Editando:* {nombre}\n\n"
                "¿Qué deseas modificar?\n"
                "1. 📍 Ubicación completa (Nivel, Pasillo, Lado, Sección)\n"
                "2. 📧 Correo electrónico\n"
                "3. 🚚 Tiempo de entrega")
        bot.reply_to(m, msg, parse_mode="Markdown")
    except: 
        bot.reply_to(m, "❌ Error al iniciar edición.")

def ejecutar_mov(m, fila, tipo, cant):
    try:
        # MEJORA: Usar data_cache
        f_data = data_cache.get(fila)
        nombre = f_data[0]
        current = num(f_data[1]) or 0
        
        if tipo == "entrada":
            valor_final = abs(cant)
            etiqueta = "Entrada"
        elif tipo == "salida":
            valor_final = -abs(cant)
            etiqueta = "Salida"
        else:
            valor_final = cant - current
            etiqueta = "Ajuste"
        
        ahora = datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S")
        mov.append_row([ahora, nombre.lower(), etiqueta, float(valor_final), m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ {etiqueta} de *{nombre}* registrada ({valor_final}).")
        # Después de un movimiento, invalidamos para que el stock se actualice en la siguiente consulta
        invalidar_indice()
    except Exception as e: 
        bot.reply_to(m, f"❌ Error en registro: {e}")

def ejecutar_eliminacion(m, fila):
    try:
        stock.delete_rows(fila)
        invalidar_indice()
        bot.reply_to(m, "🗑️ Producto eliminado.")
    except: bot.reply_to(m, "❌ Error eliminar.")

# =========================
# MANEJADOR DE PASOS Y SELECCIONES
# =========================

@bot.message_handler(func=lambda m: ok(m) and (m.chat.id in estado or m.chat.id in opciones_temp))
def manejador_pasos(m):
    cid = m.chat.id
    
    if cid in opciones_temp and m.text.isdigit():
        data = opciones_temp[cid]
        idx = int(m.text) - 1
        if 0 <= idx < len(data["opciones"]):
            fila = data["opciones"][idx]
            modo = data.get("modo")
            with lock: opciones_temp.pop(cid, None)
            
            if modo == "editar": iniciar_edicion(m, fila)
            elif modo == "ver": mostrar_detalles(m, fila)
            elif modo == "eliminar": ejecutar_eliminacion(m, fila)
            else: ejecutar_mov(m, fila, data["tipo"], data["cantidad"])
            return

    if cid in estado:
        d = estado[cid]
        modo = d.get("modo")
        
        if modo == "editar":
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
                    bot.reply_to(m, "🚚 Nuevo Tiempo de entrega (días):")
                else:
                    bot.reply_to(m, "❌ Selecciona 1, 2 o 3.")
                return

            rutas = {
                "nivel": ("C", "pasillo", "➡️ Pasillo:"),
                "pasillo": ("D", "lado", "↔️ Lado:"),
                "lado": ("E", "seccion", "🔢 Sección:"),
                "seccion": ("F", "fin", "✅ Ubicación actualizada."),
                "solo_email": ("G", "fin", "✅ Correo actualizado."),
                "solo_tiempo": ("J", "fin", "✅ Tiempo de entrega actualizado.")
            }

            if p in rutas:
                col, sig, msg_ok = rutas[p]
                if p == "solo_tiempo" and num(m.text) is None:
                    bot.reply_to(m, "❌ Ingresa un número:"); return
                
                try:
                    stock.update_acell(f"{col}{d['fila']}", m.text.strip())
                    if sig == "fin":
                        with lock: estado.pop(cid, None)
                        invalidar_indice()
                        bot.reply_to(m, msg_ok)
                    else:
                        d["paso"] = sig
                        bot.reply_to(m, msg_ok)
                except Exception as e:
                    bot.reply_to(m, f"❌ Error API: {e}")

        elif modo == "nuevo":
            p = d["paso"]
            if p == "nombre": 
                d["n"], d["paso"] = m.text.strip(), "stock"
                bot.reply_to(m, "📦 Stock inicial:")
            elif p == "stock":
                val = num(m.text)
                if val is None: bot.reply_to(m, "❌ Stock inicial (número):"); return
                d["s"], d["paso"] = val, "nivel"; bot.reply_to(m, "📌 Nivel:")
            elif p == "nivel": d["ni"], d["paso"] = m.text.strip(), "pasillo"; bot.reply_to(m, "➡️ Pasillo:")
            elif p == "pasillo": d["pa"], d["paso"] = m.text.strip(), "lado"; bot.reply_to(m, "↔️ Lado:")
            elif p == "lado": d["la"], d["paso"] = m.text.strip(), "seccion"; bot.reply_to(m, "🔢 Sección:")
            elif p == "seccion": d["se"], d["paso"] = m.text.strip(), "t"; bot.reply_to(m, "🚚 Tiempo entrega:")
            elif p == "t":
                val = num(m.text)
                if val is None: bot.reply_to(m, "❌ Tiempo entrega (número):"); return
                d["t"], d["paso"] = val, "u"; bot.reply_to(m, "📦 Unidades/Caja:")
            elif p == "u":
                val = num(m.text)
                if val is None: bot.reply_to(m, "❌ Unidades por caja (número):"); return
                d["u"], d["paso"] = val, "e"; bot.reply_to(m, "📧 Email:")
            elif p == "e":
                try:
                    fila = len(stock.get_all_values()) + 1
                    f_st = f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)'
                    f_di = f'=SI.ERROR(MIN(6, HOY() - ENTERO(QUERY(Movimientos!A:D, "select A where B = \'" & A{fila} & "\' order by A asc limit 1", 0))), 0)'
                    f_co = f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D, Movimientos!B:B, MINUSC(A{fila}), Movimientos!C:C, "Salida")) / H{fila}, 0)'

                    stock.update(
                        values=[[d['n'], f_st, d['ni'], d['pa'], d['la'], d['se'], m.text.strip(), f_di, f_co, d['t'], d['u']]],
                        range_name=f"A{fila}:K{fila}",
                        value_input_option="USER_ENTERED"
                    )
                    
                    ahora = datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S")
                    mov.append_row([ahora, d['n'].lower(), "Entrada", float(abs(d['s'])), f"Sistema ({m.from_user.first_name})"], value_input_option="USER_ENTERED")
                    
                    with lock: estado.pop(cid, None)
                    invalidar_indice()
                    bot.reply_to(m, "✅ Producto creado y stock inicial registrado.")
                except Exception as ex:
                    bot.reply_to(m, f"❌ Error al crear: {ex}")

# =========================
# LANZAMIENTO
# =========================
bot.remove_webhook()
while True:
    try: bot.polling(none_stop=True)
    except: time.sleep(5)
