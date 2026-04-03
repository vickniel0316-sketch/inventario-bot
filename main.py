import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math

# =========================
# VARIABLES
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")

AUTHORIZED = {6249114480}

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
# CACHE
# =========================
cache_stock = []

def cargar_cache():
    global cache_stock
    try:
        cache_stock = stock.get_all_records()
        print("🔄 Cache actualizado")
    except Exception as e:
        print("❌ Error cache:", e)

def auto_cache():
    while True:
        cargar_cache()
        time.sleep(120)  # cada 2 min

cargar_cache()
threading.Thread(target=auto_cache, daemon=True).start()

# =========================
# UTILS
# =========================
def ok(m): return m.from_user.id in AUTHORIZED

def num(x):
    try: return float(x)
    except: return 0

# =========================
# PEDIDOS
# =========================
def calc_pedidos():
    res = []

    for f in cache_stock:
        p = f.get("Producto","")
        s = num(f.get("Stock",0))
        c = num(f.get("Consumo_dia",0))
        t = num(f.get("Tiempo_entrega",0))
        u = num(f.get("Unidades_Caja",1))

        if c == 0 or u == 0:
            continue

        if s <= c*(t+2):
            cajas = math.ceil((c*15)/u)
            res.append((p,s,c,t,cajas))

    return res

def msg_pedidos(lista):
    if not lista:
        return "✅ Nada que pedir"

    txt = "📦 PEDIDOS:\n\n"
    for p,s,c,t,k in lista:
        txt += f"{p}\nStock:{s} Cons:{c} Ent:{t}\n👉 {k} cajas\n\n"

    return txt

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="pedidos")
def pedidos(m):
    bot.reply_to(m, msg_pedidos(calc_pedidos()))

# =========================
# AUTO MENSAJE
# =========================
def auto():
    ultimo = None
    while True:
        ahora = datetime.now(ZoneInfo("America/Santo_Domingo"))

        if ahora.strftime("%H:%M") == "08:00" and ultimo != ahora.date():
            try:
                bot.send_message(list(AUTHORIZED)[0], msg_pedidos(calc_pedidos()))
                print("✅ auto enviado")
            except Exception as e:
                print(e)
            ultimo = ahora.date()

        time.sleep(30)

threading.Thread(target=auto, daemon=True).start()

# =========================
# NUEVO (con validación)
# =========================
estado = {}

def existe_producto(nombre):
    return any(nombre.lower() == f.get("Producto","").lower() for f in cache_stock)

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="nuevo")
def nuevo(m):
    estado[m.chat.id]={"p":"nombre"}
    bot.reply_to(m,"Nombre:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo(m):
    e=estado[m.chat.id]
    t=m.text.strip()

    if e["p"]=="nombre":
        if existe_producto(t):
            bot.reply_to(m,"❌ Ya existe")
            del estado[m.chat.id]
            return

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

        try:
            stock.append_row([
                e["nombre"],"",e["nivel"],e["pasillo"],e["lado"],e["sec"],
                "", "", "", "", e["tiempo"], e["caja"]
            ])
        except Exception as ex:
            bot.reply_to(m,"❌ Error guardando")
            print(ex)
            return

        bot.reply_to(m,"✅ Creado")
        cargar_cache()
        del estado[m.chat.id]

# =========================
# MOVIMIENTOS (robusto)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p = m.text.split()

    if len(p) < 3:
        bot.reply_to(m,"Formato: entrada producto cantidad")
        return

    tipo = p[0]
    cant = num(p[-1])
    prod = " ".join(p[1:-1]).strip().lower()

    existe = any(prod == f.get("Producto","").lower() for f in cache_stock)

    if not existe:
        bot.reply_to(m,"❌ No encontrado")
        return

    try:
        mov.append_row([
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            prod,"",
            cant if tipo=="entrada" else -cant,
            m.from_user.first_name
        ])
        bot.reply_to(m,"✅ OK")
    except Exception as e:
        bot.reply_to(m,"❌ Error")
        print(e)

# =========================
# VER TODO
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and "ver todo" in m.text.lower())
def ver(m):
    txt="📦\n"
    for f in cache_stock:
        txt += f"{f.get('Producto')} → {f.get('Stock')}\n"
    bot.reply_to(m,txt)

# =========================
# BUSCAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    b = m.text.replace("buscar","").strip().lower()

    for f in cache_stock:
        if b in f.get("Producto","").lower():
            bot.reply_to(m,
                f"{f['Producto']}\nStock:{f.get('Stock')}\n"
                f"{f.get('Nivel')} {f.get('Pasillo')} {f.get('Lado')} {f.get('Seccion')}")
            return

    bot.reply_to(m,"❌")

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
