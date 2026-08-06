# Mamuil Malal ERP v2.1.0

Aplicación Streamlit desplegable en GitHub + Streamlit Community Cloud + Supabase PostgreSQL.

## Flujos esenciales

- Registro de comensales por RUT.
- Calendario mensual para seleccionar una o varias fechas, consecutivas o intercaladas.
- Reserva comercial para instituciones externas con precio por día y comprobante por correo.
- Declaración de consumo interno ALEMSI, sin cobro ni comprobante.
- Reclamos, sugerencias y felicitaciones con notificación por correo.

## Regla de precios

1. Excepción por RUT.
2. Tarifa especial institucional.
3. Precio estándar de $6.400 por día.

El plato no determina el cobro.

## ALEMSI

Solo se muestra Opción 1 de Almuerzo y Cena. El trabajador declara si consumirá, no consumirá o llevará comida propia. Solo los consumos confirmados se contabilizan para Cocina y Bodega.
