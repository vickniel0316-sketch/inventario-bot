import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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

CHATS_PERMITIDOS = [6249114480]

estado_nuevo = {}
estado_editar = {}
estado_eliminar = {}

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
def autorizado(message):
    return message.from_user.id in CHATS_PERMITIDOS

def safe_int(valor):
    try:
        return int(valor)
    except:
        return 0

# =========================
# NUEVO PRODUCTO
# =========================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower() == "nuevo")
def iniciar_nuevo(message):
    estado_nuevo[message.chat.id] = {"paso": "producto"}
    bot.reply_to(message, "📦 Nombre del producto:")

@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.chat.id in estado_nuevo)
def flujo_nuevo(message):
    chat_id = message.chat.id
    estado = estado_nuevo[chat_id]
    texto = message.text.strip()

    data = sheet_stock.get_all_records()

    if estado["paso"] == "producto":
        for fila in data:
            if texto.lower() == str(fila.get('Producto','')).lower():
                bot.reply_to(message, "❌ Ya existe.")
                return
        estado["producto"] = texto
        estado["paso"] = "stock"
        bot.reply_to(message, "🔢 Stock inicial:")
        return

    if estado["paso"] == "stock":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Número inválido")
            return
        estado["stock"] = int(texto)
        estado["paso"] = "nivel"
        bot.reply_to(message, "🏢 Nivel:")
        return

    if estado["paso"] == "nivel":
        estado["nivel"] = f"N-{texto}"
        estado["paso"] = "pasillo"
        bot.reply_to(message, "🚶 Pasillo:")
        return

    if estado["paso"] == "pasillo":
        estado["pasillo"] = f"P-{texto}"
        estado["paso"] = "lado"
        bot.reply_to(message, "↔️ Lado (A/B):")
        return

    if estado["paso"] == "lado":
        if texto.upper() not in ["A","B"]:
            bot.reply_to(message, "❌ Solo A o B")
            return
        estado["lado"] = texto.upper()
        estado["paso"] = "seccion"
        bot.reply_to(message, "📍 Sección:")
        return

    if estado["paso"] == "seccion":
        estado["seccion"] = texto
        estado["paso"] = "reorden"
        bot.reply_to(message, "⚠️ Reorden:")
        return

    if estado["paso"] == "reorden":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return
        estado["reorden"] = int(texto)
        estado["paso"] = "caja"
        bot.reply_to(message, "📦 Unidades por caja:")
        return

    if estado["paso"] == "caja":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return
        estado["caja"] = int(texto)
        estado["paso"] = "tiempo"
        bot.reply_to(message, "🚚 Tiempo de entrega (días):")
        return

    if estado["paso"] == "tiempo":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return
        estado["tiempo"] = int(texto)
        estado["paso"] = "email"
        bot.reply_to(message, "📧 Email:")
        return

    if estado["paso"] == "email":
        estado["email"] = texto
        estado["paso"] = "estado"
        bot.reply_to(message, "📌 Estado:")
        return

    if estado["paso"] == "estado":
        estado["estado"] = texto

        sheet_stock.append_row([
            estado["producto"],
            "",
            estado["nivel"],
            estado["pasillo"],
            estado["lado"],
            estado["seccion"],
            estado["reorden"],
            estado["email"],
            estado["estado"],
            "",
            estado["tiempo"],
            estado["caja"]
        ])

        if estado["stock"] > 0:
            sheet_mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                estado["producto"],
                "",
                estado["stock"],
                message.from_user.first_name
            ])

        bot.reply_to(message, f"✅ Producto creado:\n📦 {estado['producto']}")
        del estado_nuevo[chat_id]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith(("entrada","salida")))
def movimiento(message):
    partes = message.text.split()
    accion = partes[0].upper()
    cantidad = safe_int(partes[-1])
    producto = " ".join(partes[1:-1]).lower()

    data = sheet_stock.get_all_records()

    for fila in data:
        if producto == str(fila.get('Producto','')).lower():
            cantidad_real = cantidad if accion == "ENTRADA" else -cantidad

            sheet_mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                producto,
                "",
                cantidad_real,
                message.from_user.first_name
            ])

            bot.reply_to(message, f"✅ {producto} {cantidad_real}")
            return

    bot.reply_to(message, "❌ Producto no encontrado")

