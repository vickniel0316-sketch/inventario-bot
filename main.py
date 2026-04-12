import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import math
from zoneinfo import ZoneInfo
import threading

# Configuración inicial
TOKEN = "TU_TELEGRAM_BOT_TOKEN"
bot = telebot.TeleBot(TOKEN)
lock = threading.Lock()

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("tu_archivo_credenciales.json", scope)
client = gspread.authorize(creds)
sheet = client.open("Nombre de tu Hoja")
stock = sheet.worksheet("Stock")
mov = sheet.worksheet("Movimientos")

# Variables de control
CACHE_TTL = 300
indice = {}
last_update = 0
opciones_temp = {}
estado = {}

# =========================
# FUNCIONES DE APOYO
# =========================
def ok(m):
    # Aquí puedes agregar validación de usuarios permitidos
    return True

def num(x):
    try:
        return float(str(x).replace(",", "."))
    except:
        return 0

def invalidar_indice():
    global last_update
    last_update = 0

def tokenizar(texto):
    tokens = set()
    palabras = texto.lower().split()
    for p in palabras:
        if len(p) > 2:
            tokens.add(p)
        if any(char.isdigit() for char in p):
            tokens.add(''.join(filter(str.isdigit, p)))
    return tokens

def construir_indice():
    global indice, last_update
    try:
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
    except Exception as e:
        print(f"Error construyendo índice: {e}")

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
# MOVIMIENTOS (Entrada, Salida, Ajuste)
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
        bot.reply_to(m, "❌ Error procesando movimiento")

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
    def col(name):
        name = name.strip().lower()
        for i, h in enumerate(headers):
            if h.strip().lower() == name: return i
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
            if idx == -1 or idx >= len(row): return 0
            return num(row[idx])

        s, c, t, u, d = get(i_stock), get(i_cons), get(i_tiempo), get(i_caja), get(i_dias)
        producto = row[0]

        if u <= 0: u = 1
        if d <= 0: d = 999

        if d <= 3:
            if s < 5:
                cajas = math.ceil((5 - s) / u)
                txt += f"🆕 {producto} → {cajas} cajas\n"
                hay = True
            continue

        if c <= 0: continue

        punto = (c * t) + (c * 2)
        if s <= punto:
            objetivo = (c * t) + (c * 2) + (c * 5)
            cajas = math.ceil((objetivo - s) / u)
            if cajas < 1: cajas = 1
            estado_txt = "🚨 URGENTE" if s <= c * (t + 1) else "⚠️ PRONTO"
            txt += f"{estado_txt} {producto} → {cajas} cajas\n"
            hay = True

    bot.reply_to(m, txt if hay else "✅ Sin reposición", parse_mode="Markdown")

# =========================
# EDITAR (INICIO)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("editar "))
def comando_editar(m):
    nombre = m.text.replace("editar", "").strip()
    resultado = buscar_producto_inteligente(nombre)

    if resultado is None:
        bot.reply_to(m, "❌ No encontrado")
        return

    if isinstance(resultado, list):
        with lock:
            opciones_temp[m.chat.id] = {"opciones": resultado[:5], "modo": "editar"}
        texto = "🔍 Selecciona para EDITAR:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            texto += f"{i}. {stock.cell(f, 1).value}\n"
        bot.reply_to(m, texto)
        return

    with lock:
        estado[m.chat.id] = {"modo": "editar", "fila": resultado, "paso": "nivel"}
    bot.reply_to(m, f"📝 Editando: *{stock.cell(resultado, 1).value}*\n📌 Nuevo Nivel:", parse_mode="Markdown")

# =========================
# SELECCION MULTIUSO (Entrada, Salida, Ajuste, Editar, Eliminar)
# =========================
@bot.message_handler(func=lambda m: m.chat.id in opciones_temp and ok(m) and m.text.isdigit())
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
            bot.reply_to(m, "📌 Nuevo Nivel:")
            return

        if data.get("modo") == "eliminar":
            stock.delete_rows(fila)
            invalidar_indice()
            del opciones_temp[m.chat.id]
            bot.reply_to(m, "🗑️ Eliminado")
            return

        tipo, cant = data["tipo"], data["cantidad"]
        prod_real = stock.cell(fila, 1).value
        
        if tipo == "entrada": valor = cant
        elif tipo == "salida": valor = -abs(cant)
        elif tipo == "ajuste": valor = cant - num(stock.cell(fila, 2).value)

        mov.append_row([
            datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
            prod_real.lower(), tipo.capitalize(), float(valor), m.from_user.first_name
        ], value_input_option="RAW")

        del opciones_temp[m.chat.id]
        bot.reply_to(m, "✅ Movimiento aplicado")
    except Exception as e:
        print(e)
        bot.reply_to(m, "❌ Error en selección")

