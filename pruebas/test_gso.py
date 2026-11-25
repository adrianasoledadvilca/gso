"""Pruebas automatizadas de GSO v11 (pytest). Se ejecutan sobre una copia con base nueva."""
import re, sys, sqlite3, io, os, shutil, tempfile
# Copia aislada del sistema con base nueva: las pruebas nunca tocan datos/gso.db real
_ORIGEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COPIA = os.path.join(tempfile.mkdtemp(prefix='gso_pruebas_'), 'GSO')
shutil.copytree(_ORIGEN, _COPIA, ignore=shutil.ignore_patterns('datos', 'pruebas', '.venv', '__pycache__'))
sys.path.insert(0, _COPIA)
import pytest
import db, app as gso, demo

@pytest.fixture(scope='session')
def cli():
    gso.app.config['TESTING'] = True
    demo.cargar()                                   # base de demostración en la copia
    c = gso.app.test_client()
    with gso.app.app_context():
        pass
    r = c.get('/')
    tok = re.search(r'name="_csrf" value="([^"]+)"', r.text).group(1)
    r = c.post('/', data={'usuario': 'Admin', 'contrasena': 'Admin', '_csrf': tok}, follow_redirects=True)
    assert 'Cerrar sesión' in r.text
    return c

def tok(c, url):
    return re.search(r'name="_csrf" value="([^"]+)"', c.get(url).text).group(1)

def con():
    k = sqlite3.connect(db.DB_PATH); k.row_factory = sqlite3.Row; return k

def stock(eid):
    return con().execute('SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE elemento_id=?', (eid,)).fetchone()[0]

# ---------- reglas de vencimiento
@pytest.mark.parametrize('grupo,desc,esperado', [
    ('Insumo', 'Hojas de bisturí N°15', True), ('Insumo', 'Anestesia lidocaína 2%', True),
    ('Insumo', 'Fresas de diamante redondas', False), ('Insumo', 'Cuñas de madera', False),
    ('Insumo', 'Baberos descartables', False), ('Instrumental', 'Pinza para algodón', False),
    ('Instrumental', 'Espejo bucal N°5', False), ('Instrumental', 'Kit de examen descartable estéril', True)])
def test_sugerir_vencimiento(grupo, desc, esperado):
    assert db.sugerir_vencimiento(grupo, desc) is esperado

# ---------- estadística descriptiva
def test_medidas_descriptivas_conocidas():
    m = gso.medidas_descriptivas([2, 4, 4, 4, 5, 5, 7, 9])
    assert m['n'] == 8 and m['media'] == 5 and m['mediana'] == 4.5 and m['moda'] == 4
    assert round(m['desvio'], 4) == 2.1381          # desvío muestral (n-1)
    import math
    assert m['k'] == math.ceil(1 + 3.322 * math.log10(8))   # regla implementada: techo de Sturges (da 5 para n = 8)
    assert sum(c['fi'] for c in m['clases']) == 8 and m['clases'][-1]['Fr'] == 1

def test_atipicos_regla_ric():
    m = gso.medidas_descriptivas([10, 11, 12, 12, 13, 14, 100])
    assert m['atipicos'] == 1 and m['valores_atipicos'] == [100.0]

def test_variable_vacia():
    assert gso.medidas_descriptivas([]) == {'n': 0}

# ---------- rutas principales
RUTAS = ['/inicio', '/expedientes', '/expedientes/abm', '/expedientes/consultar', '/insumos', '/insumos/abm',
         '/insumos/consultar', '/instrumental', '/instrumental/consultar', '/ajustes', '/salidas/nueva', '/actas',
         '/estadisticas', '/api/estadisticas?modo=anual&anio=2026', '/listas', '/admin', '/admin/usuarios',
         '/admin/configuracion', '/admin/respaldos']
@pytest.mark.parametrize('ruta', RUTAS)
def test_rutas_responden(cli, ruta):
    assert cli.get(ruta).status_code == 200

def test_sin_sesion_redirige_al_login():
    c = gso.app.test_client()
    r = c.get('/inicio')
    assert r.status_code in (302, 303) and r.headers['Location'].rstrip('/').endswith('') 

def test_post_sin_csrf_rechazado(cli):
    n0 = con().execute('SELECT COUNT(*) FROM actas').fetchone()[0]
    r = cli.post('/salidas/nueva', data={'razon': 'Entrega', 'region': 'Puna', 'elemento_id': ['1'], 'cantidad': ['1']}, follow_redirects=True)
    assert 'no es válido' in r.text
    assert con().execute('SELECT COUNT(*) FROM actas').fetchone()[0] == n0

