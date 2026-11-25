"""Datos de demostración para probar el sistema (Administrador > Configuración)."""
import random
from datetime import date, datetime, timedelta

import db

# (especialidad, descripción, envase, especificaciones, precio, _) — si vence lo decide db.sugerir_vencimiento()
INSUMOS = [
    ("General", "Anestesia local lidocaína 2% c/epinefrina", "Caja", "Caja x 50 cartuchos de 1,8 ml", 18500, 1),
    ("General", "Anestesia mepivacaína 3% s/vasoconstrictor", "Caja", "Caja x 50 cartuchos de 1,8 ml", 21000, 1),
    ("General", "Anestesia tópica benzocaína 20%", "Frasco", "Gel sabor frutilla, 30 g", 4800, 1),
    ("General", "Agujas dentales cortas 30G", "Caja", "Caja x 100, estériles, descartables", 9200, 1),
    ("General", "Agujas dentales largas 27G", "Caja", "Caja x 100, estériles, descartables", 9600, 1),
    ("General", "Guantes de látex descartables talle M", "Caja", "Caja x 100 unidades, no estériles", 7900, 1),
    ("General", "Guantes de nitrilo talle S", "Caja", "Caja x 100 unidades, sin polvo", 9400, 1),
    ("General", "Barbijo triple capa", "Caja", "Caja x 50, con elástico", 3200, 1),
    ("General", "Gasas estériles 10x10 cm", "Paquete", "Paquete x 100", 4300, 1),
    ("General", "Eyectores de saliva descartables", "Bolsa", "Bolsa x 100", 2600, 0),
    ("General", "Rollos de algodón N°2", "Paquete", "Paquete x 500", 2100, 0),
    ("General", "Baberos descartables", "Paquete", "Paquete x 500, doble capa", 6900, 0),
    ("General", "Vasos descartables 180 ml", "Paquete", "Paquete x 100", 1500, 0),
    ("General", "Resina compuesta A2", "Jeringa", "Jeringa 4 g, fotopolimerizable", 12400, 1),
    ("General", "Resina compuesta A3", "Jeringa", "Jeringa 4 g, fotopolimerizable", 12400, 1),
    ("General", "Adhesivo universal", "Frasco", "Frasco 5 ml, monocomponente", 26800, 1),
    ("General", "Ácido grabador 37%", "Jeringa", "Jeringa 3 ml en gel", 3900, 1),
    ("General", "Ionómero vítreo restaurador", "Frasco", "Polvo 15 g + líquido 10 ml", 21500, 1),
    ("General", "Sellador de fosas y fisuras", "Jeringa", "Jeringa 1,2 ml, fotopolimerizable", 8900, 1),
    ("General", "Flúor gel acidulado 1,23%", "Frasco", "Frasco 480 ml", 5200, 1),
    ("General", "Clorhexidina 0,12% colutorio", "Botella", "Botella 1 litro", 4100, 1),
    ("General", "Hidróxido de calcio pasta", "Tubo", "Base + catalizador, 13 g", 7600, 1),
    ("General", "Fresas de diamante redondas", "Blister", "Blister x 5, alta velocidad", 5600, 0),
    ("General", "Fresas de carburo troncocónicas", "Blister", "Blister x 5, alta velocidad", 6200, 0),
    ("General", "Matrices metálicas", "Rollo", "Rollo 3 m x 5 mm", 2800, 0),
    ("General", "Cuñas de madera", "Caja", "Caja x 100, tamaños surtidos", 3100, 0),
    ("General", "Papel de articular", "Paquete", "Paquete x 12 tiras, doble faz", 2400, 0),
    ("General", "Tiras de pulir", "Caja", "Caja x 50, grano mixto", 3500, 0),
    ("Endodoncia", "Limas K 1ra serie 25 mm", "Blister", "Blister x 6, acero inoxidable", 6800, 0),
    ("Endodoncia", "Limas K 2da serie 25 mm", "Blister", "Blister x 6, acero inoxidable", 7100, 0),
    ("Endodoncia", "Limas rotatorias níquel-titanio", "Blister", "Blister x 6, secuencia universal", 32000, 0),
    ("Endodoncia", "Conos de gutapercha 2da serie", "Caja", "Caja x 120", 5400, 1),
    ("Endodoncia", "Conos de papel absorbente", "Caja", "Caja x 200, estériles", 3800, 1),
    ("Endodoncia", "Hipoclorito de sodio 2,5%", "Botella", "Botella 1 litro", 2300, 1),
    ("Endodoncia", "EDTA 17% líquido", "Frasco", "Frasco 20 ml", 6100, 1),
    ("Endodoncia", "Cemento sellador endodóntico", "Tubo", "Pasta-pasta, 2 tubos", 19800, 1),
    ("Cirugía", "Sutura seda 3-0 c/aguja", "Caja", "Caja x 24 sobres estériles", 15600, 1),
    ("Cirugía", "Sutura nylon 4-0 c/aguja", "Caja", "Caja x 24 sobres estériles", 17400, 1),
    ("Cirugía", "Hojas de bisturí N°15", "Caja", "Caja x 100, acero al carbono", 9800, 0),
    ("Cirugía", "Hojas de bisturí N°12", "Caja", "Caja x 100, acero al carbono", 10200, 0),
    ("Cirugía", "Esponja hemostática de gelatina", "Caja", "Caja x 10, 1x1x1 cm", 11200, 1),
    ("Cirugía", "Hueso liofilizado particulado", "Frasco", "Frasco 0,5 g, partícula 0,25-1 mm", 45000, 1),
    ("Cirugía", "Membrana de colágeno reabsorbible", "Unidad", "15 x 20 mm, estéril", 52000, 1),
    ("Cirugía", "Jeringas descartables 5 ml", "Caja", "Caja x 100, con aguja 21G", 8800, 1),
    ("Prótesis", "Alginato para impresiones", "Bolsa", "Bolsa 454 g, fraguado normal", 6300, 1),
    ("Prótesis", "Silicona de condensación", "Caja", "Pesada 900 g + liviana + catalizador", 34000, 1),
    ("Prótesis", "Acrílico autocurable rosa", "Frasco", "Polvo 250 g", 14200, 1),
    ("Prótesis", "Acrílico termocurable", "Frasco", "Polvo 500 g", 16800, 1),
    ("Prótesis", "Yeso piedra tipo III", "Bolsa", "Bolsa 1 kg", 2900, 0),
    ("Prótesis", "Cubetas plásticas descartables", "Bolsa", "Bolsa x 12, tamaños surtidos", 3500, 0),
]
INSTRUMENTAL = [
    ("General", "Espejo bucal N°5 con mango", "Acero inoxidable, autoclavable", 3600),
    ("General", "Kit de examen descartable estéril", "Espejo, pinza y explorador; un solo uso", 2600),
    ("General", "Explorador doble extremo", "Acero inoxidable N°5", 4100),
    ("General", "Pinza para algodón", "Tipo College, 15 cm", 3900),
    ("General", "Sonda periodontal milimetrada", "Tipo OMS, acero inoxidable", 4700),
    ("General", "Jeringa carpule", "Con aspiración, autoclavable", 14500),
    ("General", "Cucharita para dentina doble", "Acero inoxidable N°17", 4300),
    ("General", "Espátula para cemento", "Doble extremo, acero inoxidable", 3800),
    ("General", "Atacador de amalgama", "Doble extremo, punta lisa", 4100),
    ("General", "Espejos bucales descartables estériles", "Plástico, envasados individualmente", 1200),
    ("General", "Portamatriz Tofflemire", "Universal, acero inoxidable", 6900),
    ("General", "Turbina de alta velocidad", "Con luz LED, conexión Midwest", 245000),
    ("General", "Micromotor con contraángulo", "Neumático, 20.000 rpm", 198000),
    ("General", "Lámpara de fotocurado LED", "Inalámbrica, 1.200 mW/cm²", 165000),
    ("General", "Pieza de mano recta", "Baja velocidad, autoclavable", 89000),
    ("General", "Ultrasonido para detartraje", "Piezoeléctrico, 5 insertos", 310000),
    ("General", "Cureta Gracey 5-6", "Acero inoxidable, mango hueco", 8900),
    ("General", "Cureta Gracey 11-12", "Acero inoxidable, mango hueco", 8900),
    ("Cirugía", "Fórceps N°150 superior", "Acero inoxidable quirúrgico", 32500),
    ("Cirugía", "Fórceps N°151 inferior", "Acero inoxidable quirúrgico", 32500),
    ("Cirugía", "Fórceps N°17 molares superiores", "Acero inoxidable quirúrgico", 34800),
    ("Cirugía", "Fórceps N°23 cuerno de vaca", "Acero inoxidable quirúrgico", 35900),
    ("Cirugía", "Elevador recto 3 mm", "Mango hueco, acero quirúrgico", 18900),
    ("Cirugía", "Elevador apical", "Punta fina, acero quirúrgico", 17600),
    ("Cirugía", "Elevadores de Winter (par)", "Derecho e izquierdo", 36400),
    ("Cirugía", "Mango de bisturí N°3", "Acero inoxidable, graduado", 5100),
    ("Cirugía", "Porta agujas Mayo-Hegar", "14 cm, acero quirúrgico", 16800),
    ("Cirugía", "Tijera de sutura recta", "12 cm, acero quirúrgico", 9800),
    ("Cirugía", "Tijera Metzenbaum curva", "14 cm, acero quirúrgico", 14200),
    ("Cirugía", "Pinza Kelly curva", "14 cm, hemostática", 11300),
    ("Cirugía", "Pinza de disección con dientes", "12 cm, Adson", 8700),
    ("Cirugía", "Periostótomo Molt N°9", "Doble extremo", 12600),
    ("Cirugía", "Cureta alveolar Lucas", "Doble extremo, N°86", 10400),
    ("Cirugía", "Pinza gubia", "Curva, 15 cm", 41500),
    ("Endodoncia", "Regla milimetrada endodóntica", "Acero inoxidable", 5200),
    ("Endodoncia", "Localizador apical", "Digital, con batería recargable", 285000),
    ("Endodoncia", "Motor endodóntico", "Con contraángulo 16:1 y control de torque", 520000),
    ("Endodoncia", "Espaciador digital", "Juego x 4, níquel-titanio", 15800),
    ("Endodoncia", "Condensador de gutapercha", "Juego x 3, doble extremo", 13900),
    ("Endodoncia", "Clamps para aislamiento", "Juego x 10, molares y premolares", 39800),
    ("Endodoncia", "Perforador de dique de goma", "Tipo Ainsworth", 28700),
    ("Endodoncia", "Portaclamps", "Tipo Brewer", 16200),
    ("Prótesis", "Cubeta de impresión metálica", "Juego x 10, perforadas", 27400),
    ("Prótesis", "Espátula para alginato", "Plástica flexible", 1900),
    ("Prótesis", "Taza de goma", "Mediana, flexible", 2300),
    ("Prótesis", "Espátula Lecron", "Doble extremo, acero inoxidable", 4600),
    ("Prótesis", "Cuchillo para cera", "Mango metálico", 5300),
    ("Prótesis", "Articulador semiajustable", "Con arco facial", 410000),
]
MOTIVOS_FALTANTE = ["Diferencia en inventario trimestral", "No se encontró en el depósito al recontar",
                    "Error de carga en una entrega anterior", "Unidades faltantes al abrir la caja"]
