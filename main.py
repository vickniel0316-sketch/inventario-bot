import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# =========================
# CONFIG
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
def inv(m):
    bot.send_message(m.chat.id, "📦 Inventario", reply_markup=menu_inventario())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "movimientos")
def movs(m):
    bot.send_message(m.chat.id, "🔄 Movimientos", reply_markup=menu_movimientos())

@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "menu")
def volver(m):
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
                cajas = math.ceil(((5 * u) - s) / u)
                txt += f"🆕 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
                hay = True
            continue

        if c <= 0:
            continue

        critico = c * (t + 2)
        objetivo = c * 15

        if s <= critico:
            cajas = max(1, math.ceil((objetivo - s) / u))
            txt += f"📦 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
            hay = True

    bot.send_message(m.chat.id, txt if hay else "✅ Inventario saludable", parse_mode="Markdown", reply_markup=menu_inventario())

# =========================
# NUEVO (INICIO)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.send_message(m.chat.id, "📝 Nombre del producto:")

# =========================
# FLUJO COMPLETO (FIX)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado, content_types=['text'])
def flujos(m):

    if clean_text(m.text) == "menu":
        del estado[m.chat.id]
        bot.send_message(m.chat.id, "❌ Operación cancelada", reply_markup=menu_principal())
        return

    e = estado[m.chat.id]
    t = m.text
    paso = e["p"]

    pasos = [
        ("nombre","stock","🔢 Stock inicial:"),
        ("stock","nivel","🏢 Nivel:"),
        ("nivel","pasillo","🛤️ Pasillo:"),
        ("pasillo","lado","↔️ Lado (A/B):"),
        ("lado","sec","📍 Sección:"),
        ("sec","caja","📦 Unidades por caja:"),
        ("caja","tiempo","⏱️ Días de entrega:"),
        ("tiempo","correo","📧 Correo:")
    ]

    for act, sig, msg in pasos:
        if paso == act:
            e[act] = t if act not in ["stock","caja","tiempo"] else num(t)
            e["p"] = sig
            bot.send_message(m.chat.id, msg)
            return

    if paso == "correo":
        try:
            idx = len(stock.get_all_values()) + 1

            stock.append_row([
                e["nombre"],
                f'=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)',
                "N-"+str(e["nivel"]),
                "P-"+str(e["pasillo"]),
                e["lado"].upper(),
                e["sec"],
                t,
                0,0,
                e["tiempo"],
                e["caja"]
            ], value_input_option="USER_ENTERED")

            if e["stock"] > 0:
                mov.append_row([
                    datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                    e["nombre"].lower(),
                    "Carga Inicial",
                    e["stock"],
                    m.from_user.first_name
                ])

            bot.send_message(
                m.chat.id,
                f"✅ *PRODUCTO CREADO*\n\n📦 {e['nombre']}",
                parse_mode="Markdown",
                reply_markup=menu_principal()
            )

        except Exception as err:
            bot.send_message(m.chat.id, f"❌ Error: {err}")

        del estado[m.chat.id]

# =========================
# RUN
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
