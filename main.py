import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS),
    ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
)

client = gspread.authorize(creds)
ss = client.open("inventario_vickniel01")
stock = ss.worksheet("Stock")
mov = ss.worksheet("Movimientos")

# =========================
# SERVER (KEEP-ALIVE)
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

threading.Thread(target=web, daemon=True).start()

# =========================
# UTILIDADES
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}  # para selección múltiple

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

# Búsqueda exacta por nombre para editar
def buscar_fila(nombre_buscado):
    col_a = stock.col_values(1)
    for i, valor in enumerate(col_a):
        if valor.strip().lower() == nombre_buscado.strip().lower():
            return i + 1
    return None

# Búsqueda inteligente para movimientos
def buscar_fila_general(valor):
    col_productos = stock.col_values(1)
    col_codigos = stock.col_values(14)
    valor = valor.strip().lower()
    palabras = valor.split()
    coincidencias = []

    for i in range(1, len(col_productos)):
        nombre = col_productos[i].strip().lower()
        codigo = str(col_codigos[i]).strip()
        if valor == codigo:
            return i + 1
        if all(p in nombre for p in palabras):
            coincidencias.append(i + 1)

    if len(coincidencias) == 1:
        return coincidencias[0]
    if len(coincidencias) > 1:
        return coincidencias
    return None

# =========================
# PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_records()
    txt = "📦 *SUGERENCIA DE PEDIDOS*\n\n"
    hay = False
    for f in data:
        s = num(f.get('Stock_Actual', 0))
        c = num(f.get('Consumo_dia', 0))
        t = num(f.get('Tiempo_entrega', 0))
        u = num(f.get('Unidades_Caja', 1))
        dias = num(f.get('Dias', 0))

        if u <= 0: continue
        if dias < 3 and s < (2 * u):
            objetivo = 5 * u
            cajas = math.ceil((objetivo - s) / u)
            if cajas > 0:
                txt += f"🆕 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
                hay = True
            continue
        if c <= 0: continue
        stock_critico = c * (t + 2)
        objetivo = c * 15
        if s <= stock_critico:
            cajas = math.ceil((objetivo - s) / u)
            if cajas <= 0: cajas = 1
            txt += f"📦 *{f['Producto']}*\n⚠️ Bajo stock: {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
            hay = True
    bot.reply_to(m, txt if hay else "✅ Inventario saludable", parse_mode="Markdown")

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def movimientos(m):
    try:
        p = m.text.split()
        tipo = p[0].lower()
        cant = num(p[-1])
        prod = " ".join(p[1:-1]).strip()
        resultado = buscar_fila_general(prod)
        if resultado is None:
            bot.reply_to(m, f"❌ El producto '{prod}' no existe.")
            return
        if isinstance(resultado, list):
            opciones = resultado[:5]
            opciones_temp[m.chat.id] = {"opciones": opciones, "tipo": tipo, "cantidad": cant}
            texto = "⚠️ Varias coincidencias:\n\n"
            for idx, f in enumerate(opciones, 1):
                nombre = stock.cell(f, 1).value
                texto += f"{idx}. {nombre}\n"
            texto += "\nResponde con el número."
            bot.reply_to(m, texto)
            return

        fila = resultado
        prod_real = stock.cell(fila, 1).value

        if tipo == "entrada":
            valor = cant
            tipo_txt = "Entrada"
        elif tipo == "salida":
            valor = -abs(cant)
            tipo_txt = "Salida"
        elif tipo == "ajuste":
            stock_actual = num(stock.cell(fila, 2).value)
            valor = cant - stock_actual
            tipo_txt = "Ajuste"

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod_real.lower(),
            tipo_txt,
            valor,
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")

        bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod_real}*.", parse_mode="Markdown")

    except:
        bot.reply_to(m, "❌ Formato: `entrada [producto] [cantidad]`")

