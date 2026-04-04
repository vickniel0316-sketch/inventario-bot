import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# VARIABLES
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
CHAT_ID = 6249114480
MI_EMAIL = "miemail@empresa.com"

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Faltan variables de entorno")

# =========================
# GOOGLE SHEETS (CON REINTENTOS)
# =========================
def conectar_sheets():
    intentos = 0
    while intentos < 5:
        try:
            creds_dict = json.loads(GOOGLE_CREDS)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ])
            client = gspread.authorize(creds)
            ss = client.open("inventario_vickniel01")
            return ss.worksheet("Stock"), ss.worksheet("Movimientos")
        except Exception as e:
            intentos += 1
            print(f"⚠️ Error de conexión (Intento {intentos}): {e}")
            time.sleep(5)
    raise Exception("❌ No se pudo conectar a Google Sheets")

stock, mov = conectar_sheets()
print("✅ Sheets conectado")

# =========================
# BOT
# =========================
bot = telebot.TeleBot(TOKEN)

# =========================
# WEB (KEEP ALIVE)
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
# UTILS
# =========================
def ok(m): return m.from_user.id == CHAT_ID
def num(x):
    try: return float(x)
    except: return 0

# =========================
# PEDIDOS
# =========================
def calc_pedidos():
    data = stock.get_all_records()
    res = []
    for f in data:
        p = f.get("Producto","")
        s = num(f.get("Stock_Actual",0))
        c = num(f.get("Consumo_dia",0))
        t = num(f.get("Tiempo_entrega",0))
        u = num(f.get("Unidades_Caja",1))
        if u <= 0: continue
        
        stock_necesario = c * (t + 2)
        if c > 0:
            if s <= stock_necesario:
                cajas = math.ceil(stock_necesario / u)
                res.append((p,s,c,t,cajas))
        else:
            if s <= 3 * u:
                cajas = 3
                res.append((p,s,c,t,cajas))
    return res

def msg_pedidos(lista):
    if not lista: return "✅ Nada que pedir"
    txt = "📦 PEDIDOS:\n\n"
    for p,s,c,t,k in lista:
        txt += f"{p}\nStock:{s} Cons:{c} Ent:{t}\n👉 {k} cajas\n\n"
    return txt

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="pedidos")
def pedidos(m):
    bot.reply_to(m, msg_pedidos(calc_pedidos()))

def auto():
    ultimo=None
    while True:
        try:
            ahora = datetime.now(ZoneInfo("America/Santo_Domingo"))
            if ahora.hour==8 and ultimo!=ahora.date():
                bot.send_message(CHAT_ID, msg_pedidos(calc_pedidos()))
                print("✅ auto enviado")
                ultimo=ahora.date()
        except Exception as e:
            print(f"Error en hilo auto: {e}")
        time.sleep(60)

threading.Thread(target=auto, daemon=True).start()

# =========================
# NUEVO PRODUCTO
# =========================
estado = {}

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="nuevo")
def nuevo(m):
    estado[m.chat.id]={"p":"nombre"}
    bot.reply_to(m,"Nombre del producto:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo(m):
    e = estado[m.chat.id]
    t = m.text
    
    if e["p"] == "nombre":
        e["nombre"] = t
        e["p"] = "stock"
        bot.reply_to(m,"Stock inicial:")
        return
    elif e["p"] == "stock":
        e["stock"] = num(t)
        e["p"] = "nivel"
        bot.reply_to(m,"Nivel:")
        return
    elif e["p"] == "nivel":
        e["nivel"] = "N-" + t
        e["p"] = "pasillo"
        bot.reply_to(m,"Pasillo:")
        return
    elif e["p"] == "pasillo":
        e["pasillo"] = "P-" + t
        e["p"] = "lado"
        bot.reply_to(m,"Lado A/B:")
        return
    elif e["p"] == "lado":
        e["lado"] = t.upper()
        e["p"] = "sec"
        bot.reply_to(m,"Sección:")
        return
    elif e["p"] == "sec":
        e["sec"] = t
        e["p"] = "caja"
        bot.reply_to(m,"Unidades por caja:")
        return
    elif e["p"] == "caja":
        e["caja"] = num(t)
        e["p"] = "tiempo"
        bot.reply_to(m,"Tiempo entrega:")
        return
    elif e["p"] == "tiempo":
        e["tiempo"] = num(t)
        e["p"] = "correo"
        bot.reply_to(m,"Correo del responsable:")
        return
    elif e["p"] == "correo":
        e["correo"] = t
        bot.send_chat_action(m.chat.id, 'typing')
        try:
            # Obtener fila destino
            next_row = len(stock.get_all_values()) + 1
            
            # Fórmulas
            f_stock = f'=SUMAR.SI(Movimientos!B:B, A{next_row}, Movimientos!D:D)'
            
            # Fórmula de la Columna H (Dias) solicitada
            f_dias = f'''=SUMA(1/CONTAR.SI(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7),Movimientos!A:A),SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0)*(Movimientos!A:A>=HOY()-7),Movimientos!A:A)))'''
            
            # Fórmula Consumo_dia
            f_cons = f'''=SI.ERROR(ABS(SUMAR.SI.CONJUNTO(Movimientos!D:D,Movimientos!B:B,A{next_row},Movimientos!D:D,"<0"))/MAX(1,MAX(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A))-MIN(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A))+1),0)'''
            
            # Registro en Stock (A-K)
            fila = [
                e["nombre"],    # A
                f_stock,        # B
                e["nivel"],     # C
                e["pasillo"],   # D
                e["lado"],      # E
                e["sec"],       # F
                e["correo"],    # G
                f_dias,         # H (NUEVA FORMULA)
                f_cons,         # I
                e["tiempo"],    # J
                e["caja"]       # K
            ]
            
            stock.append_row(fila, value_input_option="USER_ENTERED")
            
            # Registro de Stock Inicial en Movimientos
            if e["stock"] > 0:
                mov.append_row([
                    datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), 
                    e["nombre"], 
                    "Carga Inicial", 
                    e["stock"], 
                    m.from_user.first_name
                ], value_input_option="USER_ENTERED")
            
            bot.reply_to(m, f"✅ Producto '{e['nombre']}' creado exitosamente.")
        except Exception as err:
            bot.reply_to(m, f"❌ Error al registrar: {err}")
            print(err)
        del estado[m.chat.id]

# =========================
# MOVIMIENTOS
# =========================
@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower().startswith(("entrada","salida")))
def movs(m):
    p = m.text.split()
    if len(p) < 3: return
    tipo = p[0].lower()
    cant = num(p[-1])
    prod = " ".join(p[1:-1]).lower()
    
    # Validar existencia y registrar
    data = stock.get_all_records()
    for f in data:
        if prod == f.get("Producto","").lower():
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), 
                prod, 
                "", 
                cant if tipo=="entrada" else -cant, 
                m.from_user.first_name
            ], value_input_option="USER_ENTERED")
            bot.reply_to(m, "✅ Movimiento registrado")
            return
    bot.reply_to(m, "❌ Producto no encontrado")

# =========================
# START
# =========================
print("🚀 BOT LISTO")
bot.remove_webhook()
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        time.sleep(5)