MOTIVOS_SOBRANTE = ["Diferencia en inventario trimestral", "Unidades encontradas en otro estante",
                    "Error de carga en el ingreso del expediente", "Devolución sin acta de un hospital"]


def cargar():
    con = db.conectar()
    db.inicializar(con)
    rnd = random.Random(7)
    hoy = date.today()
    usuarios = [("María", "González"), ("Juan", "Perez"), ("Lucía", "Mamani")]
    for n, a in usuarios:
        u = db.generar_usuario(con, n, a)
        if not con.execute("SELECT 1 FROM usuarios WHERE nombre=? AND apellido=?", (n, a)).fetchone():
            con.execute("INSERT INTO usuarios(usuario,nombre,apellido,contrasena,pin,rol,creado) VALUES(?,?,?,?,?,?,?)",
                        (u, n, a, db.cifrar("1234"), f"{rnd.randint(1000, 9999)}", "Usuario", db.ahora()))
    nombres_u = [r[0] for r in con.execute("SELECT usuario FROM usuarios")]

    ids = {}
    for esp, desc, env, spec, precio, vence in INSUMOS:
        cur = con.execute("""INSERT INTO elementos(grupo,especialidad,descripcion,envase,especificaciones,stock_minimo,precio_unitario,
                             lleva_vencimiento,creado) VALUES(?,?,?,?,?,?,?,?,?)""",
                          ("Insumo", esp, desc, env, spec, rnd.choice([10, 15, 20]), precio,
                           1 if db.sugerir_vencimiento("Insumo", desc) else 0, db.ahora()))
        ids[desc] = ("Insumo", cur.lastrowid)
    for esp, desc, spec, precio in INSTRUMENTAL:
        cur = con.execute("""INSERT INTO elementos(grupo,especialidad,descripcion,envase,especificaciones,stock_minimo,precio_unitario,
                             lleva_vencimiento,creado) VALUES(?,?,?,?,?,?,?,?,?)""",
                          ("Instrumental", esp, desc, None, spec, rnd.choice([5, 8, 10]), precio,
                           1 if db.sugerir_vencimiento("Instrumental", desc) else 0, db.ahora()))
        ids[desc] = ("Instrumental", cur.lastrowid)

    insumos = [v[1] for v in ids.values() if v[0] == "Insumo"]
    instr = [v[1] for v in ids.values() if v[0] == "Instrumental"]
    regiones = db.lista(con, "region")
    hospitales = {"Centro": "Hospital Pablo Soria", "Valles": "Hospital Nuestra Sra. del Carmen", "Ramal I": "Hospital San Pedro",
                  "Ramal II": "Hospital Oscar Orías", "Quebrada": "Hospital Humahuaca", "Puna": "Hospital La Quiaca"}

    # expedientes desde enero del año pasado (unos 48)
    inicio = date(hoy.year - 1, 1, 10)
    num = 10230
    fecha_exp = inicio
    exps = []
    while fecha_exp < hoy - timedelta(days=10):
        grupo = "Insumo" if rnd.random() < 0.68 else "Instrumental"
        num += rnd.randint(3, 400)
        nro = f"{fecha_exp.year}-{num:08d}"
        usuario = rnd.choice(nombres_u)
        cur = con.execute("""INSERT INTO expedientes(anio,numero,nro_expediente,grupo,fecha,estado,solicitado_por,utilizado_en,entregar_en,usuario)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (fecha_exp.year, f"{num:08d}", nro, grupo, fecha_exp.isoformat(), "Activo",
                           "Dirección Provincial de Odontología", "Dirección Provincial de Odont.", "Dirección Provincial de Odont.", usuario))
        eid = cur.lastrowid
        pool = insumos if grupo == "Insumo" else instr
        for k, el in enumerate(rnd.sample(pool, rnd.randint(4, min(9, len(pool)))), 1):
            row = con.execute("SELECT * FROM elementos WHERE id=?", (el,)).fetchone()
            cant = rnd.randint(20, 120) if grupo == "Insumo" else rnd.randint(4, 25)
            precio = round(row["precio_unitario"] * rnd.uniform(0.9, 1.15), 2)
            venc = None
            if row["lleva_vencimiento"]:
                venc = (fecha_exp + timedelta(days=rnd.randint(500, 1000))).isoformat()
            cur = con.execute("""INSERT INTO expediente_items(expediente_id,elemento_id,nro,letra,unidad,cantidad,precio_unitario,fecha_vencimiento)
                                 VALUES(?,?,?,?,?,?,?,?)""", (eid, el, str(k), "", row["envase"] or "Unidad", cant, precio, venc))
            db.ingresar_lote(con, el, cant, venc, usuario, f"{fecha_exp.isoformat()} 09:{k:02d}:00", eid, cur.lastrowid, precio)
            con.execute("UPDATE elementos SET precio_unitario=? WHERE id=?", (precio, el))
        db.recalcular_expediente(con, eid)
        con.execute("INSERT INTO expediente_log(expediente_id,nro_expediente,usuario,accion,fecha) VALUES(?,?,?,?,?)",
                    (eid, nro, usuario, "Alta", f"{fecha_exp.isoformat()} 09:00:00"))
        exps.append((eid, fecha_exp))
        fecha_exp += timedelta(days=rnd.randint(9, 17))

    # salidas mensuales
    d = inicio + timedelta(days=12)
    while d < hoy:
        razon = rnd.choices(["Entrega", "Préstamo", "Roto", "Perdido"], [70, 12, 10, 8])[0]
        region = rnd.choice(regiones)
        fecha = f"{d.isoformat()} {rnd.randint(8, 14):02d}:{rnd.randint(0, 59):02d}:00"
        cur = con.execute("INSERT INTO actas(tipo,razon,region,hospital,fecha,usuario) VALUES(?,?,?,?,?,?)",
                          ("Entrega" if razon in ("Entrega", "Préstamo") else "Baja", razon,
                           region if razon in ("Entrega", "Préstamo") else None,
                           hospitales.get(region) if razon in ("Entrega", "Préstamo") else None, fecha, rnd.choice(nombres_u)))
        acta = cur.lastrowid
        pool = instr if razon in ("Préstamo", "Roto", "Perdido") and rnd.random() < 0.7 else insumos + instr
        hechos = 0
        for el in rnd.sample(pool, rnd.randint(1, 4)):
            disp = min(con.execute("""SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE elemento_id=? AND fecha_ingreso<=?""",
                                   (el, fecha)).fetchone()[0], db.disponible(con, el, razon, fecha))
            if disp <= 2:
                continue
            maxi = max(1, disp // (3 if razon == "Entrega" else 10))
            db.egresar(con, el, rnd.randint(1, maxi), razon, con.execute("SELECT usuario FROM actas WHERE id=?", (acta,)).fetchone()[0],
                       region, acta, fecha)
            hechos += 1
        if not hechos:
            con.execute("DELETE FROM actas WHERE id=?", (acta,))
        d += timedelta(days=rnd.randint(3, 8))

    # algunos agotados/críticos para mostrar alertas
    for el in rnd.sample(insumos, 3) + rnd.sample(instr, 2):
        st = db.disponible(con, el, "Entrega")
        if st:
            cur = con.execute("INSERT INTO actas(tipo,razon,region,hospital,fecha,usuario) VALUES(?,?,?,?,?,?)",
                              ("Entrega", "Entrega", "Centro", hospitales["Centro"], db.ahora(), "Admin"))
            db.egresar(con, el, st, "Entrega", "Admin", "Centro", cur.lastrowid)
    # lotes con vencimiento cercano / vencido
    con_venc = [r[0] for r in con.execute("SELECT id FROM elementos WHERE lleva_vencimiento=1")]
    for el in rnd.sample(con_venc, 6):
        db.ingresar_lote(con, el, rnd.randint(5, 15), (hoy + timedelta(days=rnd.randint(-40, 45))).isoformat(), "Admin",
                         f"{(hoy - timedelta(days=200)).isoformat()} 10:00:00")
    # algunos en stock crítico
    for el in rnd.sample(insumos, 5) + rnd.sample(instr, 4):
        con.execute("UPDATE elementos SET stock_minimo=stock_actual+5 WHERE id=? AND stock_actual>0", (el,))
    # una baja por vencimiento
    v = con.execute("SELECT elemento_id, cantidad_actual FROM lotes WHERE cantidad_actual>0 AND fecha_vencimiento<? LIMIT 1", (hoy.isoformat(),)).fetchone()
    if v:
        cur = con.execute("INSERT INTO actas(tipo,razon,fecha,usuario) VALUES('Baja','Vencido',?,'Admin')", (db.ahora(),))
        db.egresar(con, v[0], max(1, v[1] // 2), 'Vencido', 'Admin', None, cur.lastrowid)
    # ajustes de inventario (faltantes y sobrantes por conteo físico)
    d = inicio + timedelta(days=40)
    while d < hoy:
        el = rnd.choice(insumos + instr)
        fecha = f"{d.isoformat()} {rnd.randint(9, 16):02d}:{rnd.randint(0, 59):02d}:00"
        usuario = rnd.choice(nombres_u)
        disp = con.execute("SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE elemento_id=? AND fecha_ingreso<=?",
                           (el, fecha)).fetchone()[0]
        if rnd.random() < 0.6 and disp > 3:
            db.egresar(con, el, rnd.randint(1, max(1, min(6, disp // 4))), "Ajuste", usuario, fecha=fecha,
                       observaciones=rnd.choice(MOTIVOS_FALTANTE))
        else:
            venc = (d + timedelta(days=rnd.randint(150, 500))).isoformat()
            db.ingresar_lote(con, el, rnd.randint(1, 8), venc, usuario, fecha, razon="Ajuste",
                             observaciones=rnd.choice(MOTIVOS_SOBRANTE))
        d += timedelta(days=rnd.randint(14, 30))
    # cerrar expedientes totalmente consumidos o antiguos
    for eid, f in exps:
        resto = con.execute("SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE expediente_id=?", (eid,)).fetchone()[0]
        if resto == 0 or f < hoy - timedelta(days=330):
            con.execute("UPDATE expedientes SET estado='Cerrado' WHERE id=?", (eid,))
    con.commit()
    con.close()


if __name__ == "__main__":
    cargar()
    print("Datos de demostración cargados.")
