import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN DE APIS
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
# KEEP ALIVE (SERVIDOR)
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
# MOTOR DEL BOT Y SEGURIDAD
# =========================
bot = telebot.TeleBot(TOKEN)
estado = {}
opciones_temp = {}
lock = threading.Lock()

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try:
        x = str(x).replace(',', '.').replace(' ', '').strip()
        if x == '' or x.lower() == 'none': return None
        return float(x)
    except: return None

# =========================
# BÚSQUEDA INTELIGENTE PRO
# =========================
indice = {}
last_update = 0
CACHE_TTL = 60

def invalidar_indice():
    global last_update
    last_update = 0

def normalizar(texto):
    texto = str(texto).lower().strip()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "acción": "accion"}
    for k, v in reemplazos.items(): texto = texto.replace(k, v)
    return texto

def tokenizar(texto):
    texto = normalizar(texto)
    palabras = texto.split()
    tokens = set()
    for p in palabras:
        tokens.add(p)
        if len(p) > 2: tokens.add(p[:3])
        if any(c.isdigit() for c in p): tokens.add(''.join(filter(str.isdigit, p)))
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
                if t not in indice: indice[t] = set()
                indice[t].add(i + 1)
        last_update = time.time()
    except: pass

def obtener_indice():
    global last_update
    if time.time() - last_update > CACHE_TTL: construir_indice()
    return indice

def buscar_producto_inteligente(query):
    idx = obtener_indice()
    palabras = tokenizar(query)
    resultados = None
    for p in palabras:
        if p in idx:
            if resultados is None: resultados = idx[p].copy()
            else: resultados &= idx[p]
    if not resultados: return None
    resultados = list(resultados)
    return resultados[0] if len(resultados) == 1 else resultados[:5]

# =========================
# COMANDOS PRINCIPALES
# =========================

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "cancelar")
def cmd_cancelar(m):
    with lock:
        estado.pop(m.chat.id, None)
        opciones_temp.pop(m.chat.id, None)
    bot.reply_to(m, "❌ Operación cancelada. Estado limpio.")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def cmd_nuevo(m):
    with lock: estado[m.chat.id] = {"modo": "nuevo", "paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("ver "))
def cmd_ver(m):
    prod = m.text[4:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "ver"}
        bot.reply_to(m, "🔍 Selecciona:\n" + "\n".join([f"{i+1}. {stock.cell(f,1).value}" for i,f in enumerate(res)]))
    else: mostrar_detalles(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("editar "))
def cmd_editar(m):
    prod = m.text[7:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "editar"}
        bot.reply_to(m, "📝 Selecciona para editar:\n" + "\n".join([f"{i+1}. {stock.cell(f,1).value}" for i,f in enumerate(res)]))
    else: iniciar_edicion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith("eliminar "))
def cmd_eliminar(m):
    prod = m.text[9:].strip()
    res = buscar_producto_inteligente(prod)
    if not res: bot.reply_to(m, "❌ No encontrado.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": "eliminar"}
        bot.reply_to(m, "🗑️ Selecciona para ELIMINAR:\n" + "\n".join([f"{i+1}. {stock.cell(f,1).value}" for i,f in enumerate(res)]))
    else: ejecutar_eliminacion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "pedidos")
def cmd_pedidos(m):
    try:
        data = stock.get_all_values()
        if len(data) < 2: return
        headers = [h.lower().strip() for h in data[0]]
        # Índices dinámicos: Stock(1), Consumo(8), Tiempo(9), Caja(10), Dias(7)
        idx = {n: headers.index(n) if n in headers else -1 for n in ["stock_actual", "consumo_dia", "tiempo_entrega", "unidades_caja", "dias"]}
        txt, hay = "📦 *PEDIDOS*\n\n", False
        for row in data[1:]:
            s, c, t, u, d = [num(row[idx[k]]) or 0 for k in ["stock_actual", "consumo_dia", "tiempo_entrega", "unidades_caja", "dias"]]
            if (d <= 3 and s < 5) or (c > 0 and s <= (c*t + c*2)):
                cajas = math.ceil(((c*t + c*2 + c*5 if c>0 else 5) - s) / (u if u>0 else 1))
                txt += f"{'🚨' if (c>0 and s <= c*(t+1)) else '⚠️'} {row[0]} → {max(1, cajas)} cajas\n"
                hay = True
        bot.reply_to(m, txt if hay else "✅ Todo al día", parse_mode="Markdown")
    except: bot.reply_to(m, "❌ Error al leer Stock.")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def cmd_movimientos(m):
    try:
        p = m.text.split()
        tipo, cant_str, prod = p[0].lower(), p[-1], " ".join(p[1:-1]).strip()
        cant_val = num(cant_str)
        if cant_val is None: 
            bot.reply_to(m, "❌ Cantidad inválida.")
            return
        res = buscar_producto_inteligente(prod)
        if not res: bot.reply_to(m, "❌ No existe.")
        elif isinstance(res, list):
            with lock: opciones_temp[m.chat.id] = {"opciones": res, "tipo": tipo, "cantidad": cant_val}
            bot.reply_to(m, "⚠️ Selecciona:\n" + "\n".join([f"{i+1}. {stock.cell(f,1).value}" for i,f in enumerate(res)]))
        else: ejecutar_mov(m, res, tipo, cant_val)
    except: bot.reply_to(m, "❌ Formato: [tipo] [nombre] [cantidad]")

# =========================
# LÓGICA DE APOYO
# =========================

def mostrar_detalles(m, fila):
    try:
        f = stock.row_values(fila)
        msg = f"📦 *PRODUCTO:* {f[0].upper()}\n📊 *Stock:* {f[1]}\n📍 *Ub:* P{f[3]}|L{f[4]}|S{f[5]}|N{f[2]}\n📉 *Consumo:* {f[8] if len(f)>8 else '0'}"
        bot.reply_to(m, msg, parse_mode="Markdown")
    except: bot.reply_to(m, "❌ Error detalles.")

