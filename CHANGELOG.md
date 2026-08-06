# CHANGELOG

## v2.1.4 - Seguridad opcional y estabilidad
- Agrega en Administración una opción para elegir entre **Solo RUT** y **RUT + código por correo**.
- El modo predeterminado sigue siendo **Solo RUT**; el flujo actual no cambia hasta activarlo.
- El código temporal vence y limita intentos.
- Mantiene navegación persistente por módulo.
- Mantiene reserva día por día, listas desplegables, correo, comprobante y reclamos.
- Oculta textos técnicos en la vista general.

# Mamuil Malal ERP v2.1.2

## Mejorado
- Selección de minuta día por día mediante listas desplegables.
- Orden fijo de servicios: Desayuno, Almuerzo, Once y Cena.
- Navegación hacia adelante y atrás conservando las elecciones.
- Validación de al menos un servicio por día.
- Botón final "Revisar reserva".

## Corregido
- Eliminación de botones individuales por plato y sus reruns repetidos.
- Corrección del resumen de fechas del comprobante.
- Eliminación de textos técnicos en el correo al comensal.

## Conservado
- Registro por RUT.
- Supabase/PostgreSQL.
- Guardado de reservas.
- Comprobante HTML y correo.
- Reclamos, login y reportes existentes.

# Mamuil Malal ERP v2.1.3

## Corregido
- La aplicación conserva el módulo principal después de iniciar sesión.
- Administración permanece abierta después del login y de cualquier recarga.
- Personal de Casino permanece en su módulo después del login.
- Las secciones internas de Comensal, Casino y Administración conservan la selección activa durante los reruns.
- Cerrar sesión devuelve de forma controlada a la vista de Comensal.

## Conservado
- Flujo de reservas, comprobantes, correo, reclamos y consultas existentes.

## v2.1.5 — interfaz de reserva y servicios
- Calendario mensual real, alineado de lunes a domingo y sin iconos de ayuda junto a las fechas.
- Botón inferior “Continuar a selección de menú”.
- Reserva día por día con navegación hacia atrás y adelante.
- Los cuatro servicios se muestran siempre en orden: Desayuno, Almuerzo, Once y Cena.
- Cada servicio con minuta usa un desplegable; si no tiene minuta se informa sin ocultarlo.
- Ajustes visuales compactos inspirados en la identidad institucional de ALEMSI, sin incorporar imágenes pesadas.
- Se conservaron navegación persistente, reclamos, correos, comprobantes, seguridad opcional y reglas de precios.
