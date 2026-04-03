import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import math

# =========================
# VARIABLES
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")

if not TOKEN:
    raise Exception("❌ Falta TOKEN")

if not GOOGLE_CREDS:
    raise Exception("❌ Falta GOOGLE_CREDS")

# =========================
# GOOGLE SHEETS
# =========================
try:
    creds_dict = json.loads(GOOGLE_CREDS)

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])

    client = gspread.authorize(creds)
    spreadsheet = client.open("inventario_vickniel01")
    sheet_stock = spreadsheet.worksheet("Stock")
    sheet_mov = spreadsheet.worksheet("Movimientos")

    print("✅ Conexión exitosa con Google Sheets.")

except Exception as e:
    print(f"❌ ERROR DE CONEXIÓN: {e}")
    sys.exit()

bot = telebot.TeleBot(TOKEN)
CHAT_ID = 6249114480

# =========================
# SERVIDOR WEB (RAILWAY)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"🌐 Web corriendo en puerto {port}")
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# =========================
# UTILIDADES
# =========================
def safe_float(x):
    try:
        return float(x)
    except:
        return 0

# =========================
# LÓGICA DE PEDIDOS
# =========================
def calcular_pedidos():
    data = sheet_stock.get_all_records()
    resultado = []

    for fila in data:
        producto = fila.get("Producto", "")
        stock = safe_float(fila.get("Stock", 0))
        consumo = safe_float(fila.get("Consumo_dia", 0))
        tiempo = safe_float(fila.get("Tiempo_entrega", 0))
        caja = safe_float(fila.get("Unidades_Caja", 1))

        if consumo == 0 or caja == 0:
            continue

        punto_pedido = consumo * (tiempo + 2)

        if stock <= punto_pedido:
            cajas = math.ceil((consumo * 15) / caja)

            resultado.append({
                "producto": producto,
                "stock": stock,
                "consumo": consumo,
                "tiempo": tiempo,
                "cajas": cajas
            })

    return resultado

def generar_mensaje(lista):
    if not lista:
        return "✅ No hay productos para pedir hoy."

    texto = "📦 PRODUCTOS A PEDIR HOY\n\n"

    for item in lista:
        texto += f"📦 {item['producto']}\n"
        texto += f"🔢 Stock: {item['stock']}\n"
        texto += f"📊 Consumo/día: {item['consumo']}\n"
        texto += f"🚚 Entrega: {item['tiempo']} días\n"
        texto += f"📦 Pedido: {item['cajas']} cajas\n\n"

    return texto

# =========================
# COMANDO MANUAL
# =========================
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "pedidos")
def pedidos_manual(message):
    lista = calcular_pedidos()
    mensaje = generar_mensaje(lista)
    bot.reply_to(message, mensaje)

# =========================
# ENVÍO AUTOMÁTICO (RD)
# =========================
def envio_diario():
    ultimo_envio = None

    while True:
        ahora = datetime.now(ZoneInfo("America/Santo_Domingo"))
        print("Hora RD:", ahora)

        if ahora.hour == 8:
            if ultimo_envio != ahora.date():
                lista = calcular_pedidos()
                mensaje = generar_mensaje(lista)

                try:
                    bot.send_message(CHAT_ID, mensaje)
                    print("✅ Mensaje enviado")
                except Exception as e:
                    print("❌ Error enviando:", e)

                ultimo_envio = ahora.date()

        time.sleep(60)

threading.Thread(target=envio_diario, daemon=True).start()

# =========================
# START
# =========================
print("🚀 BOT LISTO")

bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print("Error polling:", e)
        time.sleep(5)
