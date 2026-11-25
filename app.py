"""GSO - Sistema de Gestión de Stock Odontológico.

Ejecutar:  python app.py   y abrir  http://127.0.0.1:5000
"""
import difflib
import io
import os
import re
import tempfile
import secrets
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from markupsafe import Markup
from werkzeug.utils import secure_filename

import db
from exportar import exportar_xlsx

app = Flask(__name__)

_secret_path = os.path.join(db.DATA_DIR, ".clave_sesion")
os.makedirs(db.DATA_DIR, exist_ok=True)
if not os.path.exists(_secret_path):
    with open(_secret_path, "w") as f:
        f.write(secrets.token_hex(32))
with open(_secret_path) as f:
    app.secret_key = f.read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

db.inicializar()

# Minutos sin actividad tras los cuales la sesión se cierra sola.
MINUTOS_SESION = int(os.environ.get("GSO_MINUTOS_SESION", 60))
# Intentos fallidos permitidos (ingreso y recuperación) antes de bloquear temporalmente.
MAX_INTENTOS, MINUTOS_BLOQUEO = 5, 15

TIPOS = {"insumos": "Insumo", "instrumental": "Instrumental"}
GRUPOS = ("Insumo", "Instrumental")
RAZONES_BAJA = ("Entrega", "Préstamo", "Roto", "Perdido", "Vencido")


def lista_fija(con, nombre, validos):
    """Valores de una lista fija, en el orden configurado, solo los que el sistema sabe usar."""
    return [v for v in db.lista(con, nombre) if v in validos]
TEMAS = {
    "clasico": "Clásico (azul marino y naranja)",
    "oceano": "Océano (azules y turquesa)",
    "atardecer": "Atardecer (crema y naranja intenso)",
    "grafito": "Grafito (negro y celeste)",
}
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]


# ---------------------------------------------------------------- utilidades
def get_db():
    if "con" not in g:
        g.con = db.conectar()
    return g.con


@app.teardown_appcontext
def cerrar(_):
    con = g.pop("con", None)
    if con:
        con.close()


def login_requerido(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session:
            return redirect(url_for("index"))
        # Se verifica contra la base en cada pedido: un usuario eliminado queda afuera
        # y un cambio de rol o de nombre se aplica de inmediato.
        u = get_db().execute("SELECT * FROM usuarios WHERE id=?", (session["uid"],)).fetchone()
        if not u:
            session.clear()
            flash("Su usuario ya no existe en el sistema.", "error")
            return redirect(url_for("index"))
        session.update(usuario=u["usuario"], nombre=f"{u['nombre']} {u['apellido']}", rol=u["rol"])
        return f(*a, **k)
    return w


# ---------------------------------------------------------------- seguridad
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.template_global()
def csrf_campo():
    # «_envio» identifica cada formulario mostrado: si llega dos veces (doble clic,
    # reenvío), el segundo no se registra.
    return Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">'
                  f'<input type="hidden" name="_envio" value="{secrets.token_hex(12)}">')


_envios = {}
_envios_lock = threading.Lock()


@app.before_request
def controles_de_seguridad():
    if request.endpoint == "static":
        return None
    # Expiración por inactividad
    if "uid" in session:
        ultimo = session.get("ultimo_uso", 0)
        if time.time() - ultimo > MINUTOS_SESION * 60:
            session.clear()
            flash("La sesión se cerró por inactividad. Ingrese nuevamente.", "error")
            return redirect(url_for("index"))
        session["ultimo_uso"] = time.time()
    # Protección contra envíos de formularios desde otros sitios (CSRF)
    if request.method == "POST":
        enviado = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not enviado or not secrets.compare_digest(enviado, session.get("csrf", "")):
            flash("El formulario venció o no es válido. Vuelva a intentarlo.", "error")
            return redirect(request.referrer or url_for("index"))
        envio = request.form.get("_envio")
        if envio:
            ahora_ = time.time()
            with _envios_lock:
                for k in [k for k, v in _envios.items() if ahora_ - v["t"] > 6 * 3600]:
                    _envios.pop(k)
                previo = _envios.get(envio)
                if not previo:
                    _envios[envio] = {"t": ahora_, "destino": None}
                    g.envio = envio
            if previo:
                flash("Ese formulario ya había sido enviado: no se registró por segunda vez.", "error")
                return redirect(previo["destino"] or request.referrer or url_for("index"))
    return None


@app.after_request
def recordar_envio(resp):
    envio = g.pop("envio", None)
    if envio:
        with _envios_lock:
            if resp.status_code >= 500:
                _envios.pop(envio, None)
            elif envio in _envios:
                _envios[envio]["destino"] = resp.location if 300 <= resp.status_code < 400 else None
    return resp


@app.teardown_request
def olvidar_envio_fallido(exc):
    envio = g.pop("envio", None)
    if exc is not None and envio:
        with _envios_lock:
            _envios.pop(envio, None)


_intentos = {}
_intentos_lock = threading.Lock()


def bloqueado(clave):
    with _intentos_lock:
        n, hasta = _intentos.get(clave, (0, 0))
        return n >= MAX_INTENTOS and time.time() < hasta


def registrar_fallo(clave):
    with _intentos_lock:
        n, hasta = _intentos.get(clave, (0, 0))
        if time.time() >= hasta and n >= MAX_INTENTOS:
            n = 0
        _intentos[clave] = (n + 1, time.time() + MINUTOS_BLOQUEO * 60)


def limpiar_fallos(clave):
    with _intentos_lock:
        _intentos.pop(clave, None)


def admin_requerido(f):
    @wraps(f)
    @login_requerido
    def w(*a, **k):
        if session.get("rol") != "Administrador":
            abort(403)
        return f(*a, **k)
    return w


@app.template_filter("pesos")
def pesos(v):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return v
    s = f"{v:,.2f}"
    return "$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("num")
def num(v):
    return f"{int(v or 0):,}".replace(",", ".")


@app.template_filter("fecha")
def fecha_fmt(v):
    if not v:
        return "—"
    try:
        d = datetime.fromisoformat(str(v)[:19])
        return d.strftime("%d/%m/%Y") if len(str(v)) <= 10 else d.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return v


@app.context_processor
def contexto():
    con = get_db()
    return {"cfg": db.config(con), "usuario_actual": session.get("usuario"),
            "nombre_actual": session.get("nombre"), "es_admin": session.get("rol") == "Administrador",
            "hoy": date.today(), "sin_venc_claves": db.SIN_VENCIMIENTO,
            "con_venc_claves": db.CON_VENCIMIENTO_INSTRUMENTAL}


def render(tpl, seccion=None, **kw):
    return render_template(tpl, seccion=seccion, **kw)


_MILES = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def _normalizar_numero(v):
    """Acepta formato argentino («1.500», «1.500,50», «$ 1.500») y el del navegador («1500.5»)."""
    t = str(v).replace("$", "").replace(" ", "").strip()
    if "," in t:                      # 1.500,50 -> 1500.50
        return t.replace(".", "").replace(",", ".")
    if _MILES.match(t):               # 1.500 / 1.500.000 -> separador de miles
        return t.replace(".", "")
    return t


def a_int(v, defecto=0):
    try:
        f = float(_normalizar_numero(v))
        return int(f) if f == int(f) else defecto
    except (TypeError, ValueError, OverflowError):
        return defecto


def a_float(v, defecto=0.0):
    try:
        return float(_normalizar_numero(v))
    except (TypeError, ValueError):
        return defecto


def limite_venc(con):
    dias = a_int(db.config(con).get("dias_alerta_vencimiento"), 60)
    return (date.today() + timedelta(days=dias)).isoformat()


def consulta_elementos(con, grupo=None, filtros=None):
    """Elementos con su estado de stock y de vencimiento calculado."""
    filtros = filtros or {}
    hoy, lim = db.hoy(), limite_venc(con)
    sql = """
    SELECT e.*,
      (SELECT MIN(fecha_vencimiento) FROM lotes l WHERE l.elemento_id=e.id AND e.lleva_vencimiento=1 AND l.cantidad_actual>0
          AND l.fecha_vencimiento IS NOT NULL) AS prox_venc,
      (SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes l WHERE l.elemento_id=e.id AND e.lleva_vencimiento=1 AND l.cantidad_actual>0
          AND l.fecha_vencimiento < :hoy) AS cant_vencida,
      (SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes l WHERE l.elemento_id=e.id AND e.lleva_vencimiento=1 AND l.cantidad_actual>0
          AND l.fecha_vencimiento >= :hoy AND l.fecha_vencimiento <= :lim) AS cant_por_vencer
    FROM elementos e WHERE 1=1"""
    p = {"hoy": hoy, "lim": lim}
    if grupo:
        sql += " AND e.grupo=:grupo"
        p["grupo"] = grupo
    if filtros.get("q"):
        sql += " AND (e.descripcion LIKE :q OR e.especificaciones LIKE :q)"
        p["q"] = f"%{filtros['q']}%"
    if filtros.get("especialidad"):
        sql += " AND e.especialidad=:esp"
        p["esp"] = filtros["especialidad"]
    if filtros.get("vence") in ("si", "no"):
        sql += " AND e.lleva_vencimiento=:vence"
        p["vence"] = 1 if filtros["vence"] == "si" else 0
    sql += " ORDER BY e.especialidad, e.descripcion"
    filas = []
    for r in con.execute(sql, p):
        d = dict(r)
        if d["stock_actual"] <= 0:
            d["estado_stock"] = "agotado"
        elif d["stock_actual"] <= d["stock_minimo"]:
            d["estado_stock"] = "critico"
        else:
            d["estado_stock"] = "normal"
        if d["cant_vencida"] > 0:
            d["estado_venc"] = "vencido"
        elif d["cant_por_vencer"] > 0:
            d["estado_venc"] = "proximo"
        else:
            d["estado_venc"] = ""
        d["valor"] = d["stock_actual"] * d["precio_unitario"]
        filas.append(d)
    est = filtros.get("estado")
    if est in ("critico", "agotado"):
        filas = [f for f in filas if f["estado_stock"] == est]
    elif est in ("vencido", "proximo"):
        filas = [f for f in filas if f["estado_venc"] == est]
    elif est == "alerta_stock":
        filas = [f for f in filas if f["estado_stock"] != "normal"]
    elif est == "alerta_venc":
        filas = [f for f in filas if f["estado_venc"]]
    return filas


