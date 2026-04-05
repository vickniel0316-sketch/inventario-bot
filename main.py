import telebot
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN
# =========================
TOKEN = os.getenv("TOKEN")  # Asegúrate de poner tu token en Railway

if not TOKEN:
    raise Exception("❌ ERROR: Configura la variable TOKEN en Railway")

bot = telebot.TeleBot(TOKEN)

# =========================
# KEEP ALIVE (Railway)
# =========================
class Web(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Web).serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# =========================
# MENSAJE DE PRUEBA
# =========================
@bot.message_handler(func=lambda m: True)  # Responde a cualquier mensaje
def prueba_respuesta(m):
    bot.reply_to(m, f"✅ Recibido tu mensaje: {m.text}")

# =========================
# INICIO
# =========================
print("🚀 Bot iniciado y escuchando mensajes...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
