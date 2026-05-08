import telebot
import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# =========================
# SERVIDOR PARA RENDER
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# =========================
# BOT DE PRUEBA
# =========================
@bot.message_handler(func=lambda m: True)
def echo(m):
    bot.reply_to(m, f"✅ ¡Conectado! Tu ID es {m.from_user.id}")

if __name__ == "__main__":
    # 1. ARRANCAR WEB SERVER PRIMERO
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. LIMPIEZA PROFUNDA DE CONEXIÓN
    print("LOG: Limpiando Webhooks y sesiones colgadas...")
    bot.remove_webhook()
    time.sleep(2) # Pausa técnica
    
    # 3. BUCLE DE REINTENTO PARA EL ERROR 409
    print(">>> INICIANDO POLLING <<<")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            if "409" in str(e):
                print("LOG: Conflicto 409 detectado. Reintentando en 5s...")
            else:
                print(f"LOG: Error: {e}")
            time.sleep(5)
