import telebot, gspread, os, json, time, threading, math
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS),
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)
ss = gspread.authorize(creds).open("inventario_vickniel01")
stock, mov = ss.worksheet("Stock"), ss.worksheet("Movimientos")

# =========================
# KEEP ALIVE SERVER
# =========================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler).serve_forever(), daemon=True).start()

# =========================
# MOTOR Y CACHÉ
# =========================
bot = telebot.TeleBot(TOKEN)
estado, opciones_temp, lock = {}, {}, threading.Lock()
idx, data_cache, last_update = {}, {}, 0

def ok(m): return m.from_user.id == CHAT_ID

def num(x):
    try: return float(str(x).replace(',', '.').replace(' ', '')) if str(x).strip().lower() not in ['', 'none'] else None
    except: return None

def get_indice():
    global idx, data_cache, last_update
    if time.time() - last_update > 60:
        data_cache = {i+2: r for i, r in enumerate(stock.get_all_values()[1:])}
        n_idx = {}
        for f, r in data_cache.items():
            for p in str(r[0]).lower().translate(str.maketrans('áéíóú', 'aeiou')).split():
                n_idx.setdefault(p, set()).add(f)
                if len(p) > 2: n_idx.setdefault(p[:3], set()).add(f)
                if any(c.isdigit() for c in p): n_idx.setdefault(''.join(filter(str.isdigit, p)), set()).add(f)
        idx, last_update = n_idx, time.time()
    return idx

def buscar(query):
    idx_act = get_indice()
    res = None
    for p in str(query).lower().translate(str.maketrans('áéíóú', 'aeiou')).split():
        res_parcial = {f for k, f_set in idx_act.items() if p in k for f in f_set}
        res = res_parcial if res is None else res & res_parcial
    if not res: return None
    res = list(res)
    return res[0] if len(res) == 1 else res[:5]

def invalidar():
    global last_update; last_update = 0

# =========================
# COMANDOS PRINCIPALES
# =========================
@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "cancelar")
def cmd_cancel(m):
    with lock: estado.pop(m.chat.id, None); opciones_temp.pop(m.chat.id, None)
    bot.reply_to(m, "❌ Operación cancelada.")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "nuevo")
def cmd_nuevo(m):
    with lock: estado[m.chat.id] = {"modo": "nuevo", "paso": "nombre"}
    bot.reply_to(m, "📝 Nombre del producto:")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("ver ", "editar ", "eliminar ")))
def cmd_acciones(m):
    cmd, prod = m.text.split(" ", 1)
    cmd = cmd.lower()
    res = buscar(prod.strip())
    
    if not res: return bot.reply_to(m, "❌ No encontrado.")
    if isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "modo": cmd}
        iconos = {"ver": "🔍", "editar": "📝", "eliminar": "🗑️"}
        msg = f"{iconos.get(cmd, '⚠️')} Selecciona para {cmd.upper()}:\n" + "\n".join([f"{i+1}. {data_cache.get(f, ['???'])[0]}" for i, f in enumerate(res)])
        bot.reply_to(m, msg)
    else:
        if cmd == "ver": mostrar_detalles(m, res)
        elif cmd == "editar": iniciar_edicion(m, res)
        elif cmd == "eliminar": ejecutar_eliminacion(m, res)

@bot.message_handler(func=lambda m: ok(m) and m.text.lower() == "pedidos")
def cmd_pedidos(m):
    get_indice()
    if not data_cache: return
    txt, hay = "📦 *PEDIDOS*\n\n", False
    
    for r in data_cache.values():
        if len(r) < 11: continue
        nom, st, d, co, t, u = r[0], num(r[1]) or 0, num(r[7]) or 0, num(r[8]) or 0, num(r[9]) or 0, num(r[10]) or 1
        incluir, cajas = False, 0
        
        if d <= 3:
            if (st / u) < 5:
                cajas, incluir = math.ceil(5 - (st / u)), True
        elif co > 0:
            pr = (co * t) + (co * 2)
            if st <= pr:
                cajas, incluir = max(1, math.ceil(((pr + (co * 5)) - st) / u)), True
        
        if incluir:
            txt += f"{'🚨' if d <= 3 else '⚠️'} {nom} → {cajas} cajas\n"
            hay = True
            
    bot.reply_to(m, txt if hay else "✅ Todo al día", parse_mode="Markdown")

