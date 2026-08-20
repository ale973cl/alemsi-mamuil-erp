# Validación dirigida — segunda pasada

## Pendientes implementados

- Coordinación muestra la matriz reutilizable y una revisión persistente por día, servicio y opción, con decisiones Conforme/Observar, comentario condicional y acción Todo el día conforme.
- La finalización deriva el estado OBSERVADA o AUTORIZADA desde los ítems persistidos. Admin Casino ve el aviso y el detalle exacto; el reenvío crea una versión nueva.
- Se añadieron notificaciones internas y outbox de correo con estados PENDIENTE, ENVIADO y ERROR para los circuitos integrados de minuta, comprobante, excepción, encuesta y opiniones.
- El formulario público de opiniones usa una sola clasificación Reclamo/Sugerencia/Felicitación y la consulta administrativa unifica filtros por tipo, servicio y estado.
- La encuesta Casino se limita a Atención, Calidad de la comida y Limpieza; los comentarios generan notificación interna a Cocina.
- Las excepciones de cancelación se solicitan desde Mis reservas, se resuelven en Administración Casino y notifican a Finanzas al aprobarse.
- Anticipación de reserva, cancelación y máximo consecutivo se almacenan en configuración operativa editable.

## Conservación

No se modificaron Bodega, su inventario, movimientos ni descuento de producción. Tampoco se reemplazó la transacción protegida que inserta/actualiza reservas. `referencia_reserva` continúa siendo la clave interna.

## Alcance de pruebas

Los tests transaccionales usan SQLite en memoria y dobles de SMTP. Validan persistencia y transiciones sin tocar PostgreSQL productivo. La navegación real de Streamlit, entrega SMTP, Google Drive, permisos reales y PostgreSQL/Supabase requieren Secrets y una base QA aislada; por ello no se declaran certificados en este entorno.

## Riesgos restantes

- Los correos históricos de alta/recuperación de usuarios y cierre de Cocina conservan su comportamiento síncrono por compatibilidad; los eventos prioritarios modificados usan outbox persistente.
- La migración debe probarse una vez en una copia de la base real antes del despliegue.
- La prueba estática de navegación comprueba contratos de renderizadores/session state, pero no sustituye una sesión Streamlit con usuarios reales de cada rol.
