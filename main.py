import telebot
import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# ==========================================
# SERVIDOR WEB (CORRIGE EL ERROR 501 Y 404)
# ==========================================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is Live")

    def do_HEAD(self):
        # Esto elimina el error 501 que ves en el log
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"LOG: Servidor escuchando en puerto {port}")
    server.serve_forever()

# ==========================================
# LÓGICA DEL BOT
# ==========================================
@bot.message_handler(func=lambda m: True)
def respuesta_prueba(m):
    # Esto te confirmará que el bot te lee
    bot.reply_to(m, f"✅ ¡Recibido! Tu ID es: {m.from_user.id}")

if __name__ == "__main__":
    # 1. Lanzar servidor web
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. Limpieza de sesión (QUITAMOS EL LOG_OUT PARA EVITAR EL ERROR 400)
    print("LOG: Limpiando configuración previa...")
    bot.remove_webhook()
    time.sleep(2)

    # 3. Bucle principal
    print(">>> BOT EN LÍNEA Y ESCUCHANDO <<<")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"LOG: Reintentando por error: {e}")
            time.sleep(5)
