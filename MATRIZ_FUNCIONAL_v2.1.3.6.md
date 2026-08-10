# Matriz funcional protegida v2.1.3.6

| Módulo | Función protegida | Estado |
|---|---|---|
| Comensal | RUT, institución, calendario, selección, reserva | Conservada |
| Reserva | Precio diario, referencia, persistencia PostgreSQL | Conservada |
| Reserva | Detección/modificación de reserva existente | Conservada |
| Correo | Confirmación inmediata | Conservada + mejorada |
| PDF | Detalle por día en celdas Servicio/Plato | Nuevo protegido |
| Pago | Enlace personal para comprobante | Nuevo protegido |
| Finanzas | Revisar estado, método, monto con motivo/auditoría | Conservada |
| Finanzas | Descargar comprobante recibido | Nuevo protegido |
| Cocina | Jornada completa, reservadas/producidas/entregadas | Conservada |
| Cocina | Motivo obligatorio ante diferencias | Conservada |
| Cocina | ON CONFLICT fecha,servicio,tipo_opcion,plato | HOTFIX PROTEGIDO |
| Usuarios | Roles, activo, cambio de contraseña, permisos | Conservada |
| Administración | Minutas, excepciones, instituciones, correos | Conservada |
| Auditoría | Cambios sensibles con usuario/motivo | Conservada |
