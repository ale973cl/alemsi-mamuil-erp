# MATRIZ FUNCIONAL ALEMSI v2.1.3.7

## Reglas de conservación
- Ninguna mejora puede borrar, desactivar o reescribir una función aprobada sin autorización explícita.
- Reserva, PostgreSQL/Supabase, comprobante PDF, correo y carga de comprobante son funciones protegidas.
- Hotfix Cocina protegido: `ON CONFLICT (fecha,servicio,tipo_opcion,plato)`.
- Todas las fechas visibles se presentan como DD/MM/AAAA; la base puede mantener ISO internamente.
- Ocultar/desactivar módulos, reportes, usuarios, instituciones o modalidades de pago no borra historial.
- Correos institucionales se parametrizan; el cambio futuro de direcciones no modifica la lógica SMTP.

## Comensal
- Tarifa diaria base $6.400, salvo excepción autorizada.
- Selección por calendario sin rerun explícito redundante en el clic del día.
- Correo/PDF de reserva conserva enlace seguro para cargar comprobante.
- El pago no es condición previa al consumo.

## Cocina
- Minuta y producción en orden Desayuno > Almuerzo > Once > Cena, omitiendo servicios inexistentes.
- Inicio de jornada por día completo.
- Reservadas y Producidas son de consulta en el cierre; solo Entregadas es editable.
- Diferencias requieren motivo y quedan auditadas.
- Bodega: consulta, carga individual, carga CSV e inventario físico con responsable y diferencia teórico/real.

## Finanzas
- Dashboard financiero con pagado, pendiente, institución y modalidad.
- Comprobante recibido requiere validación de Finanzas para quedar Pagado.
- Modalidades de pago activas provienen de catálogo administrable.
- Ajustes de monto/estado conservan auditoría.
- Recordatorio de las 17:00 sigue definido para automatización externa.

## Gerencia / Administración
- No se muestran SQL, PostgreSQL, Streamlit ni nombres técnicos innecesarios en pantallas de usuario.
- Dashboard integral financiero y operacional.
- Planilla con filtros por comensal, institución, modalidad de pago, estado y fechas.
- Minutas por fecha, vista 2x2 por servicios, carga manual, CSV y copia mensual.
- Resumen de producción dentro de la vista diaria de minuta.
- Instituciones pueden crearse y activarse/desactivarse sin borrar historial.

## Administrador Total
- Usuarios/permisos, alta, desactivación, roles y restablecimiento de contraseña.
- Cuentas iniciales activas: admin, cocina, gerencia, finanzas.
- Cuentas históricas extras quedan desactivadas; pueden crearse perfiles adicionales desde interfaz.
- Depuración controlada de reservas y comensales de prueba con confirmación explícita.
- Modalidades de pago: agregar, activar/desactivar sin borrar historial.

## Pendientes deliberadamente no mezclados en esta candidata
- Parsing automático genérico de PDF de minuta: mantener carga CSV y edición por fecha hasta definir parser robusto.
- Clima en Cocina: mejora visual opcional; no se incorpora hasta asegurar que no añada latencia ni dependencia externa.
- Automatización real de las 17:00: se conectará mediante programador externo, no por un reloj de Streamlit.
