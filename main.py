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
# VER
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "ver")
def ver(m):
    data = stock.get_all_records()
    txt = "📋 *STOCK ACTUALIZADO*\n\n" + "\n".join(
        [f"• *{f['Producto']}*: {f['Stock_Actual']}" for f in data]
    )
    bot.send_message(m.chat.id, txt, parse_mode="Markdown", reply_markup=menu_inventario())

# =========================
# ELIMINAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith("eliminar"))
def eliminar_producto(m):
    try:
        prod = clean_text(m.text).replace("eliminar", "").strip()
        celda = stock.find(prod)
        stock.delete_rows(celda.row)

        bot.send_message(m.chat.id, f"✅ Producto eliminado: {prod}", reply_markup=menu_inventario())
    except:
        bot.send_message(m.chat.id, "❌ No se encontró el producto.")

# =========================
# EDITAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith("editar"))
def editar_producto(m):
    prod = clean_text(m.text).replace("editar", "").strip()
    data = stock.get_all_records()
    p = next((f for f in data if f['Producto'].lower() == prod), None)

    if p:
        estado[m.chat.id] = {"p": "edit_opcion", "prod": prod}
        bot.send_message(
            m.chat.id,
            f"⚙️ Editando {p['Producto']}\n\n1. Ubicación\n2. Tiempo Entrega\n3. Unidades/Caja"
        )
    else:
        bot.send_message(m.chat.id, "❌ Producto no encontrado.")

# =========================
# ENTRADA / SALIDA
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text).startswith(("entrada","salida")))
def movimientos(m):
    try:
        partes = m.text.split()
        tipo = clean_text(partes[0])
        cant = num(partes[-1])
        prod = " ".join(partes[1:-1]).lower()

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod,
            tipo.capitalize(),
            cant if tipo == "entrada" else -abs(cant),
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")

        bot.send_message(
            m.chat.id,
            f"✅ {tipo.upper()} registrada\nProducto: {prod}\nCantidad: {cant}",
            reply_markup=menu_movimientos()
        )

    except:
        bot.send_message(m.chat.id, "❌ Error. Usa: entrada producto cantidad")

# =========================
# NUEVO + FLUJO
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and clean_text(m.text) == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.send_message(m.chat.id, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado, content_types=['text'])
def flujos(m):

    if clean_text(m.text) == "menu":
        del estado[m.chat.id]
        bot.send_message(m.chat.id, "❌ Cancelado", reply_markup=menu_principal())
        return

    # tu flujo original sigue aquí (no modificado)
