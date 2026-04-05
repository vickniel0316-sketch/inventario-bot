import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json, time, threading, math
from http.server import BaseHTTPRequestHandler, HTTPServer

# =========================
# CONFIGURACIÓN Y ENTORNO
# =========================
TOKEN = os.getenv("TOKEN")
GOOGLE_CREDS = os.getenv("GOOGLE_CREDS")
ADMIN_IDS = [6249114480] # Tu ID de Telegram

if not TOKEN or not GOOGLE_CREDS:
    raise Exception("❌ Faltan variables de entorno: TOKEN o GOOGLE_CREDS")

# =========================
# CONEXIÓN A GOOGLE SHEETS
# =========================
def conectar_sheets():
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
        print(f"❌ Error conectando a Sheets: {e}")
        return None, None

stock, mov = conectar_sheets()

# =========================
# FUNCIONES AUXILIARES
# =========================
def num(x):
    try:
        return float(str(x).replace(',', '.'))
    except:
        return 0

def es_admin(m):
    return m.from_user.id in ADMIN_IDS

# Diccionario para estados de flujos (Nuevo, Eliminar, etc.)
estados_espera = {}

# =========================
# LÓGICA DE PEDIDOS (3 + 1)
# =========================
def calc_pedidos():
    try:
        data = stock.get_all_records()
        res = []
        tolerancia = 2
        for f in data:
            p = f.get("Producto", "")
            s = num(f.get("Stock_Actual", 0))
            c = num(f.get("Consumo_dia", 0))
            t = num(f.get("Tiempo_entrega", 0))
            u = num(f.get("Unidades_Caja", 1))
            dias_mov = num(f.get("Dias", 0))

            if u <= 0 or not p: continue

            # --- APLICACIÓN ESTRICTA LÓGICA 3+1 ---
            if dias_mov < 3:
                p_reorden = 3 * u
                obj_stock = 4 * u
            else:
                p_reorden = c * (t + tolerancia)
                obj_stock = c * 15

            if s <= p_reorden:
                unidades_a_pedir = max(0, obj_stock - s)
                cajas = math.ceil(unidades_a_pedir / u)
                if cajas <= 0: cajas = 1
                res.append((p, s, cajas))
        return res
    except Exception as e:
        return f"⚠️ Error: {e}"

# =========================
# BOT Y COMANDOS
# =========================
bot = telebot.TeleBot(TOKEN)

# --- 1. VER TODO EL INVENTARIO ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "ver todo")
def ver_todos_productos(m):
    data = stock.get_all_records()
    if not data:
        bot.reply_to(m, "📭 El inventario está vacío.")
        return
    txt = "📋 *INVENTARIO ACTUAL*\n\n"
    for f in data:
        txt += f"• *{f['Producto']}*: {f['Stock_Actual']} uds\n"
    bot.reply_to(m, txt, parse_mode="Markdown")

# --- 2. BUSCAR (Nombre o Código de Barras) ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("buscar"))
def buscar_por_nombre_o_codigo(m):
    query = m.text.lower().replace("buscar", "").strip()
    if not query:
        bot.reply_to(m, "🔍 Uso: `buscar [nombre o código]`")
        return
    
    data = stock.get_all_records()
    encontrados = [f for f in data if query in str(f.get("Producto","")).lower() or query == str(f.get("Codigo_Barras",""))]
    
    if not encontrados:
        bot.reply_to(m, f"❌ No se encontró nada para '{query}'.")
        return
    
    for p in encontrados:
        msg = (f"🔍 *PRODUCTO ENCONTRADO*\n\n"
               f"📦 *Nombre:* {p['Producto']}\n"
               f"🔢 *Stock:* {p['Stock_Actual']}\n"
               f"📍 *Ubicación:* {p['Nivel']}, {p['Pasillo']}\n"
               f"📦 *Caja:* {p['Unidades_Caja']} uds\n"
               f"⏱️ *Entrega:* {p['Tiempo_entrega']} días")
        bot.reply_to(m, msg, parse_mode="Markdown")

