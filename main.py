import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock

# =========================
# 1. CONFIGURACIÓN
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

if not TOKEN or not GOOGLE_CREDS:
    raise ValueError("Faltan variables TOKEN o GOOGLE_CREDS")

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
# 2. KEEP ALIVE
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
# 3. UTILIDADES
# =========================
bot = telebot.TeleBot(TOKEN)
def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

estado = {}
estado_lock = Lock()

# 🔥 CACHE
_cache = {"data": None, "time": 0}
def get_stock_data():
    now = time.time()
    if now - _cache["time"] > 5:
        _cache["data"] = stock.get_all_records()
        _cache["time"] = now
    return _cache["data"]

# 🔥 BUSCAR FILA POR COLUMNA A
def find_row_by_product(name):
    name = name.strip().lower()
    col = stock.col_values(1)
    for i, val in enumerate(col, start=1):
        if str(val).strip().lower() == name:
            return i
    return None

# =========================
# 4. PEDIDOS
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

        if dias < 3:
            if s < (u * 2):
                txt += f"🆕 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *3 cajas*\n\n"
                hay = True
            continue

        punto = c * (t + 2)
        if s <= punto and c > 0:
            faltante = (punto + (c * 7)) - s
            cajas = math.ceil(faltante / u) if u > 0 else 0

            if cajas > 0:
                dias_rest = round(s/c, 1) if c > 0 else "N/A"
                txt += f"📈 *{f['Producto']}*\n📦 Stock: {int(s)} | *{cajas} cajas*\n⏱️ {dias_rest} días\n\n"
                hay = True

    bot.reply_to(m, txt if hay else "✅ *Inventario Saludable*", parse_mode="Markdown")

# =========================
# 5. EDITAR / ELIMINAR
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    prod = m.text.lower().replace("eliminar", "").strip()
    row = find_row_by_product(prod)

    if row:
        stock.delete_rows(row)
        bot.reply_to(m, f"✅ Eliminado: {prod}")
    else:
        bot.reply_to(m, "❌ No encontrado")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("editar"))
def editar(m):
    prod = m.text.lower().replace("editar", "").strip()
    data = get_stock_data()
    p = next((f for f in data if f['Producto'].strip().lower() == prod), None)

    if p:
        with estado_lock:
            estado[m.chat.id] = {"p": "edit_opcion", "prod": prod}

        bot.reply_to(m, "1. Ubicación\n2. Tiempo entrega\n3. Unidades/caja")
    else:
        bot.reply_to(m, "❌ Producto no encontrado")

# =========================
# 6. FLUJOS
# =========================
@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujos(m):
    e = estado[m.chat.id]
    t = m.text
    paso = e["p"]

    if paso == "edit_opcion":
        if t == "1": e["p"] = "edit_ubi"; bot.reply_to(m, "Nivel Pasillo Lado Sección")
        elif t == "2": e["p"] = "edit_tiempo"; bot.reply_to(m, "Nuevo tiempo:")
        elif t == "3": e["p"] = "edit_caja"; bot.reply_to(m, "Unidades por caja:")
        else:
            bot.reply_to(m, "❌ Opción inválida")
            del estado[m.chat.id]
        return

    if paso.startswith("edit_"):
        try:
            row = find_row_by_product(e["prod"])
            if not row:
                bot.reply_to(m, "❌ No encontrado")
                del estado[m.chat.id]
                return

            if paso == "edit_ubi":
                p = t.split()
                stock.update_cell(row, 3, f"N-{p[0]}")
                stock.update_cell(row, 4, f"P-{p[1]}")
                stock.update_cell(row, 5, p[2].upper())
                stock.update_cell(row, 6, p[3])
                bot.reply_to(m, "✅ Ubicación actualizada")

            elif paso == "edit_tiempo":
                stock.update_cell(row, 10, num(t))
                bot.reply_to(m, "✅ Tiempo actualizado")

            elif paso == "edit_caja":
                stock.update_cell(row, 11, num(t))
                bot.reply_to(m, "✅ Caja actualizada")

        except Exception as e:
            bot.reply_to(m, f"❌ Error: {e}")

        del estado[m.chat.id]
        return

# =========================
# 7. OTROS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "ver")
def ver(m):
    data = get_stock_data()
    txt = "\n".join([f"{f['Producto']}: {f['Stock_Actual']}" for f in data[:20]])
    bot.reply_to(m, txt)

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    q = m.text.lower().replace("buscar", "").strip()
    data = get_stock_data()
    res = [f for f in data if q in f['Producto'].lower()]

    if not res:
        bot.reply_to(m, "❌ No encontrado")
    else:
        for i in res:
            bot.reply_to(m, f"{i['Producto']} - {i['Stock_Actual']}")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    try:
        tipo, *rest = m.text.split()
        cant = num(rest[-1])
        prod = " ".join(rest[:-1]).lower()

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod,
            tipo.capitalize(),
            cant if tipo=="entrada" else -abs(cant),
            m.from_user.first_name
        ])

        bot.reply_to(m, "✅ Movimiento registrado")
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

# =========================
# 8. START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception:
        time.sleep(5)