# =========================
# SELECCIÓN MÚLTIPLE PARA MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.chat.id in opciones_temp and ok(m))
def seleccionar_opcion(m):
    try:
        seleccion = int(m.text.strip()) - 1
        data = opciones_temp[m.chat.id]
        opciones = data["opciones"]
        if seleccion < 0 or seleccion >= len(opciones):
            bot.reply_to(m, "❌ Opción inválida.")
            return
        fila = opciones[seleccion]
        tipo = data["tipo"]
        cant = data["cantidad"]
        prod = stock.cell(fila, 1).value

        if tipo == "entrada":
            valor = cant
            tipo_txt = "Entrada"
        elif tipo == "salida":
            valor = -abs(cant)
            tipo_txt = "Salida"
        elif tipo == "ajuste":
            stock_actual = num(stock.cell(fila, 2).value)
            valor = cant - stock_actual
            tipo_txt = "Ajuste"

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod.lower(),
            tipo_txt,
            valor,
            m.from_user.first_name
        ], value_input_option="USER_ENTERED")

        bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod}*.", parse_mode="Markdown")
        del opciones_temp[m.chat.id]

    except:
        bot.reply_to(m, "❌ Responde con un número válido.")

# =========================
# EDITAR (original, sin cambios)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith("editar"))
def editar(m):
    prod = m.text.lower().replace("editar", "").strip()
    fila = buscar_fila(prod)
    if fila:
        estado[m.chat.id] = {"p": "edit_opcion", "prod": prod, "fila": fila}
        bot.reply_to(m, f"⚙️ *EDITAR: {prod.upper()}*\n\n1. Ubicación\n2. Tiempo Entrega\n3. Unidades/Caja\n\nResponde con el número.", parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ No encontrado.")

# =========================
# VER (original, tal cual)
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "ver")
def ver(m):
    data = stock.get_all_records()
    txt = "📋 *RESUMEN STOCK*\n\n" + "\n".join([
        f"• *{f['Producto']}*: {int(num(f['Stock_Actual']))}" for f in data
    ])
    bot.reply_to(m, txt, parse_mode="Markdown")

# =========================
# NUEVO PRODUCTO (paso a paso con fórmulas)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo_producto_inicio(m):
    chat_id = m.chat.id
    estado[chat_id] = {"paso": "nombre"}
    bot.reply_to(m, "📝 Ingresa el nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado)
def nuevo_producto_flujo(m):
    chat_id = m.chat.id
    data = estado[chat_id]
    paso = data["paso"]
    texto = m.text.strip()

    if paso == "nombre":
        data["nombre"] = texto
        data["paso"] = "stock"
        bot.reply_to(m, "📦 Ingresa el Stock inicial:")
        return
    if paso == "stock":
        data["stock"] = num(texto)
        data["paso"] = "nivel"
        bot.reply_to(m, "📌 Ingresa el Nivel:")
        return
    if paso == "nivel":
        data["nivel"] = texto
        data["paso"] = "pasillo"
        bot.reply_to(m, "➡️ Ingresa el Pasillo:")
        return
    if paso == "pasillo":
        data["pasillo"] = texto
        data["paso"] = "lado"
        bot.reply_to(m, "↔️ Ingresa el Lado:")
        return
    if paso == "lado":
        data["lado"] = texto
        data["paso"] = "seccion"
        bot.reply_to(m, "🔢 Ingresa la Sección:")
        return
    if paso == "seccion":
        data["seccion"] = texto
        data["paso"] = "email"
        bot.reply_to(m, "📧 Ingresa el Email:")
        return
    if paso == "email":
        data["email"] = texto
        ultima_fila = len(stock.get_all_values()) + 1
        stock.update(f"A{ultima_fila}:G{ultima_fila}", [[
            data["nombre"], data["stock"], data["nivel"],
            data["pasillo"], data["lado"], data["seccion"], data["email"]
        ]])
        # fórmulas H e I
        stock.update_cell(ultima_fila, 8, f'=SI.ERROR(MIN(6, HOY() - QUERY(Movimientos!A:D, "select A where B = \'\" & A{ultima_fila} & \"\' order by A asc limit 1", 0)), 0)')
        stock.update_cell(ultima_fila, 9, f'=ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D, Movimientos!B:B, A{ultima_fila}, Movimientos!D:D, "<0"))')

        bot.reply_to(m, f"✅ Producto '{data['nombre']}' agregado.")
        del estado[chat_id]

# =========================
# START
# =========================
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
