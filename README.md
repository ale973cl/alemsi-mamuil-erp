# Mamuil Malal ERP v2.1.1

Aplicación Streamlit con PostgreSQL/Supabase para registro de comensales, reserva de servicios de alimentación, comprobantes por correo y gestión operativa.

## Flujo comercial
1. El comensal selecciona fechas y servicios.
2. Elige el plato disponible para cada servicio.
3. Revisa el total y confirma.
4. La reserva se guarda en PostgreSQL.
5. Se genera una referencia de consulta.
6. Se envía el comprobante al correo del comensal y la notificación a Cocina.

## Regla de duplicados y cambios
La combinación RUT + fecha + servicio representa una sola reserva. Una reserva existente puede actualizarse cuando faltan al menos 48 horas para el inicio del servicio.

## Planilla
Administración incluye una planilla consultable y descargable en Excel, con referencia, fecha, servicio, comensal, plato, monto y estado.
