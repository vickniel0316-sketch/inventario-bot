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
# KEEP ALIVE
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
# BOT
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try:
        return float(str(x).replace(',', '.').strip())
    except:
        return 0

# =========================
# BUSQUEDA INTELIGENTE
# =========================
indice = {}
last_update = 0
CACHE_TTL = 60

def invalidar_indice():
    global last_update
    last_update = 0

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
    global indice, last_update
    data = stock.get_all_values()
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
            with lock:
                opciones_temp[m.chat.id] = {"opciones": resultado[:5], "tipo": tipo, "cantidad": cant}

            texto = "⚠️ Varias coincidencias:\n\n"
            for i, f in enumerate(resultado[:5], 1):
                nombre = stock.cell(f, 1).value
                texto += f"{i}. {nombre}\n"
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
            float(valor),
            m.from_user.first_name
        ], value_input_option="RAW")

        bot.reply_to(m, f"✅ {tipo_txt} aplicado a *{prod_real}*.", parse_mode="Markdown")

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error")

# =========================
# 📦 PEDIDOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower() == "pedidos")
def pedidos(m):
    data = stock.get_all_values()

    if not data or len(data) < 2:
        bot.reply_to(m, "❌ No hay datos en Stock")
        return

    headers = data[0]

    # 🔎 búsqueda flexible de columnas
    def col(name):
        name = name.strip().lower()
        for i, h in enumerate(headers):
            if h.strip().lower() == name:
                return i
        return -1

    i_stock = col("Stock_Actual")
    i_cons = col("Consumo_dia")
    i_tiempo = col("Tiempo_entrega")
    i_caja = col("Unidades_Caja")
    i_dias = col("Dias")

    txt = "📦 *PEDIDOS*\n\n"
    hay = False

    for i in range(1, len(data)):
        row = data[i]

        def get(idx):
            if idx == -1 or idx >= len(row):
                return 0
            return num(row[idx])

        s = get(i_stock)
        c = get(i_cons)
        t = get(i_tiempo)
        u = get(i_caja)
        d = get(i_dias)

        producto = row[0]

        # 🔧 NORMALIZACIÓN
        if u <= 0:
            u = 1

        if d <= 0:
            d = 999

        # 🆕 PRODUCTOS NUEVOS
        if d <= 3:
            if s < 5:
                cajas = math.ceil((5 - s) / u)
                txt += f"🆕 {producto} → {cajas} cajas\n"
                hay = True
            continue

        # ⚠️ sin consumo no se evalúa
        if c <= 0:
            continue

        # 📦 LÓGICA DE REPOSICIÓN
        punto = (c * t) + (c * 2)

        if s <= punto:
            objetivo = (c * t) + (c * 2) + (c * 5)
            cajas = math.ceil((objetivo - s) / u)

            if cajas < 1:
                cajas = 1

            estado_txt = "🚨 URGENTE" if s <= c * (t + 1) else "⚠️ PRONTO"

            txt += f"{estado_txt} {producto} → {cajas} cajas\n"
            hay = True

    bot.reply_to(m, txt if hay else "✅ Sin reposición", parse_mode="Markdown")

# =========================
# SELECCION MULTIUSO
# =========================
@bot.message_handler(func=lambda m: m.chat.id in opciones_temp and ok(m))
def seleccionar(m):
    try:
        data = opciones_temp[m.chat.id]
        idx = int(m.text.strip()) - 1

        if idx < 0 or idx >= len(data["opciones"]):
            bot.reply_to(m, "❌ Opción inválida")
            return

        fila = data["opciones"][idx]

        if data.get("modo") == "editar":
            with lock:
                estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "nivel"}
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "📌 Nivel:")
            return

        if data.get("modo") == "eliminar":
            stock.delete_rows(fila)
            invalidar_indice()
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "🗑️ Eliminado")
            return

        tipo = data["tipo"]
        cant = data["cantidad"]

        prod_real = stock.cell(fila, 1).value

        if tipo == "entrada":
            valor = cant
        elif tipo == "salida":
            valor = -abs(cant)
        elif tipo == "ajuste":
            stock_actual = num(stock.cell(fila, 2).value)
            valor = cant - stock_actual

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod_real.lower(),
            tipo,
            float(valor),
            m.from_user.first_name
        ], value_input_option="RAW")

        del opciones_temp[m.chat.id]
        bot.reply_to(m, "✅ Movimiento aplicado")

    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error selección")

# =========================
# NUEVO PRODUCTO
# =========================
def safe_num(text):
    try:
        return float(text)
    except:
        return 0
        
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    with lock:
        estado[m.chat.id] = {"paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")


