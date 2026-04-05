import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN Y ENTORNO
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
ADMIN_IDS = [6249114480] 

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Faltan variables de entorno: TOKEN o GOOGLE_CREDS")

# =========================
# CONEXIÓN A GOOGLE SHEETS
# =========================
def conectar_sheets():
    try:
        creds_dict = json.loads(GOOGLE_CREDS)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ])
        client = gspread.authorize(creds)
        ss = client.open("inventario_vickniel01")
        return ss.worksheet("Stock"), ss.worksheet("Movimientos")
    except Exception as e:
        print(f"❌ Error conectando a Sheets: {e}")
        return None, None

stock, mov = conectar_sheets()

def num(x):
    try:
        return float(str(x).replace(',', '.'))
    except:
        return 0

def es_admin(m):
    return m.from_user.id in ADMIN_IDS

estados_espera = {}

# =========================
# BOT Y COMANDOS
# =========================
bot = telebot.TeleBot(TOKEN)

# --- 1. VER TODO ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "ver")
def ver_todo(m):
    data = stock.get_all_records()
    if not data:
        bot.reply_to(m, "📭 Vacío.")
        return
    txt = "📋 *INVENTARIO*\n\n"
    for f in data:
        txt += f"• *{f['Producto']}*: {f['Stock_Actual']} uds\n"
    bot.reply_to(m, txt, parse_mode="Markdown")

# --- 2. BUSCAR ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("buscar"))
def buscar_producto(m):
    query = m.text.lower().replace("buscar", "").strip()
    data = stock.get_all_records()
    encontrados = [f for f in data if query in str(f.get("Producto","")).lower()]
    
    if not encontrados:
        bot.reply_to(m, f"❌ No encontrado.")
        return
    
    for p in encontrados:
        msg = (f"🔍 *ENCONTRADO*\n\n"
               f"📦 *Producto:* {p['Producto']}\n"
               f"🔢 *Stock:* {p['Stock_Actual']}\n"
               f"📍 *Ubicación:* Nivel {p['Nivel']}, Pasillo {p['Pasillo']}, Lado {p['Lado']}, Sec. {p['Seccion']}")
        bot.reply_to(m, msg, parse_mode="Markdown")

# --- 3. ELIMINAR ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("eliminar"))
def eliminar_prod(m):
    prod_nombre = m.text.lower().replace("eliminar", "").strip()
    try:
        celda = stock.find(prod_nombre)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ '{prod_nombre}' eliminado.")
    except:
        bot.reply_to(m, "❌ No se encontró.")

# --- 4. ENTRADA / SALIDA ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() in ["entrada", "salida"])
def iniciar_mov(m):
    tipo = m.text.lower()
    estados_espera[m.chat.id] = {"tipo": tipo, "paso": "nombre"}
    bot.reply_to(m, f"🔄 *{tipo.upper()}*\nEscribe el nombre del producto:")

# --- 5. NUEVO ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "nuevo")
def iniciar_nuevo(m):
    estados_espera[m.chat.id] = {"tipo": "nuevo", "paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\n1. Escribe el NOMBRE:")

# --- MANEJADOR UNIVERSAL DE PASOS ---
@bot.message_handler(func=lambda m: m.chat.id in estados_espera and es_admin(m))
def manejador_pasos(m):
    uid = m.chat.id
    est = estados_espera[uid]
    
    try:
        # Lógica Entrada/Salida
        if est.get("tipo") in ["entrada", "salida"]:
            if est["paso"] == "nombre":
                est["prod"] = m.text.strip().lower()
                est["paso"] = "cant"
                bot.send_message(uid, f"¿Cantidad para {est['prod']}?")
            elif est["paso"] == "cant":
                c = num(m.text)
                final_c = c if est["tipo"] == "entrada" else -abs(c)
                mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), est["prod"], est["tipo"].capitalize(), final_c, m.from_user.first_name], value_input_option="USER_ENTERED")
                bot.send_message(uid, f"✅ {est['tipo'].capitalize()} registrada.")
                del estados_espera[uid]

        # Lógica Nuevo Producto (8 pasos)
        elif est.get("tipo") == "nuevo":
            p = est["paso"]
            if p == 1: est["n"] = m.text.strip(); est["paso"] = 2; bot.send_message(uid, "2. STOCK INICIAL:")
            elif p == 2: est["s"] = num(m.text); est["paso"] = 3; bot.send_message(uid, "3. UNIDADES POR CAJA:")
            elif p == 3: est["u"] = num(m.text); est["paso"] = 4; bot.send_message(uid, "4. TIEMPO ENTREGA:")
            elif p == 4: est["t"] = num(m.text); est["paso"] = 5; bot.send_message(uid, "5. NIVEL (Col. C):")
            elif p == 5: est["niv"] = m.text.strip(); est["paso"] = 6; bot.send_message(uid, "6. PASILLO (Col. D):")
            elif p == 6: est["pas"] = m.text.strip(); est["paso"] = 7; bot.send_message(uid, "7. LADO (A o B):")
            elif p == 7: est["lad"] = m.text.strip().upper(); est["paso"] = 8; bot.send_message(uid, "8. SECCIÓN (Col. F):")
            elif p == 8:
                est["sec"] = m.text.strip()
                idx = len(stock.get_all_values()) + 1
                fila = [est["n"], f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)", est["niv"], est["pas"], est["lad"], est["sec"], "vickniel0316@gmail.com", f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)", f"=SIERROR(ABS(B{idx})/H{idx}; 0)", est["t"], est["u"]]
                stock.append_row(fila, value_input_option="USER_ENTERED")
                mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), est["n"].lower(), "Carga Inicial", est["s"], m.from_user.first_name], value_input_option="USER_ENTERED")
                bot.send_message(uid, f"✅ '{est['n']}' registrado en ubicación {est['niv']}-{est['pas']}.")
                del estados_espera[uid]
    except Exception as e:
        bot.send_message(uid, f"❌ Error: {e}")
        del estados_espera[uid]

# =========================
# KEEP ALIVE (Railway)
# =========================
class Web(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
def run_w(): HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Web).serve_forever()
threading.Thread(target=run_w, daemon=True).start()

print("🚀 Bot Vickniel con Ubicaciones y Comandos Activos...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
