import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN Y ENTORNO
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480  # Tu ID de Telegram

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Faltan variables de entorno: TOKEN o GOOGLE_CREDS")

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
        print(f"❌ Error conectando a Sheets: {e}")
        return None, None

stock, mov = conectar_sheets()

# =========================
# LÓGICA DE PEDIDOS (Sincronizada 3 + 1)
# =========================
def calc_pedidos():
    try:
        # Forzamos refresco de datos
        data = stock.get_all_records()
    except Exception as e:
        return f"⚠️ Error al leer la base de datos: {e}"
    
    res = []
    tolerancia = 2

    for f in data:
        p = f.get("Producto", "")
        s = num(f.get("Stock_Actual", 0))
        c = num(f.get("Consumo_dia", 0))
        t = num(f.get("Tiempo_entrega", 0))
        u = num(f.get("Unidades_Caja", 1))
        dias_mov = num(f.get("Dias", 0)) # Columna H

        if u <= 0 or not p: continue

        # --- DETERMINACIÓN DE CRITERIO (3 + 1) ---
        if dias_mov < 3:
            # Data Insuficiente: Avisa en 3 cajas, repone hasta 4
            punto_reorden = 3 * u
            objetivo_stock = 4 * u
        else:
            # Alta Rotación: Avisa en T+2, repone hasta 15 días
            punto_reorden = c * (t + tolerancia)
            objetivo_stock = c * 15

        # --- VERIFICACIÓN DE ALERTA ---
        if s <= punto_reorden:
            # Calculamos cuántas unidades faltan para el objetivo
            unidades_a_pedir = max(0, objetivo_stock - s)
            cajas = math.ceil(unidades_a_pedir / u)
            
            # Si el stock es bajo pero el cálculo da 0, pedimos al menos 1 caja
            if cajas <= 0: cajas = 1
            
            res.append((p, s, cajas))
    return res

def msg_pedidos(lista):
    if isinstance(lista, str): return lista
    if not lista: return "✅ Inventario saludable. Todos los niveles están por encima del punto de reorden."
    
    txt = "📦 *REPORTE DE PEDIDOS SUGERIDOS*\n"
    txt += "Crit.: Avisa en 3 cajas / Repone a 4\n"
    txt += "--------------------------------\n\n"
    for p, s, k in lista:
        txt += f"🔹 *{p}*\n   Stock Actual: {s}\n   👉 *Pedir: {k} cajas*\n\n"
    return txt

# =========================
# FUNCIONES AUXILIARES
# =========================
def num(x):
    try:
        # Maneja strings con coma decimal o formatos europeos/RD
        return float(str(x).replace(',', '.'))
    except:
        return 0

def ok(m):
    return m.from_user.id == CHAT_ID

# =========================
# BOT Y COMANDOS
# =========================
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def enviar_reporte(m):
    bot.send_chat_action(m.chat.id, 'typing')
    resultado = calc_pedidos()
    bot.reply_to(m, msg_pedidos(resultado), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada", "salida")))
def registrar_movimiento(m):
    partes = m.text.split()
    if len(partes) < 3:
        bot.reply_to(m, "❌ Formato incorrecto. Usa: `entrada [producto] [cantidad]`")
        return

    tipo = partes[0].lower()
    try:
        cant = num(partes[-1])
        # El nombre del producto puede tener espacios
        prod_nombre = " ".join(partes[1:-1]).strip().lower()
        
        # Registro con USER_ENTERED para que Sheets procese números y fechas correctamente
        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod_nombre,
            "Bot Telegram",
            cant if tipo == "entrada" else -cant,
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")
        
        bot.reply_to(m, f"✅ {tipo.capitalize()} de {cant} registrada para '{prod_nombre}'.")
    except Exception as e:
        bot.reply_to(m, f"❌ Error al registrar: {e}")

# =========================
# SERVIDOR WEB (KEEP ALIVE)
# =========================
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_web():
    server_address = ("0.0.0.0", int(os.environ.get("PORT", 8080)))
    HTTPServer(server_address, HealthCheck).serve_forever()

# Iniciar servidor en hilo aparte
threading.Thread(target=run_web, daemon=True).start()

# =========================
# INICIO DEL BOT
# =========================
print("🚀 Vickniel Bot sincronizado (Lógica 3+1) iniciado...")
bot.infinity_polling()