@bot.message_handler(func=lambda m: ok(m) and m.text.lower().startswith(("entrada", "salida", "ajuste")))
def cmd_movimientos(m):
    p = m.text.split()
    if len(p) < 3: return bot.reply_to(m, "❌ Formato: `[tipo] [producto] [cantidad]`")
    tipo, cant, prod = p[0].lower(), num(p[-1]), " ".join(p[1:-1]).strip()
    if cant is None: return bot.reply_to(m, "❌ Cantidad inválida.")
    
    res = buscar(prod)
    if not res: return bot.reply_to(m, "❌ No existe.")
    if isinstance(res, list):
        with lock: opciones_temp[m.chat.id] = {"opciones": res, "tipo": tipo, "cantidad": cant}
        bot.reply_to(m, "⚠️ Selecciona:\n" + "\n".join([f"{i+1}. {data_cache.get(f, ['???'])[0]}" for i, f in enumerate(res)]))
    else: ejecutar_mov(m, res, tipo, cant)

# =========================
# FUNCIONES DE APOYO
# =========================
def mostrar_detalles(m, fila):
    f = data_cache.get(fila)
    if f: bot.reply_to(m, f"📦 *{f[0].upper()}*\n📊 *Stock_Actual:* {f[1]}\n📍 *Ubicacion:* P{f[3]}|L{f[4]}|S{f[5]}|N{f[2]}\n📉 *Consumo:* {f[8] if len(f)>8 else '0'}", parse_mode="Markdown")

def iniciar_edicion(m, fila):
    with lock: estado[m.chat.id] = {"modo": "editar", "fila": fila, "paso": "menu"}
    bot.reply_to(m, f"🛠 *Editando:* {data_cache.get(fila, ['???'])[0]}\n\n1. 📍 Ubicación\n2. 📧 Correo\n3. 🚚 Tiempo de entrega", parse_mode="Markdown")

def ejecutar_eliminacion(m, fila):
    stock.delete_rows(fila); invalidar(); bot.reply_to(m, "🗑️ Producto eliminado.")

def ejecutar_mov(m, fila, tipo, cant):
    f_data = data_cache.get(fila)
    nom, actual = f_data[0], num(f_data[1]) or 0
    v_final = abs(cant) if tipo == "entrada" else -abs(cant) if tipo == "salida" else (cant - actual)
    
    ahora = datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S")
    mov.append_row([ahora, nom.lower(), tipo.capitalize(), float(v_final), m.from_user.first_name], value_input_option="USER_ENTERED")
    invalidar()
    bot.reply_to(m, f"✅ {tipo.capitalize()} de *{nom}* registrada ({v_final}).", parse_mode="Markdown")

