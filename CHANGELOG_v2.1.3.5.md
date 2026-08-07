# v2.1.3.5 - Candidato usuarios + hotfix Cocina

## Cambios incluidos
- COC-01: corrige `ON CONFLICT` de `jornada_detalle` para usar la clave real `(fecha, servicio, tipo_opcion, plato)`.
- Habilita perfiles internos de prueba: Administrador Total, Administrador Casino, Operaciones, Cocina, Finanzas y Gerencia.
- Deshabilita el login independiente de Bodega; Bodega sigue disponible como función autorizada dentro de Cocina/Administración.
- Agrega perfil Operaciones con acceso administrativo equivalente a Administrador Casino.
- Añade contraseña temporal y cambio obligatorio en el primer ingreso.
- Gerencia y Administrador Total pueden restablecer contraseñas; no pueden visualizar contraseñas actuales.
- Administrador Total conserva creación de usuarios, cambio de rol, activación/desactivación y permisos.
- Migración única `BOOTSTRAP_USUARIOS_V2135` habilita los usuarios de prueba sin volver a sobrescribir sus contraseñas en cada rerun.

## Zona protegida / NO ROMPER
- Registro y validación de RUT de comensal.
- Selección y guardado de reservas.
- PostgreSQL/Supabase como fuente oficial.
- Tarifa comercial base de $6.400 por día y excepciones vigentes.
- Generación y envío de comprobante por correo.
- Historial de reservas y auditoría existente.

## Pendiente para candidata siguiente
- OPT-01: eliminar rerun redundante del calendario del comensal.
- RES-01: detectar reserva existente y ofrecer Ver/Modificar antes de crear una superpuesta.
- Mejoras de Minutas/Instituciones acordadas (carga masiva, fecha concreta, relación con recetas, altas/bajas de instituciones).