# ---------- circuito completo
def test_circuito_expediente_fefo_acta_anulacion_ajuste(cli):
    k = con()
    eid = k.execute("SELECT id FROM elementos WHERE grupo='Insumo' AND lleva_vencimiento=1 ORDER BY id LIMIT 1").fetchone()[0]
    s0 = stock(eid)
    # 1) expediente con dos renglones del mismo elemento y distinto vencimiento
    r = cli.post('/expedientes/nuevo', data={'_csrf': tok(cli, '/expedientes/nuevo'), 'anio': '2026', 'numero': '99001',
        'fecha': '2026-11-01', 'grupo': 'Insumo', 'estado': 'Activo', 'solicitado_por': 'Prueba', 'utilizado_en': 'Prueba',
        'entregar_en': 'Depósito', 'item_id': ['', ''], 'elemento_id': [str(eid), str(eid)], 'nro': ['1', '2'], 'letra': ['', ''],
        'unidad': ['Caja', 'Caja'], 'cantidad': ['10', '5'], 'precio': ['100', '100'],
        'vencimiento': ['2030-12-31', '2026-12-15'], 'confirmar_repetidos': '1'})
    assert r.status_code in (302, 303)
    assert stock(eid) == s0 + 15
    # 2) FEFO: una entrega de 5 debe salir del lote que vence antes (2026-12-15) o de otro anterior
    antes = {row['id']: row['cantidad_actual'] for row in con().execute('SELECT id,cantidad_actual FROM lotes WHERE elemento_id=?', (eid,))}
    r = cli.post('/salidas/nueva', data={'_csrf': tok(cli, '/salidas/nueva'), 'razon': 'Entrega', 'region': 'Puna',
        'hospital': 'Hospital de prueba', 'elemento_id': [str(eid)], 'cantidad': ['5']})
    assert r.status_code in (302, 303)
    aid = int(re.search(r'/actas/(\d+)', r.headers['Location']).group(1))
    assert stock(eid) == s0 + 10
    usados = con().execute("""SELECT l.fecha_vencimiento FROM movimiento_lotes ml JOIN lotes l ON l.id=ml.lote_id
                              JOIN movimientos m ON m.id=ml.movimiento_id WHERE m.acta_id=?""", (aid,)).fetchall()
    # FEFO entre lotes NO vencidos (los vencidos no se entregan: se dan de baja)
    venc_min = con().execute("""SELECT MIN(fecha_vencimiento) FROM lotes WHERE elemento_id=? AND fecha_vencimiento >= date('now','localtime')
                                AND (cantidad_actual > 0 OR id IN (SELECT lote_id FROM movimiento_lotes ml JOIN movimientos m ON m.id=ml.movimiento_id WHERE m.acta_id=?))""", (eid, aid)).fetchone()[0]
    assert min(u[0] for u in usados) == venc_min
    # 3) no se puede entregar más que el stock
    r = cli.post('/salidas/nueva', data={'_csrf': tok(cli, '/salidas/nueva'), 'razon': 'Entrega', 'region': 'Puna',
        'hospital': 'X', 'elemento_id': [str(eid)], 'cantidad': [str(stock(eid) + 1)]}, follow_redirects=True)
    assert stock(eid) == s0 + 10
    # 4) anular el acta devuelve las unidades
    r = cli.post(f'/actas/{aid}/anular', data={'_csrf': tok(cli, f'/actas/{aid}'), 'motivo': 'Prueba de anulación'})
    assert stock(eid) == s0 + 15
    # 5) ajuste sin motivo es rechazado; con motivo descuenta
    url = f'/insumos/{eid}/ajuste'
    cli.post(url, data={'_csrf': tok(cli, url), 'sentido': 'Faltante', 'cantidad': '2', 'motivo': ''})
    assert stock(eid) == s0 + 15
    cli.post(url, data={'_csrf': tok(cli, url), 'sentido': 'Faltante', 'cantidad': '2', 'motivo': 'Conteo físico'})
    assert stock(eid) == s0 + 13

def test_exportar_excel(cli):
    r = cli.get('/estadisticas/excel?modo=anual&anio=2026')
    assert r.status_code == 200 and r.data[:2] == b'PK'
