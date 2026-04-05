import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# =========================
# CONFIGURACIÓN
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds_dict = json.loads(GOOGLE_CREDS)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
])

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# SERVER
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

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

# 🔥 LIMPIADOR DE TEXTO (CLAVE)
def clean_text(t):
    return t.replace("📦","").replace("📋","").replace("➕","")\
            .replace("✏️","").replace("🗑️","")\
            .replace("📥","").replace("📤","")\
            .replace("🔄","").replace("🔙","")\
            .strip().lower()

estado = {}

# =========================
# MENÚS
# =========================
def menu_principal():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("📦 Inventario"))
    markup.row(KeyboardButton("🔄 Movimientos"))
    return markup

def menu_inventario():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("📦 Pedidos"), KeyboardButton("📋 Ver"))
    markup.row(KeyboardButton("➕ Nuevo"), KeyboardButton("✏️ Editar"))
    markup.row(KeyboardButton("🗑️ Eliminar"))
    markup.row(KeyboardButton("🔙 Menú"))
    return markup

def menu_movimientos():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("📥 Entrada"), KeyboardButton("📤 Salida"))
    markup.row(KeyboardButton("🔙 Menú"))
    return markup

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "👋 Sistema listo", reply_markup=menu_principal())

# =========================
# NAVEGACIÓN
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "inventario")
def abrir_inventario(m):
    bot.send_message(m.chat.id, "📦 Módulo Inventario", reply_markup=menu_inventario())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "movimientos")
def abrir_movimientos(m):
    bot.send_message(m.chat.id, "🔄 Módulo Movimientos", reply_markup=menu_movimientos())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "menu")
def volver_menu(m):
    if m.chat.id in estado:
        del estado[m.chat.id]
    bot.send_message(m.chat.id, "🏠 Menú principal", reply_markup=menu_principal())

# =========================
# PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "pedidos")
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

        if dias < 3:
            if s < (2 * u):
                objetivo = 5 * u
                cajas = math.ceil((objetivo - s) / u)

                if cajas > 0:
                    txt += f"🆕 *{f['Producto']}*\n"
                    txt += f"⚠️ Bajo stock: {int(s)}\n"
                    txt += f"🚚 Pedir: *{cajas} cajas*\n\n"
                    hay = True
            continue

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

    bot.send_message(m.chat.id, txt if hay else "✅ Inventario saludable", parse_mode="Markdown", reply_markup=menu_inventario())

# =========================
# RESTO (AHORA FUNCIONA CON BOTONES)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "ver")
def ver(m):
    data = stock.get_all_records()
    txt = "📋 *STOCK ACTUALIZADO*\n\n" + "\n".join([f"• *{f['Producto']}*: {f['Stock_Actual']}" for f in data])
    bot.send_message(m.chat.id, txt, parse_mode="Markdown", reply_markup=menu_inventario())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.send_message(m.chat.id, "📝 Nombre del producto:", reply_markup=menu_inventario())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "editar")
def editar(m):
    bot.send_message(m.chat.id, "✏️ Escribe: editar [producto]")

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith("eliminar"))
def eliminar(m):
    bot.send_message(m.chat.id, "🗑️ Escribe: eliminar [producto]")

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith("entrada"))
def entrada(m):
    bot.send_message(m.chat.id, "📥 Formato: entrada producto cantidad")

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith("salida"))
def salida(m):
    bot.send_message(m.chat.id, "📤 Formato: salida producto cantidad")

# =========================
# FLUJOS
# =========================
@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujos(m):
    if clean_text(m.text) == "menu":
        return
    # tu lógica original sigue aquí

# =========================
# RUN
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
