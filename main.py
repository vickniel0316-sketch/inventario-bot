import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# 1. CONFIGURACIÓN DE CONEXIÓN (TU ESTRUCTURA GANADORA)
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480  # Tu ID verificado

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ ERROR: Configura TOKEN y GOOGLE_CREDS en Railway")

creds_dict = json.loads(GOOGLE_CREDS)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
])

client = gspread.authorize(creds)
sheet = client.open("inventario_vickniel01")
stock = sheet.worksheet("Stock")
mov = sheet.worksheet("Movimientos")

# =========================
# 2. KEEP ALIVE (PARA QUE RAILWAY NO LO DUERMA)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")

def web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# 3. UTILIDADES Y BOT
# =========================
bot = telebot.TeleBot(TOKEN)
def ok(m): return m.from_user.id == CHAT_ID
def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

estado = {}

# =========================
# 4. COMANDOS: VER, BUSCAR, ELIMINAR, PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "ver")
def ver_todo(m):
    data = stock.get_all_records()
    if not data:
        bot.reply_to(m, "📭 Inventario vacío.")
        return
    txt = "📋 *INVENTARIO ACTUAL*\n\n"
    for f in data:
        txt += f"• *{f['Producto']}*: {f['Stock_Actual']} uds\n"
    bot.reply_to(m, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    q = m.text.lower().replace("buscar", "").strip()
    data = stock.get_all_records()
    encontrados = [f for f in data if q in str(f.get("Producto","")).lower()]
    if not encontrados:
        bot.reply_to(m, "❌ No encontrado."); return
    for p in encontrados:
        res = (f"🔍 *ENCONTRADO*\n\n📦 *Producto:* {p['Producto']}\n🔢 *Stock:* {p['Stock_Actual']}\n"
               f"📍 *Ubicación:* {p.get('Nivel','')} {p.get('Pasillo','')} {p.get('Lado','')} {p.get('Seccion','')}")
        bot.reply_to(m, res, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    prod = m.text.lower().replace("eliminar", "").strip()
    try:
        celda = stock.find(prod)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ '{prod}' eliminado correctamente.")
    except:
        bot.reply_to(m, "❌ No encontrado.")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_records()
    txt = "📦 *SUGERENCIA DE PEDIDOS*\n\n"
    hay_pedidos = False
    for f in data:
        s = num(f.get("Stock_Actual", 0))
        c = num(f.get("Consumo_dia", 0))
        t = num(f.get("Tiempo_entrega", 0))
        u = num(f.get("Unidades_Caja", 1))
        
        stock_seguridad = c * (t + 2)
        if s <= stock_seguridad and u > 0:
            cajas = math.ceil((stock_seguridad + (c * 7) - s) / u)
            if cajas > 0:
                txt += f"⚠️ *{f['Producto']}*\nStock: {s} | Pedir: {cajas} cajas\n\n"
                hay_pedidos = True
    
    bot.reply_to(m, txt if hay_pedidos else "✅ Todo en orden, no hay pedidos pendientes.", parse_mode="Markdown")

# =========================
# 5. FLUJO NUEVO (UBICACIÓN + TUS FÓRMULAS MAESTRAS)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    estado[m.chat.id] = {"p": "nombre"}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\nEscribe el NOMBRE:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo_nuevo(m):
    e = estado[m.chat.id]; t = m.text; paso = e["p"]
    
    secuencia = [
        ("nombre", "stock", "Stock inicial:"),
        ("stock", "nivel", "Nivel (ej: 1):"),
        ("nivel", "pasillo", "Pasillo (ej: A):"),
        ("pasillo", "lado", "Lado (A/B):"),
        ("lado", "sec", "Sección:"),
        ("sec", "caja", "Unidades por caja:"),
        ("caja", "tiempo", "Tiempo entrega (días):"),
        ("tiempo", "correo", "Correo responsable:")
    ]

    for act, sig, msg in secuencia:
        if paso == act:
            e[act] = t if act not in ["stock", "caja", "tiempo"] else num(t)
            e["p"] = sig
            bot.reply_to(m, msg); return

    if paso == "correo":
        e["correo"] = t
        idx = len(stock.get_all_values()) + 1
        
        # --- TUS FÓRMULAS EXACTAS ADAPTADAS A LA FILA ---
        f_stock = f'=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)'
        
        f_dias_unicos = (
            f'=SI.ERROR(SUMA(1/CONTAR.SI('
            f'SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7); Movimientos!A:A);'
            f'SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7); Movimientos!A:A)'
            f')); 0)'
        )
        
        f_consumo_pro = (
            f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D; Movimientos!B:B; A{idx}; Movimientos!D:D; "<0")) / '
            f'MAX(1; MAX(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) - '
            f'MIN(SI((Movimientos!B:B=A{idx})*(Movimientos!D:D<0); Movimientos!A:A)) + 1); 0)'
        )
        
        nueva_fila = [
            e["nombre"], f_stock, "N-"+str(e["nivel"]), "P-"+str(e["pasillo"]), 
            e["lado"].upper(), e["sec"], e["correo"], f_dias_unicos, f_consumo_pro, 
            e["tiempo"], e["caja"]
        ]
        
        stock.append_row(nueva_fila, value_input_option="USER_ENTERED")
        
        if e["stock"] > 0:
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                e["nombre"].lower(), "Carga Inicial", e["stock"], m.from_user.first_name
            ], value_input_option="USER_ENTERED")
        
        bot.reply_to(m, f"✅ '{e['nombre']}' creado con éxito en la fila {idx}."); del estado[m.chat.id]

# =========================
# 6. ENTRADA / SALIDA (MOVIMIENTOS)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p = m.text.split(); tipo = p[0].lower(); cant = num(p[-1]); prod = " ".join(p[1:-1]).lower()
    mov.append_row([
        datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
        prod, tipo.capitalize(), cant if tipo=="entrada" else -abs(cant), m.from_user.first_name
    ], value_input_option="USER_ENTERED")
    bot.reply_to(m, f"✅ {tipo.capitalize()} de {abs(cant)} unidades registrada.")

# =========================
# 7. CIERRE (EL DESPERTADOR)
# =========================
print("🚀 BOT VICKNIEL HÍBRIDO LISTO")
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        print(f"Error conexión: {e}"); time.sleep(5)
