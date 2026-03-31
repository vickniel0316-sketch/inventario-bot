import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import sys
import warnings
import difflib
import time
import json
import threading

warnings.filterwarnings("ignore", category=FutureWarning)

# 🔐 VARIABLES
TOKEN = os.getenv("TOKEN")
CHATS_PERMITIDOS = [6249114480]

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 🔐 GOOGLE CREDS
try:
    credenciales_json = os.getenv("GOOGLE_CREDS")
    creds_dict = json.loads(credenciales_json)

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open("inventario_vickniel01")
    sheet_stock = spreadsheet.worksheet("Stock")
    sheet_mov = spreadsheet.worksheet("Movimientos")

    print("✅ Conexión exitosa con Google Sheets.")
except Exception as e:
    print(f"❌ ERROR DE CONEXIÓN: {e}")
    sys.exit()

bot = telebot.TeleBot(TOKEN)

# ==========================================
# FUNCIONES AUX
# ==========================================
def autorizado(message):
    return message.from_user.id in CHATS_PERMITIDOS

def safe_int(valor):
    try:
        return int(valor)
    except:
        return 0

pendientes = {}
estado_nuevo = {}

def sugerir_producto(nombre, lista):
    matches = difflib.get_close_matches(nombre, lista, n=1, cutoff=0.6)
    return matches[0] if matches else None

# ==========================================
# REPORTE DIARIO
# ==========================================
def enviar_reporte_diario():
    while True:
        ahora = datetime.now().strftime("%H:%M")

        if ahora == "08:00":
            try:
                data = sheet_stock.get_all_records()

                bajos, iguales, cercanos = [], [], []

                for fila in data:
                    producto = fila.get("Producto", "")
                    stock = safe_int(fila.get("Stock_Actual", 0))
                    reorden = safe_int(fila.get("Reorden", 0))

                    if stock < reorden:
                        bajos.append(f"{producto} ({stock}/{reorden})")
                    elif stock == reorden:
                        iguales.append(f"{producto} ({stock}/{reorden})")
                    elif stock <= reorden + 3:
                        cercanos.append(f"{producto} ({stock}/{reorden})")

                mensaje = "📊 REPORTE DIARIO INVENTARIO\n\n"

                if bajos:
                    mensaje += "🔻 Bajo mínimo:\n" + "\n".join(bajos) + "\n\n"
                if iguales:
                    mensaje += "⚠️ En mínimo:\n" + "\n".join(iguales) + "\n\n"
                if cercanos:
                    mensaje += "🔜 Próximos a reorden:\n" + "\n".join(cercanos) + "\n\n"

                if not (bajos or iguales or cercanos):
                    mensaje += "✅ Todo el inventario está en buen estado"

                bot.send_message(CHATS_PERMITIDOS[0], mensaje)

            except Exception as e:
                print(f"Error en reporte diario: {e}")

            time.sleep(60)

        time.sleep(30)

# ==========================================
# CONFIRMAR SUGERENCIA
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.chat.id in pendientes)
def confirmar(message):
    resp = message.text.lower().strip()

    if resp not in ["si", "sí", "no"]:
        bot.reply_to(message, "❓ Responde si o no")
        return

    datos = pendientes.pop(message.chat.id)

    if resp == "no":
        bot.reply_to(message, "❌ Cancelado")
        return

    registrar_movimiento(message, datos["producto"], datos["accion"], datos["cantidad"])

# ==========================================
# NUEVO PRODUCTO
# ==========================================
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
                bot.reply_to(message, f"❌ Ya existe.\n👉 Usa:\nentrada {texto} 10")
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
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return

        estado["nivel"] = f"N-{texto}"
        estado["paso"] = "pasillo"
        bot.reply_to(message, "🚶 Pasillo:")
        return

    if estado["paso"] == "pasillo":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return

        estado["pasillo"] = f"P-{texto}"
        estado["paso"] = "lado"
        bot.reply_to(message, "↔️ Lado (A/B):")
        return

    if estado["paso"] == "lado":
        if texto.upper() not in ["A", "B"]:
            bot.reply_to(message, "❌ Solo A o B")
            return

        estado["lado"] = texto.upper()
        estado["paso"] = "seccion"
        bot.reply_to(message, "📍 Sección:")
        return

    if estado["paso"] == "seccion":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return

        estado["seccion"] = texto
        estado["paso"] = "reorden"
        bot.reply_to(message, "⚠️ Reorden:")
        return

    if estado["paso"] == "reorden":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return

        estado["reorden"] = int(texto)
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

        nueva_fila_index = len(sheet_stock.get_all_records()) + 2

        sheet_stock.append_row([
            estado["producto"], "", estado["nivel"], estado["pasillo"],
            estado["lado"], estado["seccion"], estado["reorden"],
            estado["email"], estado["estado"]
        ])

        formula = f"=SUMAR.SI(Movimientos!B:B,A{nueva_fila_index},Movimientos!D:D)"
        sheet_stock.update_cell(nueva_fila_index, 2, formula)

        if estado["stock"] > 0:
            sheet_mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                estado["producto"], "", estado["stock"],
                message.from_user.first_name
            ])

        bot.reply_to(message, f"✅ Producto creado\n📦 {estado['producto']}")
        del estado_nuevo[chat_id]

