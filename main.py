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
CHAT_ID = 6249114480  # <--- ASEGÚRATE QUE ESTE SEA TU ID

# Función de seguridad
def ok(m):
    # Este print es CLAVE: te dirá en el log quién le está escribiendo al bot
    print(f"DEBUG: Mensaje recibido de ID {m.from_user.id}")
    return m.from_user.id == CHAT_ID

# =========================
# KEEP ALIVE (SERVIDOR)
# =========================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is Live")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"LOG: Servidor web iniciado en puerto {port}")
    server.serve_forever()

# =========================
# MOTOR DEL BOT
# =========================

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda m: True) # Responde a TODOS para la prueba
def prueba_conexion(m):
    print(f"LOG: Procesando mensaje de {m.from_user.first_name}")
    bot.reply_to(m, f"✅ ¡Hola César! El bot está vivo. Tu ID es: {m.from_user.id}")

# =========================
# LANZAMIENTO
# =========================

if __name__ == "__main__":
    print("LOG: Iniciando despliegue...")
    
    # 1. Limpiar Webhook
    bot.remove_webhook()
    
    # 2. Servidor Web (Hilo separado)
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    # 3. Intento de conexión a Google (Opcional para esta prueba)
    try:
        print("LOG: Intentando conectar con Google Sheets...")
        # Aquí iría tu lógica de credenciales si quieres probarla de una vez
        # creds = ServiceAccountCredentials.from_json_keyfile_dict(...)
        print("LOG: Conexión a Google exitosa (o saltada para prueba).")
    except Exception as e:
        print(f"ERROR GOOGLE: {e}")

    # 4. Iniciar Polling
    print(">>> BOT INICIANDO POLLING AHORA <<<")
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            print(f"ERROR POLLING: {e}")
            time.sleep(10)
