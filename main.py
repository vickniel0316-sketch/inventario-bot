import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, sys, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# VARIABLES
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

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
# WEB (RAILWAY)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print("🌐 Ping recibido")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def web():
    port = int(os.environ.get("PORT", 8080))
    print("🌐 Web corriendo en puerto", port)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

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
        s = num(f.get("Stock",0))
        c = num(f.get("Consumo_dia",0))
        t = num(f.get("Tiempo_entrega",0))
        u = num(f.get("Unidades_Caja",1))

        if c == 0 or u == 0: continue

        if s <= c*(t+2):
            cajas = math.ceil((c*15)/u)
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

        stock.append_row([
            e["nombre"],"",e["nivel"],e["pasillo"],e["lado"],e["sec"],
            "", "", "", "", e["tiempo"], e["caja"]
        ])

        if e["stock"]>0:
            mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M"),
                e["nombre"],"",e["stock"],m.from_user.first_name
            ])

        bot.reply_to(m,"✅ Creado")
        del estado[m.chat.id]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p=m.text.split()
    tipo=p[0]
    cant=num(p[-1])
    prod=" ".join(p[1:-1]).lower()

    data=stock.get_all_records()

    for f in data:
        if prod==f.get("Producto","").lower():
            mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M"),
                prod,"",
                cant if tipo=="entrada" else -cant,
                m.from_user.first_name
            ])
            bot.reply_to(m,"✅ OK")
            return

    bot.reply_to(m,"❌ No encontrado")

# =========================
# VER TODO
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and "ver todo" in m.text.lower())
def ver(m):
    prods=stock.col_values(1)
    st=stock.col_values(2)

    txt="📦\n"
    for i in range(1,len(prods)):
        txt+=f"{prods[i]} → {st[i]}\n"

    bot.reply_to(m,txt)

# =========================
# BUSCAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    b=m.text.replace("buscar","").strip().lower()
    data=stock.get_all_records()

    for f in data:
        if b in f.get("Producto","").lower():
            bot.reply_to(m,
                f"{f['Producto']}\nStock:{f.get('Stock')}\n{f.get('Nivel')} {f.get('Pasillo')} {f.get('Lado')} {f.get('Seccion')}")
            return

    bot.reply_to(m,"❌")

# =========================
# ELIMINAR
# =========================
elim={}

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    nombre=m.text.replace("eliminar","").strip().lower()
    data=stock.get_all_records()

    for i,f in enumerate(data):
        if nombre==f.get("Producto","").lower():
            elim[m.chat.id]=i+2
            bot.reply_to(m,"Escribe SI")
            return

@bot.message_handler(func=lambda m: m.chat.id in elim and ok(m))
def conf(m):
    if m.text.lower()=="si":
        stock.delete_rows(elim[m.chat.id])
        bot.reply_to(m,"🗑️")
    del elim[m.chat.id]

# =========================
# START (FIX RAILWAY)
# =========================
def start_bot():
    print("🚀 BOT LISTO")
    bot.remove_webhook()

    threading.Thread(target=auto, daemon=True).start()

    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(e)
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    web()