@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado and estado[m.chat.id].get("modo") != "editar")
def flujo_nuevo(m):
    chat_id = m.chat.id
    data = estado.get(chat_id)

    if not data:
        return

    paso = data.get("paso")
   
    if paso == "nombre":
        data["nombre"] = m.text.strip()
        data["paso"] = "stock"
        bot.reply_to(m, "📦 Stock inicial:")
        return

    if paso == "stock":
        data["stock"] = safe_num(m.text)
        data["paso"] = "nivel"
        bot.reply_to(m, "📌 Nivel:")
        return

    if paso == "nivel":
        data["nivel"] = m.text.strip()
        data["paso"] = "pasillo"
        bot.reply_to(m, "➡️ Pasillo:")
        return

    if paso == "pasillo":
        data["pasillo"] = m.text.strip()
        data["paso"] = "lado"
        bot.reply_to(m, "↔️ Lado:")
        return

    if paso == "lado":
        data["lado"] = m.text.strip()
        data["paso"] = "seccion"
        bot.reply_to(m, "🔢 Sección:")
        return

    if paso == "seccion":
        data["seccion"] = m.text.strip()
        data["paso"] = "tiempo_entrega"
        bot.reply_to(m, "🚚 Tiempo entrega:")
        return

    if paso == "tiempo_entrega":
        data["tiempo_entrega"] = safe_num(m.text)
        data["paso"] = "unidades_caja"
        bot.reply_to(m, "📦 Unidades por caja:")
        return

    if paso == "unidades_caja":
        data["unidades_caja"] = safe_num(m.text)
        data["paso"] = "email"
        bot.reply_to(m, "📧 Email:")
        return

    if paso == "email":
        data["email"] = m.text.strip()

        fila = len(stock.get_all_values()) + 1

        try:
            stock.update(f"A{fila}:K{fila}", [[
                data.get("nombre", ""),
                f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)',
                data.get("nivel", ""),
                data.get("pasillo", ""),
                data.get("lado", ""),
                data.get("seccion", ""),
                data.get("email", ""),
                f'=SI.ERROR(MIN(6, HOY() - MIN(FILTRAR(Movimientos!A:A, Movimientos!B:B = A{fila}))), 0)',
                f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D,Movimientos!B:B,A{fila},Movimientos!C:C,"Salida"))/H{fila},0)',
                data.get("tiempo_entrega", 0),
                data.get("unidades_caja", 0)
            ]], value_input_option="USER_ENTERED")

        except Exception as e:
            bot.reply_to(m, f"❌ Error al guardar: {e}")
            return

        with lock:
            if chat_id in estado:
                del estado[chat_id]

        invalidar_indice()

        bot.reply_to(m, "✅ Producto creado correctamente")
        return
# =========================
# EDITAR
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado)
def flujo_editar(m):

    d = estado.get(m.chat.id)

    if not d:
        return

    if d.get("modo") != "editar":
        return

    fila = d.get("fila")
    paso = d.get("paso")

    if not fila or not paso:
        bot.reply_to(m, "⚠️ Estado inválido. Reinicia edición.")
        estado.pop(m.chat.id, None)
        return

    pasos = {
        "nivel": ("C", "pasillo", "➡️ Pasillo:"),
        "pasillo": ("D", "lado", "↔️ Lado:"),
        "lado": ("E", "seccion", "🔢 Sección:")
    }

    if paso not in pasos:
        bot.reply_to(m, f"⚠️ Paso desconocido: {paso}")
        estado.pop(m.chat.id, None)
        return

    col, next_step, msg = pasos[paso]

    try:
        stock.update_acell(f"{col}{fila}", m.text)
    except Exception as e:
        bot.reply_to(m, f"❌ Error Sheets: {e}")
        return

    # avanzar paso
    d["paso"] = next_step

    # responder siguiente campo
    bot.reply_to(m, msg)

    # cerrar flujo cuando ya no hay más pasos
    if next_step not in pasos:
        invalidar_indice()
        estado.pop(m.chat.id, None)
        bot.reply_to(m, "✅ Editado correctamente")
        return
# =========================
# ELIMINAR
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("eliminar "))
def eliminar(m):
    nombre = m.text.replace("eliminar", "").strip()

    resultado = buscar_producto_inteligente(nombre)

    if resultado is None:
        bot.reply_to(m, "❌ No encontrado")
        return

    if isinstance(resultado, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": resultado[:5], "modo": "eliminar"}

        texto = "⚠️ Varias coincidencias:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            nombre = stock.cell(f, 1).value
            texto += f"{i}. {nombre}\n"
        texto += "\nResponde con el número."
        bot.reply_to(m, texto)
        return

    stock.delete_rows(resultado)
    invalidar_indice()

    bot.reply_to(m, "🗑️ Eliminado")

# =========================
# START
# =========================
bot.remove_webhook()

while True:
    try:
        bot.polling(none_stop=True)
    except:
        time.sleep(5)
