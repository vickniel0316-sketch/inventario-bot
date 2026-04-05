import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# 1. CONFIGURACIÓN Y CONEXIÓN
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
# 2. SERVER PARA RAILWAY (KEEP-ALIVE)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")

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

# =========================
# 4. COMANDO PEDIDOS (LÓGICA ESPEJO)
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

        if dias < 3:
            if s < (u * 2): # Alerta: menos de 2 cajas
                txt += f"🆕 *{f['Producto']} (Nuevo)*\n⚠️ Stock bajo 2 cajas: {int(s)} uds.\n🚚 Pedir: *3 cajas*\n\n"
                hay_alertas = True
            continue 

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
# 5. COMANDOS DE GESTIÓN (EDITAR / ELIMINAR)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar_producto(m):
    prod_nom = m.text.lower().replace("eliminar", "").strip()
    try:
        celda = stock.find(prod_nom)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ Producto '{prod_nom}' eliminado correctamente.")
    except:
        bot.reply_to(m, "❌ No se encontró el producto.")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("editar"))
def editar_producto(m):
    prod_nom = m.text.lower().replace("editar", "").strip()
    data = stock.get_all_records()
    p = next((f for f in data if f['Producto'].lower() == prod_nom), None)
    
    if p:
        estado[m.chat.id] = {"p": "edit_opcion", "prod": prod_nom}
        bot.reply_to(m, f"⚙️ Editando *{p['Producto']}*.\n¿Qué deseas cambiar?\n1. Ubicación\n2. Tiempo Entrega\n3. Unidades/Caja\n\nResponde con el número.", parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ Producto no encontrado.")

# =========================
# 6. FLUJOS CONVERSACIONALES
# =========================
@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujos(m):
    e = estado[m.chat.id]; t = m.text; paso = e["p"]

    # --- FLUJO EDITAR ---
    if paso == "edit_opcion":
        if t == "1": e["p"] = "edit_ubi"; bot.reply_to(m, "📍 Nueva Ubicación (Nivel Pasillo Lado Sección):")
        elif t == "2": e["p"] = "edit_tiempo"; bot.reply_to(m, "⏱️ Nuevo tiempo de entrega (días):")
        elif t == "3": e["p"] = "edit_caja"; bot.reply_to(m, "📦 Nuevas unidades por caja:")
        else: bot.reply_to(m, "❌ Opción inválida."); del estado[m.chat.id]
        return

    if paso.startswith("edit_"):
        celda = stock.find(e["prod"])
        if paso == "edit_ubi":
            partes = t.split()
            if len(partes) >= 4:
                stock.update(f"C{celda.row}:F{celda.row}", [[f"N-{partes[0]}", f"P-{partes[1]}", partes[2].upper(), partes[3]]])
            else: bot.reply_to(m, "❌ Formato incorrecto."); del estado[m.chat.id]; return
        elif paso == "edit_tiempo": stock.update_cell(celda.row, 10, num(t))
        elif paso == "edit_caja": stock.update_cell(celda.row, 11, num(t))
        
        bot.reply_to(m, "✅ ACTUALIZADO"); del estado[m.chat.id]; return

    # --- FLUJO NUEVO ---
    pasos_n = [("nombre","stock","Stock inicial:"), ("stock","nivel","Nivel:"), ("nivel","pasillo","Pasillo:"), ("pasillo","lado","Lado:"), ("lado","sec","Sección:"), ("sec","caja","Und/Caja:"), ("caja","tiempo","Días entrega:"), ("tiempo","correo","Correo:")]
    
    for act, sig, msg in pasos_n:
        if paso == act:
            e[act] = t if act not in ["stock","caja","tiempo"] else num(t)
            e["p"] = sig; bot.reply_to(m, msg); return

    if paso == "correo":
        idx = len(stock.get_all_values()) + 1
        f_dias = f'=SI.ERROR(MAX(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) - MIN(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) + 1; 0)'
        f_cons = f'=SI(H{idx}<3; 0; SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D; Movimientos!B:B; A{idx}; Movimientos!D:D; "<0")) / H{idx}; 0))'
        
        stock.append_row([e["nombre"], f'=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)', "N-"+str(e["nivel"]), "P-"+str(e["pasillo"]), e["lado"].upper(), e["sec"], t, f_dias, f_cons, e["tiempo"], e["caja"]], value_input_option="USER_ENTERED")
        if e["stock"] > 0:
            mov.append_row([datetime.now(ZoneInfo("America/Santo_Domino")).strftime("%Y-%m-%d %H:%M:%S"), e["nombre"].lower(), "Carga Inicial", e["stock"], m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, "✅ CREADO"); del estado[m.chat.id]

# =========================
# 7. OTROS COMANDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

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

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movimientos(m):
    p = m.text.split(); tipo = p[0].lower(); cant = num(p[-1]); prod = " ".join(p[1:-1]).lower()
    mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), prod, tipo.capitalize(), cant if tipo=="entrada" else -abs(cant), m.from_user.first_name], value_input_option="USER_ENTERED")
    bot.reply_to(m, f"✅ {tipo.capitalize()} OK")

# =========================
# 8. ARRANQUE
# =========================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        time.sleep(5)
