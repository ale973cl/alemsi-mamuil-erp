# Changelog

## v2.0.0
- Recupera el flujo rápido: multiselección de días y listas desplegables por servicio.
- Carga toda la minuta seleccionada con una sola consulta a Supabase.
- Guarda todas las elecciones mediante un único formulario.
- Añade etapa de revisión previa a confirmar.
- Aplica el orden obligatorio: guardar y confirmar transacción; luego generar comprobante y enviar correos.
- Si el guardado falla, no se genera ni envía ningún comprobante.
- Mantiene notificación a cocina y correos demo de reclamos/sugerencias.
- Elimina el wizard y los reruns por cada plato.

# Changelog

## v1.0.5
- Reemplaza los botones individuales de fechas por una selección múltiple dentro de un formulario.
- La selección de varios días ya no ejecuta toda la aplicación por cada clic.
- Reemplaza los botones individuales de platos por un formulario de menú por día.
- Corrige definitivamente las claves duplicadas usando controles únicos por fecha y servicio.
- Reduce llamadas repetidas a Supabase mediante caché para instituciones y precios especiales.
- Conserva la minuta real de agosto de 2026, comprobantes, reservas y correos demo.

# Changelog

## v1.0.4
- Corrige `StreamlitDuplicateElementKey` en la selección de menú cuando un mismo plato aparece en más de una opción del mismo servicio.
- Cada botón de minuta utiliza ahora una clave estable y única basada en fecha, servicio, tipo de opción y posición.
- Mantiene sin cambios el plato almacenado, los reportes y el comprobante de reserva.

## v1.0.3
- Integra la minuta real ALEMSI de agosto 2026 por fecha, servicio y tipo de opción.
- Carga idempotente de 168 opciones desde `minuta_agosto_2026.csv`.
- Corrige el `NameError` que impedía construir y enviar el comprobante de reserva.
- Mantiene el comprobante al correo del comensal y la notificación de nueva reserva a Cocina.
- Envía reclamos, sugerencias y felicitaciones a `ale973@gmail.com` y `araucaniashop@gmail.com`.
- Agrega índices de PostgreSQL para acelerar minutas, reservas, fechas y pagos.
- Añade caché de 5 minutos para consultar la minuta por fecha.


## v1.0.2
- Corrige `KeyError` al seleccionar un plato cuando la sesión de pedidos está incompleta.
- Recupera automáticamente el estado de pedidos por cada día seleccionado.
- Evita modificar la minuta global al mezclarla con datos de Supabase.
- Inicializa la base de datos una sola vez por proceso de Streamlit.
- Carga precios de platos en una consulta con caché de 120 segundos.
- Mantiene compatibilidad con PostgreSQL, Supabase y SQLAlchemy 2.x.

# Historial de cambios

## v1.0.1
- Corrige `List argument must consist only of dictionaries` al consultar por RUT.
- Convierte todas las consultas `conn.query()` parametrizadas a marcadores nombrados.
- Mantiene las escrituras compatibles con SQLAlchemy 2.x mediante `execute_sql()`.
- Sincroniza `app.py` y `streamlit_app.py`.
- Añade reglas permanentes del proyecto y guía de despliegue.
