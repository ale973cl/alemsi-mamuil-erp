# Changelog

## v2.1.0
- Calendario mensual tipo compra de pasajes, con siete columnas y selección múltiple.
- Permite un día, días consecutivos o fechas intercaladas.
- Deshabilita fechas pasadas y fechas sin minuta real.
- Separa ALEMSI como consumo interno: solo Opción 1 en Almuerzo y Cena.
- ALEMSI declara «Consumiré», «No consumiré» o «Comida propia».
- ALEMSI no genera cobro, código, comprobante ni correo.
- Los demás comensales mantienen reserva comercial, tarifa por día, comprobante y correo.
- Agrega `tipo_registro` a solicitudes para separar consumo interno y reserva comercial.
- Cocina contabiliza solo consumos internos confirmados y reservas comerciales.
- Finanzas excluye consumo interno ALEMSI.
- Corrige la validación del botón de confirmación dentro de formularios.
