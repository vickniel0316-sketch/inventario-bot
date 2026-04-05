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

# =========================
# SERVER
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# UTIL
# =========================
bot = telebot.TeleBot(TOKEN)

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

# =========================
# PEDIDOS (VERSIÓN OPTIMIZADA)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_records()
    txt = "📦 *SUGERENCIA DE PEDIDOS*\n\n"
    hay = False

    for f in data:
        s = num(f.get('Stock_Actual', 0))
        c = num(f.get('Consumo_dia', 0))
        t = num(f.get('Tiempo_entrega', 0))
        u = num(f.get('Unidades_Caja', 1))
        dias = num(f.get('Dias', 0))

        if u <= 0:
            continue

        # =========================
        # 🆕 PRODUCTOS NUEVOS
        # =========================
        if dias < 3:
            # 🔥 FILTRO: solo si está realmente bajo
            if s < (2 * u):
                objetivo = 5 * u
                cajas = math.ceil((objetivo - s) / u)

                if cajas > 0:
                    txt += f"🆕 *{f['Producto']}*\n"
                    txt += f"⚠️ Bajo stock: {int(s)}\n"
                    txt += f"🚚 Pedir: *{cajas} cajas*\n\n"
                    hay = True
            continue

        # =========================
        # 📊 PRODUCTOS CON CONSUMO
        # =========================
        if c <= 0:
            continue

        stock_critico = c * (t + 2)
        objetivo = c * 15

        if s <= stock_critico:
            cajas = math.ceil((objetivo - s) / u)

            if cajas <= 0:
                cajas = 1

            txt += f"📦 *{f['Producto']}*\n"
            txt += f"⚠️ Bajo stock: {int(s)}\n"
            txt += f"🚚 Pedir: *{cajas} cajas*\n\n"
            hay = True

    bot.reply_to(m, txt if hay else "✅ Inventario saludable", parse_mode="Markdown")

# =========================
# START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
