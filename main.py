import telebot
import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# Servidor básico para que Render no falle
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    # 1. Iniciar servidor web
    threading.Thread(target=run_web_server, daemon=True).start()
    
    print("LOG: Iniciando limpieza de sesión...")
    try:
        bot.remove_webhook()
        # Log_out fuerza el cierre de todas las sesiones de polling activas
        bot.log_out() 
        print("LOG: Sesión cerrada en servidores de Telegram. Esperando 10 segundos...")
    except Exception as e:
        print(f"LOG: Nota de limpieza: {e}")
    
    # Pausa obligatoria para que Telegram procese el cierre
    time.sleep(10)

    @bot.message_handler(func=lambda m: True)
    def test(m):
        bot.reply_to(m, "¡POR FIN! Conexión establecida.")

    print(">>> INTENTANDO CONECTAR NUEVAMENTE <<<")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"LOG: Reintentando... ({e})")
            time.sleep(5)
