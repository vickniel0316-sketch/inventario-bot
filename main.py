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

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

# =========================
# 🔥 BUSQUEDA INTELIGENTE (RESTAURADA ORIGINAL)
# =========================
indice = {}
productos_cache = []
last_update = 0
CACHE_TTL = 60

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
    global indice, productos_cache, last_update

    data = stock.get_all_values()
    productos_cache = data
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
            opciones = resultado[:5]
            opciones_temp[m.chat.id] = {"opciones": opciones, "tipo": tipo, "cantidad": cant}
            texto = "⚠️ Varias coincidencias:\n\n"
            for idx, f in enumerate(opciones, 1):
                nombre = stock.cell(f, 1).value
                texto += f"{idx}. {nombre}\n"
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
            valor,
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")

        bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod_real}*.", parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

# =========================
# (RESTO DEL CÓDIGO SIN CAMBIOS)
# =========================
# nuevo producto + editar + eliminar + pedidos
# permanecen EXACTAMENTE como ya estaban en tu última versión funcional

# =========================
# START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
