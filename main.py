import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from telebot.types import ReplyKeyboardMarkup

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

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.getenv("PORT",8080))), Handler).serve_forever(),
    daemon=True
).start()

bot = telebot.TeleBot(TOKEN)

def ok(m): return m.from_user.id == CHAT_ID
def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0
def clean_text(t): return t.lower().strip()

estado = {}

# ================= MENUS =================
def menu_principal():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📦 Inventario","🔄 Movimientos")
    return kb

def menu_inventario():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📦 Pedidos","📋 Ver")
    kb.row("➕ Nuevo","✏️ Editar")
    kb.row("🗑️ Eliminar")
    kb.row("🔙 Menú")
    return kb

def menu_mov():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📥 Entrada","📤 Salida")
    kb.row("🔙 Menú")
    return kb

# ================= START =================
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id,"Sistema listo",reply_markup=menu_principal())

# ================= NAVEGACION =================
@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="inventario")
def inv(m): bot.send_message(m.chat.id,"Inventario",reply_markup=menu_inventario())

@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="movimientos")
def movs(m): bot.send_message(m.chat.id,"Movimientos",reply_markup=menu_mov())

@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="menu")
def menu(m):
    estado.pop(m.chat.id,None)
    bot.send_message(m.chat.id,"Menú principal",reply_markup=menu_principal())

# ================= PEDIDOS =================
@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="pedidos")
def pedidos(m):
    data = stock.get_all_records()
    txt="📦 *SUGERENCIA DE PEDIDOS*\n\n"; hay=False

    for f in data:
        s=num(f.get('Stock_Actual',0))
        c=num(f.get('Consumo_dia',0))
        t=num(f.get('Tiempo_entrega',0))
        u=num(f.get('Unidades_Caja',1))
        d=num(f.get('Dias',0))
        if u<=0: continue

        if d<3:
            if s<2*u:
                cajas=math.ceil((5*u - s)/u)
                txt+=f"🆕 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
                hay=True
            continue

        if c<=0: continue
        crit=c*(t+3)
        obj=c*15
        if s<=crit:
            cajas=max(1,math.ceil((obj-s)/u))
            txt+=f"📦 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
            hay=True

    bot.send_message(m.chat.id,txt if hay else "✅ Inventario saludable",parse_mode="Markdown",reply_markup=menu_inventario())

# ================= VER =================
@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="ver")
def ver(m):
    data=stock.get_all_records()
    txt="📋 *STOCK*\n\n"+"\n".join([f"{f['Producto']}: {f['Stock_Actual']}" for f in data])
    bot.send_message(m.chat.id,txt,parse_mode="Markdown")

# ================= NUEVO =================
@bot.message_handler(func=lambda m: ok(m) and clean_text(m.text)=="nuevo")
def nuevo(m):
    estado[m.chat.id]={"p":"nombre"}
    bot.send_message(m.chat.id,"Nombre del producto:")

# ================= FLUJOS =================
@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado)
def flujo(m):
    if clean_text(m.text)=="menu":
        estado.pop(m.chat.id,None)
        bot.send_message(m.chat.id,"Cancelado",reply_markup=menu_principal())
        return

    e=estado[m.chat.id]
    paso=e["p"]

    pasos=[
        ("nombre","stock"),
        ("stock","nivel"),
        ("nivel","pasillo"),
        ("pasillo","lado"),
        ("lado","sec"),
        ("sec","caja"),
        ("caja","tiempo"),
        ("tiempo","correo")
    ]

    for act,sig in pasos:
        if paso==act:
            e[act]=m.text if act not in ["stock","caja","tiempo"] else num(m.text)
            e["p"]=sig
            bot.send_message(m.chat.id,f"{sig}:")
            return

    if paso=="correo":
        try:
            stock.append_row([e["nombre"],e["stock"]])
            bot.send_message(m.chat.id,"✅ Producto creado",reply_markup=menu_principal())
        except Exception as err:
            bot.send_message(m.chat.id,f"Error {err}")
        estado.pop(m.chat.id)

# ================= RUN =================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
