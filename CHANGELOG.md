# CHANGELOG

## v2.1.3.1-candidato
- Integra la línea visual de la maqueta ALEMSI/Mamuil Malal en el banner superior.
- Adopta paleta turquesa/verde petróleo, blanco y acento amarillo, con tarjetas y botones redondeados.
- Agrega ancla de cambio seguro en `app.py`, `streamlit_app.py` y `PROJECT_RULES.md`.
- No modifica lógica de reservas, PostgreSQL/Supabase, precios, comprobantes, SMTP, reglas ALEMSI, duplicados ni regla de 48 horas.
- Archivos modificados: `common.py`, `streamlit_app.py`, `app.py`, `PROJECT_RULES.md`, `CHANGELOG.md`.
- Pruebas realizadas: compilación Python, comparación hash `app.py`/`streamlit_app.py` y revisión de que el cambio se limite a presentación/documentación.
- Prueba pendiente: validación visual y reserva real en Streamlit publicado.

## v2.1.3-candidato
- Reemplaza las casillas del calendario por botones de fecha tipo reserva de pasajes.
- Permite seleccionar fechas consecutivas o intercaladas y resalta visualmente los días elegidos.
- Elimina el icono de ayuda “?” que aparecía junto a las fechas del comensal.
- Mantiene el avance día por día y los servicios desplegables Desayuno, Almuerzo, Once y Cena.
- No se modificaron el guardado de reservas, precios, comprobantes, SMTP, reglas ALEMSI ni base de datos.
- Archivos modificados: `streamlit_app.py`, `app.py`, `CHANGELOG.md`.
- Pruebas realizadas: compilación Python y verificación de igualdad entre `app.py` y `streamlit_app.py`.
- Prueba pendiente: validación visual y reserva real en Streamlit.

## v2.1.2-candidato
- Interfaz de reserva comercial: los servicios se muestran en desplegables separados y ordenados como Desayuno, Almuerzo, Once y Cena.
- Cada desplegable presenta únicamente las alternativas disponibles en la minuta de la fecha.
- Los servicios sin minuta permanecen visibles e indican que no hay opciones disponibles.
- No se modificaron el guardado de reservas, precios, comprobantes, SMTP, reglas ALEMSI ni base de datos.
- Archivos modificados: `streamlit_app.py`, `app.py`, `CHANGELOG.md`.
- Prueba realizada: compilación Python.
- Prueba pendiente: validación visual y reserva real en Streamlit.

# Changelog

## v2.1.1
- Agrega una referencia única para consultar cada operación de reserva.
- Muestra la referencia y el valor total en el comprobante enviado al comensal.
- Muestra una confirmación clara: “¡Felicitaciones! Tu reserva fue realizada con éxito. Te esperamos.”
- Agrega una planilla administrativa de reservas con búsqueda por referencia y descarga en Excel.
- Evita duplicar una reserva por la combinación RUT + fecha + servicio.
- Permite actualizar una reserva existente únicamente cuando faltan 48 horas o más para el servicio.
- Registra fecha de modificación y usuario/RUT que realizó el cambio.
- Mantiene el flujo especial de ALEMSI sin comprobante ni correo.
- Oculta textos técnicos del encabezado y pie de página públicos.

## v2.1.0
- Calendario mensual y reglas diferenciadas para ALEMSI y comensales comerciales.