# =========================
# FLUJO DE EDICION (PASO A PASO)
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado and estado[m.chat.id].get("modo") == "editar")
def flujo_editar(m):
    d = estado.get(m.chat.id)
    fila = d.get("fila")
    paso = d.get("paso")

    pasos = {
        "nivel": ("C", "pasillo", "➡️ Pasillo:"),
        "pasillo": ("D", "lado", "↔️ Lado:"),
        "lado": ("E", "seccion", "🔢 Sección:"),
        "seccion": ("F", "final", "✅ Editado correctamente")
    }

    if paso not in pasos: return
    col, next_step, msg = pasos[paso]

    try:
        stock.update_acell(f"{col}{fila}", m.text.strip())
        if next_step == "final":
            invalidar_indice()
            estado.pop(m.chat.id, None)
            bot.reply_to(m, msg)
        else:
            d["paso"] = next_step
            bot.reply_to(m, msg)
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {e}")

# =========================
# NUEVO PRODUCTO
# =========================
def safe_num(text):
    try: return float(text)
    except: return 0
        
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def nuevo(m):
    with lock:
        estado[m.chat.id] = {"paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.chat.id in estado and estado[m.chat.id].get("modo") != "editar")
def flujo_nuevo(m):
    chat_id = m.chat.id
    data = estado.get(chat_id)
    if not data: return
    paso = data.get("paso")
   
    if paso == "nombre":
        data["nombre"], data["paso"] = m.text.strip(), "stock"
        bot.reply_to(m, "📦 Stock inicial:")
    elif paso == "stock":
        data["stock"], data["paso"] = safe_num(m.text), "nivel"
        bot.reply_to(m, "📌 Nivel:")
    elif paso == "nivel":
        data["nivel"], data["paso"] = m.text.strip(), "pasillo"
        bot.reply_to(m, "➡️ Pasillo:")
    elif paso == "pasillo":
        data["pasillo"], data["paso"] = m.text.strip(), "lado"
        bot.reply_to(m, "↔️ Lado:")
    elif paso == "lado":
        data["lado"], data["paso"] = m.text.strip(), "seccion"
        bot.reply_to(m, "🔢 Sección:")
    elif paso == "seccion":
        data["seccion"], data["paso"] = m.text.strip(), "tiempo_entrega"
        bot.reply_to(m, "🚚 Tiempo entrega:")
    elif paso == "tiempo_entrega":
        data["tiempo_entrega"], data["paso"] = safe_num(m.text), "unidades_caja"
        bot.reply_to(m, "📦 Unidades por caja:")
    elif paso == "unidades_caja":
        data["unidades_caja"], data["paso"] = safe_num(m.text), "email"
        bot.reply_to(m, "📧 Email:")
    elif paso == "email":
        data["email"] = m.text.strip()
        fila = len(stock.get_all_values()) + 1
        try:
            stock.update(f"A{fila}:K{fila}", [[
                data.get("nombre", ""),
                f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)',
                data.get("nivel", ""), data.get("pasillo", ""), data.get("lado", ""),
                data.get("seccion", ""), data.get("email", ""),
                f'=SI.ERROR(MIN(6, HOY() - MIN(FILTRAR(Movimientos!A:A, Movimientos!B:B = A{fila}))), 0)',
                f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D,Movimientos!B:B,A{fila},Movimientos!C:C,"Salida"))/H{fila},0)',
                data.get("tiempo_entrega", 0), data.get("unidades_caja", 0)
            ]], value_input_option="USER_ENTERED")
            
            # Registrar stock inicial como una entrada si es > 0
            if data["stock"] > 0:
                mov.append_row([
                    datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                    data["nombre"].lower(), "Entrada", data["stock"], m.from_user.first_name
                ], value_input_option="RAW")

        except Exception as e:
            bot.reply_to(m, f"❌ Error al guardar: {e}")
            return

        with lock:
            if chat_id in estado: del estado[chat_id]
        invalidar_indice()
        bot.reply_to(m, "✅ Producto creado correctamente")

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
        texto = "🗑️ Selecciona para ELIMINAR:\n\n"
        for i, f in enumerate(resultado[:5], 1):
            texto += f"{i}. {stock.cell(f, 1).value}\n"
        bot.reply_to(m, texto)
        return
    
    stock.delete_rows(resultado)
    invalidar_indice()
    bot.reply_to(m, "🗑️ Eliminado")

if __name__ == "__main__":
    print("Bot en marcha...")
    bot.infinity_polling()