def exportar_si_corresponde(titulo, columnas, filas):
    if request.args.get("formato") == "xlsx":
        cfg = db.config(get_db())
        buf = exportar_xlsx(titulo, columnas, filas, cfg.get("organismo", ""))
        nombre = secure_filename(titulo.replace(" ", "_")) + ".xlsx"
        return send_file(buf, as_attachment=True, download_name=nombre,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return None


# ---------------------------------------------------------------- 1 INDEX
@app.route("/", methods=["GET", "POST"])
def index():
    if "uid" in session:
        return redirect(url_for("inicio"))
    if request.method == "POST":
        con = get_db()
        nombre = request.form.get("usuario", "").strip()
        clave_bloqueo = ("login", request.remote_addr, nombre.upper())
        if bloqueado(clave_bloqueo):
            flash(f"Demasiados intentos fallidos. Espere {MINUTOS_BLOQUEO} minutos o use «Recuperar contraseña».", "error")
            return render("login.html")
        u = con.execute("SELECT * FROM usuarios WHERE usuario=?", (nombre,)).fetchone()
        if u and db.clave_correcta(u["contrasena"], request.form.get("contrasena", "")):
            limpiar_fallos(clave_bloqueo)
            session.clear()
            session.update(uid=u["id"], usuario=u["usuario"], nombre=f"{u['nombre']} {u['apellido']}", rol=u["rol"],
                           ultimo_uso=time.time())
            return redirect(url_for("inicio"))
        registrar_fallo(clave_bloqueo)
        flash("Usuario o contraseña incorrectos.", "error")
    return render("login.html")


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    """Paso 1: apellido + PIN. Paso 2: el usuario define una contraseña nueva.
    La contraseña anterior nunca se muestra (se guarda cifrada)."""
    con = get_db()
    paso, usuario = 1, None
    if request.method == "POST" and request.form.get("paso") == "2":
        rid = session.get("recuperar_uid")
        vence = session.get("recuperar_hasta", 0)
        u = con.execute("SELECT * FROM usuarios WHERE id=?", (rid,)).fetchone() if rid else None
        if not u or time.time() > vence:
            session.pop("recuperar_uid", None)
            flash("El tiempo para cambiar la contraseña venció. Vuelva a ingresar apellido y PIN.", "error")
            return redirect(url_for("recuperar"))
        nueva, repetir = request.form.get("nueva", ""), request.form.get("repetir", "")
        if len(nueva) < 4:
            flash("La contraseña nueva debe tener al menos 4 caracteres.", "error")
            return render("recuperar.html", paso=2, usuario=u["usuario"])
        if nueva != repetir:
            flash("Las contraseñas no coinciden.", "error")
            return render("recuperar.html", paso=2, usuario=u["usuario"])
        con.execute("UPDATE usuarios SET contrasena=? WHERE id=?", (db.cifrar(nueva), u["id"]))
        con.commit()
        session.pop("recuperar_uid", None)
        flash(f"Contraseña actualizada. Ingrese con el usuario {u['usuario']}.", "ok")
        return redirect(url_for("index"))
    if request.method == "POST":
        clave_bloqueo = ("recuperar", request.remote_addr)
        if bloqueado(clave_bloqueo):
            flash(f"Demasiados intentos fallidos. Espere {MINUTOS_BLOQUEO} minutos.", "error")
            return render("recuperar.html", paso=1)
        u = con.execute("SELECT * FROM usuarios WHERE apellido=? COLLATE NOCASE AND pin=?",
                        (request.form.get("apellido", "").strip(), request.form.get("pin", "").strip())).fetchone()
        if u:
            limpiar_fallos(clave_bloqueo)
            session["recuperar_uid"] = u["id"]
            session["recuperar_hasta"] = time.time() + 10 * 60
            paso, usuario = 2, u["usuario"]
        else:
            registrar_fallo(clave_bloqueo)
            flash("No se encontró un usuario con ese apellido y PIN de seguridad.", "error")
    return render("recuperar.html", paso=paso, usuario=usuario)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- 2 INICIO
@app.route("/inicio")
@login_requerido
def inicio():
    con = get_db()
    total_bienes = con.execute("SELECT COALESCE(SUM(stock_actual*precio_unitario),0) FROM elementos").fetchone()[0]
    exp = con.execute("""SELECT COUNT(*) t, SUM(estado='Activo') a, SUM(estado='Cerrado') c FROM expedientes""").fetchone()
    insumos = consulta_elementos(con, "Insumo")
    instr = consulta_elementos(con, "Instrumental")
    alertas = {
        "ins_vencido": [e for e in insumos if e["estado_venc"] == "vencido"],
        "ins_proximo": [e for e in insumos if e["estado_venc"] == "proximo"],
        "inst_vencido": [e for e in instr if e["estado_venc"] == "vencido"],
        "inst_proximo": [e for e in instr if e["estado_venc"] == "proximo"],
        "ins_agotado": [e for e in insumos if e["estado_stock"] == "agotado"],
        "ins_critico": [e for e in insumos if e["estado_stock"] == "critico"],
        "ins_t_agotado": [e for e in instr if e["estado_stock"] == "agotado"],
        "ins_t_critico": [e for e in instr if e["estado_stock"] == "critico"],
    }
    por_grupo = {r["grupo"]: r["v"] for r in con.execute(
        "SELECT grupo, SUM(stock_actual*precio_unitario) v FROM elementos GROUP BY grupo")}
    ultimos_mov = con.execute("""SELECT m.*, e.descripcion, e.grupo FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
                                 ORDER BY m.fecha DESC, m.id DESC LIMIT 6""").fetchall()
    return render("inicio.html", "inicio", total_bienes=total_bienes, exp=exp, alertas=alertas,
                  por_grupo=por_grupo, ultimos_mov=ultimos_mov,
                  n_insumos=len(insumos), n_instr=len(instr))


# ---------------------------------------------------------------- 3 EXPEDIENTES
@app.route("/expedientes")
@login_requerido
def expedientes():
    con = get_db()
    ultimos = con.execute("SELECT * FROM expedientes ORDER BY id DESC LIMIT 5").fetchall()
    return render("expedientes.html", "expedientes", ultimos=ultimos)


@app.route("/expedientes/abm")
@login_requerido
def expedientes_abm():
    con = get_db()
    filas = con.execute("SELECT * FROM expedientes ORDER BY anio DESC, numero DESC").fetchall()
    r = exportar_si_corresponde("Expedientes", ["Expediente", "Grupo", "Fecha", "Primera entrega", "Estado", "Valor total"],
                                [[f["nro_expediente"], f["grupo"], f["fecha"], f["fecha_entrega"] or "", f["estado"], f["valor_total"]] for f in filas])
    return r or render("expedientes_abm.html", "expedientes", filas=filas)


def elementos_json(con, grupo=None):
    """Elementos para los formularios. «vencido» = unidades ya vencidas;
    «vigente» = unidades que pueden entregarse."""
    sql = """SELECT id, grupo, especialidad, descripcion, envase, precio_unitario, stock_actual, lleva_vencimiento,
                    (SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes l WHERE l.elemento_id=e.id AND e.lleva_vencimiento=1 AND l.cantidad_actual>0
                       AND l.fecha_vencimiento IS NOT NULL AND l.fecha_vencimiento < :hoy) AS vencido
             FROM elementos e"""
    p = {"hoy": db.hoy()}
    if grupo:
        sql += " WHERE grupo=:grupo"
        p["grupo"] = grupo
    filas = [dict(r) for r in con.execute(sql + " ORDER BY grupo, especialidad, descripcion", p)]
    for f in filas:
        f["vigente"] = f["stock_actual"] - f["vencido"]
    return filas


def items_bloqueados(con, expediente_id):
    """Ítems con consumo (bajas) no pueden cambiar cantidad ni eliminarse."""
    return {r["item_id"] for r in con.execute(
        "SELECT item_id FROM lotes WHERE expediente_id=? AND cantidad_actual<cantidad_inicial", (expediente_id,))}


@app.route("/expedientes/nuevo", methods=["GET", "POST"])
@app.route("/expedientes/<int:eid>/editar", methods=["GET", "POST"])
@login_requerido
def expediente_form(eid=None):
    con = get_db()
    exp = con.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone() if eid else None
    if eid and not exp:
        abort(404)
    items = [dict(r) for r in con.execute(
        "SELECT i.*, e.descripcion FROM expediente_items i JOIN elementos e ON e.id=i.elemento_id WHERE expediente_id=? ORDER BY i.id",
        (eid,))] if eid else []
    bloqueados = items_bloqueados(con, eid) if eid else set()

    if request.method == "POST":
        f = request.form
        if exp and exp["estado"] == "Cerrado":
            # Un expediente cerrado no se modifica: solo puede reabrirse.
            if f.get("estado") != "Activo":
                flash("El expediente está cerrado y no puede modificarse. Para cambiarlo, primero páselo a «Activo».", "error")
                return redirect(request.url)
            con.execute("UPDATE expedientes SET estado='Activo' WHERE id=?", (eid,))
            con.execute("INSERT INTO expediente_log(expediente_id, nro_expediente, usuario, accion, fecha) VALUES(?,?,?,?,?)",
                        (eid, exp["nro_expediente"], session["usuario"], "Reapertura", db.ahora()))
            con.commit()
            flash(f"Expediente {exp['nro_expediente']} reabierto. Ya puede modificarlo.", "ok")
            return redirect(url_for("expediente_form", eid=eid))
        anio = a_int(f.get("anio"))
        numero = "".join(ch for ch in f.get("numero", "") if ch.isdigit())
        if not (1990 <= anio <= 2100) or not numero or len(numero) > 8:
            flash("Número de expediente inválido. Formato: AAAA-NNNNNNNN (hasta 8 dígitos).", "error")
            return redirect(request.url)
        numero = numero.zfill(8)
        nro = f"{anio}-{numero}"
        otro = con.execute("SELECT id FROM expedientes WHERE nro_expediente=?", (nro,)).fetchone()
        if otro and otro["id"] != eid:
            flash(f"El expediente {nro} ya existe.", "error")
            return redirect(request.url)
        fecha_exp = f.get("fecha") or db.hoy()
        try:
            date.fromisoformat(fecha_exp)
        except ValueError:
            flash("La fecha del expediente no es válida.", "error")
            return redirect(request.url)
        if exp and fecha_exp != exp["fecha"]:
            # Las altas del expediente toman su fecha; no puede quedar posterior a una baja ya registrada.
            primera_baja = con.execute("""SELECT MIN(m.fecha) FROM movimientos m
                JOIN movimiento_lotes ml ON ml.movimiento_id=m.id JOIN lotes l ON l.id=ml.lote_id
                WHERE l.expediente_id=? AND m.tipo='Baja'""", (eid,)).fetchone()[0]
            if primera_baja and fecha_exp > primera_baja[:10]:
                flash(f"La fecha no puede ser posterior al {fecha_fmt(primera_baja[:10])}: "
                      "ese día ya se registraron bajas de elementos de este expediente.", "error")
                return redirect(request.url)
        grupo = f.get("grupo") or "Insumo"
        if exp and exp["grupo"] != grupo and items:
            grupo = exp["grupo"]
        campos = (anio, numero, nro, grupo, fecha_exp, f.get("estado") or "Activo",
                  f.get("solicitado_por", ""), f.get("utilizado_en", ""), f.get("entregar_en", ""))
        usuario = session["usuario"]
        try:
            if exp:
                con.execute("""UPDATE expedientes SET anio=?, numero=?, nro_expediente=?, grupo=?, fecha=?, estado=?,
                               solicitado_por=?, utilizado_en=?, entregar_en=? WHERE id=?""", campos + (eid,))
                accion = "Modificación"
            else:
                cur = con.execute("""INSERT INTO expedientes(anio, numero, nro_expediente, grupo, fecha, estado,
                               solicitado_por, utilizado_en, entregar_en, usuario) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                                  campos + (usuario,))
                eid = cur.lastrowid
                accion = "Alta"
            # ---- ítems
            ids = f.getlist("item_id")
            elems = f.getlist("elemento_id")
            nros, letras, unidades = f.getlist("nro"), f.getlist("letra"), f.getlist("unidad")
            cants, precios, vencs = f.getlist("cantidad"), f.getlist("precio"), f.getlist("vencimiento")
            enviados, sin_cambio = set(), []
            previos = {it["id"]: it for it in items}
            fecha_mov = fecha_exp + datetime.now().strftime(" %H:%M:%S")
            for i, el in enumerate(elems):
                if not el:
                    continue
                item_id = a_int(ids[i]) if i < len(ids) and ids[i] else None
                el = a_int(el)
                cant, precio = a_int(cants[i]), a_float(precios[i])
                venc = (vencs[i] if i < len(vencs) else "") or None
                if not db.lleva_vencimiento(con, el):
                    venc = None
                if cant <= 0:
                    continue
                if item_id:
                    enviados.add(item_id)
                    if item_id in bloqueados:
                        con.execute("UPDATE expediente_items SET nro=?, letra=?, unidad=? WHERE id=?",
                                    (nros[i], letras[i], unidades[i], item_id))
                        ant = previos.get(item_id)
                        if ant and (el != ant["elemento_id"] or cant != ant["cantidad"]
                                    or abs(precio - ant["precio_unitario"]) > 0.005 or venc != ant["fecha_vencimiento"]):
                            sin_cambio.append(f"renglón {ant['nro'] or ''}{ant['letra'] or ''} ({ant['descripcion']})".replace("renglón  ", "renglón "))
                        continue
                    con.execute("""UPDATE expediente_items SET elemento_id=?, nro=?, letra=?, unidad=?, cantidad=?,
                                   precio_unitario=?, fecha_vencimiento=? WHERE id=? AND expediente_id=?""",
                                (el, nros[i], letras[i], unidades[i], cant, precio, venc, item_id, eid))
                    lote = con.execute("SELECT * FROM lotes WHERE item_id=?", (item_id,)).fetchone()
                    if lote:
                        viejo_el = lote["elemento_id"]
                        con.execute("""UPDATE lotes SET elemento_id=?, cantidad_inicial=?, cantidad_actual=?,
                                       fecha_vencimiento=? WHERE id=?""", (el, cant, cant, venc, lote["id"]))
                        con.execute("""UPDATE movimientos SET elemento_id=?, cantidad=?, precio_unitario=? WHERE tipo='Alta'
                                       AND id IN (SELECT movimiento_id FROM movimiento_lotes WHERE lote_id=?)""",
                                    (el, cant, precio, lote["id"]))
                        db.recalcular_stock(con, viejo_el)
                else:
                    cur = con.execute("""INSERT INTO expediente_items(expediente_id, elemento_id, nro, letra, unidad,
                                         cantidad, precio_unitario, fecha_vencimiento) VALUES(?,?,?,?,?,?,?,?)""",
                                      (eid, el, nros[i], letras[i], unidades[i], cant, precio, venc))
                    db.ingresar_lote(con, el, cant, venc, usuario, fecha_mov, eid, cur.lastrowid, precio)
                if precio > 0:
                    con.execute("UPDATE elementos SET precio_unitario=? WHERE id=?", (precio, el))
                db.recalcular_stock(con, el)
            for it in items:
                if it["id"] not in enviados and it["id"] not in bloqueados:
                    borrar_item(con, it)
            # Los ingresos (movimientos de Alta y lotes) llevan siempre la fecha del expediente,
            # así las estadísticas por período reflejan la fecha real de compra.
            con.execute("""UPDATE movimientos SET fecha = ? || substr(fecha, 11)
                           WHERE expediente_id=? AND tipo='Alta'""", (fecha_exp, eid))
            con.execute("UPDATE lotes SET fecha_ingreso = ? || substr(fecha_ingreso, 11) WHERE expediente_id=?",
                        (fecha_exp, eid))
            db.recalcular_expediente(con, eid)
            nuevo_estado = f.get("estado") or "Activo"
            if exp and nuevo_estado != exp["estado"]:
                accion = "Cierre" if nuevo_estado == "Cerrado" else "Reapertura"
            con.execute("INSERT INTO expediente_log(expediente_id, nro_expediente, usuario, accion, fecha) VALUES(?,?,?,?,?)",
                        (eid, nro, usuario, accion, db.ahora()))
            con.commit()
        except Exception as e:  # noqa
            con.rollback()
            flash(f"No se pudo guardar: {e}", "error")
            return redirect(request.url)
        flash(f"Expediente {nro} guardado.", "ok")
        if sin_cambio:
            flash("No se cambió elemento, cantidad, precio ni vencimiento de: " + "; ".join(sin_cambio) +
                  ". Esos renglones ya tienen bajas registradas. Para corregirlos, primero anule las actas de esas salidas.",
                  "error")
        return redirect(url_for("expediente_detalle", eid=eid))

    return render("expediente_form.html", "expedientes", exp=exp, items=items, bloqueados=bloqueados,
                  elementos=elementos_json(con), grupos=lista_fija(con, "grupo", GRUPOS), estados=db.lista(con, "estado"),
                  envases=db.lista(con, "envase"))


def borrar_item(con, it):
    lote = con.execute("SELECT * FROM lotes WHERE item_id=?", (it["id"],)).fetchone()
    if lote:
        con.execute("DELETE FROM movimientos WHERE tipo='Alta' AND id IN (SELECT movimiento_id FROM movimiento_lotes WHERE lote_id=?)",
                    (lote["id"],))
        con.execute("DELETE FROM lotes WHERE id=?", (lote["id"],))
    con.execute("DELETE FROM expediente_items WHERE id=?", (it["id"],))
    db.recalcular_stock(con, it["elemento_id"])


@app.route("/expedientes/<int:eid>/eliminar", methods=["POST"])
@login_requerido
def expediente_eliminar(eid):
    con = get_db()
    exp = con.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone()
    if not exp:
        abort(404)
    if exp["estado"] == "Cerrado":
        flash("No se puede eliminar un expediente cerrado. Si realmente corresponde, primero reábralo.", "error")
        return redirect(url_for("expediente_detalle", eid=eid))
    if items_bloqueados(con, eid):
        flash("No se puede eliminar: el expediente tiene elementos con bajas registradas.", "error")
        return redirect(url_for("expediente_detalle", eid=eid))
    for it in con.execute("SELECT * FROM expediente_items WHERE expediente_id=?", (eid,)).fetchall():
        borrar_item(con, it)
    con.execute("DELETE FROM expedientes WHERE id=?", (eid,))
    con.execute("INSERT INTO expediente_log(expediente_id, nro_expediente, usuario, accion, fecha) VALUES(?,?,?,?,?)",
                (eid, exp["nro_expediente"], session["usuario"], "Baja", db.ahora()))
    con.commit()
    flash(f"Expediente {exp['nro_expediente']} eliminado.", "ok")
    return redirect(url_for("expedientes_abm"))


@app.route("/expedientes/consultar")
@login_requerido
def expedientes_consultar():
    con = get_db()
    anio, numero, usuario = request.args.get("anio", ""), request.args.get("numero", "").strip(), request.args.get("usuario", "")
    buscado = bool(anio or numero or usuario)
    filas = []
    if buscado:
        sql, p = "SELECT DISTINCT x.* FROM expedientes x LEFT JOIN expediente_log l ON l.expediente_id=x.id WHERE 1=1", []
        if anio:
            sql += " AND x.anio=?"
            p.append(a_int(anio))
        if numero:
            sql += " AND (x.numero LIKE ? OR x.nro_expediente LIKE ?)"
            p += [f"%{numero}%", f"%{numero}%"]
        if usuario:
            sql += " AND (l.usuario=? OR x.usuario=?)"
            p += [usuario, usuario]
        filas = con.execute(sql + " ORDER BY x.anio DESC, x.numero DESC", p).fetchall()
        if len(filas) == 1 and anio and numero:
            return redirect(url_for("expediente_detalle", eid=filas[0]["id"]))
    anios = [r[0] for r in con.execute("SELECT DISTINCT anio FROM expedientes ORDER BY anio DESC")]
    usuarios = [r[0] for r in con.execute(
        "SELECT DISTINCT usuario FROM expediente_log UNION SELECT DISTINCT usuario FROM expedientes WHERE usuario IS NOT NULL ORDER BY 1")]
    return render("expedientes_consultar.html", "expedientes", filas=filas, buscado=buscado,
                  anios=anios, usuarios=usuarios, a=request.args)


def detalle_items(con, eid):
    return [dict(r) for r in con.execute("""
        SELECT i.*, e.descripcion, e.especialidad, e.especificaciones, e.envase,
               COALESCE((SELECT SUM(cantidad_actual) FROM lotes l WHERE l.item_id=i.id),0) AS restante
        FROM expediente_items i JOIN elementos e ON e.id=i.elemento_id
        WHERE i.expediente_id=? ORDER BY CAST(i.nro AS INTEGER), i.nro, i.letra, i.id""", (eid,))]


@app.route("/expedientes/<int:eid>")
@login_requerido
def expediente_detalle(eid):
    con = get_db()
    exp = con.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone()
    if not exp:
        abort(404)
    items = detalle_items(con, eid)
    r = exportar_si_corresponde(f"Expediente {exp['nro_expediente']}",
                                ["Elemento", "Especialidad", "Cantidad comprada", "Sin consumir", "Precio unitario", "Subtotal"],
                                [[i["descripcion"], i["especialidad"], i["cantidad"], i["restante"], i["precio_unitario"],
                                  i["cantidad"] * i["precio_unitario"]] for i in items]
                                + [["TOTAL", "", "", "", "", exp["valor_total"]]])
    if r:
        return r
    log = con.execute("SELECT * FROM expediente_log WHERE expediente_id=? ORDER BY id DESC", (eid,)).fetchall()
    return render("expediente_detalle.html", "expedientes", exp=exp, items=items, log=log,
                  bloqueado=bool(items_bloqueados(con, eid)))


@app.route("/expedientes/<int:eid>/pedido")
@login_requerido
def expediente_pedido(eid):
    con = get_db()
    exp = con.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone()
    if not exp:
        abort(404)
    items = detalle_items(con, eid)
    r = exportar_si_corresponde(f"Pedido de provision {exp['nro_expediente']}",
                                ["Orden", "Nro", "Letra", "Unidad", "Descripción", "$ Unitario", "Cantidad", "Subtotal"],
                                [[n + 1, i["nro"], i["letra"], i["unidad"], i["descripcion"], i["precio_unitario"], i["cantidad"],
                                  i["cantidad"] * i["precio_unitario"]] for n, i in enumerate(items)]
                                + [["", "", "", "", "TOTAL", "", "", exp["valor_total"]]])
    return r or render("pedido_print.html", "expedientes", exp=exp, items=items)


@app.route("/expedientes/<int:eid>/especificaciones")
@login_requerido
def expediente_especificaciones(eid):
    con = get_db()
    exp = con.execute("SELECT * FROM expedientes WHERE id=?", (eid,)).fetchone()
    if not exp:
        abort(404)
    items = detalle_items(con, eid)
    r = exportar_si_corresponde(f"Especificaciones tecnicas {exp['nro_expediente']}",
                                ["Renglón", "Descripción", "Especialidad", "Unidad", "Cantidad", "Especificaciones técnicas"],
                                [[f"{i['nro'] or n + 1}{i['letra'] or ''}", i["descripcion"], i["especialidad"], i["unidad"],
                                  i["cantidad"], i["especificaciones"] or ""] for n, i in enumerate(items)])
    return r or render("especificaciones_print.html", "expedientes", exp=exp, items=items)


# ---------------------------------------------------------------- 4/5 INSTRUMENTAL e INSUMOS
def grupo_de(tipo):
    if tipo not in TIPOS:
        abort(404)
    return TIPOS[tipo]


@app.route("/<tipo>")
@login_requerido
def modulo_elementos(tipo):
    grupo = grupo_de(tipo)
    con = get_db()
    filas = consulta_elementos(con, grupo)
    criticos = sorted([f for f in filas if f["estado_stock"] == "critico"], key=lambda f: f["stock_actual"] / max(f["stock_minimo"], 1))[:5]
    agotados = [f for f in filas if f["estado_stock"] == "agotado"][:5]
    vencidos = [f for f in filas if f["estado_venc"] == "vencido"][:5]
    proximos = sorted([f for f in filas if f["estado_venc"] == "proximo"], key=lambda f: f["prox_venc"])[:5]
    resumen = {"total": len(filas), "unidades": sum(f["stock_actual"] for f in filas),
               "valor": sum(f["valor"] for f in filas),
               "criticos": sum(f["estado_stock"] == "critico" for f in filas),
               "agotados": sum(f["estado_stock"] == "agotado" for f in filas),
               "con_venc": sum(1 for f in filas if f["lleva_vencimiento"]),
               "sin_venc": sum(1 for f in filas if not f["lleva_vencimiento"]),
               "valor_con": sum(f["valor"] for f in filas if f["lleva_vencimiento"]),
               "valor_sin": sum(f["valor"] for f in filas if not f["lleva_vencimiento"])}
    return render("elementos.html", tipo, tipo=tipo, grupo=grupo, criticos=criticos, agotados=agotados,
                  vencidos=vencidos, proximos=proximos, resumen=resumen)


@app.route("/<tipo>/abm")
@login_requerido
def elementos_abm(tipo):
    return _elementos_listado(tipo, True)


@app.route("/<tipo>/consultar")
@login_requerido
def elementos_consultar(tipo):
    return _elementos_listado(tipo, False)


def _elementos_listado(tipo, es_abm):
    grupo = grupo_de(tipo)
    con = get_db()
    filtros = {k: request.args.get(k, "") for k in ("q", "especialidad", "estado", "vence")}
    filas = consulta_elementos(con, grupo, filtros)
    # Cantidad por categoría de vencimiento con los demás filtros aplicados (para las pestañas)
    base = consulta_elementos(con, grupo, {**filtros, "vence": ""})
    categorias = {"": len(base), "si": sum(1 for f in base if f["lleva_vencimiento"]),
                  "no": sum(1 for f in base if not f["lleva_vencimiento"])}
    cols = ["Descripción", "Especialidad"] + (["Envase"] if grupo == "Insumo" else []) + ["Categoría"] + \
           ["Stock actual", "Stock mínimo", "Precio unitario", "Valor en stock"] + \
           ["Próximo vencimiento", "Unid. vencidas", "Unid. por vencer"] + ["Estado stock"]
    datos = []
    for f in filas:
        row = [f["descripcion"], f["especialidad"]] + \
              ([f["envase"]] if grupo == "Insumo" else []) + ["Con vencimiento" if f["lleva_vencimiento"] else "Sin vencimiento"] + \
              [f["stock_actual"], f["stock_minimo"], f["precio_unitario"], f["valor"]] + \
              [f["prox_venc"] or "", f["cant_vencida"], f["cant_por_vencer"]] + \
              [{"agotado": "Agotado", "critico": "Crítico", "normal": "Normal"}[f["estado_stock"]]]
        datos.append(row)
    r = exportar_si_corresponde(f"{grupo} - consulta", cols, datos)
    return r or render("elementos_consultar.html", tipo, tipo=tipo, grupo=grupo, filas=filas, f=filtros,
                       especialidades=db.lista(con, "especialidad"), es_abm=es_abm, categorias=categorias)


def normalizar_nombre(txt):
    t = db.sin_acentos(str(txt or "")).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def elementos_parecidos(con, grupo, descripcion, excluir_id=None):
    """Elementos del mismo grupo con nombre igual o muy parecido (sin importar
    mayúsculas, acentos, espacios ni signos, ni el orden de las palabras)."""
    buscado = normalizar_nombre(descripcion)
    palabras = sorted(buscado.split())
    res = []
    for r in con.execute("SELECT id, descripcion, especialidad, stock_actual FROM elementos WHERE grupo=?", (grupo,)):
        if r["id"] == excluir_id:
            continue
        otro = normalizar_nombre(r["descripcion"])
        parecido = difflib.SequenceMatcher(None, buscado, otro).ratio()
        if otro == buscado or sorted(otro.split()) == palabras or parecido >= 0.85:
            res.append((1 if otro == buscado else parecido, dict(r)))
    return [r for _, r in sorted(res, key=lambda x: -x[0])[:5]]


@app.route("/<tipo>/nuevo", methods=["GET", "POST"])
@app.route("/<tipo>/<int:elid>/editar", methods=["GET", "POST"])
@login_requerido
def elemento_form(tipo, elid=None):
    grupo = grupo_de(tipo)
    con = get_db()
    el = con.execute("SELECT * FROM elementos WHERE id=? AND grupo=?", (elid, grupo)).fetchone() if elid else None
    if elid and not el:
        abort(404)
    cfg = db.config(con)
    if request.method == "POST":
        f = request.form
        if not f.get("descripcion", "").strip():
            flash("La descripción es obligatoria.", "error")
            return redirect(request.url)
        cambia_nombre = not el or normalizar_nombre(el["descripcion"]) != normalizar_nombre(f["descripcion"])
        if cambia_nombre and not f.get("confirmar_duplicado"):
            parecidos = elementos_parecidos(con, grupo, f["descripcion"], elid)
            if parecidos:
                return render("elemento_form.html", tipo, tipo=tipo, grupo=grupo, el=el, v=f, parecidos=parecidos,
                              lotes=[], movs=[], especialidades=db.lista(con, "especialidad"),
                              envases=db.lista(con, "envase"), minimo_defecto=cfg["stock_minimo_defecto"])
        vals = (f.get("especialidad"), f["descripcion"].strip(), f.get("envase") if grupo == "Insumo" else None,
                f.get("especificaciones", ""), a_int(f.get("stock_minimo"), a_int(cfg["stock_minimo_defecto"], 10)),
                a_float(f.get("precio_unitario")))
        vals += (1 if f.get("lleva_vencimiento") else 0,)
        if el:
            con.execute("""UPDATE elementos SET especialidad=?, descripcion=?, envase=?, especificaciones=?,
                           stock_minimo=?, precio_unitario=?, lleva_vencimiento=? WHERE id=?""", vals + (elid,))
        else:
            cur = con.execute("""INSERT INTO elementos(especialidad, descripcion, envase, especificaciones, stock_minimo,
                                 precio_unitario, lleva_vencimiento, grupo, creado) VALUES(?,?,?,?,?,?,?,?,?)""",
                              vals + (grupo, db.ahora()))
            elid = cur.lastrowid
        if not vals[-1]:
            db.quitar_vencimientos(con, elid)
        inicial = a_int(f.get("stock_inicial"))
        if inicial > 0:
            db.ingresar_lote(con, elid, inicial, f.get("vencimiento") or None, session["usuario"])
        con.commit()
        flash("Elemento guardado.", "ok")
        return redirect(url_for("elementos_abm", tipo=tipo))
    lotes = con.execute("""SELECT l.*, x.nro_expediente FROM lotes l LEFT JOIN expedientes x ON x.id=l.expediente_id
                           WHERE elemento_id=? ORDER BY fecha_vencimiento IS NULL, fecha_vencimiento, fecha_ingreso""",
                        (elid,)).fetchall() if elid else []
    movs = con.execute("SELECT * FROM movimientos WHERE elemento_id=? ORDER BY fecha DESC, id DESC LIMIT 15",
                       (elid,)).fetchall() if elid else []
    return render("elemento_form.html", tipo, tipo=tipo, grupo=grupo, el=el, v=el or {}, parecidos=None, lotes=lotes, movs=movs,
                  especialidades=db.lista(con, "especialidad"), envases=db.lista(con, "envase"),
                  minimo_defecto=cfg["stock_minimo_defecto"])


@app.route("/<tipo>/<int:elid>/eliminar", methods=["POST"])
@login_requerido
def elemento_eliminar(tipo, elid):
    grupo_de(tipo)
    con = get_db()
    usado = con.execute("SELECT 1 FROM expediente_items WHERE elemento_id=?", (elid,)).fetchone() or \
        con.execute("SELECT 1 FROM movimientos WHERE elemento_id=? AND tipo='Baja'", (elid,)).fetchone() or \
        con.execute("SELECT 1 FROM movimientos_anulados WHERE elemento_id=?", (elid,)).fetchone()
    if usado:
        flash("No se puede eliminar: el elemento figura en expedientes o tiene bajas registradas.", "error")
    else:
        con.execute("DELETE FROM movimientos WHERE elemento_id=?", (elid,))
        con.execute("DELETE FROM lotes WHERE elemento_id=?", (elid,))
        con.execute("DELETE FROM elementos WHERE id=?", (elid,))
        con.commit()
        flash("Elemento eliminado.", "ok")
    return redirect(url_for("elementos_abm", tipo=tipo))


@app.route("/<tipo>/<int:elid>/ajuste", methods=["GET", "POST"])
@login_requerido
def elemento_ajuste(tipo, elid):
    grupo = grupo_de(tipo)
    con = get_db()
    el = con.execute("SELECT * FROM elementos WHERE id=? AND grupo=?", (elid, grupo)).fetchone()
    if not el:
        abort(404)
    if request.method == "POST":
        f = request.form
        try:
            db.ajustar(con, elid, f.get("sentido"), a_int(f.get("cantidad")), f.get("motivo"), session["usuario"],
                       lote_id=a_int(f.get("lote_id")) or None,
                       vencimiento=(f.get("vencimiento") or None) if db.lleva_vencimiento(con, elid) else None)
            con.commit()
        except ValueError as e:
            con.rollback()
            flash(str(e), "error")
            return redirect(request.url)
        flash("Ajuste de inventario registrado.", "ok")
        return redirect(url_for("elemento_form", tipo=tipo, elid=elid))
    lotes = con.execute("""SELECT l.*, x.nro_expediente FROM lotes l LEFT JOIN expedientes x ON x.id=l.expediente_id
                           WHERE elemento_id=? AND cantidad_actual>0
                           ORDER BY fecha_vencimiento IS NULL, fecha_vencimiento, fecha_ingreso""", (elid,)).fetchall()
    return render("ajuste_form.html", tipo, tipo=tipo, grupo=grupo, el=el, lotes=lotes, elementos=elementos_json(con))


@app.route("/ajustes")
@login_requerido
def ajustes():
    con = get_db()
    grupo = request.args.get("grupo", "")
    sql = """SELECT m.*, e.descripcion, e.grupo FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
             WHERE m.razon='Ajuste'"""
    p = []
    if grupo in GRUPOS:
        sql += " AND e.grupo=?"
        p.append(grupo)
    filas = con.execute(sql + " ORDER BY m.fecha DESC, m.id DESC", p).fetchall()
    r = exportar_si_corresponde("Ajustes de inventario", ["Fecha", "Elemento", "Grupo", "Tipo", "Cantidad", "Valor", "Motivo", "Usuario"],
                                [[m["fecha"], m["descripcion"], m["grupo"], "Sobrante" if m["tipo"] == "Alta" else "Faltante",
                                  m["cantidad"], m["cantidad"] * m["precio_unitario"], m["observaciones"] or "", m["usuario"]]
                                 for m in filas])
    return r or render("ajustes.html", None, filas=filas, grupo=grupo, elementos=elementos_json(con))


# ---------------------------------------------------------------- SALIDAS / ACTAS
@app.route("/salidas/nueva", methods=["GET", "POST"])
@login_requerido
def salida_nueva():
    con = get_db()
    if request.method == "POST":
        f = request.form
        razon = f.get("razon")
        if razon not in RAZONES_BAJA:
            flash("Seleccione el tipo de baja.", "error")
            return redirect(request.url)
        es_entrega = razon in ("Entrega", "Préstamo")
        region = f.get("region") if es_entrega else None
        if es_entrega and not region:
            flash("Para una Entrega o Préstamo debe indicar la región.", "error")
            return redirect(request.url)
        pedidos = {}
        for el, cant in zip(f.getlist("elemento_id"), f.getlist("cantidad")):
            if el and a_int(cant) > 0:
                pedidos[a_int(el)] = pedidos.get(a_int(el), 0) + a_int(cant)
        if not pedidos:
            flash("Agregue al menos un elemento con cantidad.", "error")
            return redirect(request.url)
        try:
            fecha = db.ahora()
            cur = con.execute("INSERT INTO actas(tipo, razon, region, hospital, fecha, usuario, observaciones) VALUES(?,?,?,?,?,?,?)",
                              ("Entrega" if es_entrega else "Baja", razon, region, f.get("hospital") if es_entrega else None,
                               fecha, session["usuario"], f.get("observaciones", "")))
            acta_id = cur.lastrowid
            for el, cant in pedidos.items():
                # egresar() valida el stock según el tipo: las entregas solo usan unidades
                # sin vencer y la baja por «Vencido» solo unidades vencidas.
                db.egresar(con, el, cant, razon, session["usuario"], region, acta_id, fecha)
            con.commit()
        except ValueError as e:
            con.rollback()
            flash(str(e), "error")
            return redirect(request.url)
        flash("Movimiento registrado. Se generó el acta.", "ok")
        return redirect(url_for("acta_ver", aid=acta_id))
    tipo = request.args.get("tipo")
    pre = request.args.get("elemento")
    return render("salida_form.html", tipo if tipo in TIPOS else None, elementos=elementos_json(con),
                  razones=lista_fija(con, "baja", RAZONES_BAJA), regiones=db.lista(con, "region"),
                  razon_pre=request.args.get("razon", ""), elemento_pre=pre, grupo_pre=TIPOS.get(tipo))


@app.route("/actas")
@login_requerido
def actas():
    con = get_db()
    razon = request.args.get("razon", "")
    sql = """SELECT a.*, COUNT(m.id) n, COALESCE(SUM(m.cantidad),0) unidades, COALESCE(SUM(m.cantidad*m.precio_unitario),0) valor
             FROM actas a LEFT JOIN (SELECT id, acta_id, cantidad, precio_unitario FROM movimientos
                                     UNION ALL SELECT id, acta_id, cantidad, precio_unitario FROM movimientos_anulados) m
             ON m.acta_id=a.id"""
    p = []
    if razon:
        sql += " WHERE a.razon=?"
        p.append(razon)
    filas = con.execute(sql + " GROUP BY a.id ORDER BY a.id DESC", p).fetchall()
    r = exportar_si_corresponde("Actas", ["N° Acta", "Fecha", "Tipo", "Razón", "Región", "Hospital", "Ítems", "Unidades", "Valor",
                                          "Usuario", "Estado", "Motivo anulación"],
                                [[a["id"], a["fecha"], a["tipo"], a["razon"], a["region"] or "", a["hospital"] or "", a["n"],
                                  a["unidades"], a["valor"], a["usuario"],
                                  f"Anulada {a['anulada_fecha'][:10]} por {a['anulada_por']}" if a["anulada_fecha"] else "Vigente",
                                  a["anulada_motivo"] or ""] for a in filas])
    return r or render("actas.html", None, filas=filas, razones=db.lista(con, "baja"), razon=razon)


@app.route("/actas/<int:aid>")
@login_requerido
def acta_ver(aid):
    con = get_db()
    acta = con.execute("SELECT * FROM actas WHERE id=?", (aid,)).fetchone()
    if not acta:
        abort(404)
    tabla = "movimientos_anulados" if acta["anulada_fecha"] else "movimientos"
    items = con.execute(f"""SELECT m.*, e.descripcion, e.grupo, e.envase FROM {tabla} m JOIN elementos e ON e.id=m.elemento_id
                           WHERE acta_id=? ORDER BY m.id""", (aid,)).fetchall()
    r = exportar_si_corresponde(f"Acta {aid}", ["Orden", "Descripción", "Grupo", "Cantidad", "Región"],
                                [[n + 1, i["descripcion"], i["grupo"], i["cantidad"], i["region"] or ""] for n, i in enumerate(items)])
    return r or render("acta_print.html", None, acta=acta, items=items)


@app.route("/actas/<int:aid>/anular", methods=["POST"])
@login_requerido
def acta_anular(aid):
    con = get_db()
    try:
        db.anular_acta(con, aid, session["usuario"], request.form.get("motivo"))
        con.commit()
        flash(f"Acta N° {aid} anulada. El stock volvió a los lotes de origen.", "ok")
    except ValueError as e:
        con.rollback()
        flash(str(e), "error")
    return redirect(url_for("acta_ver", aid=aid))


# ---------------------------------------------------------------- 6 ESTADÍSTICAS
@app.route("/estadisticas")
@login_requerido
def estadisticas():
    con = get_db()
    anios = sorted({r[0] for r in con.execute(
        "SELECT CAST(substr(fecha,1,4) AS INTEGER) FROM movimientos UNION SELECT anio FROM expedientes")} | {date.today().year},
        reverse=True)
    return render("estadisticas.html", "estadisticas", anios=anios, meses=MESES, elementos=elementos_json(con))


def rango(modo, anio, mes):
    if modo == "mensual":
        ini = date(anio, mes, 1)
        fin = date(anio + (mes == 12), mes % 12 + 1, 1)
        etiqueta = f"{MESES[mes - 1]} {anio}"
    else:
        ini, fin, etiqueta = date(anio, 1, 1), date(anio + 1, 1, 1), f"Año {anio}"
    return ini.isoformat(), fin.isoformat(), etiqueta


def rango_anterior(modo, anio, mes):
    if modo == "mensual":
        return rango(modo, anio - (mes == 1), 12 if mes == 1 else mes - 1)
    return rango(modo, anio - 1, mes)


def params_estadisticas():
    modo = request.args.get("modo", "anual")
    anio = a_int(request.args.get("anio"), date.today().year)
    mes = min(max(a_int(request.args.get("mes"), date.today().month), 1), 12)
    return modo, anio, mes, request.args.get("elemento", "todos")


def resumen_periodo(con, ini, fin):
    """Indicadores generales de un período (todos los grupos)."""
    r = {k: {"cantidad": 0, "valor": 0.0} for k in ("Entrega", "Préstamo", "Roto", "Perdido", "Vencido", "Ingreso")}
    aj = {"Alta": 0, "Baja": 0}
    for x in con.execute("""SELECT razon, tipo, SUM(cantidad) c, SUM(cantidad*precio_unitario) v FROM movimientos
                            WHERE fecha>=? AND fecha<? GROUP BY razon, tipo""", (ini, fin)):
        if x["razon"] in r:
            r[x["razon"]] = {"cantidad": x["c"] or 0, "valor": round(x["v"] or 0, 2)}
        elif x["razon"] == "Ajuste":
            aj[x["tipo"]] = x["c"] or 0
    ex = con.execute("SELECT COUNT(*) n, COALESCE(SUM(valor_total),0) v FROM expedientes WHERE fecha>=? AND fecha<?",
                     (ini, fin)).fetchone()
    actas = con.execute("SELECT COUNT(*) FROM actas WHERE fecha>=? AND fecha<?" +
                        (" AND anulada_fecha IS NULL" if "anulada_fecha" in {c["name"] for c in con.execute("PRAGMA table_info(actas)")} else ""),
                        (ini, fin)).fetchone()[0]
    return {
        "entregado_valor": round(r["Entrega"]["valor"] + r["Préstamo"]["valor"], 2),
        "entregado_cant": r["Entrega"]["cantidad"] + r["Préstamo"]["cantidad"],
        "bajas_cant": r["Roto"]["cantidad"] + r["Perdido"]["cantidad"] + r["Vencido"]["cantidad"],
        "bajas_valor": round(r["Roto"]["valor"] + r["Perdido"]["valor"] + r["Vencido"]["valor"], 2),
        "expedientes": ex["n"], "comprado": round(ex["v"], 2), "actas": actas,
        "ajuste_neto": aj["Alta"] - aj["Baja"], "ajuste_sobrante": aj["Alta"], "ajuste_faltante": aj["Baja"],
        "por_razon": {k: r[k]["cantidad"] for k in ("Entrega", "Préstamo", "Roto", "Perdido", "Vencido")},
    }


def medidas_descriptivas(valores):
    """Medidas de estadística descriptiva + tabla de frecuencias (regla de Sturges)."""
    import math
    import statistics as st
    x = sorted(float(v) for v in valores if v is not None)
    n = len(x)
    if n == 0:
        return {"n": 0}
    media = st.fmean(x)
    mediana = st.median(x)
    desvio = st.stdev(x) if n > 1 else 0.0
    q1, q2, q3 = st.quantiles(x, n=4, method="inclusive") if n > 1 else (x[0], x[0], x[0])
    iqr = q3 - q1
    li_out, ls_out = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    atipicos = [v for v in x if v < li_out or v > ls_out]
    dentro = [v for v in x if li_out <= v <= ls_out] or x
    asim = curt = None
    if n > 2 and desvio > 0:
        m2 = sum((v - media) ** 2 for v in x) / n
        m3 = sum((v - media) ** 3 for v in x) / n
        g1 = m3 / m2 ** 1.5
        asim = math.sqrt(n * (n - 1)) / (n - 2) * g1          # asimetría de Fisher (muestral)
    if n > 3 and desvio > 0:
        m2 = sum((v - media) ** 2 for v in x) / n
        m4 = sum((v - media) ** 4 for v in x) / n
        g2 = m4 / m2 ** 2 - 3
        curt = ((n + 1) * g2 + 6) * (n - 1) / ((n - 2) * (n - 3))  # curtosis en exceso (muestral)
    modas = st.multimode(x)
    moda = modas[0] if len(modas) < len(set(x)) or n == 1 else None
    # tabla de frecuencias
    k = max(1, math.ceil(1 + 3.322 * math.log10(n)))
    rango = x[-1] - x[0]
    ancho = rango / k if rango else 1
    clases, acum = [], 0
    for i in range(k):
        li = x[0] + i * ancho
        ls = x[0] + (i + 1) * ancho if rango else x[0] + 1
        fi = sum(1 for v in x if (li <= v < ls) or (i == k - 1 and v == ls))
        acum += fi
        clases.append({"li": round(li, 2), "ls": round(ls, 2), "marca": round((li + ls) / 2, 2), "fi": fi,
                       "fr": round(fi / n, 4), "Fi": acum, "Fr": round(acum / n, 4)})
    modal = max(clases, key=lambda c: c["fi"])
    return {"n": n, "suma": round(sum(x), 2), "media": round(media, 4), "mediana": round(mediana, 4),
            "moda": None if moda is None else round(moda, 4), "multimodal": len(modas) > 1 and moda is not None,
            "clase_modal": [modal["li"], modal["ls"]],
            "varianza": round(desvio ** 2, 4), "desvio": round(desvio, 4),
            "cv": round(desvio / media * 100, 2) if media else None,
            "min": x[0], "max": x[-1], "rango": round(rango, 4),
            "q1": round(q1, 4), "q3": round(q3, 4), "iqr": round(iqr, 4),
            "bigote_inf": min(dentro), "bigote_sup": max(dentro),
            "atipicos": len(atipicos), "valores_atipicos": atipicos[:50],
            "asimetria": None if asim is None else round(asim, 4), "curtosis": None if curt is None else round(curt, 4),
            "k": k, "ancho": round(ancho, 4), "clases": clases}


def variables_descriptivas(con, ini, fin, anio, serie_valor):
    hoy = db.hoy()
    anul = " AND a.anulada_fecha IS NULL" if "anulada_fecha" in {c["name"] for c in con.execute("PRAGMA table_info(actas)")} else ""
    actas = con.execute(f"""SELECT a.id, SUM(m.cantidad) u, SUM(m.cantidad*m.precio_unitario) v FROM actas a
                            JOIN movimientos m ON m.acta_id=a.id
                            WHERE a.tipo='Entrega' AND a.fecha>=? AND a.fecha<?{anul} GROUP BY a.id""", (ini, fin)).fetchall()
    hoyd = date.today()
    corte = hoyd.month if anio == hoyd.year else (12 if anio < hoyd.year else 0)
    dias = [r[0] for r in con.execute("""SELECT julianday(l.fecha_vencimiento) - julianday(?) FROM lotes l
                                        JOIN elementos e ON e.id=l.elemento_id
                                        WHERE e.lleva_vencimiento=1 AND l.cantidad_actual>0 AND l.fecha_vencimiento IS NOT NULL""", (hoy,))]
    defs = [
        ("valor_acta", "Valor entregado por acta", "pesos", "período", [r["v"] for r in actas]),
        ("unidades_acta", "Unidades entregadas por acta", "unidades", "período", [r["u"] for r in actas]),
        ("valor_mes", f"Valor entregado por mes ({anio})", "pesos", "año", serie_valor[str(anio)][:corte]),
        ("precio", "Precio unitario de los elementos", "pesos", "actual",
         [r[0] for r in con.execute("SELECT precio_unitario FROM elementos WHERE precio_unitario>0")]),
        ("stock", "Stock por elemento", "unidades", "actual", [r[0] for r in con.execute("SELECT stock_actual FROM elementos")]),
        ("dias_venc", "Días hasta el vencimiento (lotes en depósito)", "días", "actual", [round(d) for d in dias]),
    ]
    return [{"clave": c, "nombre": nom, "unidad": u, "alcance": a, **medidas_descriptivas(v)} for c, nom, u, a, v in defs]


@app.route("/api/estadisticas")
@login_requerido
def api_estadisticas():
    return jsonify(calcular_estadisticas(get_db(), *params_estadisticas()))


@app.route("/estadisticas/excel")
@login_requerido
def estadisticas_excel():
    con = get_db()
    d = calcular_estadisticas(con, *params_estadisticas())
    r, p = d["resumen"]["actual"], d["resumen"]["anterior"]
    filas = [
        ["Valor entregado (entregas y préstamos)", r["entregado_valor"], p["entregado_valor"]],
        ["Unidades entregadas", r["entregado_cant"], p["entregado_cant"]],
        ["Unidades dadas de baja (roto, perdido, vencido)", r["bajas_cant"], p["bajas_cant"]],
        ["Valor dado de baja", r["bajas_valor"], p["bajas_valor"]],
        ["Expedientes ingresados", r["expedientes"], p["expedientes"]],
        ["Monto comprado", r["comprado"], p["comprado"]],
        ["Actas emitidas", r["actas"], p["actas"]],
        ["Ajustes: sobrantes (unidades)", r["ajuste_sobrante"], p["ajuste_sobrante"]],
        ["Ajustes: faltantes (unidades)", r["ajuste_faltante"], p["ajuste_faltante"]],
    ]
    for g_, k in (("Instrumental", "instrumental"), ("Insumos", "insumos")):
        b = d[k]
        filas.append([f"{g_}: existentes al cierre", b["existentes"], ""])
        for raz in ("Ingreso", "Entrega", "Préstamo", "Roto", "Perdido", "Vencido"):
            if k == "instrumental" and raz == "Vencido":
                continue
            filas.append([f"{g_}: {raz.lower()} (unidades)", b[raz], b["prev"].get(raz, 0)])
    for i, reg in enumerate(d["resumen"]["regiones"]["labels"]):
        filas.append([f"Valor entregado a región {reg}", d["resumen"]["regiones"]["valor"][i], ""])
    for i, esp in enumerate(d["especialidad"]["labels"]):
        filas.append([f"Valor en stock — {esp}", d["especialidad"]["stock"]["Insumo"][i] + d["especialidad"]["stock"]["Instrumental"][i], ""])
    filas = [[a, float(b) if isinstance(b, float) else b, float(c) if isinstance(c, float) else c] for a, b, c in filas]
    titulo = f"Estadisticas {d['periodo']}"
    buf = exportar_xlsx(titulo, ["Indicador", d["periodo"], d["resumen"]["etiqueta_anterior"]], filas,
                        db.config(con).get("organismo", ""))
    return send_file(buf, as_attachment=True, download_name=secure_filename(titulo.replace(" ", "_")) + ".xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def calcular_estadisticas(con, modo, anio, mes, sel):
    ini, fin, etiqueta = rango(modo, anio, mes)
    p_ini, p_fin, p_etiqueta = rango_anterior(modo, anio, mes)
    hoy, lim = db.hoy(), limite_venc(con)

    # ---- expedientes
    ex_periodo = {r["grupo"]: r["n"] for r in con.execute(
        "SELECT grupo, COUNT(*) n FROM expedientes WHERE fecha>=? AND fecha<? GROUP BY grupo", (ini, fin))}
    ex_valor = con.execute("SELECT COALESCE(SUM(valor_total),0) FROM expedientes WHERE fecha>=? AND fecha<?", (ini, fin)).fetchone()[0]
    ex_exist = con.execute("""SELECT COUNT(*) t, COALESCE(SUM(estado='Activo'),0) a, COALESCE(SUM(estado='Cerrado'),0) c
                              FROM expedientes WHERE fecha<?""", (fin,)).fetchone()
    serie_ex = {g_: [0] * 12 for g_ in ("Insumo", "Instrumental")}
    for r in con.execute("""SELECT grupo, CAST(substr(fecha,6,2) AS INTEGER) m, COUNT(*) n FROM expedientes
                            WHERE anio_f=? GROUP BY grupo, m""".replace("anio_f", "CAST(substr(fecha,1,4) AS INTEGER)"), (anio,)):
        if r["grupo"] in serie_ex:
            serie_ex[r["grupo"]][r["m"] - 1] = r["n"]

    # ---- movimientos por grupo
    def bloque(grupo):
        razones = {r["razon"]: (r["c"], r["v"]) for r in con.execute(
            """SELECT m.razon, SUM(m.cantidad) c, SUM(m.cantidad*m.precio_unitario) v FROM movimientos m
               JOIN elementos e ON e.id=m.elemento_id WHERE e.grupo=? AND m.fecha>=? AND m.fecha<? GROUP BY m.razon""",
            (grupo, ini, fin))}
        existentes = con.execute(
            """SELECT COALESCE(SUM(CASE WHEN m.tipo='Alta' THEN m.cantidad ELSE -m.cantidad END),0) FROM movimientos m
               JOIN elementos e ON e.id=m.elemento_id WHERE e.grupo=? AND m.fecha<?""", (grupo, fin)).fetchone()[0]
        regiones = db.lista(con, "region")
        por_region = {"Entrega": [0] * len(regiones), "Préstamo": [0] * len(regiones)}
        for r in con.execute("""SELECT m.razon, m.region, SUM(m.cantidad) c FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
                                WHERE e.grupo=? AND m.fecha>=? AND m.fecha<? AND m.razon IN ('Entrega','Préstamo')
                                GROUP BY m.razon, m.region""", (grupo, ini, fin)):
            if r["region"] in regiones:
                por_region[r["razon"]][regiones.index(r["region"])] = r["c"]
        serie = {k: [0] * 12 for k in ("Ingreso", "Entrega", "Préstamo", "Roto", "Perdido", "Vencido")}
        for r in con.execute("""SELECT m.razon, CAST(substr(m.fecha,6,2) AS INTEGER) mm, SUM(m.cantidad) c FROM movimientos m
                                JOIN elementos e ON e.id=m.elemento_id WHERE e.grupo=? AND substr(m.fecha,1,4)=?
                                GROUP BY m.razon, mm""", (grupo, str(anio))):
            if r["razon"] in serie:
                serie[r["razon"]][r["mm"] - 1] = r["c"]
        top = [dict(r) for r in con.execute(
            """SELECT e.descripcion, SUM(m.cantidad) c FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
               WHERE e.grupo=? AND m.razon IN ('Entrega','Préstamo') AND m.fecha>=? AND m.fecha<?
               GROUP BY e.id ORDER BY c DESC LIMIT 8""", (grupo, ini, fin))]
        prev = {r["razon"]: r["c"] or 0 for r in con.execute(
            """SELECT m.razon, SUM(m.cantidad) c FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
               WHERE e.grupo=? AND m.fecha>=? AND m.fecha<? GROUP BY m.razon""", (grupo, p_ini, p_fin))}
        d = {"existentes": existentes, "regiones": regiones, "por_region": por_region, "serie": serie, "top": top,
             "prev": prev}
        for k in ("Ingreso", "Entrega", "Préstamo", "Roto", "Perdido", "Vencido"):
            d[k] = razones.get(k, (0, 0))[0] or 0
        return d

    instr, ins = bloque("Instrumental"), bloque("Insumo")
    def venc_grupo(grupo):
        return dict(con.execute("""SELECT COALESCE(SUM(CASE WHEN l.fecha_vencimiento < :h THEN l.cantidad_actual END),0) vencidas,
                                 COALESCE(SUM(CASE WHEN l.fecha_vencimiento >= :h AND l.fecha_vencimiento <= :l THEN l.cantidad_actual END),0) proximas,
                                 COUNT(DISTINCT CASE WHEN l.fecha_vencimiento < :h THEN l.elemento_id END) el_vencidos,
                                 COUNT(DISTINCT CASE WHEN l.fecha_vencimiento >= :h AND l.fecha_vencimiento <= :l THEN l.elemento_id END) el_proximos
                          FROM lotes l JOIN elementos e ON e.id=l.elemento_id
                          WHERE e.grupo=:g AND e.lleva_vencimiento=1 AND l.cantidad_actual>0 AND l.fecha_vencimiento IS NOT NULL""",
                                {"h": hoy, "l": lim, "g": grupo}).fetchone())
    ins["vencimiento"] = venc_grupo("Insumo")
    instr["vencimiento"] = venc_grupo("Instrumental")

    # ---- especialidad
    especialidades = db.lista(con, "especialidad")
    esp = {g_: [0] * len(especialidades) for g_ in ("Insumo", "Instrumental")}
    for r in con.execute("SELECT grupo, especialidad, SUM(stock_actual*precio_unitario) v FROM elementos GROUP BY grupo, especialidad"):
        if r["especialidad"] in especialidades and r["grupo"] in esp:
            esp[r["grupo"]][especialidades.index(r["especialidad"])] = round(r["v"] or 0, 2)
    entregado_esp = [0] * len(especialidades)
    for r in con.execute("""SELECT e.especialidad, SUM(m.cantidad*m.precio_unitario) v FROM movimientos m JOIN elementos e ON e.id=m.elemento_id
                            WHERE m.razon IN ('Entrega','Préstamo') AND m.fecha>=? AND m.fecha<? GROUP BY e.especialidad""", (ini, fin)):
        if r["especialidad"] in especialidades:
            entregado_esp[especialidades.index(r["especialidad"])] = round(r["v"] or 0, 2)

    # ---- elemento seleccionado
    filtro, p = "", [ini, fin]
    if sel == "Insumo" or sel == "Instrumental":
        filtro, p = " AND e.grupo=?", [ini, fin, sel]
    elif sel.isdigit():
        filtro, p = " AND e.id=?", [ini, fin, int(sel)]
    det = {r["razon"]: {"cantidad": r["c"] or 0, "valor": round(r["v"] or 0, 2)} for r in con.execute(
        f"""SELECT m.razon, SUM(m.cantidad) c, SUM(m.cantidad*m.precio_unitario) v FROM movimientos m
            JOIN elementos e ON e.id=m.elemento_id WHERE m.fecha>=? AND m.fecha<? {filtro} GROUP BY m.razon""", p)}
    stock = con.execute(f"SELECT COALESCE(SUM(stock_actual),0) c, COALESCE(SUM(stock_actual*precio_unitario),0) v FROM elementos e WHERE 1=1 {filtro}",
                        p[2:]).fetchone()
    det["Stock"] = {"cantidad": stock["c"], "valor": round(stock["v"], 2)}

    # ---- resumen general (con comparación contra el período anterior)
    serie_valor = {str(a): [0] * 12 for a in (anio, anio - 1)}
    for r in con.execute("""SELECT substr(fecha,1,4) a, CAST(substr(fecha,6,2) AS INTEGER) mm, SUM(cantidad*precio_unitario) v
                            FROM movimientos WHERE razon IN ('Entrega','Préstamo') AND substr(fecha,1,4) IN (?,?)
                            GROUP BY a, mm""", (str(anio), str(anio - 1))):
        serie_valor[r["a"]][r["mm"] - 1] = round(r["v"] or 0, 2)
    regiones = db.lista(con, "region")
    reg_valor = [0] * len(regiones)
    for r in con.execute("""SELECT region, SUM(cantidad*precio_unitario) v FROM movimientos
                            WHERE razon IN ('Entrega','Préstamo') AND fecha>=? AND fecha<? GROUP BY region""", (ini, fin)):
        if r["region"] in regiones:
            reg_valor[regiones.index(r["region"])] = round(r["v"] or 0, 2)
    resumen = {"actual": resumen_periodo(con, ini, fin), "anterior": resumen_periodo(con, p_ini, p_fin),
               "etiqueta_anterior": p_etiqueta, "serie_valor": serie_valor,
               "regiones": {"labels": regiones, "valor": reg_valor},
               "stock_valor": round(con.execute("SELECT COALESCE(SUM(stock_actual*precio_unitario),0) FROM elementos").fetchone()[0], 2)}

    return {
        "periodo": etiqueta, "desde": ini, "hasta": fin, "meses": [m[:3] for m in MESES], "anio": anio,
        "resumen": resumen,
        "descriptiva": variables_descriptivas(con, ini, fin, anio, serie_valor),
        "expedientes": {"periodo": sum(ex_periodo.values()), "por_grupo": ex_periodo, "valor": ex_valor,
                        "existentes": ex_exist["t"], "activos": ex_exist["a"], "cerrados": ex_exist["c"], "serie": serie_ex},
        "instrumental": instr, "insumos": ins,
        "especialidad": {"labels": especialidades, "stock": esp, "entregado": entregado_esp},
        "elemento": det,
    }


# ---------------------------------------------------------------- 7 LISTAS
LISTAS_ABM = {"grupo": "Grupo", "especialidad": "Especialidad", "envase": "Envase", "baja": "Baja", "region": "Región"}
PROTEGIDAS = {"grupo": set(GRUPOS), "baja": set(RAZONES_BAJA)}
# Listas fijas: el sistema solo sabe manejar sus valores originales; no se pueden agregar ni renombrar.
LISTAS_FIJAS = {"grupo", "baja"}


def valor_en_uso(con, nombre, valor):
    consultas = {
        "grupo": ["SELECT 1 FROM elementos WHERE grupo=?", "SELECT 1 FROM expedientes WHERE grupo=?"],
        "baja": ["SELECT 1 FROM actas WHERE razon=?", "SELECT 1 FROM movimientos WHERE razon=?",
                 "SELECT 1 FROM movimientos_anulados WHERE razon=?"],
        "especialidad": ["SELECT 1 FROM elementos WHERE especialidad=?"],
        "envase": ["SELECT 1 FROM elementos WHERE envase=?"],
    }.get(nombre, [])
    return any(con.execute(q, (valor,)).fetchone() for q in consultas)


@app.route("/listas")
@login_requerido
def listas():
    con = get_db()
    conteo = {k: len(db.lista(con, k)) for k in LISTAS_ABM}
    return render("listas.html", "listas", listas=LISTAS_ABM, conteo=conteo)


@app.route("/listas/<nombre>", methods=["GET", "POST"])
@login_requerido
def lista_abm(nombre):
    if nombre not in LISTAS_ABM:
        abort(404)
    con = get_db()
    if request.method == "POST":
        accion, valor = request.form.get("accion"), request.form.get("valor", "").strip()
        lid = a_int(request.form.get("id"))
        actual = con.execute("SELECT valor FROM listas WHERE id=?", (lid,)).fetchone() if lid else None
        protegido = actual and actual["valor"] in PROTEGIDAS.get(nombre, set())
        try:
            if nombre in LISTAS_FIJAS and accion in ("alta", "modificar"):
                raise ValueError(f"La lista «{LISTAS_ABM[nombre]}» es fija: el sistema solo maneja sus valores originales.")
            if accion == "alta" and valor:
                orden = con.execute("SELECT COALESCE(MAX(orden),0)+1 FROM listas WHERE lista=?", (nombre,)).fetchone()[0]
                con.execute("INSERT INTO listas(lista, valor, orden) VALUES(?,?,?)", (nombre, valor, orden))
                flash(f"«{valor}» agregado.", "ok")
            elif accion == "modificar" and actual and valor:
                if protegido:
                    raise ValueError("Este valor es usado internamente por el sistema y no puede modificarse.")
                con.execute("UPDATE listas SET valor=? WHERE id=?", (valor, lid))
                campo = {"especialidad": "especialidad", "envase": "envase"}.get(nombre)
                if campo:
                    con.execute(f"UPDATE elementos SET {campo}=? WHERE {campo}=?", (valor, actual["valor"]))
                if nombre == "region":
                    con.execute("UPDATE movimientos SET region=? WHERE region=?", (valor, actual["valor"]))
                    con.execute("UPDATE actas SET region=? WHERE region=?", (valor, actual["valor"]))
                flash("Valor modificado.", "ok")
            elif accion == "baja" and actual:
                if protegido:
                    raise ValueError("Este valor es usado internamente por el sistema y no puede eliminarse.")
                if valor_en_uso(con, nombre, actual["valor"]):
                    raise ValueError("No se puede eliminar: este valor ya está en uso.")
                con.execute("DELETE FROM listas WHERE id=?", (lid,))
                flash("Valor eliminado.", "ok")
            elif accion in ("subir", "bajar") and actual:
                filas = con.execute("SELECT id FROM listas WHERE lista=? ORDER BY orden, valor", (nombre,)).fetchall()
                ids = [r["id"] for r in filas]
                i = ids.index(lid)
                j = i - 1 if accion == "subir" else i + 1
                if 0 <= j < len(ids):
                    ids[i], ids[j] = ids[j], ids[i]
                    for n, x in enumerate(ids):
                        con.execute("UPDATE listas SET orden=? WHERE id=?", (n, x))
            con.commit()
        except ValueError as e:
            flash(str(e), "error")
        except Exception:
            flash("Ese valor ya existe en la lista.", "error")
        return redirect(url_for("lista_abm", nombre=nombre))
    filas = con.execute("SELECT * FROM listas WHERE lista=? ORDER BY orden, valor", (nombre,)).fetchall()
    return render("lista_abm.html", "listas", nombre=nombre, titulo=LISTAS_ABM[nombre], filas=filas,
                  protegidos=PROTEGIDAS.get(nombre, set()), listas=LISTAS_ABM, fija=nombre in LISTAS_FIJAS)


# ---------------------------------------------------------------- 8 ADMINISTRADOR
@app.route("/admin")
@admin_requerido
def admin():
    con = get_db()
    n_usuarios = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    return render("admin.html", "admin", n_usuarios=n_usuarios)


@app.route("/admin/usuarios")
@admin_requerido
def usuarios():
    filas = get_db().execute("SELECT * FROM usuarios ORDER BY rol, apellido").fetchall()
    return render("usuarios.html", "admin", filas=filas)


@app.route("/admin/usuarios/nuevo", methods=["GET", "POST"])
@app.route("/admin/usuarios/<int:uid>/editar", methods=["GET", "POST"])
@admin_requerido
def usuario_form(uid=None):
    con = get_db()
    u = con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone() if uid else None
    if uid and not u:
        abort(404)
    if request.method == "POST":
        f = request.form
        nombre, apellido = f.get("nombre", "").strip(), f.get("apellido", "").strip()
        pin, clave = f.get("pin", "").strip(), f.get("contrasena", "")
        if not nombre or not apellido:
            flash("Nombre y apellido son obligatorios.", "error")
            return redirect(request.url)
        if not (pin.isdigit() and len(pin) == 4):
            flash("El PIN de seguridad debe tener 4 dígitos.", "error")
            return redirect(request.url)
        es_admin_base = u and u["usuario"] == "Admin"
        rol = "Administrador" if es_admin_base else f.get("rol", "Usuario")
        if u:
            usuario = u["usuario"]  # el nombre de ingreso se asigna al crear y no cambia
            con.execute("UPDATE usuarios SET usuario=?, nombre=?, apellido=?, pin=?, rol=? WHERE id=?",
                        (usuario, nombre, apellido, pin, rol, uid))
            if clave:
                con.execute("UPDATE usuarios SET contrasena=? WHERE id=?", (db.cifrar(clave), uid))
        else:
            if not clave:
                flash("La contraseña es obligatoria.", "error")
                return redirect(request.url)
            usuario = db.generar_usuario(con, nombre, apellido)
            con.execute("INSERT INTO usuarios(usuario,nombre,apellido,contrasena,pin,rol,creado) VALUES(?,?,?,?,?,?,?)",
                        (usuario, nombre, apellido, db.cifrar(clave), pin, rol, db.ahora()))
        con.commit()
        if uid == session.get("uid"):
            session.update(usuario=usuario, nombre=f"{nombre} {apellido}")
        flash(f"Usuario {usuario} guardado.", "ok")
        return redirect(url_for("usuarios"))
    return render("usuario_form.html", "admin", u=u)


@app.route("/admin/usuarios/<int:uid>/eliminar", methods=["POST"])
@admin_requerido
def usuario_eliminar(uid):
    con = get_db()
    u = con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
    if not u or u["usuario"] == "Admin" or uid == session.get("uid"):
        flash("Ese usuario no puede eliminarse.", "error")
    else:
        con.execute("DELETE FROM usuarios WHERE id=?", (uid,))
        con.commit()
        flash("Usuario eliminado.", "ok")
    return redirect(url_for("usuarios"))


@app.route("/admin/configuracion", methods=["GET", "POST"])
@admin_requerido
def configuracion():
    con = get_db()
    if request.method == "POST":
        f = request.form
        for clave in ("nombre_sistema", "organismo", "dependencia", "dias_alerta_vencimiento", "stock_minimo_defecto"):
            if clave in f:
                con.execute("UPDATE config SET valor=? WHERE clave=?", (f[clave].strip(), clave))
        if f.get("aplicar_minimo"):
            con.execute("UPDATE elementos SET stock_minimo=?", (a_int(f.get("stock_minimo_defecto"), 10),))
        logo = request.files.get("logo")
        if logo and logo.filename:
            ext = os.path.splitext(logo.filename)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"):
                flash("Formato de imagen no admitido.", "error")
                return redirect(request.url)
            nombre = f"logo_{datetime.now():%Y%m%d%H%M%S}{ext}"
            logo.save(os.path.join(app.static_folder, "uploads", nombre))
            con.execute("UPDATE config SET valor=? WHERE clave='logo'", (f"uploads/{nombre}",))
        if f.get("restaurar_logo"):
            con.execute("UPDATE config SET valor='img/logo.png' WHERE clave='logo'")
        con.commit()
        flash("Configuración guardada.", "ok")
        return redirect(url_for("configuracion"))
    return render("configuracion.html", "admin")


@app.route("/admin/temas", methods=["GET", "POST"])
@admin_requerido
def temas():
    con = get_db()
    if request.method == "POST" and request.form.get("tema") in TEMAS:
        con.execute("UPDATE config SET valor=? WHERE clave='tema'", (request.form["tema"],))
        con.commit()
        flash("Tema aplicado.", "ok")
        return redirect(url_for("temas"))
    return render("temas.html", "admin", temas=TEMAS)


@app.route("/admin/datos", methods=["POST"])
@admin_requerido
def admin_datos():
    accion = request.form.get("accion")
    if accion == "demo":
        if get_db().execute("SELECT 1 FROM elementos").fetchone():
            flash("La base ya tiene elementos cargados. Use «Reiniciar base» antes de cargar los datos de demostración.", "error")
            return redirect(url_for("configuracion"))
        import demo
        g.pop("con", None)
        demo.cargar()
        flash("Se cargaron datos de demostración.", "ok")
    elif accion == "reiniciar" and request.form.get("confirmar") == "REINICIAR":
        con = g.pop("con", None)
        if con:
            con.close()
        db.reiniciar()
        session.clear()
        flash("La base de datos fue reiniciada. Ingrese con Admin / Admin.", "ok")
        return redirect(url_for("index"))
    else:
        flash("Para reiniciar escriba REINICIAR en el cuadro de confirmación.", "error")
    return redirect(url_for("configuracion"))


@app.route("/admin/respaldo")
@admin_requerido
def respaldo():
    """Descarga una copia consistente de la base, aunque el sistema esté en uso."""
    fd, tmp = tempfile.mkstemp(suffix=".db", dir=db.DATA_DIR)
    os.close(fd)
    try:
        db.copiar_base(tmp)
        with open(tmp, "rb") as fh:
            buf = io.BytesIO(fh.read())
    finally:
        os.remove(tmp)
    return send_file(buf, as_attachment=True, download_name=f"gso_respaldo_{datetime.now():%Y%m%d_%H%M}.db",
                     mimetype="application/octet-stream")


def copias_automaticas():
    if not os.path.isdir(db.RESPALDOS_DIR):
        return []
    res = []
    for n in sorted(os.listdir(db.RESPALDOS_DIR), reverse=True):
        if n.endswith(".db"):
            ruta = os.path.join(db.RESPALDOS_DIR, n)
            res.append({"nombre": n, "kb": os.path.getsize(ruta) // 1024,
                        "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d %H:%M:%S")})
    return res


@app.route("/admin/respaldos", methods=["GET", "POST"])
@admin_requerido
def respaldos():
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if request.form.get("confirmar", "").strip().upper() != "RESTAURAR":
            flash("Para restaurar escriba RESTAURAR en el cuadro de confirmación.", "error")
            return redirect(url_for("respaldos"))
        if not archivo or not archivo.filename:
            flash("Elija el archivo de respaldo (.db).", "error")
            return redirect(url_for("respaldos"))
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=db.DATA_DIR)
        os.close(fd)
        try:
            archivo.save(tmp)
            resumen = db.validar_respaldo(tmp)
            con = g.pop("con", None)
            if con:
                con.close()
            previa = db.restaurar(tmp)
        except ValueError as e:
            flash(f"No se restauró: {e}", "error")
            return redirect(url_for("respaldos"))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        session.clear()
        flash(f"Respaldo restaurado ({resumen['expedientes']} expedientes, {resumen['elementos']} elementos, "
              f"{resumen['actas']} actas). La base anterior se guardó como «{os.path.basename(previa)}». "
              "Ingrese nuevamente.", "ok")
        return redirect(url_for("index"))
    return render("respaldos.html", "admin", copias=copias_automaticas())


@app.route("/admin/respaldos/<nombre>")
@admin_requerido
def respaldo_automatico(nombre):
    if nombre not in {c["nombre"] for c in copias_automaticas()}:
        abort(404)
    return send_file(os.path.join(db.RESPALDOS_DIR, nombre), as_attachment=True, download_name=nombre)


@app.errorhandler(403)
def prohibido(_):
    return render("error.html", None, codigo=403, mensaje="Esta sección es solo para el Administrador."), 403


@app.errorhandler(404)
def no_encontrado(_):
    return render("error.html", None, codigo=404, mensaje="La página solicitada no existe."), 404


if __name__ == "__main__":
    puerto = int(os.environ.get("GSO_PUERTO", 5000))
    host = os.environ.get("GSO_HOST", "127.0.0.1")
    if not os.environ.get("GSO_SIN_NAVEGADOR"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{puerto}")).start()
    print(f"\n  GSO en funcionamiento:  http://127.0.0.1:{puerto}\n  (cierre esta ventana para detener el sistema)\n")
    try:
        from waitress import serve
        serve(app, host=host, port=puerto, threads=8)
    except ImportError:
        app.run(host=host, port=puerto, debug=False)
