import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import sys
import traceback
import warnings
import difflib
import re
import time
import json

warnings.filterwarnings("ignore", category=FutureWarning)

# 🔐 VARIABLES DE ENTORNO
TOKEN = os.getenv("TOKEN")

CHATS_PERMITIDOS = [6249114480]

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 🔐 CREDENCIALES DESDE RAILWAY
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
# FUNCIONES AUXILIARES
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
# NUEVO PRODUCTO GUIADO
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
        bot.reply_to(message, "🏢 Nivel (ej: 1):")
        return

    if estado["paso"] == "nivel":
        if not texto.isdigit():
            bot.reply_to(message, "❌ Solo número")
            return

        estado["nivel"] = f"N-{texto}"
        estado["paso"] = "pasillo"
        bot.reply_to(message, "🚶 Pasillo (ej: 1):")
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
            estado["producto"],
            "",
            estado["nivel"],
            estado["pasillo"],
            estado["lado"],
            estado["seccion"],
            estado["reorden"],
            estado["email"],
            estado["estado"]
        ])

        formula = f"=SUMAR.SI(Movimientos!B:B,A{nueva_fila_index},Movimientos!D:D)"
        sheet_stock.update_cell(nueva_fila_index, 2, formula)

        if estado["stock"] > 0:
            sheet_mov.append_row([
                datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                estado["producto"],
                "",
                estado["stock"],
                message.from_user.first_name
            ])

        bot.reply_to(
            message,
            f"✅ Producto creado\n📦 {estado['producto']}\n📍 {estado['nivel']},{estado['pasillo']},{estado['lado']},{estado['seccion']}"
        )

        del estado_nuevo[chat_id]

# ==========================================
# CONSULTAR STOCK
# ==========================================
@bot.message_handler(func=lambda m: m.text and autorizado(m) and m.text.lower().startswith("cantidad"))
def consultar(message):
    nombre_input = message.text.replace("cantidad", "").strip().lower()
    data = sheet_stock.get_all_records()

    match = None
    for fila in data:
        if nombre_input == str(fila.get('Producto','')).lower():
            match = fila
            break

    if match:
        ubicacion = f"{match.get('Nivel','')},{match.get('Pasillo','')},{match.get('Lado','')},{match.get('Seccion','')}"
        stock = safe_int(match.get('Stock_Actual', 0))

        bot.reply_to(
            message,
            f"📦 {match.get('Producto')}\n🔢 Stock: {stock}\n📍 {ubicacion}"
        )
    else:
        productos = [str(f.get('Producto','')).lower() for f in data]
        sugerido = sugerir_producto(nombre_input, productos)

        if sugerido:
            bot.reply_to(message, f"❓ ¿Quisiste decir {sugerido}?")
        else:
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
    productos = [str(f.get('Producto','')).lower() for f in data]

    for fila in data:
        if producto == str(fila.get('Producto','')).lower():
            registrar_movimiento(message, producto, accion, cantidad)
            return

    sugerido = sugerir_producto(producto, productos)

    if sugerido:
        pendientes[message.chat.id] = {
            "producto": sugerido,
            "accion": accion,
            "cantidad": cantidad
        }
        bot.reply_to(message, f"❓ ¿Quisiste decir {sugerido}? (si/no)")
    else:
        bot.reply_to(message, "❌ Producto no existe")

def registrar_movimiento(message, producto, accion, cantidad):
    cantidad_real = cantidad if accion == "ENTRADA" else -cantidad

    sheet_mov.append_row([
        datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        producto,
        "",
        cantidad_real,
        message.from_user.first_name
    ])

    bot.reply_to(message, f"✅ {producto} {cantidad_real}")

# ==========================================
# START BOT
# ==========================================
print("🚀 BOT LISTO")
bot.infinity_polling()
