import telebot
import gspread
from google.oauth2.service_account import Credentials
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# 1. CONFIGURACIÓN DE APIS
# El TOKEN se lee de las Variables de Railway, no se escribe aquí.
TOKEN = os.getenv("TOKEN")
bot = telebot.TeleBot(TOKEN)

# Configuración de Google Sheets
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
# Asegúrate de que el archivo creds.json esté en la raíz de tu repositorio de GitHub
creds = Credentials.from_service_account_file("creds.json", scopes=scope)
client = gspread.authorize(creds)

# Apertura de la hoja (Ajusta el nombre si cambió)
sheet = client.open("inventario_vickniel01")
stock = sheet.worksheet("Stock")
mov = sheet.worksheet("Movimientos")

# Tu ID de Telegram para seguridad
ADMIN_ID = 6249114480

# 2. FUNCIONES DE APOYO
def es_admin(m):
    return m.from_user.id == ADMIN_ID

def num(texto):
    try:
        return float(texto.replace(',', '.'))
    except:
        return 0

# Diccionario para manejar los pasos del registro
estados_espera = {}

# 3. FLUJO: REGISTRO DE PRODUCTO (UBICACIÓN C-F)
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower() == "nuevo")
def iniciar_nuevo(m):
    estados_espera[m.chat.id] = {"paso": 1}
    bot.reply_to(m, "📝 *NUEVO PRODUCTO*\n\n1. Escribe el NOMBRE:")

@bot.message_handler(func=lambda m: m.chat.id in estados_espera and es_admin(m))
def manejador_pasos(m):
    uid = m.chat.id
    est = estados_espera[uid]
    paso = est["paso"]

    try:
        if paso == 1:
            est["nombre"] = m.text.strip()
            est["paso"] = 2
            bot.send_message(uid, "2. STOCK INICIAL (Unidades):")
        
        elif paso == 2:
            est["stock"] = num(m.text)
            est["paso"] = 3
            bot.send_message(uid, "3. NIVEL (Columna C):")
        
        elif paso == 3:
            est["nivel"] = m.text.strip()
            est["paso"] = 4
            bot.send_message(uid, "4. PASILLO (Columna D):")
        
        elif paso == 4:
            est["pasillo"] = m.text.strip()
            est["paso"] = 5
            bot.send_message(uid, "5. LADO (Columna E - Escribe A o B):")
        
        elif paso == 5:
            est["lado"] = m.text.strip().upper()
            est["paso"] = 6
            bot.send_message(uid, "6. SECCIÓN (Columna F):")
        
        elif paso == 6:
            est["seccion"] = m.text.strip()
            est["paso"] = 7
            bot.send_message(uid, "7. UNIDADES POR CAJA:")
        
        elif paso == 7:
            est["u_caja"] = num(m.text)
            est["paso"] = 8
            bot.send_message(uid, "8. TIEMPO DE ENTREGA (Días):")
        
        elif paso == 8:
            est["tiempo"] = num(m.text)
            
            # --- GUARDADO EN GOOGLE SHEETS ---
            idx = len(stock.get_all_values()) + 1
            fila = [
                est["nombre"],                                      # A: Producto
                f"=SUMAR.SI(Movimientos!B:B; A{idx}; Movimientos!D:D)", # B: Stock (Fórmula)
                est["nivel"],                                       # C: Nivel
                est["pasillo"],                                     # D: Pasillo
                est["lado"],                                        # E: Lado
                est["seccion"],                                     # F: Sección
                "vickniel0316@gmail.com",                           # G: Email
                f"=CONTAR.SI.CONJUNTO(Movimientos!B:B; A{idx}; Movimientos!A:A; \">\"&HOY()-30)", # H: Días
                f"=SIERROR(ABS(B{idx})/H{idx}; 0)",                  # I: Consumo
                est["tiempo"],                                      # J: Tiempo
                est["u_caja"]                                       # K: Unidades/Caja
            ]
            
            stock.append_row(fila, value_input_option="USER_ENTERED")
            
            # Movimiento de Carga Inicial
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")).strftime("%Y-%m-%d %H:%M:%S"),
                est["nombre"].lower(), "Carga Inicial", est["stock"], m.from_user.first_name
            ], value_input_option="USER_ENTERED")

            bot.send_message(uid, f"✅ Registrado: *{est['nombre']}*\n📍 Ubicación: Nivel {est['nivel']}, Pasillo {est['pasillo']}, Lado {est['lado']}, Sec. {est['seccion']}", parse_mode="Markdown")
            del estados_espera[uid]

    except Exception as e:
        bot.send_message(uid, f"❌ Error: {e}")
        if uid in estados_espera: del estados_espera[uid]

# 4. COMANDO: BUSCAR
@bot.message_handler(func=lambda m: m.text and es_admin(m) and m.text.lower().startswith("buscar"))
def buscar_producto(m):
    query = m.text.replace("buscar", "").strip().lower()
    if not query:
        bot.reply_to(m, "Escribe el nombre después de 'buscar'.")
        return

    data = stock.get_all_records()
    encontrados = [f for f in data if query in str(f.get("Producto", "")).lower()]
    
    if encontrados:
        for p in encontrados:
            res = f"📦 *{p['Producto']}*\n"
            res += f"🔢 Stock: {p['Stock_Actual']} uds\n"
            res += f"📍 Ubicación: Nivel {p['Nivel']}, Pasillo {p['Pasillo']}, Lado {p['Lado']}, Sec. {p['Seccion']}"
            bot.send_message(m.chat.id, res, parse_mode="Markdown")
    else:
        bot.reply_to(m, "❌ No encontrado.")

# 5. INICIO SEGURO PARA RAILWAY
if __name__ == "__main__":
    print("🚀 Bot main.py iniciado...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
