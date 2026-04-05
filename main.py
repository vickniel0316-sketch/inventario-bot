import telebot
import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. CONFIGURACIÓN
TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("credenciales.json", scopes=scope)
client = gspread.authorize(creds)

sheet = client.open("inventario_vickniel01")
stock = sheet.worksheet("Stock")
mov = sheet.worksheet("Movimientos")

ADMIN_ID = 6249114480

def es_admin(m):
    return m.from_user.id == ADMIN_ID

def num(texto):
    try:
        return float(texto.replace(',', '.'))
    except:
        return 0

estados_espera = {}

# --- LÓGICA DE MOVIMIENTOS (ENTRADA / SALIDA) ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() in ["entrada", "salida"])
def gestionar_movimiento(m):
    tipo = m.text.lower()
    estados_espera[m.chat.id] = {"tipo": tipo, "paso": "nombre"}
    bot.reply_to(m, f"🔄 Has iniciado una *{tipo.upper()}*.\nEscribe el nombre del producto:")

# --- COMANDO: NUEVO ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "nuevo")
def iniciar_nuevo(m):
    estados_espera[m.chat.id] = {"tipo": "nuevo", "paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\n1. Escribe el NOMBRE:")

# --- MANEJADOR DE PASOS (ENTRADA, SALIDA, NUEVO) ---
@bot.message_handler(func=lambda m: m.chat.id in estados_espera and es_admin(m))
def manejador_general(m):
    uid = m.chat.id
    est = estados_espera[uid]
    
    # Lógica para ENTRADA y SALIDA
    if est["tipo"] in ["entrada", "salida"]:
        if est["paso"] == "nombre":
            est["prod_nombre"] = m.text.strip().lower()
            est["paso"] = "cantidad"
            bot.send_message(uid, f"¿Qué cantidad de '{m.text}' vas a registrar?")
        elif est["paso"] == "cantidad":
            cantidad = num(m.text)
            if est["tipo"] == "salida": cantidad = -abs(cantidad)
            
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                est["prod_nombre"], est["tipo"].capitalize(), cantidad, m.from_user.first_name
            ], value_input_option="USER_ENTERED")
            
            bot.send_message(uid, f"✅ {est['tipo'].capitalize()} de {abs(cantidad)} unidades registrada.")
            del estados_espera[uid]

    # Lógica para NUEVO (8 Pasos con Ubicación)
    elif est["tipo"] == "nuevo":
        paso = est["paso"]
        if paso == 1:
            est["n"] = m.text.strip(); est["paso"] = 2
            bot.send_message(uid, "2. STOCK INICIAL:")
        elif paso == 2:
            est["s"] = num(m.text); est["paso"] = 3
            bot.send_message(uid, "3. UNIDADES POR CAJA:")
        elif paso == 3:
            est["u"] = num(m.text); est["paso"] = 4
            bot.send_message(uid, "4. TIEMPO ENTREGA (Días):")
        elif paso == 4:
            est["t"] = num(m.text); est["paso"] = 5
            bot.send_message(uid, "5. NIVEL (Col. C):")
        elif paso == 5:
            est["niv"] = m.text.strip(); est["paso"] = 6
            bot.send_message(uid, "6. PASILLO (Col. D):")
        elif paso == 6:
            est["pas"] = m.text.strip(); est["paso"] = 7
            bot.send_message(uid, "7. LADO (A o B):")
        elif paso == 7:
            est["lad"] = m.text.strip().upper(); est["paso"] = 8
            bot.send_message(uid, "8. SECCIÓN (Col. F):")
        elif paso == 8:
            est["sec"] = m.text.strip()
            idx = len(stock.get_all_values()) + 1
            fila = [est["n"], f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)", est["niv"], est["pas"], est["lad"], est["sec"], "vickniel0316@gmail.com", f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)", f"=SIERROR(ABS(B{idx})/H{idx}; 0)", est["t"], est["u"]]
            stock.append_row(fila, value_input_option="USER_ENTERED")
            mov.append_row([datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"), est["n"].lower(), "Carga Inicial", est["s"], m.from_user.first_name], value_input_option="USER_ENTERED")
            bot.send_message(uid, "✅ Producto y ubicación guardados.")
            del estados_espera[uid]

# --- COMANDO: BUSCAR ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("buscar"))
def buscar(m):
    query = m.text.replace("buscar", "").strip().lower()
    data = stock.get_all_records()
    encontrados = [p for p in data if query in str(p.get("Producto", "")).lower()]
    if encontrados:
        for p in encontrados:
            res = f"📦 *{p['Producto']}*\n🔢 Stock: {p['Stock_Actual']} uds\n📍 Ubicación: Nivel {p['Nivel']}, Pasillo {p['Pasillo']}, Lado {p['Lado']}, Sec. {p['Seccion']}"
            bot.send_message(m.chat.id, res, parse_mode="Markdown")
    else: bot.reply_to(m, "❌ No encontrado.")

# --- COMANDO: VER (VER TODO) ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "ver")
def ver_todo(m):
    data = stock.get_all_records()
    if not data: return bot.reply_to(m, "Inventario vacío.")
    lista = "📋 *INVENTARIO ACTUAL*\n\n"
    for p in data:
        lista += f"• {p['Producto']}: {p['Stock_Actual']} uds\n"
    bot.send_message(m.chat.id, lista, parse_mode="Markdown")

# --- COMANDO: ELIMINAR ---
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("eliminar"))
def eliminar(m):
    nombre = m.text.replace("eliminar", "").strip().lower()
    celda = stock.find(nombre)
    if celda:
        stock.delete_rows(celda.row)
        bot.reply_to(m, f"🗑️ '{nombre}' eliminado de Stock.")
    else: bot.reply_to(m, "❌ No se encontró para eliminar.")

# 4. CIERRE SEGURO
if __name__ == "__main__":
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
