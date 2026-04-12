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

# MEJORA 1: num() ahora sí devuelve None para validaciones reales
def num(x):
    if x is None: return None
    try:
        x = str(x).replace(',', '.').replace(' ', '').strip()
        if x == '' or x.lower() == 'none': return None
        return float(x)
    except (ValueError, TypeError):
        return None

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

# MEJORA 3: Evitamos .cell() en loops usando lectura masiva
def construir_indice():
    global indice, last_update
    try:
        data = stock.get_all_values()
        nuevo_indice = {}
        for i in range(1, len(data)):
            tokens = tokenizar(data[i][0])
            for t in tokens:
                if t not in nuevo_indice: nuevo_indice[t] = set()
                nuevo_indice[t].add(i + 1)
        indice = nuevo_indice
        last_update = time.time()
    except Exception as e:
        print(f"DEBUG: Error construyendo índice: {e}")

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
# FUNCIONES DE APOYO
# =========================

def mostrar_detalles(m, fila):
    try:
        f = stock.row_values(fila)
        msg = f"📦 *PRODUCTO:* {f[0].upper()}\n📊 *Stock:* {f[1]}\n📍 *Ub:* P{f[3]}|L{f[4]}|S{f[5]}|N{f[2]}\n📉 *Consumo:* {f[8] if len(f)>8 else '0'}"
        bot.reply_to(m, msg, parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(m, "❌ Error al obtener detalles.")

def iniciar_edicion(m, fila):
    try:
        nombre = stock.cell(fila, 1).value
        with lock:
            estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "menu"}
        
        menu = (f"🛠 *Editando:* {nombre}\n\n"
                "1️⃣ Ubicación (Nivel, Pasillo, Lado, Sec)\n"
                "2️⃣ Unidades por Caja\n"
                "3️⃣ Tiempo de Entrega\n"
                "4️⃣ Correo (Email)\n\n"
                "Elige una opción o /cancelar")
        bot.reply_to(m, menu, parse_mode="Markdown")
    except:
        bot.reply_to(m, "❌ Error al conectar con la base de datos.")

def ejecutar_mov(m, fila, tipo, cant):
    try:
        # MEJORA 3: row_values(fila) para no hacer .cell() varias veces
        fila_data = stock.row_values(fila)
        nombre = fila_data[0]
        current = num(fila_data[1]) or 0
        
        if tipo == "entrada":
            valor_final = abs(cant)
            etiqueta = "Entrada"
        elif tipo == "salida":
            valor_final = -abs(cant)
            etiqueta = "Salida"
        else:
            valor_final = cant - current
            etiqueta = "Ajuste"
        
        ahora = datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S")
        mov.append_row([ahora, nombre.lower(), etiqueta, float(valor_final), m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ {etiqueta} de *{nombre}* ok ({valor_final}).")
    except Exception as e:
        bot.reply_to(m, f"❌ Error: {str(e)}")

# =========================
# COMANDOS
# =========================

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("entrada","salida","ajuste")))
def cmd_movimientos(m):
    p = m.text.split()
    # MEJORA 2: Validación de longitud de split()
    if len(p) < 3:
        bot.reply_to(m, "❌ Formato: `tipo producto cantidad` (Ej: entrada arroz 10)")
        return

    tipo = p[0].lower()
    cant_val = num(p[-1])
    prod = " ".join(p[1:-1]).strip()

    if cant_val is None:
        bot.reply_to(m, "❌ Cantidad inválida.")
        return

    res = buscar_producto_inteligente(prod)
    if not res:
        bot.reply_to(m, "❌ No existe.")
    elif isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "tipo": tipo, "cantidad": cant_val}
        # Solo usamos cell() aquí porque son máximo 5 llamadas controladas
        bot.reply_to(m, "⚠️ Selecciona:\n" + "\n".join([f"{i+1}. {stock.cell(f,1).value}" for i,f in enumerate(res)]))
    else:
        ejecutar_mov(m, res, tipo, cant_val)

# ... (Demás comandos Ver, Editar, Eliminar integrados con la misma lógica)

# =========================
# MANEJADOR DE PASOS (INTEGRADO)
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
            elif modo == "eliminar": 
                stock.delete_rows(fila)
                invalidar_indice()
                bot.reply_to(m, "🗑️ Eliminado.")
            else: ejecutar_mov(m, fila, data["tipo"], data["cantidad"])
        return

    if cid in estado:
        d = estado[cid]
        if d["modo"] == "editar":
            p = d["paso"]
            if p == "menu":
                if m.text == "1": d["paso"] = "nivel"; bot.reply_to(m, "📌 Nuevo Nivel:")
                elif m.text == "2": d["paso"] = "u_caja"; bot.reply_to(m, "📦 Unidades/Caja:")
                elif m.text == "3": d["paso"] = "t_entrega"; bot.reply_to(m, "🚚 Tiempo entrega:")
                elif m.text == "4": d["paso"] = "email"; bot.reply_to(m, "📧 Nuevo Email:")
                else: bot.reply_to(m, "❌ Elige 1, 2, 3 o 4.")
            
            elif p == "nivel": d["ni"], d["paso"] = m.text.strip(), "pasillo"; bot.reply_to(m, "➡️ Pasillo:")
            elif p == "pasillo": d["pa"], d["paso"] = m.text.strip(), "lado"; bot.reply_to(m, "↔️ Lado:")
            elif p == "lado": d["la"], d["paso"] = m.text.strip(), "seccion"; bot.reply_to(m, "🔢 Sección:")
            elif p == "seccion":
                stock.update(values=[[d["ni"], d["pa"], d["la"], m.text.strip()]], range_name=f"C{d['fila']}:F{d['fila']}", value_input_option="USER_ENTERED")
                estado.pop(cid, None); bot.reply_to(m, "✅ Ubicación ok.")
            elif p in ["u_caja", "t_entrega", "email"]:
                col = {"u_caja":"K", "t_entrega":"J", "email":"G"}[p]
                stock.update_acell(f"{col}{d['fila']}", m.text.strip())
                estado.pop(cid, None); bot.reply_to(m, "✅ Actualizado.")

# =========================
# LANZAMIENTO
# =========================
bot.remove_webhook()
while True:
    try: bot.polling(none_stop=True)
    except Exception as e:
        print(f"CRASH: {e}")
        time.sleep(5)