# ==========================================
# VER TODO
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower() == "ver todo")
def ver_todo(message):
    data = sheet_stock.get_all_records()

    if not data:
        bot.reply_to(message, "📭 Inventario vacío")
        return

    mensaje = "📦 INVENTARIO:\n\n"

    for fila in data:
        producto = fila.get("Producto", "")
        stock = safe_int(fila.get("Stock_Actual", 0))
        ubicacion = f"{fila.get('Nivel','')},{fila.get('Pasillo','')},{fila.get('Lado','')},{fila.get('Seccion','')}"

        mensaje += f"{producto} → {stock} | {ubicacion}\n"

    bot.reply_to(message, mensaje)

# ==========================================
# ELIMINAR PRODUCTO
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith("eliminar"))
def eliminar_producto(message):
    nombre = message.text.replace("eliminar", "").strip().lower()
    data = sheet_stock.get_all_records()

    for i, fila in enumerate(data, start=2):
        if nombre == str(fila.get("Producto", "")).lower():
            sheet_stock.delete_rows(i)
            bot.reply_to(message, f"🗑️ Eliminado: {fila.get('Producto')}")
            return

    bot.reply_to(message, "❌ Producto no encontrado")

# ==========================================
# CONSULTAR
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith("cantidad"))
def consultar(message):
    nombre_input = message.text.replace("cantidad", "").strip().lower()
    data = sheet_stock.get_all_records()

    for fila in data:
        if nombre_input == str(fila.get('Producto','')).lower():
            stock = safe_int(fila.get('Stock_Actual', 0))
            ubicacion = f"{fila.get('Nivel','')},{fila.get('Pasillo','')},{fila.get('Lado','')},{fila.get('Seccion','')}"
            bot.reply_to(message, f"📦 {fila.get('Producto')}\n🔢 {stock}\n📍 {ubicacion}")
            return

    bot.reply_to(message, "❌ No encontrado")

# ==========================================
# MOVIMIENTOS
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith(("entrada", "salida")))
def movimiento(message):
    partes = message.text.split()
    accion = partes[0].upper()
    cantidad = safe_int(partes[-1])
    producto = " ".join(partes[1:-1]).lower()

    data = sheet_stock.get_all_records()

    for fila in data:
        if producto == str(fila.get('Producto','')).lower():
            registrar_movimiento(message, producto, accion, cantidad)
            return

    bot.reply_to(message, "❌ Producto no existe")

def registrar_movimiento(message, producto, accion, cantidad):
    cantidad_real = cantidad if accion == "ENTRADA" else -cantidad

    sheet_mov.append_row([
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        producto, "", cantidad_real,
        message.from_user.first_name
    ])

    bot.reply_to(message, f"✅ {producto} {cantidad_real}")

# ==========================================
# BUSQUEDA FLEXIBLE (AL FINAL)
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m))
def busqueda_general(message):
    texto = message.text.lower().strip()

    if texto.startswith(("entrada", "salida", "cantidad", "nuevo", "eliminar", "ver")):
        return

    data = sheet_stock.get_all_records()
    resultados = []

    for fila in data:
        nombre = str(fila.get("Producto", "")).lower()
        if texto in nombre:
            stock = safe_int(fila.get("Stock_Actual", 0))
            resultados.append(f"{fila.get('Producto')} → {stock}")

    if resultados:
        bot.reply_to(message, "🔍 Resultados:\n\n" + "\n".join(resultados))

# ==========================================
# START
# ==========================================
threading.Thread(target=enviar_reporte_diario, daemon=True).start()

bot.remove_webhook()
time.sleep(2)

print("🚀 BOT LISTO")
bot.infinity_polling(none_stop=True, interval=0, timeout=20)
