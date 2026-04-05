import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN Y ENTORNO
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ ERROR: Configura TOKEN y GOOGLE_CREDS en Railway")

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
        print(f"❌ Error Sheets: {e}")
        return None, None

stock, mov = conectar_sheets()

def num(x):
    try:
        return float(str(x).replace(',', '.'))
    except:
        return 0

# Diccionario para estados de flujos
estados_espera = {}

# =========================
# BOT Y COMANDOS
# =========================
bot = telebot.TeleBot(TOKEN)

# --- 1. VER TODO ---
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "ver")
def ver_todo(m):
    data = stock.get_all_records()
    if not data:
        bot.reply_to(m, "📭 El inventario está vacío.")
        return
    txt = "📋 *INVENTARIO ACTUAL*\n\n"
    for f in data:
        txt += f"• *{f['Producto']}*: {f['Stock_Actual']} uds\n"
    bot.reply_to(m, txt, parse_mode="Markdown")

# --- 2. BUSCAR ---
@bot.message_handler(func=lambda m: m.text and m.text.lower().startswith("buscar"))
def buscar_producto(m):
    query = m.text.lower().replace("buscar", "").strip()
    if not query:
        bot.reply_to(m, "🔍 Uso: `buscar [nombre]`")
        return
    
    data = stock.get_all_records()
    encontrados = [f for f in data if query in str(f.get("Producto","")).lower()]
    
    if not encontrados:
        bot.reply_to(m, f"❌ No se encontró '{query}'.")
        return
    
    for p in encontrados:
        msg = (f"🔍 *PRODUCTO ENCONTRADO*\n\n"
               f"📦 *Nombre:* {p['Producto']}\n"
               f"🔢 *Stock:* {p['Stock_Actual']}\n"
               f"📍 *Ubicación:* Nivel {p['Nivel']}, Pasillo {p['Pasillo']}, Lado {p['Lado']}, Sec. {p['Seccion']}")
        bot.reply_to(m, msg, parse_mode="Markdown")

# --- 3. ELIMINAR ---
@bot.message_handler(func=lambda m: m.text and m.text.lower().startswith("eliminar"))
def eliminar_prod(m):
    nombre = m.text.lower().replace("eliminar", "").strip()
    try:
        celda = stock.find(nombre)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ '{nombre}' eliminado correctamente.")
    except:
        bot.reply_to(m, f"❌ No encontré '{nombre}' para eliminar.")

# --- 4. ENTRADA / SALIDA ---
@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["entrada", "salida"])
def iniciar_movimiento(m):
    tipo = m.text.lower()
    estados_espera[m.chat.id] = {"tipo": tipo, "paso": "nombre"}
    bot.reply_to(m, f"🔄 *{tipo.upper()}*\nEscribe el NOMBRE del producto:")

# --- 5. NUEVO PRODUCTO ---
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "nuevo")
def iniciar_nuevo(m):
    estados_espera[m.chat.id] = {"tipo": "nuevo", "paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\n1. Escribe el NOMBRE:")

# --- MANEJADOR DE FLUJOS (ASISTENTE) ---
@bot.message_handler(func=lambda m: m.chat.id in estados_espera)
def manejar_pasos(m):
    uid = m.chat.id
    est = estados_espera[uid]
    
    try:
        # Lógica para Entrada o Salida
        if est.get("tipo") in ["entrada", "salida"]:
            if est["paso"] == "nombre":
                est["prod_nombre"] = m.text.strip().lower()
                est["paso"] = "cantidad"
                bot.send_message(uid, f"¿Qué cantidad de '{m.text}' quieres registrar?")
            elif est["paso"] == "cantidad":
                cantidad = num(m.text)
                if est["tipo"] == "salida": cantidad = -abs(cantidad)
                
                mov.append_row([
                    datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                    est["prod_nombre"], est["tipo"].capitalize(), cantidad, m.from_user.first_name
                ], value_input_option="USER_ENTERED")
                
                bot.send_message(uid, f"✅ {est['tipo'].capitalize()} de {abs(cantidad)} unidades lista.")
                del estados_espera[uid]

        # Lógica para Nuevo Producto (8 Pasos)
        elif est.get("tipo") == "nuevo":
            paso = est["paso"]
            if paso == 1:
                est["n"] = m.text.strip(); est["paso"] = 2
                bot.send_message(uid, "2. STOCK INICIAL (Unidades):")
            elif paso == 2:
                est["s"] = num(m.text); est["paso"] = 3
                bot.send_message(uid, "3. UNIDADES POR CAJA:")
            elif paso == 3:
                est["u"] = num(m.text); est["paso"] = 4
                bot.send_message(uid, "4. TIEMPO DE ENTREGA (Días):")
            elif paso == 4:
                est["t"] = num(m.text); est["paso"] = 5
                bot.send_message(uid, "5. NIVEL (Ubicación vertical):")
            elif paso == 5:
                est["niv"] = m.text.strip(); est["paso"] = 6
                bot.send_message(uid, "6. PASILLO:")
            elif paso == 6:
                est["pas"] = m.text.strip(); est["paso"] = 7
                bot.send_message(uid, "7. LADO (A o B):")
            elif paso == 7:
                est["lad"] = m.text.strip().upper(); est["paso"] = 8
                bot.send_message(uid, "8. SECCIÓN:")
            elif paso == 8:
                est["sec"] = m.text.strip()
                # Guardado final
                idx = len(stock.get_all_values()) + 1
                fila = [
                    est["n"], f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)", 
                    est["niv"], est["pas"], est["lad"], est["sec"], "vickniel0316@gmail.com",
                    f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)",
                    f"=SIERROR(ABS(B{idx})/H{idx}; 0)", est["t"], est["u"]
                ]
                stock.append_row(fila, value_input_option="USER_ENTERED")
                mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), est["n"].lower(), "Carga Inicial", est["s"], m.from_user.first_name], value_input_option="USER_ENTERED")
                bot.send_message(uid, f"✅ '{est['n']}' guardado con éxito.")
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

print("🚀 Bot Vickniel iniciado SIN restricciones...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
