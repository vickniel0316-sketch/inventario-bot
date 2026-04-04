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

# =========================
# BOT
# =========================
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
# PEDIDOS
# =========================
def calc_pedidos():
    data = stock.get_all_records()
    res = []

    for f in data:
        p = f.get("Producto","")
        s = num(f.get("Stock_Actual",0))
        c = num(f.get("Consumo_dia",0))
        t = num(f.get("Tiempo_entrega",0))
        u = num(f.get("Unidades_Caja",1))
        dias_historico = 7 if c>0 else 0

        if u == 0: continue

        stock_necesario = c * (t + 2)

        if dias_historico >= 3:
            if s <= stock_necesario:
                cajas = math.ceil(stock_necesario / u)
                res.append((p,s,c,t,cajas))
        else:
            if s <= 3 * u:
                cajas = math.ceil((3*c if c>0 else 3*u)/u)
                res.append((p,s,c,t,cajas))

    return res

def msg_pedidos(lista):
    if not lista: return "✅ Nada que pedir"
    txt = "📦 PEDIDOS:\n\n"
    for p,s,c,t,k in lista:
        txt += f"{p}\nStock:{s} Cons:{c} Ent:{t}\n👉 {k} cajas\n\n"
    return txt

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="pedidos")
def pedidos(m):
    bot.reply_to(m, msg_pedidos(calc_pedidos()))

def auto():
    ultimo=None
    while True:
        ahora = datetime.now(ZoneInfo("America/Santo_Domingo"))
        if ahora.hour==8 and ultimo!=ahora.date():
            try:
                bot.send_message(CHAT_ID, msg_pedidos(calc_pedidos()))
                print("✅ auto enviado")
            except Exception as e:
                print(e)
            ultimo=ahora.date()
        time.sleep(60)

threading.Thread(target=auto, daemon=True).start()

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
    e = estado[m.chat.id]
    t = m.text

    if e["p"] == "nombre":
        e["nombre"] = t
        e["p"] = "stock"
        bot.reply_to(m,"Stock:")
        return

    if e["p"] == "stock":
        e["stock"] = num(t)
        e["p"] = "nivel"
        bot.reply_to(m,"Nivel:")
        return

    if e["p"] == "nivel":
        e["nivel"] = "N-" + t
        e["p"] = "pasillo"
        bot.reply_to(m,"Pasillo:")
        return

    if e["p"] == "pasillo":
        e["pasillo"] = "P-" + t
        e["p"] = "lado"
        bot.reply_to(m,"Lado A/B:")
        return

    if e["p"] == "lado":
        e["lado"] = t.upper()
        e["p"] = "sec"
        bot.reply_to(m,"Sección:")
        return

    if e["p"] == "sec":
        e["sec"] = t
        e["p"] = "caja"
        bot.reply_to(m,"Unidades por caja:")
        return

    if e["p"] == "caja":
        e["caja"] = num(t)
        e["p"] = "tiempo"
        bot.reply_to(m,"Tiempo entrega:")
        return

    if e["p"] == "tiempo":
        e["tiempo"] = num(t)
        e["p"] = "correo"
        bot.reply_to(m,"Correo del responsable:")
        return

    if e["p"] == "correo":
        e["correo"] = t

        # ========================
        # BUSCAR PRIMERA FILA VACÍA EN COL A
        # ========================
        col_a = stock.col_values(1)
        next_row = len(col_a) + 1

        # INSERTAR DATOS MANUALES
        stock.update(f"A{next_row}", e["nombre"], value_input_option="USER_ENTERED")
        stock.update(f"C{next_row}", e["nivel"], value_input_option="USER_ENTERED")
        stock.update(f"D{next_row}", e["pasillo"], value_input_option="USER_ENTERED")
        stock.update(f"E{next_row}", e["lado"], value_input_option="USER_ENTERED")
        stock.update(f"F{next_row}", e["sec"], value_input_option="USER_ENTERED")
        stock.update(f"G{next_row}", e["correo"], value_input_option="USER_ENTERED")
        stock.update(f"J{next_row}", e["tiempo"], value_input_option="USER_ENTERED")
        stock.update(f"K{next_row}", e["caja"], value_input_option="USER_ENTERED")

        # FÓRMULA Stock_Actual (col B)
        stock.update(f"B{next_row}",
                     f'=SUMAR.SI(Movimientos!B:B, A{next_row}, Movimientos!D:D)',
                     value_input_option="USER_ENTERED")

        # FÓRMULA Consumo_dia (col I)
        stock.update(f"I{next_row}",
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
0)''', value_input_option="USER_ENTERED")

        # REGISTRAR STOCK INICIAL SI ES >0
        if e["stock"] > 0:
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")),
                e["nombre"], "",
                e["stock"], m.from_user.first_name
            ])

        bot.reply_to(m, "✅ Creado")
        del estado[m.chat.id]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p = m.text.split()
    tipo = p[0].strip().lower()
    cant = num(p[-1])
    prod = " ".join(p[1:-1]).lower()

    data = stock.get_all_records()
    for f in data:
        if prod == f.get("Producto","").lower():
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")),
                prod, "", cant if tipo=="entrada" else -cant, m.from_user.first_name
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
