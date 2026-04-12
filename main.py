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

        fila = resultado
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

        bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod_real}*.", parse_mode="Markdown")

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error")

# =========================
# SELECCION MULTIUSO
# =========================
@bot.message_handler(func=lambda m: m.chat.id in opciones_temp and ok(m))
def seleccionar(m):
    try:
        data = opciones_temp[m.chat.id]
        idx = int(m.text.strip()) - 1

        if idx < 0 or idx >= len(data["opciones"]):
            bot.reply_to(m, "❌ Opción inválida")
            return

        fila = data["opciones"][idx]

        if data.get("modo") == "editar":
            with lock:
                estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "nivel"}
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "📌 Nivel:")
            return

        if data.get("modo") == "eliminar":
            stock.delete_rows(fila)
            invalidar_indice()
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "🗑️ Eliminado")
            return

        tipo = data["tipo"]
        cant = data["cantidad"]

        prod_real = stock.cell(fila, 1).value

        if tipo == "entrada":
            valor = cant
        elif tipo == "salida":
            valor = -abs(cant)
        elif tipo == "ajuste":
            stock_actual = num(stock.cell(fila, 2).value)
            valor = cant - stock_actual

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod_real.lower(),
            tipo,
            float(valor),
            m.from_user.first_name
        ], value_input_option="RAW")

        del opciones_temp[m.chat.id]
        bot.reply_to(m, "✅ Movimiento aplicado")

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error selección")

# =========================
# NUEVO PRODUCTO
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    with lock:
        estado[m.chat.id] = {"paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado)
def flujo_nuevo(m):
    chat_id = m.chat.id
    data = estado[chat_id]
    paso = data["paso"]

    if paso == "nombre":
        data["nombre"] = m.text
        data["paso"] = "stock"
        bot.reply_to(m, "📦 Stock inicial:")
        return

    if paso == "stock":
        data["stock"] = num(m.text)
        data["paso"] = "nivel"
        bot.reply_to(m, "📌 Nivel:")
        return

    if paso == "nivel":
        data["nivel"] = m.text
        data["paso"] = "pasillo"
        bot.reply_to(m, "➡️ Pasillo:")
        return

    if paso == "pasillo":
        data["pasillo"] = m.text
        data["paso"] = "lado"
        bot.reply_to(m, "↔️ Lado:")
        return

    if paso == "lado":
        data["lado"] = m.text
        data["paso"] = "seccion"
        bot.reply_to(m, "🔢 Sección:")
        return

    if paso == "seccion":
        data["seccion"] = m.text
        data["paso"] = "tiempo_entrega"
        bot.reply_to(m, "🚚 Tiempo entrega:")
        return

    if paso == "tiempo_entrega":
        data["tiempo_entrega"] = m.text
        data["paso"] = "unidades_caja"
        bot.reply_to(m, "📦 Unidades por caja:")
        return

    if paso == "unidades_caja":
        data["unidades_caja"] = m.text
        data["paso"] = "email"
        bot.reply_to(m, "📧 Email:")
        return

    if paso == "email":
        data["email"] = m.text
        fila = len(stock.get_all_values()) + 1

        stock.update(f"A{fila}:K{fila}", [[
            data["nombre"],
            float(data["stock"]),
            data["nivel"],
            data["pasillo"],
            data["lado"],
            data["seccion"],
            data["email"],
            0.0,
            0.0,
            float(num(data["tiempo_entrega"])),
            float(num(data["unidades_caja"]))
        ]], value_input_option="RAW")

        invalidar_indice()

        with lock:
            del estado[chat_id]

        bot.reply_to(m, "✅ Producto creado")

# =========================
# EDITAR
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

        texto = "⚠️ Varias coincidencias:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            nombre = stock.cell(f, 1).value
            texto += f"{i}. {nombre}\n"
        texto += "\nResponde con el número."
        bot.reply_to(m, texto)
        return

    with lock:
        estado[m.chat.id] = {"modo": "editar", "fila": resultado, "paso": "nivel"}

    bot.reply_to(m, "📌 Nivel:")

@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado and estado[m.chat.id].get("modo") == "editar")
def flujo_editar(m):
    d = estado[m.chat.id]
    fila = d["fila"]
    paso = d["paso"]

    if paso == "nivel":
        stock.update_acell(f"C{fila}", m.text)
        d["paso"] = "pasillo"
        bot.reply_to(m, "➡️ Pasillo:")
        return

    if paso == "pasillo":
        stock.update_acell(f"D{fila}", m.text)
        d["paso"] = "lado"
        bot.reply_to(m, "↔️ Lado:")
        return

    if paso == "lado":
        stock.update_acell(f"E{fila}", m.text)
        d["paso"] = "seccion"
        bot.reply_to(m, "🔢 Sección:")
        return

    if paso == "seccion":
        stock.update_acell(f"F{fila}", m.text)
        invalidar_indice()
        del estado[m.chat.id]
        bot.reply_to(m, "✅ Editado")

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
        texto += "\nResponde con el número."
        bot.reply_to(m, texto)
        return

    stock.delete_rows(resultado)
    invalidar_indice()

    bot.reply_to(m, "🗑️ Eliminado")

# =========================
# START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
