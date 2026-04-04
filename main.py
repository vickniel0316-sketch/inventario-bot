import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# VARIABLES
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480
MI_EMAIL = "miemail@empresa.com"

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Faltan variables")

# =========================
# GOOGLE SHEETS
# =========================
creds_dict = json.loads(GOOGLE_CREDS)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
])

client = gspread.authorize(creds)
sheet = client.open("inventario_vickniel01")
stock = sheet.worksheet("Stock")
mov = sheet.worksheet("Movimientos")

print("✅ Sheets conectado")

bot = telebot.TeleBot(TOKEN)

# =========================
# WEB
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
# UTILS
# =========================
def ok(m): return m.from_user.id == CHAT_ID
def num(x):
    try: return float(x)
    except: return 0

# =========================
# NUEVO
# =========================
estado = {}

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="nuevo")
def nuevo(m):
    estado[m.chat.id]={"p":"nombre"}
    bot.reply_to(m,"Nombre:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo(m):
    e=estado[m.chat.id]
    t=m.text

    if e["p"]=="nombre":
        e["nombre"]=t
        e["p"]="stock"
        bot.reply_to(m,"Stock:")
        return

    if e["p"]=="stock":
        e["stock"]=num(t)
        e["p"]="nivel"
        bot.reply_to(m,"Nivel:")
        return

    if e["p"]=="nivel":
        e["nivel"]="N-"+t
        e["p"]="pasillo"
        bot.reply_to(m,"Pasillo:")
        return

    if e["p"]=="pasillo":
        e["pasillo"]="P-"+t
        e["p"]="lado"
        bot.reply_to(m,"Lado A/B:")
        return

    if e["p"]=="lado":
        e["lado"]=t.upper()
        e["p"]="sec"
        bot.reply_to(m,"Sección:")
        return

    if e["p"]=="sec":
        e["sec"]=t
        e["p"]="caja"
        bot.reply_to(m,"Unidades por caja:")
        return

    if e["p"]=="caja":
        e["caja"]=num(t)
        e["p"]="tiempo"
        bot.reply_to(m,"Tiempo entrega:")
        return

    if e["p"]=="tiempo":
        e["tiempo"]=num(t)
        e["p"]="correo"
        bot.reply_to(m,"Correo del responsable:")
        return

    if e["p"]=="correo":
        e["correo"]=t

        # ✅ fila correcta
        next_row = len(stock.get_all_values()) + 1

        fila = [
            e["nombre"],
            f'=SUMAR.SI(Movimientos!B:B, A{next_row}, Movimientos!D:D)',
            "", e["nivel"], e["pasillo"], e["lado"], e["sec"],
            e["correo"], "", "", "", "",
            f'''=SI.ERROR(
 ABS(SUMAR.SI.CONJUNTO(
   Movimientos!D:D,
   Movimientos!B:B,A{next_row},
   Movimientos!D:D,"<0"
 )) /
 MAX(1,
   MAX(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A)) -
   MIN(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A)) + 1
 ),
0)'''
        ]

        stock.append_row(fila, value_input_option="USER_ENTERED")

        if e["stock"]>0:
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")),
                e["nombre"],"",
                e["stock"],m.from_user.first_name
            ])

        bot.reply_to(m,"✅ Creado")
        del estado[m.chat.id]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p=m.text.split()
    tipo=p[0].strip().lower()
    cant=num(p[-1])
    prod=" ".join(p[1:-1]).lower()

    data=stock.get_all_records()

    for f in data:
        if prod==f.get("Producto","").lower():
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")),
                prod,"",
                cant if tipo=="entrada" else -cant,
                m.from_user.first_name
            ])
            bot.reply_to(m,"✅ OK")
            return

    bot.reply_to(m,"❌ No encontrado")

# =========================
# START
# =========================
print("🚀 BOT LISTO")
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(e)
        time.sleep(5)