# =========================
# MANEJADOR DE PASOS
# =========================
@bot.message_handler(func=lambda m: ok(m) and (m.chat.id in estado or m.chat.id in opciones_temp))
def manejador(m):
    cid, txt = m.chat.id, m.text.strip()
    
    if cid in opciones_temp and txt.isdigit():
        d = opciones_temp[cid]
        idx_op = int(txt) - 1
        if 0 <= idx_op < len(d["opciones"]):
            fila = d["opciones"][idx_op]
            with lock: opciones_temp.pop(cid, None)
            if d.get("modo") == "ver": mostrar_detalles(m, fila)
            elif d.get("modo") == "editar": iniciar_edicion(m, fila)
            elif d.get("modo") == "eliminar": ejecutar_eliminacion(m, fila)
            else: ejecutar_mov(m, fila, d["tipo"], d["cantidad"])
        return

    if cid in estado:
        d = estado[cid]
        if d.get("modo") == "editar":
            p = d["paso"]
            if p == "menu":
                if txt == "1": d["paso"] = "nivel"; bot.reply_to(m, "📌 Nuevo Nivel:")
                elif txt == "2": d["paso"] = "solo_email"; bot.reply_to(m, "📧 Nuevo Correo:")
                elif txt == "3": d["paso"] = "solo_tiempo"; bot.reply_to(m, "🚚 Nuevo Tiempo:")
                else: bot.reply_to(m, "❌ 1, 2 o 3.")
                return
            
            rutas = {"nivel": ("C", "pasillo", "➡️ Pasillo:"), "pasillo": ("D", "lado", "↔️ Lado:"), "lado": ("E", "seccion", "🔢 Sección:"), "seccion": ("F", "fin", "✅ Ubicación actualizada."), "solo_email": ("G", "fin", "✅ Correo actualizado."), "solo_tiempo": ("J", "fin", "✅ Tiempo actualizado.")}
            if p in rutas:
                if p == "solo_tiempo" and num(txt) is None: return bot.reply_to(m, "❌ Número:")
                col, sig, msg_ok = rutas[p]
                stock.update_acell(f"{col}{d['fila']}", txt)
                if sig == "fin":
                    with lock: estado.pop(cid, None)
                    invalidar(); bot.reply_to(m, msg_ok)
                else:
                    d["paso"] = sig; bot.reply_to(m, msg_ok)

        elif d.get("modo") == "nuevo":
            pasos = ["nombre", "stock", "nivel", "pasillo", "lado", "seccion", "t", "u", "e"]
            msjs = {"stock":"📦 Stock inicial:", "nivel":"📌 Nivel:", "pasillo":"➡️ Pasillo:", "lado":"↔️ Lado:", "seccion":"🔢 Sección:", "t":"🚚 Tiempo entrega:", "u":"📦 Unidades/Caja:", "e":"📧 Email:"}
            p = d["paso"]
            
            if p in ["stock", "t", "u"] and num(txt) is None: return bot.reply_to(m, "❌ Debe ser número:")
            d[p] = num(txt) if p in ["stock", "t", "u"] else txt
            
            if p != "e":
                sig = pasos[pasos.index(p)+1]
                d["paso"] = sig
                bot.reply_to(m, msjs[sig])
            else:
                fila = len(stock.get_all_values()) + 1
                f_st = f'=SI.ERROR(SUMAR.SI(Movimientos!B:B, A{fila}, Movimientos!D:D), 0)'
                f_di = f'=SI.ERROR(DIAS.LAB.INTL(MAX(HOY()-7, MIN(FILTER(Movimientos!A:A, Movimientos!B:B=A{fila}))), HOY(), 11)-1, 0)'
                f_co = f'=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D, Movimientos!B:B, MINUSC(A{fila}), Movimientos!C:C, "Salida")) / H{fila}, 0)'
                
                stock.update(values=[[d['nombre'], f_st, d['nivel'], d['pasillo'], d['lado'], d['seccion'], txt, f_di, f_co, d['t'], d['u']]], range_name=f"A{fila}:K{fila}", value_input_option="USER_ENTERED")
                
                ahora = datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S")
                mov.append_row([ahora, d['nombre'].lower(), "Entrada", float(abs(d['stock'])), f"Sistema ({m.from_user.first_name})"], value_input_option="USER_ENTERED")
                
                with lock: estado.pop(cid, None)
                invalidar(); bot.reply_to(m, "✅ Producto creado.")

# =========================
# INICIO
# =========================
bot.remove_webhook()
while True:
    try: bot.polling(none_stop=True)
    except: time.sleep(5)
