# GSO — Gestión de Stock Odontológico

Sistema web en Python (Flask + SQLite) para gestionar insumos, instrumental, expedientes de compra, entregas, bajas y estadísticas. Se usa desde el navegador de la computadora.

## Cómo iniciarlo

**Requisito:** Python 3.10 o superior (https://www.python.org/downloads/). En Windows, marcar **"Add Python to PATH"** al instalar.

- **Windows:** doble clic en `INICIAR_WINDOWS.bat`.
- **Linux / Mac:** ejecutar `./iniciar_linux_mac.sh`.

La primera vez se instalan las dependencias (necesita internet unos segundos). Después se abre solo el navegador en **http://127.0.0.1:5000**. Para detener el sistema, cierre la ventana negra.

Instalación manual alternativa:
```
pip install -r requirements.txt
python app.py
```

## Primer ingreso

| Usuario | Contraseña | PIN de seguridad |
|---|---|---|
| Admin | Admin | 0000 |

Cambie la contraseña y el PIN en **Administrador → ABM Usuarios**.
Para recuperar la contraseña: en la pantalla de ingreso, **"Recuperar contraseña."** → apellido + PIN de 4 dígitos → se muestra el nombre de usuario y se define una contraseña nueva.

Para probar el sistema con información de ejemplo: **Administrador → Configuración → Cargar datos de demostración**. Antes de usarlo en serio, use **Reiniciar base** en la misma pantalla.

## Módulos

1. **Index** — logo, usuario, contraseña, recuperar contraseña.
2. **Inicio** — total estimado en pesos en depósito; expedientes existentes, activos y cerrados; alertas de vencimiento (amarillo: próximo a vencer, rojo: vencido) y de stock mínimo (amarillo: crítico, rojo: agotado). Cada alerta lleva al listado filtrado.
3. **Expedientes** — últimos 5; ABM; consulta por año, número o usuario que hizo el ABM; detalle con elementos, cantidades compradas, saldo sin consumir y total; **Pedido de provisión** y **Especificaciones técnicas**.
4. **Instrumental** y 5. **Insumos** — 5 en estado crítico y 5 agotados (y en insumos, próximos a vencer y vencidos); ABM; consulta por nombre, especialidad, vencimiento, crítico o agotado.
6. **Estadísticas** — período mensual o anual (con flechas para recorrer), pestañas: Expedientes, Instrumental, Insumos, Especialidad y Por elemento. Gráficos interactivos.
7. **Listas** — ABM de Grupo, Especialidad, Envase, Baja y Región (con orden).
8. **Administrador** (solo administradores) — ABM de usuarios, configuración (logo, nombre del sistema, encabezados de actas, días de alerta de vencimiento, stock mínimo), temas de color y respaldo de la base.

## Reglas del sistema

- **N° de expediente:** año + número de 8 dígitos → `2026-00012345`.
- **Nombre de usuario:** inicial del nombre + apellido completo (Juan Pérez → `JPEREZ`). Si ya existe, se agrega un número.
- **Stock por lotes:** cada renglón de un expediente (o ingreso manual) crea un lote con su vencimiento. Al registrar una salida, se descuentan **primero los elementos más antiguos** (vencimiento más próximo).
- **Vencimiento opcional:** cada insumo tiene la casilla *Lleva fecha de vencimiento*. Desmarcada (hojas de bisturí, limas, fresas, yeso…), no pide fecha ni genera alertas de vencimiento. El instrumental nunca lleva vencimiento.
- **Las unidades vencidas nunca se entregan ni se prestan.** Solo pueden darse de baja por *Vencido*.
- **Fecha del expediente:** los ingresos de stock del expediente toman su fecha. Si se modifica, se actualizan también; no puede quedar posterior a una baja ya registrada.
- **Toda baja genera un acta** (botón *Registrar entrega / baja*):
  - *Entrega* y *Préstamo* → **Acta de entrega** (hospital, región, casilla Préstamo).
  - *Roto*, *Perdido*, *Vencido* → **Acta por baja**. Por *Vencido* solo se pueden dar de baja unidades ya vencidas.
- **Anular un acta:** si un acta se cargó por error, desde el acta → *Anular esta acta* (con motivo obligatorio). Las unidades vuelven a los mismos lotes de donde salieron, el acta queda marcada como **Anulada** (no se borra) y deja de contar en las estadísticas. Queda registrado quién la anuló, cuándo y por qué.
- **Fecha de entrega del expediente:** se asienta sola con la primera entrega de un elemento de ese expediente (si esa acta se anula, se recalcula).
- **Ajustes de inventario:** cuando el conteo físico no coincide con el sistema, desde el elemento → *Ajuste de inventario*: **Faltante** (descuenta) o **Sobrante** (suma un lote), con motivo obligatorio. No cuentan como compras ni entregas y no generan acta. Se listan en *Ajustes de inventario* (con Excel).
- **Expediente Cerrado:** no puede modificarse ni eliminarse. Para cambiarlo hay que reabrirlo (pasarlo a *Activo*); el cierre y la reapertura quedan en el historial. Las unidades de un expediente cerrado se pueden seguir entregando.
- **Listas fijas:** *Grupo* (Insumo, Instrumental) y *Baja* (Entrega, Préstamo, Roto, Perdido, Vencido) no admiten valores nuevos, porque el sistema solo sabe manejar esos. Especialidad, Envase y Región sí.
- **Envíos duplicados:** si un formulario se envía dos veces (doble clic), el segundo envío se ignora.
- **Elementos repetidos:** al crear un insumo o instrumental con un nombre igual o muy parecido a otro existente, el sistema avisa y pide confirmar. Al guardar un expediente con el mismo elemento en dos renglones, pide confirmar.
- **Nombre de usuario:** se asigna al crear el usuario y no cambia aunque se corrija el nombre o el apellido.
- **Números:** los campos aceptan el formato argentino (1.500 = mil quinientos; 1.500,50).
- Un expediente con bajas registradas no puede eliminarse (se puede pasar a *Cerrado*).

## Imprimir y exportar

Todas las consultas, actas, pedidos y especificaciones tienen:
- **Imprimir / PDF:** abre la impresión del navegador; elija *Guardar como PDF* para obtener el archivo.
- **Excel:** descarga un `.xlsx` con formato.

## Uso en red (opcional)

Para que otras computadoras de la oficina accedan, inicie con la variable `GSO_HOST=0.0.0.0` y entre desde las otras PC a `http://IP-DE-ESTA-PC:5000`. El puerto se cambia con `GSO_PUERTO`.

## Archivos

```
app.py            aplicación web (rutas de todos los módulos)
db.py             base de datos interna, lotes y movimientos
exportar.py       exportación a Excel
demo.py           datos de demostración
templates/        páginas
static/           estilos, tipografía Poppins, gráficos (Chart.js), logo
datos/gso.db      base de datos (se crea sola al iniciar)
```

**Respaldo:** *Administrador → Respaldo* permite **descargar** una copia (aunque el sistema esté en uso) y **restaurar** una copia anterior. Antes de restaurar y antes de *Reiniciar base*, el sistema guarda una copia automática de la base actual en `datos/respaldos/`. También puede copiar la carpeta `datos/` con el sistema cerrado.

## Seguridad

- Las contraseñas se guardan **cifradas** (no se pueden leer ni siquiera abriendo la base). Las bases creadas con versiones anteriores se convierten solas al iniciar.
- Tras **5 intentos fallidos** de ingreso o de recuperación, se bloquean los intentos por 15 minutos.
- La sesión se cierra sola tras **60 minutos sin actividad** (se cambia con la variable `GSO_MINUTOS_SESION`).
- Los formularios llevan un código de verificación que impide que otra página web envíe acciones en nombre del usuario.
- Si se elimina un usuario o se le cambia el rol, el cambio se aplica de inmediato aunque tenga la sesión abierta.
