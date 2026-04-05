import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# 1. CONEXIÓN (TU ESTRUCTURA FIJA)
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
# 2. SERVER (KEEP ALIVE RAILWAY)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")

def web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# 3. BOT Y UTILIDADES
# =========================
bot = telebot.TeleBot(TOKEN)
def ok(m): return m.from_user.id == CHAT_ID
def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

estado = {}

# =========================
# 4. COMANDOS (VER, BUSCAR, ELIMINAR)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "ver")
def ver(m):
    data = stock.get_all_records()
    txt = "📋 *STOCK*\n\n" + "\n".join([f"• *{f['Producto']}*: {f['Stock_Actual']}" for f in data])
    bot.reply_to(m, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    q = m.text.lower().replace("buscar", "").strip()
    p = [f for f in stock.get_all_records() if q in str(f['Producto']).lower()]
    for i in p:
        bot.reply_to(m, f"📦 *{i['Producto']}*\n🔢 Stock: {i['Stock_Actual']}\n📍 {i.get('Nivel','')} {i.get('Pasillo','')} {i.get('Lado','')} {i.get('Seccion','')}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    prod = m.text.lower().replace("eliminar", "").strip()
    try:
        celda = stock.find(prod)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ '{prod}' eliminado correctamente.")
    except:
        bot.reply_to(m, "❌ No encontrado.")

# =========================
# 5. COMANDO PEDIDOS (LÓGICA REVISADA 3 DÍAS / 4 CAJAS)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_records()
    txt = "📦 *SUGERENCIA DE PEDIDOS*\n\n"
    hay_alertas = False
    
    for f in data:
        s = num(f.get('Stock_Actual', 0))
        c = num(f.get('Consumo_dia', 0))
        t = num(f.get('Tiempo_entrega', 0))
        u = num(f.get('Unidades_Caja', 1))
        dias = num(f.get('Dias', 0))

        # REGLA PRODUCTO NUEVO: Menos de 3 días
        if dias < 3:
            if s < (u * 0.5): # Menos de media caja
                txt += f"🆕 *{f['Producto']} (Nuevo)*\n⚠️ Stock crítico: {int(s)} uds. Pedir: *4 cajas*\n\n"
                hay_alertas = True
            continue 

        # REGLA PRODUCTO ESTABLE: 3 días o más
        punto_pedido = c * (t + 2)
        if s <= punto_pedido and c > 0:
            faltante = (punto_pedido + (c * 7)) - s
            cajas_sugeridas = math.ceil(faltante / u) if u > 0 else 0
            if cajas_sugeridas > 0:
                txt += f"📈 *{f['Producto']}*\n📦 Stock: {int(s)} | Sugerencia: *{cajas_sugeridas} cajas*\n"
                txt += f"⏱️ Agota en: {round(s/c, 1)} días\n\n"
                hay_alertas = True

    bot.reply_to(m, txt if hay_alertas else "✅ *Inventario Saludable*", parse_mode="Markdown")

# =========================
# 6. NUEVO (FILA ÚNICA + FÓRMULAS)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo_nuevo(m):
    e = estado[m.chat.id]; t = m.text; paso = e["p"]
    pasos = [("nombre","stock","Stock inicial:"), ("stock","nivel","Nivel:"), ("nivel","pasillo","Pasillo:"), ("pasillo","lado","Lado:"), ("lado","sec","Sección:"), ("sec","caja","Und/Caja:"), ("caja","tiempo","Días entrega:"), ("tiempo","correo","Correo:")]
    
    for act, sig, msg in pasos:
        if paso == act:
            e[act] = t if act not in ["stock","caja","tiempo"] else num(t)
            e["p"] = sig; bot.reply_to(m, msg); return

    if paso == "correo":
        idx = len(stock.get_all_values()) + 1
        f1 = f'=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)'
        f2 = f'=SI.ERROR(SUMA(1/CONTAR.SI(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7); Movimientos!A:A);SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7); Movimientos!A:A))); 0)'
        f3 = f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D; Movimientos!B:B; A{idx}; Movimientos!D:D; "<0")) / MAX(1; MAX(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) - MIN(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) + 1); 0)'
        
        stock.append_row([e["nombre"], f1, "N-"+str(e["nivel"]), "P-"+str(e["pasillo"]), e["lado"].upper(), e["sec"], t, f2, f3, e["tiempo"], e["caja"]], value_input_option="USER_ENTERED")
        if e["stock"] > 0:
            mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), e["nombre"].lower(), "Carga Inicial", e["stock"], m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, "✅ CREADO"); del estado[m.chat.id]

# =========================
# 7. ENTRADA/SALIDA
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movimientos(m):
    p = m.text.split(); tipo = p[0].lower(); cant = num(p[-1]); prod = " ".join(p[1:-1]).lower()
    mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), prod, tipo.capitalize(), cant if tipo=="entrada" else -abs(cant), m.from_user.first_name], value_input_option="USER_ENTERED")
    bot.reply_to(m, f"✅ {tipo.capitalize()} OK")

# =========================
# 8. START (EL QUE SÍ SUBE)
# =========================
print("🚀 BOT VICKNIEL INICIADO")
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"Error: {e}"); time.sleep(5)
