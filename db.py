"""Base de datos interna (SQLite) del Sistema de Gestión de Stock Odontológico."""
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "datos")
DB_PATH = os.path.join(DATA_DIR, "gso.db")

LISTAS_INICIALES = {
    "grupo": ["Insumo", "Instrumental"],
    "especialidad": ["Cirugía", "Endodoncia", "Prótesis", "General"],
    "envase": ["Avio", "Bolsa", "Botella", "Blister", "Caja", "Frasco", "Jeringa",
               "Paquete", "Rollo", "Tableta", "Tubo", "Unidad"],
    "estado": ["Activo", "Cerrado"],
    "baja": ["Entrega", "Préstamo", "Roto", "Perdido", "Vencido"],
    "tipo": ["Alta", "Baja"],
    "region": ["Centro", "Valles", "Ramal I", "Ramal II", "Quebrada", "Puna"],
}

CONFIG_INICIAL = {
    "nombre_sistema": "Gestión de Stock Odontológico",
    "organismo": "DIRECCION PROVINCIAL DE ODONTOLOGIA",
    "dependencia": "Secretaría de Salud - MINISTERIO DE SALUD",
    "logo": "img/logo.png",
    "dias_alerta_vencimiento": "60",
    "stock_minimo_defecto": "10",
    "tema": "clasico",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE NOT NULL COLLATE NOCASE,
    nombre TEXT NOT NULL,
    apellido TEXT NOT NULL,
    contrasena TEXT NOT NULL,
    pin TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'Usuario',
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
CREATE TABLE IF NOT EXISTS listas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lista TEXT NOT NULL,
    valor TEXT NOT NULL,
    orden INTEGER DEFAULT 0,
    UNIQUE(lista, valor)
);
CREATE TABLE IF NOT EXISTS elementos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grupo TEXT NOT NULL,
    especialidad TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    envase TEXT,
    especificaciones TEXT,
    stock_actual INTEGER NOT NULL DEFAULT 0,
    stock_minimo INTEGER NOT NULL DEFAULT 10,
    precio_unitario REAL NOT NULL DEFAULT 0,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expedientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anio INTEGER NOT NULL,
    numero TEXT NOT NULL,
    nro_expediente TEXT UNIQUE NOT NULL,
    grupo TEXT NOT NULL,
    valor_total REAL NOT NULL DEFAULT 0,
    fecha TEXT NOT NULL,
    fecha_entrega TEXT,
    estado TEXT NOT NULL DEFAULT 'Activo',
    solicitado_por TEXT,
    utilizado_en TEXT,
    entregar_en TEXT,
    usuario TEXT
);
CREATE TABLE IF NOT EXISTS expediente_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER NOT NULL REFERENCES expedientes(id) ON DELETE CASCADE,
    elemento_id INTEGER NOT NULL REFERENCES elementos(id),
    nro TEXT,
    letra TEXT,
    unidad TEXT,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL DEFAULT 0,
    fecha_vencimiento TEXT
);
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    elemento_id INTEGER NOT NULL REFERENCES elementos(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES expediente_items(id) ON DELETE CASCADE,
    cantidad_inicial INTEGER NOT NULL,
    cantidad_actual INTEGER NOT NULL,
    fecha_vencimiento TEXT,
    fecha_ingreso TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,          -- Entrega | Baja
    razon TEXT NOT NULL,         -- Entrega/Préstamo/Roto/Perdido/Vencido
    region TEXT,
    hospital TEXT,
    fecha TEXT NOT NULL,
    usuario TEXT,
    observaciones TEXT
);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    usuario TEXT,
    elemento_id INTEGER NOT NULL REFERENCES elementos(id),
    tipo TEXT NOT NULL,          -- Alta | Baja
    razon TEXT NOT NULL,         -- Ingreso / Entrega / Préstamo / Roto / Perdido / Vencido
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL DEFAULT 0,
    region TEXT,
    acta_id INTEGER REFERENCES actas(id),
    expediente_id INTEGER REFERENCES expedientes(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS movimiento_lotes (
    movimiento_id INTEGER REFERENCES movimientos(id) ON DELETE CASCADE,
    lote_id INTEGER REFERENCES lotes(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS movimientos_anulados (
    id INTEGER PRIMARY KEY,      -- mismo id que tenía en movimientos
    fecha TEXT NOT NULL,
    usuario TEXT,
    elemento_id INTEGER NOT NULL REFERENCES elementos(id),
    tipo TEXT NOT NULL,
    razon TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL DEFAULT 0,
    region TEXT,
    acta_id INTEGER REFERENCES actas(id),
    lotes TEXT                   -- detalle de lotes devueltos: "lote_id:cantidad,..."
);
CREATE TABLE IF NOT EXISTS expediente_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente_id INTEGER,
    nro_expediente TEXT,
    usuario TEXT,
    accion TEXT,                 -- Alta / Modificación / Baja
    fecha TEXT NOT NULL
);
"""


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoy():
    return date.today().isoformat()


def conectar():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def cifrar(clave):
    """Las contraseñas se guardan cifradas (hash), nunca en texto legible."""
    return generate_password_hash(clave)


def clave_correcta(guardada, ingresada):
    try:
        return check_password_hash(guardada, ingresada)
    except (ValueError, TypeError):
        return False


def _es_hash(valor):
    return isinstance(valor, str) and valor.split(":", 1)[0] in ("scrypt", "pbkdf2")


def inicializar(con=None):
    propio = con is None
    con = con or conectar()
    con.executescript(SCHEMA)
    if not con.execute("SELECT 1 FROM usuarios WHERE usuario='Admin'").fetchone():
        con.execute(
            "INSERT INTO usuarios(usuario,nombre,apellido,contrasena,pin,rol,creado) VALUES(?,?,?,?,?,?,?)",
            ("Admin", "Admin", "Admin", cifrar("Admin"), "0000", "Administrador", ahora()))
    # Migración: bases anteriores guardaban las contraseñas en texto legible.
    for u in con.execute("SELECT id, contrasena FROM usuarios").fetchall():
        if not _es_hash(u["contrasena"]):
            con.execute("UPDATE usuarios SET contrasena=? WHERE id=?", (cifrar(u["contrasena"]), u["id"]))
    # Migración: columnas de anulación de actas (bases anteriores no las tienen).
    cols = {r["name"] for r in con.execute("PRAGMA table_info(actas)")}
    for col in ("anulada_fecha", "anulada_por", "anulada_motivo"):
        if col not in cols:
            con.execute(f"ALTER TABLE actas ADD COLUMN {col} TEXT")
    # Migración: motivo/observaciones de cada movimiento (se usa en los ajustes de inventario).
    if "observaciones" not in {r["name"] for r in con.execute("PRAGMA table_info(movimientos)")}:
        con.execute("ALTER TABLE movimientos ADD COLUMN observaciones TEXT")
    # Migración: no todos los elementos vencen (ej. hojas de bisturí, limas, instrumental).
    if "lleva_vencimiento" not in {r["name"] for r in con.execute("PRAGMA table_info(elementos)")}:
        con.execute("ALTER TABLE elementos ADD COLUMN lleva_vencimiento INTEGER NOT NULL DEFAULT 1")
        con.execute("UPDATE elementos SET lleva_vencimiento=0 WHERE grupo='Instrumental'")
    # Migración: clasifica automáticamente lo que no vence y borra fechas que no corresponden
    # (bases cargadas antes de existir la categoría tenían todo «con vencimiento»).
    clasif = con.execute("SELECT valor FROM config WHERE clave='clasif_vencimiento'").fetchone()
    if not clasif or clasif["valor"] != "2":
        # v2: clasificación por producto según fichas técnicas (reemplaza la anterior, que daba
        # por «sin vencimiento» productos estériles como hojas de bisturí o limas).
        for e in con.execute("SELECT id, grupo, descripcion FROM elementos").fetchall():
            vence = sugerir_vencimiento(e["grupo"], e["descripcion"])
            con.execute("UPDATE elementos SET lleva_vencimiento=? WHERE id=?", (1 if vence else 0, e["id"]))
            if not vence:
                quitar_vencimientos(con, e["id"])
        con.execute("INSERT OR REPLACE INTO config(clave,valor) VALUES('clasif_vencimiento','2')")
    for clave, valor in CONFIG_INICIAL.items():
        con.execute("INSERT OR IGNORE INTO config(clave,valor) VALUES(?,?)", (clave, valor))
    if not con.execute("SELECT 1 FROM listas").fetchone():
        for lista, valores in LISTAS_INICIALES.items():
            for i, v in enumerate(valores):
                con.execute("INSERT INTO listas(lista,valor,orden) VALUES(?,?,?)", (lista, v, i))
    con.commit()
    if propio:
        con.close()


def config(con):
    return {r["clave"]: r["valor"] for r in con.execute("SELECT clave, valor FROM config")}


def lista(con, nombre):
    return [r["valor"] for r in con.execute(
        "SELECT valor FROM listas WHERE lista=? ORDER BY orden, valor", (nombre,))]


def sin_acentos(txt):
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def generar_usuario(con, nombre, apellido, excluir_id=None):
    base = (sin_acentos(nombre.strip())[:1] + sin_acentos(apellido.strip()).replace(" ", "")).upper()
    candidato, n = base, 2
    while True:
        r = con.execute("SELECT id FROM usuarios WHERE usuario=?", (candidato,)).fetchone()
        if not r or r["id"] == excluir_id:
            return candidato
        candidato, n = f"{base}{n}", n + 1


def recalcular_stock(con, elemento_id):
    total = con.execute("SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE elemento_id=?",
                        (elemento_id,)).fetchone()[0]
    con.execute("UPDATE elementos SET stock_actual=? WHERE id=?", (total, elemento_id))
    return total


def recalcular_expediente(con, expediente_id):
    total = con.execute("SELECT COALESCE(SUM(cantidad*precio_unitario),0) FROM expediente_items WHERE expediente_id=?",
                        (expediente_id,)).fetchone()[0]
    con.execute("UPDATE expedientes SET valor_total=? WHERE id=?", (total, expediente_id))


# Clasificación sugerida por nombre, según las fichas técnicas de fabricantes:
# - Insumos: vencen salvo los que el fabricante declara sin caducidad (fresas no estériles,
#   cuñas de madera, matrices metálicas, baberos, vasos, eyectores, cubetas plásticas).
#   Los estériles (hojas de bisturí, limas, suturas), químicos y materiales con vida útil
#   (rollos de algodón, papel de articular, yeso) SÍ vencen.
# - Instrumental: reutilizable, sin caducidad; vence solo el descartable o estéril de un solo uso.
SIN_VENCIMIENTO = ("fresa", "fresas", "cuna", "cunas", "matriz", "matrices", "babero", "baberos",
                   "vaso descartable", "vasos descartables", "eyector", "eyectores", "cubeta plastica",
                   "cubetas plasticas", "tira de pulir", "tiras de pulir")
CON_VENCIMIENTO_INSTRUMENTAL = ("descartable", "descartables", "esteril", "esteriles", "un solo uso", "desechable",
                                "desechables")


def _contiene(texto, claves):
    t = " ".join(sin_acentos(str(texto or "")).lower().split())
    return any(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z]{3})", t) for k in claves)


def sugerir_vencimiento(grupo, descripcion):
    """Sugerencia inicial (el usuario puede cambiarla en la ficha del elemento)."""
    if grupo == "Instrumental":
        return _contiene(descripcion, CON_VENCIMIENTO_INSTRUMENTAL)
    return not _contiene(descripcion, SIN_VENCIMIENTO)


def vence_por_nombre(descripcion):
    return sugerir_vencimiento("Insumo", descripcion)


def lleva_vencimiento(con, elemento_id):
    r = con.execute("SELECT lleva_vencimiento FROM elementos WHERE id=?", (elemento_id,)).fetchone()
    return bool(r) and bool(r["lleva_vencimiento"])


def quitar_vencimientos(con, elemento_id):
    """Elemento marcado «sin vencimiento»: sus lotes y renglones de compra dejan de tener fecha."""
    con.execute("UPDATE lotes SET fecha_vencimiento=NULL WHERE elemento_id=?", (elemento_id,))
    con.execute("UPDATE expediente_items SET fecha_vencimiento=NULL WHERE elemento_id=?", (elemento_id,))


def ingresar_lote(con, elemento_id, cantidad, vencimiento, usuario, fecha=None,
                  expediente_id=None, item_id=None, precio=None, razon="Ingreso", observaciones=None):
    """Alta de stock: crea un lote y su movimiento de Alta (Ingreso o Ajuste)."""
    fecha = fecha or ahora()
    if not lleva_vencimiento(con, elemento_id):
        vencimiento = None
    if precio is None:
        precio = con.execute("SELECT precio_unitario FROM elementos WHERE id=?", (elemento_id,)).fetchone()[0]
    cur = con.execute(
        "INSERT INTO lotes(elemento_id,expediente_id,item_id,cantidad_inicial,cantidad_actual,fecha_vencimiento,fecha_ingreso)"
        " VALUES(?,?,?,?,?,?,?)", (elemento_id, expediente_id, item_id, cantidad, cantidad, vencimiento or None, fecha))
    lote_id = cur.lastrowid
    cur = con.execute(
        "INSERT INTO movimientos(fecha,usuario,elemento_id,tipo,razon,cantidad,precio_unitario,expediente_id,observaciones)"
        " VALUES(?,?,?,?,?,?,?,?,?)", (fecha, usuario, elemento_id, "Alta", razon, cantidad, precio, expediente_id,
                                       observaciones))
    con.execute("INSERT INTO movimiento_lotes VALUES(?,?,?)", (cur.lastrowid, lote_id, cantidad))
    recalcular_stock(con, elemento_id)
    return lote_id


RAZONES_ENTREGA = ("Entrega", "Préstamo")


def lotes_disponibles(con, elemento_id, razon, ref=None):
    """Lotes con saldo que pueden usarse para una salida, en orden FEFO.
    - Entrega / Préstamo: solo lotes sin vencer a la fecha de referencia.
    - Vencido: solo lotes ya vencidos.
    - Otras bajas (Roto, Perdido...): cualquier lote."""
    ref = (ref or hoy())[:10]
    sql = "SELECT * FROM lotes WHERE elemento_id=? AND cantidad_actual>0"
    p = [elemento_id]
    if razon in RAZONES_ENTREGA:
        sql += " AND (fecha_vencimiento IS NULL OR fecha_vencimiento >= ?)"
        p.append(ref)
    elif razon == "Vencido":
        sql += " AND fecha_vencimiento IS NOT NULL AND fecha_vencimiento < ?"
        p.append(ref)
    sql += " ORDER BY fecha_vencimiento IS NULL, fecha_vencimiento, fecha_ingreso, id"
    return con.execute(sql, p).fetchall()


def disponible(con, elemento_id, razon, ref=None):
    return sum(l["cantidad_actual"] for l in lotes_disponibles(con, elemento_id, razon, ref))


def egresar(con, elemento_id, cantidad, razon, usuario, region=None, acta_id=None, fecha=None,
            observaciones=None, lote_id=None):
    """Baja de stock. Se descuentan primero los elementos más antiguos
    (vencimiento más próximo; luego fecha de ingreso). Las entregas y
    préstamos nunca toman unidades vencidas."""
    fecha = fecha or ahora()
    el = con.execute("SELECT * FROM elementos WHERE id=?", (elemento_id,)).fetchone()
    lotes = lotes_disponibles(con, elemento_id, razon, fecha)
    if lote_id:                       # descontar de un lote determinado
        lotes = [l for l in lotes if l["id"] == lote_id]
        if not lotes:
            raise ValueError("El lote elegido no tiene unidades disponibles.")
    disp = sum(l["cantidad_actual"] for l in lotes)
    if cantidad > disp:
        if razon in RAZONES_ENTREGA:
            vencidas = el["stock_actual"] - disp
            extra = (f" Hay {vencidas} unidades vencidas que no pueden entregarse; dé de baja por «Vencido»."
                     if vencidas > 0 else "")
            raise ValueError(f"Stock sin vencer insuficiente de «{el['descripcion']}»: disponible {disp}, "
                             f"solicitado {cantidad}.{extra}")
        if razon == "Vencido":
            raise ValueError(f"«{el['descripcion']}» tiene {disp} unidades vencidas; "
                             f"no puede dar de baja {cantidad} por vencimiento.")
        raise ValueError(f"Stock insuficiente{' en ese lote' if lote_id else ''} de «{el['descripcion']}»: "
                         f"disponible {disp}, solicitado {cantidad}.")
    cur = con.execute(
        "INSERT INTO movimientos(fecha,usuario,elemento_id,tipo,razon,cantidad,precio_unitario,region,acta_id,observaciones)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (fecha, usuario, elemento_id, "Baja", razon, cantidad, el["precio_unitario"],
         region if razon in RAZONES_ENTREGA else None, acta_id, observaciones))
    mov_id = cur.lastrowid
    resto = cantidad
    for lote in lotes:
        if resto <= 0:
            break
        usa = min(resto, lote["cantidad_actual"])
        con.execute("UPDATE lotes SET cantidad_actual=cantidad_actual-? WHERE id=?", (usa, lote["id"]))
        con.execute("INSERT INTO movimiento_lotes VALUES(?,?,?)", (mov_id, lote["id"], usa))
        if lote["expediente_id"] and razon == "Entrega":
            con.execute("UPDATE expedientes SET fecha_entrega=? WHERE id=? AND fecha_entrega IS NULL",
                        (fecha[:10], lote["expediente_id"]))
        resto -= usa
    recalcular_stock(con, elemento_id)
    return mov_id


def ajustar(con, elemento_id, sentido, cantidad, motivo, usuario, lote_id=None, vencimiento=None):
    """Ajuste de inventario por diferencia con el conteo físico.
    - Faltante: descuenta (de un lote elegido o de los más antiguos).
    - Sobrante: suma un lote nuevo.
    Se registra con razón «Ajuste»: no cuenta como compra ni como entrega."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indique el motivo del ajuste.")
    if cantidad <= 0:
        raise ValueError("La cantidad del ajuste debe ser mayor que cero.")
    if sentido == "Faltante":
        return egresar(con, elemento_id, cantidad, "Ajuste", usuario, observaciones=motivo, lote_id=lote_id)
    if sentido == "Sobrante":
        return ingresar_lote(con, elemento_id, cantidad, vencimiento, usuario, razon="Ajuste", observaciones=motivo)
    raise ValueError("Indique si es un faltante o un sobrante.")


def copiar_base(destino):
    """Copia consistente de la base (aunque el sistema esté en uso)."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    origen, dst = conectar(), sqlite3.connect(destino)
    try:
        origen.backup(dst)
    finally:
        dst.close()
        origen.close()
    return destino


RESPALDOS_DIR = os.path.join(DATA_DIR, "respaldos")
TABLAS_REQUERIDAS = {"usuarios", "config", "listas", "elementos", "expedientes", "expediente_items",
                     "lotes", "movimientos", "actas"}


def validar_respaldo(ruta):
    """Verifica que el archivo sea una base de GSO sana. Devuelve un resumen o lanza ValueError."""
    try:
        c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("El archivo está dañado.")
        tablas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        faltan = TABLAS_REQUERIDAS - tablas
        if faltan:
            raise ValueError("El archivo no es un respaldo de GSO (faltan tablas: " + ", ".join(sorted(faltan)) + ").")
        if not c.execute("SELECT 1 FROM usuarios WHERE rol='Administrador'").fetchone():
            raise ValueError("El respaldo no tiene ningún usuario Administrador.")
        resumen = {k: c.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0] for k in ("expedientes", "elementos", "actas", "usuarios")}
        c.close()
        return resumen
    except sqlite3.DatabaseError:
        raise ValueError("El archivo no es una base de datos válida.")


def restaurar(ruta):
    """Reemplaza la base actual por el respaldo, dejando antes una copia automática de la actual."""
    validar_respaldo(ruta)
    previa = copiar_base(os.path.join(RESPALDOS_DIR, f"antes_de_restaurar_{datetime.now():%Y%m%d_%H%M%S}.db"))
    src, dst = sqlite3.connect(ruta), conectar()
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    inicializar()      # aplica migraciones si el respaldo es de una versión anterior
    return previa


def anular_acta(con, acta_id, usuario, motivo):
    """Revierte un acta: cada unidad vuelve al mismo lote del que salió.
    Los movimientos pasan a «movimientos_anulados», así dejan de contar en el
    stock y en las estadísticas, pero el acta conserva su detalle."""
    acta = con.execute("SELECT * FROM actas WHERE id=?", (acta_id,)).fetchone()
    if not acta:
        raise ValueError("El acta no existe.")
    if acta["anulada_fecha"]:
        raise ValueError(f"El acta N° {acta_id} ya fue anulada.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indique el motivo de la anulación.")
    elementos, expedientes = set(), set()
    for m in con.execute("SELECT * FROM movimientos WHERE acta_id=?", (acta_id,)).fetchall():
        detalle = con.execute("SELECT ml.lote_id, ml.cantidad, l.expediente_id FROM movimiento_lotes ml "
                              "JOIN lotes l ON l.id=ml.lote_id WHERE ml.movimiento_id=?", (m["id"],)).fetchall()
        for d in detalle:
            con.execute("UPDATE lotes SET cantidad_actual=cantidad_actual+? WHERE id=?", (d["cantidad"], d["lote_id"]))
            if d["expediente_id"]:
                expedientes.add(d["expediente_id"])
        con.execute("""INSERT INTO movimientos_anulados(id,fecha,usuario,elemento_id,tipo,razon,cantidad,precio_unitario,
                       region,acta_id,lotes) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (m["id"], m["fecha"], m["usuario"], m["elemento_id"], m["tipo"], m["razon"], m["cantidad"],
                     m["precio_unitario"], m["region"], m["acta_id"],
                     ",".join(f"{d['lote_id']}:{d['cantidad']}" for d in detalle)))
        con.execute("DELETE FROM movimientos WHERE id=?", (m["id"],))
        elementos.add(m["elemento_id"])
    for el in elementos:
        recalcular_stock(con, el)
    # La «primera entrega» de cada expediente afectado se recalcula sin esta acta.
    for x in expedientes:
        primera = con.execute("""SELECT MIN(substr(m.fecha,1,10)) FROM movimientos m
            JOIN movimiento_lotes ml ON ml.movimiento_id=m.id JOIN lotes l ON l.id=ml.lote_id
            WHERE l.expediente_id=? AND m.razon='Entrega'""", (x,)).fetchone()[0]
        con.execute("UPDATE expedientes SET fecha_entrega=? WHERE id=?", (primera, x))
    con.execute("UPDATE actas SET anulada_fecha=?, anulada_por=?, anulada_motivo=? WHERE id=?",
                (ahora(), usuario, motivo, acta_id))


def reiniciar():
    if os.path.exists(DB_PATH):
        copiar_base(os.path.join(RESPALDOS_DIR, f"antes_de_reiniciar_{datetime.now():%Y%m%d_%H%M%S}.db"))
        os.remove(DB_PATH)
    inicializar()
