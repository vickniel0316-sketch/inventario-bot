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
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")

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
# PEDIDOS (TU VERSIÓN OPTIMIZADA)
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
# GESTIÓN (EDITAR / ELIMINAR / BUSCAR / VER)
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
# MOVIMIENTOS (ENTRADA / SALIDA)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movimientos(m):
    try:
        p = m.text.split(); tipo = p[0].lower(); cant = num(p[-1]); prod = " ".join(p[1:-1]).lower()
        fila = buscar_fila(prod)
        if not fila:
            bot.reply_to(m, f"❌ El producto '{prod}' no existe."); return
        
        mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), prod, tipo.capitalize(), cant if tipo=="entrada" else -abs(cant), m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ {tipo.capitalize()} de {int(cant)} unidades registrada para *{prod}*.", parse_mode="Markdown")
    except:
        bot.reply_to(m, "❌ Formato: `entrada [producto] [cantidad]`")

# =========================
# FLUJOS (NUEVO / EDITAR)
# =========================
@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujos(m):
    e = estado[m.chat.id]; t = m.text; paso = e["p"]

    # --- FLUJO EDITAR ---
    if paso == "edit_opcion":
        if t == "1": e["p"] = "edit_ubi"; bot.reply_to(m, "📍 Nueva Ubicación (Nivel Pasillo Lado Sección):")
        elif t == "2": e["p"] = "edit_tiempo"; bot.reply_to(m, "⏱️ Tiempo entrega (días):")
        elif t == "3": e["p"] = "edit_caja"; bot.reply_to(m, "📦 Unidades/Caja:")
        else: bot.reply_to(m, "❌ Inválido."); del estado[m.chat.id]
        return

    if paso.startswith("edit_"):
        try:
            if paso == "edit_ubi":
                p = t.split()
                if len(p) >= 4:
                    stock.update(f"C{e['fila']}:F{e['fila']}", [[f"N-{p[0]}", f"P-{p[1]}", p[2].upper(), p[3]]])
                    bot.reply_to(m, "✅ Ubicación actualizada.")
                else: bot.reply_to(m, "❌ Error datos.")
            elif paso == "edit_tiempo": stock.update_cell(e['fila'], 10, num(t)); bot.reply_to(m, "✅ Tiempo actualizado.")
            elif paso == "edit_caja": stock.update_cell(e['fila'], 11, num(t)); bot.reply_to(m, "✅ Caja actualizada.")
        except: bot.reply_to(m, "❌ Error Google Sheets.")
        del estado[m.chat.id]; return

    # --- FLUJO NUEVO ---
    pasos_n = [("nombre","stock","🔢 Stock inicial:"), ("stock","nivel","🏢 Nivel:"), ("nivel","pasillo","🛤️ Pasillo:"), ("pasillo","lado","↔️ Lado:"), ("lado","sec","📍 Sección:"), ("sec","caja","📦 Und/Caja:"), ("caja","tiempo","⏱️ Días entrega:"), ("tiempo","correo","📧 Correo:")]
    for act, sig, msg in pasos_n:
        if paso == act:
            # 🔥 VALIDACIÓN DE DUPLICADO SOLO AQUÍ
            if act == "nombre":
                nombre = t.strip().lower()
                if buscar_fila(nombre):
                    bot.reply_to(m, "❌ Este producto ya existe.")
                    del estado[m.chat.id]
                    return
                e[act] = nombre
            else:
                e[act] = t if act not in ["stock","caja","tiempo"] else num(t)

            e["p"] = sig
            bot.reply_to(m, msg)
            return

    if paso == "correo":
        idx = len(stock.get_all_values()) + 1
        f_dias = f'=SI.ERROR(MAX(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) - MIN(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) + 1; 0)'
        f_cons = f'=SI(H{idx}<3; 0; SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D; Movimientos!B:B; A{idx}; Movimientos!D:D; "<0")) / H{idx}; 0))'
        stock.append_row([e["nombre"], f'=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)', "N-"+str(e["nivel"]), "P-"+str(e["pasillo"]), e["lado"].upper(), e["sec"], t, f_dias, f_cons, e["tiempo"], e["caja"]], value_input_option="USER_ENTERED")
        if e["stock"] > 0:
            mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), e["nombre"].lower(), "Carga Inicial", e["stock"], m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ *{e['nombre']}* creado correctamente.", parse_mode="Markdown"); del estado[m.chat.id]

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}; bot.reply_to(m, "📝 Nombre del producto:")

# =========================
# START
# =========================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
