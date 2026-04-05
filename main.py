import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

if not TOKEN or not GOOGLE_CREDS:
    raise ValueError("Faltan variables de entorno")

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
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# UTILIDADES
# =========================
bot = telebot.TeleBot(TOKEN)
def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

estado = {}
estado_lock = Lock()

# CACHE
_cache = {"data": None, "time": 0}
def get_stock_data():
    if time.time() - _cache["time"] > 5:
        _cache["data"] = stock.get_all_records()
        _cache["time"] = time.time()
    return _cache["data"]

def normalize(t): return str(t).strip().lower()

def find_row_by_product(name):
    col = stock.col_values(1)
    for i, v in enumerate(col, start=1):
        if normalize(v) == normalize(name):
            return i
    return None

# =========================
# PEDIDOS (🔥 NUEVA LÓGICA)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = get_stock_data()
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

        # 🔥 MISMA LÓGICA QUE APPS SCRIPT
        if dias < 3:
            stock_critico = 2 * u
            stock_objetivo = 3 * u
        else:
            if c <= 0:
                continue
            stock_critico = c * (t + 2)
            stock_objetivo = c * 15

        if s <= stock_critico:
            faltante = max(0, stock_objetivo - s)
            cajas = math.ceil(faltante / u)

            if cajas <= 0:
                cajas = 1

            dias_rest = round(s / c, 1) if c > 0 else "N/A"

            txt += f"📦 *{f['Producto']}*\n"
            txt += f"Stock: {int(s)} | Sugerido: *{cajas} cajas*\n"
            txt += f"📍 {f.get('Nivel','')} {f.get('Pasillo','')} {f.get('Lado','')} {f.get('Seccion','')}\n"
            txt += f"⏱️ Días restantes: {dias_rest}\n\n"

            hay = True

    bot.reply_to(m, txt if hay else "✅ Inventario saludable", parse_mode="Markdown")

# =========================
# EDITAR / ELIMINAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    prod = m.text.replace("eliminar","").strip()
    row = find_row_by_product(prod)
    if row:
        stock.delete_rows(row)
        bot.reply_to(m, "✅ Eliminado")
    else:
        bot.reply_to(m, "❌ No encontrado")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("editar"))
def editar(m):
    prod = m.text.replace("editar","").strip()

    with estado_lock:
        estado[m.chat.id] = {"p":"edit_opcion","prod":prod}

    bot.reply_to(m,"1.Ubicación\n2.Tiempo\n3.Caja")

# =========================
# FLUJOS
# =========================
@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo(m):
    e = estado[m.chat.id]
    t = m.text

    if e["p"] == "edit_opcion":
        if t=="1": e["p"]="ubi"; bot.reply_to(m,"Nivel Pasillo Lado Sección")
        elif t=="2": e["p"]="tiempo"; bot.reply_to(m,"Nuevo tiempo")
        elif t=="3": e["p"]="caja"; bot.reply_to(m,"Nueva caja")
        else: bot.reply_to(m,"❌"); estado.pop(m.chat.id)
        return

    try:
        row = find_row_by_product(e["prod"])
        if not row:
            bot.reply_to(m,"❌ No encontrado")
            estado.pop(m.chat.id)
            return

        if e["p"]=="ubi":
            p = t.split()
            stock.update_cell(row,3,f"N-{p[0]}")
            stock.update_cell(row,4,f"P-{p[1]}")
            stock.update_cell(row,5,p[2].upper())
            stock.update_cell(row,6,p[3])
            bot.reply_to(m,"✅ Ubicación")

        elif e["p"]=="tiempo":
            stock.update_cell(row,10,num(t))
            bot.reply_to(m,"✅ Tiempo")

        elif e["p"]=="caja":
            stock.update_cell(row,11,num(t))
            bot.reply_to(m,"✅ Caja")

    except Exception as err:
        bot.reply_to(m,f"❌ {err}")

    estado.pop(m.chat.id)

# =========================
# OTROS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text=="ver")
def ver(m):
    data = get_stock_data()
    txt = "\n".join([f"{i['Producto']}: {i['Stock_Actual']}" for i in data[:20]])
    bot.reply_to(m,txt)

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.startswith(("entrada","salida")))
def movs(m):
    try:
        tipo,*rest = m.text.split()
        cant = num(rest[-1])
        prod = " ".join(rest[:-1])

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod.lower(),
            tipo.capitalize(),
            cant if tipo=="entrada" else -abs(cant),
            m.from_user.first_name
        ])

        bot.reply_to(m,"✅ Movimiento")
    except Exception as e:
        bot.reply_to(m,f"❌ {e}")

# =========================
# START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except:
        time.sleep(5)
