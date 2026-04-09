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
opciones_temp = {}

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.'))
    except: return 0

# =========================
# 🔥 BUSQUEDA INTELIGENTE
# =========================
indice = {}
productos_cache = []
last_update = 0
CACHE_TTL = 60

def normalizar(texto):
    texto = str(texto).lower().strip()
    reemplazos = {
        "acción": "accion",
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"
    }
    for k, v in reemplazos.items():
        texto = texto.replace(k, v)
    return texto

def tokenizar(texto):
    texto = normalizar(texto)
    palabras = texto.split()
    tokens = set()

    for p in palabras:
        tokens.add(p)
        tokens.add(p[:3])

        if any(c.isdigit() for c in p):
            tokens.add(''.join(filter(str.isdigit, p)))

    return tokens

def construir_indice():
    global indice, productos_cache, last_update

    data = stock.get_all_values()
    productos_cache = data
    indice = {}

    for i in range(1, len(data)):
        nombre = data[i][0]
        tokens = tokenizar(nombre)

        for t in tokens:
            if t not in indice:
                indice[t] = set()
            indice[t].add(i + 1)

    last_update = time.time()

def obtener_indice():
    global last_update
    if time.time() - last_update > CACHE_TTL:
        construir_indice()
    return indice

def buscar_producto_inteligente(query):
    idx = obtener_indice()
    palabras = tokenizar(query)

    resultados = None

    for p in palabras:
        if p in idx:
            if resultados is None:
                resultados = idx[p].copy()
            else:
                resultados &= idx[p]

    if not resultados:
        return None

    resultados = list(resultados)

    if len(resultados) == 1:
        return resultados[0]

    return resultados[:5]

# =========================
# PEDIDOS (MEJORADO)
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

        if u <= 0:
            continue

        # 🆕 PRODUCTO NUEVO
        if dias < 3:
            if s < (2 * u):
                objetivo = 5 * u
                cajas = math.ceil((objetivo - s) / u)

                if cajas > 0:
                    txt += f"🆕 *{f['Producto']}*\n⚠️ Stock bajo (nuevo): {int(s)}\n🚚 Pedir: *{cajas} cajas*\n\n"
                    hay = True
            continue

        # 📦 PRODUCTO NORMAL
        punto_reorden = c * (t + 2)

        if s <= punto_reorden:
            stock_objetivo = c * 15
            cajas = math.ceil((stock_objetivo - s) / u)

            if cajas <= 0:
                cajas = 1

            # 🔥 PRIORIDAD
            if s <= c * (t + 1):
                icono = "🚨"
                estado_txt = "URGENTE"
            else:
                icono = "⚠️"
                estado_txt = "PRONTO"

            txt += f"{icono} *{f['Producto']}*\n"
            txt += f"Estado: {estado_txt}\n"
            txt += f"Stock: {int(s)}\n"
            txt += f"🚚 Pedir: *{cajas} cajas*\n\n"

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

        resultado = buscar_producto_inteligente(prod)

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

    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

# =========================
# SELECCIÓN MÚLTIPLE
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
# NUEVO PRODUCTO
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo_producto_inicio(m):
    estado[m.chat.id] = {"paso": "nombre"}
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

        bot.reply_to(m, f"✅ Producto '{data['nombre']}' agregado.")

        construir_indice()

        del estado[chat_id]

# =========================
# START
# =========================
bot.remove_webhook()
construir_indice()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