# =========================
# VER TODO
# =========================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and "ver todo" in m.text.lower())
def ver_todo(message):
    data = sheet_stock.get_all_records()

    if not data:
        bot.reply_to(message, "📭 No hay productos.")
        return

    respuesta = "📦 INVENTARIO:\n\n"

    for fila in data:
        producto = fila.get("Producto", "")
        stock = fila.get("Stock", 0)
        pedido = fila.get("Pedido", "")

        respuesta += f"📦 {producto}\n"
        respuesta += f"🔢 Stock: {stock}\n"

        if pedido:
            respuesta += f"📦 Pedido: {pedido} cajas\n"

        respuesta += "\n"

    bot.reply_to(message, respuesta)

# =========================
# MODIFICAR
# =========================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith("modificar"))
def iniciar_editar(message):
    partes = message.text.split()

    if len(partes) < 2:
        bot.reply_to(message, "❌ Usa: modificar nombre_producto")
        return

    producto = " ".join(partes[1:]).lower()
    data = sheet_stock.get_all_records()

    for i, fila in enumerate(data):
        if producto == str(fila.get("Producto", "")).lower():
            estado_editar[message.chat.id] = {
                "fila": i + 2,
                "producto": producto,
                "paso": "campo"
            }

            bot.reply_to(message,
                f"✏️ Editando: {producto}\n\n"
                "1️⃣ Stock\n"
                "2️⃣ Reorden\n"
                "3️⃣ Tiempo entrega\n"
                "4️⃣ Unidades por caja\n\n"
                "Escribe el número:"
            )
            return

    bot.reply_to(message, "❌ Producto no encontrado")

@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.chat.id in estado_editar)
def flujo_editar(message):
    estado = estado_editar[message.chat.id]
    texto = message.text.strip()

    if estado["paso"] == "campo":
        opciones = {"1": 2, "2": 7, "3": 11, "4": 12}

        if texto not in opciones:
            bot.reply_to(message, "❌ Opción inválida")
            return

        estado["columna"] = opciones[texto]
        estado["paso"] = "valor"
        bot.reply_to(message, "✏️ Nuevo valor:")
        return

    if estado["paso"] == "valor":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo números")
            return

        sheet_stock.update_cell(estado["fila"], estado["columna"], int(texto))

        bot.reply_to(message, "✅ Producto actualizado")
        del estado_editar[message.chat.id]

# =========================
# ELIMINAR
# =========================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith("eliminar"))
def iniciar_eliminar(message):
    partes = message.text.split()

    if len(partes) < 2:
        bot.reply_to(message, "❌ Usa: eliminar nombre_producto")
        return

    producto = " ".join(partes[1:]).lower()
    data = sheet_stock.get_all_records()

    for i, fila in enumerate(data):
        if producto == str(fila.get("Producto", "")).lower():
            estado_eliminar[message.chat.id] = {
                "fila": i + 2,
                "producto": producto
            }

            bot.reply_to(message,
                f"⚠️ Vas a eliminar:\n📦 {producto}\n\n"
                "Escribe SI para confirmar o NO para cancelar"
            )
            return

    bot.reply_to(message, "❌ Producto no encontrado")

@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.chat.id in estado_eliminar)
def confirmar_eliminar(message):
    texto = message.text.strip().lower()
    estado = estado_eliminar[message.chat.id]

    if texto == "si":
        sheet_stock.delete_rows(estado["fila"])
        bot.reply_to(message, f"🗑️ Eliminado: {estado['producto']}")
    else:
        bot.reply_to(message, "❌ Eliminación cancelada")

    del estado_eliminar[message.chat.id]

# =========================
# START
# =========================
print("🚀 BOT LISTO")

bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(e)
        time.sleep(5)
