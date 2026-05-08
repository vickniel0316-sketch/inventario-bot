import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN DE APIS
# =========================

TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS),
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# KEEP ALIVE (SERVIDOR MEJORADO)
# =========================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is Live")

    def do_HEAD(self): # Añadido para evitar el error 501 que vimos en tus logs
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000)) # Puerto estándar de Render
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Servidor web iniciado en puerto {port}")
    server.serve_forever()

# =========================
# MOTOR DEL BOT
# =========================

bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()

# ... (Aquí va todo tu código de lógica: ok, num, normalizar, tokenizar, etc.)
# Mantén todas tus funciones de búsqueda y comandos exactamente igual hasta llegar al final

# =========================
# LANZAMIENTO FINAL (CORREGIDO)
# =========================

if __name__ == "__main__":
    # 1. Limpiar Webhook por si acaso
    bot.remove_webhook()
    
    # 2. Iniciar el servidor web en un HILO SEPARADO
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    # 3. Bucle principal del Bot con manejo de errores
    print("Bot iniciando polling...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Error en polling: {e}")
            time.sleep(10)
