# ALEMSI v2.1.3.37 — Auditoría de cierre

## Cambios verificados

- Coordinación conserva acceso por el login principal y no obtiene dashboard operativo por defecto.
- Coordinación puede revisar **Minutas** y **Recetas** mediante permisos independientes.
- La revisión de recetas permite **Aprobar** u **Observar** con comentario; no modifica directamente la receta oficial.
- Cocina y Administración pueden consultar el consolidado de observaciones de recetas de Coordinación.
- Se incorporó **Calidad y satisfacción** como función habilitable por permisos, con promedios agregados; comentarios y reclamos requieren permisos separados.
- El Maestro de AdminTotal expone un catálogo ampliado de permisos para habilitar/deshabilitar módulos y funciones por usuario.
- La depuración continúa siendo transaccional y **no elimina Usuarios/contraseñas, permisos, Minutas, Platos, Recetas, Instituciones ni configuración**.
- La nueva tabla de revisión de recetas se incorpora al respaldo lógico.

## Reglas protegidas

1. Reserva no descuenta Bodega.
2. El descuento de Bodega se ejecuta al iniciar Producción y una sola vez.
3. Coordinación no edita directamente la Minuta ni la Receta oficial.
4. Usuarios, contraseñas y maestros quedan fuera de la depuración de datos de prueba.
5. AdminTotal mantiene gobierno total de permisos.

## Validación estática

Compilación Python y AST: OK. Se verificaron 18 controles estructurales sin fallos.

La aprobación final requiere prueba desplegada con PostgreSQL, SMTP y sesión real.
