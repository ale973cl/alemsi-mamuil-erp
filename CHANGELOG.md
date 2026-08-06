# CHANGELOG

## v2.1.7 Recuperación

- Se restauró la base funcional previa a la integración de seguridad opcional.
- Se retiró la validación por código para aislar el origen de las fallas.
- Se corrigieron todas las escrituras SQL para SQLAlchemy 2.x mediante `exec_driver_sql`.
- Se agregó Administración → Pruebas.
- Se puede borrar únicamente la tabla de reservas con confirmación explícita.
- Se agregó el perfil demo 12.345.678-5 / Comensal Demo.
- Se agregó acceso rápido al perfil demo desde el portal del comensal.
- No se eliminan comensales reales, minutas, usuarios, reclamos, inventario ni instituciones.
