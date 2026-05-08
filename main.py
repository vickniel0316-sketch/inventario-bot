import telebot
import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# Servidor para Render
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# Tu lógica de prueba
@bot.message_handler(func=lambda m: True)
def responder(m):
    bot.reply_to(m, f"✅ ¡Conexión exitosa! Tu ID es: {m.from_user.id}")

if __name__ == "__main__":
    # 1. Servidor web para mantener vivo el servicio en Render
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. Limpieza rápida (sin log_out)
    print("LOG: Limpiando Webhook...")
    bot.remove_webhook()
    time.sleep(2) 

    # 3. Inicio del Bot
    print(">>> BOT ESCUCHANDO MENSAJES <<<")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"LOG: Error en polling: {e}")
            time.sleep(5)