def iniciar_edicion(m, fila):
    with lock: estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "nivel"}
    bot.reply_to(m, f"🛠 Editando: *{stock.cell(fila, 1).value}*\n📌 Nivel:")

def ejecutar_mov(m, fila, tipo, cant):
    try:
        nombre = stock.cell(fila, 1).value
        current = num(stock.cell(fila, 2).value) or 0
        v = cant if tipo=="entrada" else (-abs(cant) if tipo=="salida" else cant - current)
        mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), nombre.lower(), tipo.capitalize(), float(v), m.from_user.first_name], value_input_option="RAW")
        bot.reply_to(m, f"✅ {tipo.capitalize()} de *{nombre}* ok.")
    except: bot.reply_to(m, "❌ Error movimiento.")

def ejecutar_eliminacion(m, fila):
    try:
        stock.delete_rows(fila)
        invalidar_indice()
        bot.reply_to(m, "🗑️ Producto eliminado.")
    except: bot.reply_to(m, "❌ Error eliminar.")

# =========================
# MANEJADOR DE PASOS Y SELECCIONES
# =========================

@bot.message_handler(func=lambda m: ok(m) and (m.chat.id in estado or m.chat.id in opciones_temp))
def manejador_pasos(m):
    cid = m.chat.id
    
    if cid in opciones_temp and m.text.isdigit():
        data = opciones_temp[cid]
        idx = int(m.text) - 1
        if 0 <= idx < len(data["opciones"]):
            fila = data["opciones"][idx]
            modo = data.get("modo")
            opciones_temp.pop(cid, None)
            if modo == "editar": iniciar_edicion(m, fila)
            elif modo == "ver": mostrar_detalles(m, fila)
            elif modo == "eliminar": ejecutar_eliminacion(m, fila)
            else: ejecutar_mov(m, fila, data["tipo"], data["cantidad"])
        return

    if cid in estado:
        d = estado[cid]
        modo = d.get("modo")
        
        if modo == "editar":
            pasos = {"nivel": ("C", "pasillo", "➡️ Pasillo:"), "pasillo": ("D", "lado", "↔️ Lado:"), "lado": ("E", "seccion", "🔢 Sección:"), "seccion": ("F", "fin", "✅ Ubicación Editada.")}
            col, sig, msg = pasos[d["paso"]]
            stock.update_acell(f"{col}{d['fila']}", m.text.strip())
            if sig == "fin": estado.pop(cid, None); bot.reply_to(m, msg)
            else: d["paso"] = sig; bot.reply_to(m, msg)

        elif modo == "nuevo":
            pasos_validos = ["nombre","stock","nivel","pasillo","lado","seccion","t","u","e"]
            if d.get("paso") not in pasos_validos:
                estado.pop(cid, None)
                return

            p = d["paso"]
            if p == "nombre": 
                d["n"], d["paso"] = m.text.strip(), "stock"
                bot.reply_to(m, "📦 Stock inicial:")
            
            elif p == "stock":
                val = num(m.text)
                if val is None:
                    bot.reply_to(m, "❌ Valor inválido. Ingresa el stock:")
                    return
                d["s"], d["paso"] = val, "nivel"
                bot.reply_to(m, "📌 Nivel:")
                    
            elif p == "nivel": d["ni"], d["paso"] = m.text.strip(), "pasillo"; bot.reply_to(m, "➡️ Pasillo:")
            elif p == "pasillo": d["pa"], d["paso"] = m.text.strip(), "lado"; bot.reply_to(m, "↔️ Lado:")
            elif p == "lado": d["la"], d["paso"] = m.text.strip(), "seccion"; bot.reply_to(m, "🔢 Sección:")
            elif p == "seccion": d["se"], d["paso"] = m.text.strip(), "t"; bot.reply_to(m, "🚚 Tiempo entrega:")
            
            elif p == "t":
                val = num(m.text)
                if val is None:
                    bot.reply_to(m, "❌ Valor inválido. Tiempo de entrega:")
                    return
                d["t"], d["paso"] = val, "u"
                bot.reply_to(m, "📦 Unidades/Caja:")
                    
            elif p == "u":
                val = num(m.text)
                if val is None:
                    bot.reply_to(m, "❌ Valor inválido. Unidades por caja:")
                    return
                d["u"], d["paso"] = val, "e"
                bot.reply_to(m, "📧 Email:")
                    
            elif p == "e":
                try:
                    fila = len(stock.get_all_values()) + 1
                    
                    # FÓRMULAS EXACTAS SOLICITADAS
                    f_stock = f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)'
                    f_dias = f'=SI.ERROR(MIN(6, HOY() - QUERY(Movimientos!A:D, "select A where B = \'" & A{fila} & "\' order by A asc limit 1", 0)), 0)'
                    f_consumo = f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D, Movimientos!B:B, MINUSC(A{fila}), Movimientos!C:C, "Salida")) / H{fila}, 0)'

                    stock.update(f"A{fila}:K{fila}", [[
                        d['n'], f_stock, d['ni'], d['pa'], d['la'], d['se'], m.text.strip(), 
                        f_dias, f_consumo, d['t'], d['u']
                    ]], value_input_option="USER_ENTERED")
                    
                    estado.pop(cid, None); invalidar_indice(); bot.reply_to(m, "✅ Producto creado.")
                except:
                    bot.reply_to(m, "❌ Error conectando a Sheets.")

# =========================
# LANZAMIENTO
# =========================
bot.remove_webhook()
while True:
    try: bot.polling(none_stop=True)
    except: time.sleep(5)