# --- 3. ELIMINAR PRODUCTO ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("eliminar"))
def eliminar_confirmar(m):
    prod_nombre = m.text.replace("eliminar", "").strip()
    if not prod_nombre:
        bot.reply_to(m, "🗑️ Uso: `eliminar [Nombre Exacto]`")
        return
    
    try:
        celda = stock.find(prod_nombre)
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ Producto '{prod_nombre}' eliminado con éxito.")
    except:
        bot.reply_to(m, f"❌ No se encontró el producto '{prod_nombre}'.")

# --- 4. NUEVO PRODUCTO (FLUJO PASO A PASO) ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "nuevo")
def iniciar_flujo_nuevo(m):
    estados_espera[m.chat.id] = {"paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\nEscribe el NOMBRE del producto:")

@bot.message_handler(func=lambda m: m.chat.id in estados_espera and es_admin(m))
def procesar_flujo_nuevo(m):
    uid = m.chat.id
    est = estados_espera[uid]
    paso = est["paso"]

    try:
        if paso == 1:
            est["nombre"] = m.text.strip()
            est["paso"] = 2
            bot.send_message(uid, "Stock inicial (unidades):")
        elif paso == 2:
            est["stock"] = num(m.text)
            est["paso"] = 3
            bot.send_message(uid, "Unidades por caja:")
        elif paso == 3:
            est["u_caja"] = num(m.text)
            est["paso"] = 4
            bot.send_message(uid, "Tiempo de entrega (días):")
        elif paso == 4:
            est["tiempo"] = num(m.text)
            est["paso"] = 5
            bot.send_message(uid, "Código de Barras (o '0'):")
        elif paso == 5:
            est["barras"] = m.text.strip()
            # Finalizar y guardar
            idx = len(stock.get_all_values()) + 1
            fila = [
                est["nombre"], 
                f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)", 
                "Nivel 1", "", "", "", "vickniel0316@gmail.com",
                f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)",
                f"=SIERROR(ABS(B{idx})/H{idx}; 0)",
                est["tiempo"], est["u_caja"], est["barras"]
            ]
            stock.append_row(fila, value_input_option="USER_ENTERED")
            mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), est["nombre"].lower(), "Carga Inicial", est["stock"], m.from_user.first_name], value_input_option="USER_ENTERED")
            bot.send_message(uid, f"✅ '{est['nombre']}' registrado correctamente.")
            del estados_espera[uid]
    except Exception as e:
        bot.send_message(uid, f"❌ Error: {e}")
        del estados_espera[uid]

# --- 5. COMANDOS OPERATIVOS (PEDIDOS, ENTRADA, SALIDA) ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "pedidos")
def mostrar_pedidos(m):
    res = calc_pedidos()
    if not res:
        bot.reply_to(m, "✅ Inventario saludable.")
    else:
        txt = "📦 *REPORTE DE PEDIDOS (3+1)*\n\n"
        for p, s, k in res:
            txt += f"🔹 *{p}*: {s} uds -> *Pedir {k} cajas*\n"
        bot.reply_to(m, txt, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith(("entrada", "salida")))
def registro_mov_manual(m):
    partes = m.text.split()
    if len(partes) < 3: return
    try:
        tipo = partes[0].lower()
        cant = num(partes[-1])
        prod = " ".join(partes[1:-1]).strip().lower()
        mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), prod, "Bot", cant if tipo=="entrada" else -cant, m.from_user.first_name], value_input_option="USER_ENTERED")
        bot.reply_to(m, f"✅ {tipo.capitalize()} de {cant} registrada.")
    except Exception as e: bot.reply_to(m, f"❌ Error: {e}")

# =========================
# KEEP ALIVE Y POLLING
# =========================
class Web(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
def run_w(): HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Web).serve_forever()
threading.Thread(target=run_w, daemon=True).start()
print("🚀 Vickniel Bot RECONSTRUIDO Y COMPLETO iniciado...")
bot.infinity_polling()
