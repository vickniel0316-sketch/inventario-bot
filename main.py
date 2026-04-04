# =========================
# NUEVO
# =========================
estado = {}

@bot.message_handler(func=lambda m: m.text and ok(m) and m.text.lower()=="nuevo")
def nuevo(m):
    estado[m.chat.id]={"p":"nombre"}
    bot.reply_to(m,"Nombre:")

@bot.message_handler(func=lambda m: m.chat.id in estado and ok(m))
def flujo(m):
    e=estado[m.chat.id]
    t=m.text

    if e["p"]=="nombre":
        e["nombre"]=t
        e["p"]="stock"
        bot.reply_to(m,"Stock:")
        return

    if e["p"]=="stock":
        e["stock"]=num(t)
        e["p"]="nivel"
        bot.reply_to(m,"Nivel:")
        return

    if e["p"]=="nivel":
        e["nivel"]="N-"+t
        e["p"]="pasillo"
        bot.reply_to(m,"Pasillo:")
        return

    if e["p"]=="pasillo":
        e["pasillo"]="P-"+t
        e["p"]="lado"
        bot.reply_to(m,"Lado A/B:")
        return

    if e["p"]=="lado":
        e["lado"]=t.upper()
        e["p"]="sec"
        bot.reply_to(m,"Sección:")
        return

    if e["p"]=="sec":
        e["sec"]=t
        e["p"]="caja"
        bot.reply_to(m,"Unidades por caja:")
        return

    if e["p"]=="caja":
        e["caja"]=num(t)
        e["p"]="tiempo"
        bot.reply_to(m,"Tiempo entrega:")
        return

    if e["p"]=="tiempo":
        e["tiempo"]=num(t)
        e["p"]="correo"
        bot.reply_to(m,"Correo del responsable:")
        return

    if e["p"]=="correo":
        e["correo"]=t

        # ✅ fila correcta
        next_row = len(stock.get_all_values()) + 1

        fila = [
            e["nombre"],  # A
            f'=SUMAR.SI(Movimientos!B:B, A{next_row}, Movimientos!D:D)',  # B
            "",  # C
            e["nivel"],  # D
            e["pasillo"],  # E
            e["lado"],  # F
            e["correo"],  # G ✅ CORRECTO
            "",  # H
            f'''=SI.ERROR(
 ABS(SUMAR.SI.CONJUNTO(
   Movimientos!D:D,
   Movimientos!B:B,A{next_row},
   Movimientos!D:D,"<0"
 )) /
 MAX(1,
   MAX(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A)) -
   MIN(SI((Movimientos!B:B=A{next_row})*(Movimientos!D:D<0),Movimientos!A:A)) + 1
 ),
0)'''  # I ✅ CORRECTO
        ]

        stock.append_row(fila, value_input_option="USER_ENTERED")

        if e["stock"]>0:
            mov.append_row([
                datetime.now(ZoneInfo("America/Santo_Domingo")),
                e["nombre"],"",
                e["stock"],m.from_user.first_name
            ])

        bot.reply_to(m,"✅ Creado")
        del estado[m.chat.id]
