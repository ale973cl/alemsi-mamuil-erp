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

## v2.1.3.2-candidato-pruebas
- Navegación persistente por portal/perfil: Inicio, Comensal, Personal de Casino y Administración.
- Los módulos internos ya no se renderizan públicamente antes de elegir un acceso.
- Login de Cocina/Bodega/Finanzas permanece en el portal de Casino después de `st.rerun()`.
- Login de Administración/Gerencia permanece en Administración después de `st.rerun()`.
- Perfil Cocina ve únicamente funciones operativas de Cocina: resumen diario, minuta, recetas y consulta de Bodega; no ve cobros.
- Cocina consolida reservas por fecha, servicio, plato y cantidad.
- Flujo comercial de selección de menú corregido a avance día por día, exigiendo al menos un servicio por día.
- Precio diario se mantiene como tarifa única por día, independiente del número de servicios seleccionados.
- Carga de minuta CSV reforzada para actualizar cada combinación fecha/servicio/opción existente y evitar datos parciales obsoletos.
- Código/voucher de reserva se conserva internamente por compatibilidad; no se agrega ninguna nueva dependencia sobre él.
- Google Sheets, recordatorios financieros 17:00 y descuento automático de Bodega al iniciar producción permanecen DESACTIVADOS.

## v2.1.3.3-candidato-comensal-cocina
- Tarifa comercial estándar corregida/normalizada a $6.400 por día; excepciones se conservan por regla especial.
- Eliminado precio por plato de la experiencia visual del comensal.
- Códigos de servicio ocultos visualmente pero conservados internamente por compatibilidad.
- Reserva deja de descontar Bodega automáticamente.
- Cocina incorpora Ver minuta, Visualizar servicio, Iniciar servicio y Terminar servicio con confirmación.
- Cierre de servicio registra cantidades planificadas/producidas/entregadas y novedades.
- Nueva tabla idempotente `servicios_produccion`.
- Descuento de Bodega al inicio de producción todavía desactivado en esta candidata.

## v2.1.3.3-candidato-comensal-cocina — 2026-08-07
- Tarifa comercial base visible y aplicada: $6.400/día.
- Oculta precio de referencia por plato y códigos de reserva en la experiencia del comensal.
- Reserva ya no descuenta inventario.
- Cocina incorpora calendario/minuta, visualizar servicio, iniciar con confirmación y cierre con cantidades/novedades.
- Descuento automático de Bodega por inicio de producción permanece desactivado hasta validación.

## v2.1.3.7 — Correcciones de chequeo
Ver `CHANGELOG_v2.1.3.7.md`. Se preservan todas las funciones de v2.1.3.6 y se añaden limpieza de interfaz, dashboards, filtros, minutas por fecha, inventario trazable y administración de catálogos/usuarios.
