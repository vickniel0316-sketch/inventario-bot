import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIG
# =========================
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

# =========================
# SERVER (KEEP-ALIVE)
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
# UTILIDADES
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

def buscar_fila(nombre_buscado):
    col_a = stock.col_values(1)
    for i, valor in enumerate(col_a):
        if valor.strip().lower() == nombre_buscado.strip().lower():
            return i + 1
    return None

# =========================
# PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
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

        if u <= 0: continue

        if dias < 3:
            if s < (2 * u):
                objetivo = 5 * u
                cajas = math.ceil((objetivo - s) / u)
                if cajas > 0:
                    txt += f"🆕 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
                    hay = True
            continue

        if c <= 0: continue

        stock_critico = c * (t + 2)
        objetivo = c * 15

        if s <= stock_critico:
            cajas = math.ceil((objetivo - s) / u)
            if cajas <= 0: cajas = 1
            txt += f"📦 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
            hay = True

    bot.reply_to(m, txt if hay else "✅ Inventario saludable", parse_mode="Markdown")

# =========================
# GESTIÓN
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    prod = m.text.lower().replace("eliminar", "").strip()
    fila = buscar_fila(prod)
    if fila:
        stock.delete_rows(fila)
        bot.reply_to(m, f"🗑️ *{prod}* eliminado correctamente.", parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ Producto no encontrado.")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("editar"))
def editar(m):
    prod = m.text.lower().replace("editar", "").strip()
    fila = buscar_fila(prod)
    if fila:
        estado[m.chat.id] = {"p": "edit_opcion", "prod": prod, "fila": fila}
        bot.reply_to(m, f"⚙️ *EDITAR: {prod.upper()}*\n\n1. Ubicación\n2. Tiempo Entrega\n3. Unidades/Caja\n\nResponde con el número.", parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ No encontrado.")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "ver")
def ver(m):
    data = stock.get_all_records()
    txt = "📋 *RESUMEN STOCK*\n\n" + "\n".join([f"• *{f['Producto']}*: {int(num(f['Stock_Actual']))}" for f in data])
    bot.reply_to(m, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    q = m.text.lower().replace("buscar", "").strip()
    encontrados = [f for f in stock.get_all_records() if q in str(f['Producto']).lower()]
    if encontrados:
        for i in encontrados:
            bot.reply_to(m, f"📦 *{i['Producto']}*\n🔢 Stock: {i['Stock_Actual']}\n📍 {i.get('Nivel','')} {i.get('Pasillo','')} {i.get('Lado','')} {i.get('Seccion','')}", parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ Sin resultados.")

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movimientos(m):
    try:
        p = m.text.split()
        tipo = p[0].lower()
        cant = num(p[-1])
        prod = " ".join(p[1:-1]).lower()
        fila = buscar_fila(prod)
        if not fila:
            bot.reply_to(m, f"❌ El producto '{prod}' no existe.")
            return
        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod,
            tipo.capitalize(),
            cant if tipo=="entrada" else -abs(cant),
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ {tipo.capitalize()} de {int(cant)} unidades registrada para *{prod}*.", parse_mode="Markdown")
    except:
        bot.reply_to(m, "❌ Formato: entrada [producto] [cantidad]")

# =========================
# FLUJOS (NUEVO PRODUCTO PASO A PASO CON FORMULAS H E I)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujos(m):
    e = estado[m.chat.id]
    t = m.text.strip()
    paso = e["p"]

    if paso == "nombre":
        e["nombre"] = t; e["p"] = "stock"; bot.reply_to(m, "📦 Stock inicial:"); return
    if paso == "stock":
        e["stock"] = num(t); e["p"] = "nivel"; bot.reply_to(m, "🏢 Nivel:"); return
    if paso == "nivel":
        e["nivel"] = t; e["p"] = "pasillo"; bot.reply_to(m, "🛤️ Pasillo:"); return
    if paso == "pasillo":
        e["pasillo"] = t; e["p"] = "lado"; bot.reply_to(m, "↔️ Lado:"); return
    if paso == "lado":
        e["lado"] = t; e["p"] = "seccion"; bot.reply_to(m, "📍 Sección:"); return
    if paso == "seccion":
        e["seccion"] = t; e["p"] = "email"; bot.reply_to(m, "📧 Email:"); return
    if paso == "email":
        e["email"] = t
        idx = len(stock.get_all_values()) + 1
        stock.update(f"A{idx}:G{idx}", [[
            e["nombre"], e["stock"], e["nivel"],
            e["pasillo"], e["lado"], e["seccion"], e["email"]
        ]])
        # 🔥 Fórmulas automáticas H e I
        stock.update_cell(idx, 8, f'=SI.ERROR(MIN(6, HOY() - QUERY(Movimientos!A:D, "select A where B = \'" & A{idx} & "\' order by A asc limit 1", 0)), 0)')
        stock.update_cell(idx, 9, f'=SI(H{idx}<3; 0; SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D; Movimientos!B:B; A{idx}; Movimientos!D:D; "<0")) / H{idx}; 0))')
        bot.reply_to(m, f"✅ Producto '{e['nombre']}' agregado con fórmulas en H e I.")
        del estado[m.chat.id]

# =========================
# START
# =========================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
