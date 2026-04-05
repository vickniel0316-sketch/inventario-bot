import os
import json
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480  # Tu chat de Telegram

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Configura TOKEN y GOOGLE_CREDS en Railway correctamente")

# =========================
# CONEXIÓN A GOOGLE SHEETS
# =========================
def conectar_sheets():
    intentos = 0
    while intentos < 5:
        try:
            creds_dict = json.loads(GOOGLE_CREDS)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ])
            client = gspread.authorize(creds)
            ss = client.open("inventario_vickniel01")
            stock = ss.worksheet("Stock")
            mov = ss.worksheet("Movimientos")
            print("✅ Conexión a Google Sheets OK")
            return stock, mov
        except Exception as e:
            intentos += 1
            print(f"⚠️ Error de conexión Sheets (Intento {intentos}): {e}")
            time.sleep(5)
    raise Exception("❌ No se pudo conectar a Google Sheets después de varios intentos")

stock, mov = conectar_sheets()

# =========================
# UTILIDADES
# =========================
def num(x):
    try: return float(str(x).replace(",", "."))
    except: return 0

# Diccionario para flujos
estados_espera = {}

# =========================
# BOT
# =========================
bot = telebot.TeleBot(TOKEN)

# Debug: mensaje general para ver si el bot recibe mensajes
@bot.message_handler(func=lambda m: True)
def debug_general(m):
    print(f"📨 Mensaje de {m.from_user.username if m.from_user else m.chat.id}: {m.text}")

# =========================
# COMANDOS
# =========================

# 1️⃣ Ver inventario
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "ver")
def ver_todo(m):
    data = stock.get_all_records()
    if not data:
        bot.reply_to(m, "📭 Inventario vacío")
        return
    txt = "📋 *INVENTARIO ACTUAL*\n\n"
    for f in data:
        txt += f"• *{f['Producto']}*: {f['Stock_Actual']} uds\n"
    bot.reply_to(m, txt, parse_mode="Markdown")

# 2️⃣ Nuevo producto (flujo)
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "nuevo")
def iniciar_nuevo(m):
    estados_espera[m.chat.id] = {"tipo": "nuevo", "paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\n1. Escribe el NOMBRE:", parse_mode="Markdown")

# 3️⃣ Entrada / Salida
@bot.message_handler(func=lambda m: m.text and m.text.lower() in ["entrada", "salida"])
def iniciar_movimiento(m):
    estados_espera[m.chat.id] = {"tipo": m.text.lower(), "paso": "nombre"}
    bot.reply_to(m, f"🔄 *{m.text.upper()}*\nEscribe el NOMBRE del producto:", parse_mode="Markdown")

# 4️⃣ Manejador de flujos
@bot.message_handler(func=lambda m: m.chat.id in estados_espera)
def manejar_flujos(m):
    uid = m.chat.id
    est = estados_espera[uid]

    try:
        # Entrada/Salida
        if est.get("tipo") in ["entrada", "salida"]:
            if est["paso"] == "nombre":
                est["prod"] = m.text.strip().lower()
                est["paso"] = "cantidad"
                bot.send_message(uid, f"Cantidad a registrar de '{m.text}':")
            elif est["paso"] == "cantidad":
                cant = num(m.text)
                if est["tipo"] == "salida": cant = -abs(cant)
                mov.append_row([
                    datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                    est["prod"], est["tipo"].capitalize(), cant,
                    m.from_user.first_name
                ], value_input_option="USER_ENTERED")
                bot.send_message(uid, f"✅ {est['tipo'].capitalize()} de {abs(cant)} registrada")
                del estados_espera[uid]

        # Nuevo producto
        elif est.get("tipo") == "nuevo":
            paso = est["paso"]
            if paso == 1: est["n"] = m.text.strip(); est["paso"] = 2; bot.send_message(uid, "2. STOCK INICIAL:")
            elif paso == 2: est["s"] = num(m.text); est["paso"] = 3; bot.send_message(uid, "3. UNIDADES POR CAJA:")
            elif paso == 3: est["u"] = num(m.text); est["paso"] = 4; bot.send_message(uid, "4. TIEMPO ENTREGA (días):")
            elif paso == 4: est["t"] = num(m.text); est["paso"] = 5; bot.send_message(uid, "5. NIVEL:")
            elif paso == 5: est["niv"] = m.text.strip(); est["paso"] = 6; bot.send_message(uid, "6. PASILLO:")
            elif paso == 6: est["pas"] = m.text.strip(); est["paso"] = 7; bot.send_message(uid, "7. LADO (A/B):")
            elif paso == 7: est["lad"] = m.text.strip().upper(); est["paso"] = 8; bot.send_message(uid, "8. SECCIÓN:")
            elif paso == 8:
                est["sec"] = m.text.strip()
                idx = len(stock.get_all_values()) + 1
                fila = [
                    est["n"],
                    f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)",
                    est["niv"], est["pas"], est["lad"], est["sec"], "miemail@empresa.com",
                    f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)",
                    f"=SIERROR(ABS(B{idx})/H{idx};0)",
                    est["t"], est["u"]
                ]
                stock.append_row(fila, value_input_option="USER_ENTERED")
                # Registrar stock inicial
                if est["s"] > 0:
                    mov.append_row([
                        datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                        est["n"].lower(), "Carga Inicial", est["s"], m.from_user.first_name
                    ], value_input_option="USER_ENTERED")
                bot.send_message(uid, f"✅ '{est['n']}' registrado con éxito")
                del estados_espera[uid]

    except Exception as e:
        bot.send_message(uid, f"❌ Error: {e}")
        del estados_espera[uid]

# =========================
# KEEP ALIVE (Railway)
# =========================
class Web(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Web).serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# =========================
# INICIAR BOT
# =========================
print("🚀 Bot iniciado y escuchando mensajes...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
