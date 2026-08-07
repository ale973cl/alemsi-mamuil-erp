# v2.1.3.4 — Candidato integrado

## Cocina
- Jornada completa por fecha en vez de inicio por servicio aislado.
- Producción agrupada por servicio/opción/plato.
- Registro persistente de reservadas, producidas y entregadas.
- Justificación obligatoria de diferencias.
- Novedades y cierre diario.
- Reporte de cierre por correo a Administración Casino.
- Cinco recetas tipo BORRADOR con merma y margen de producción.

## Finanzas
- Portal de Finanzas separado.
- Estados: Pendiente, Comprobante recibido, Observado, Pagado.
- Métodos: Transferencia bancaria y Débito en la instalación.
- Ajuste de monto con motivo obligatorio y auditoría.
- Reporte semanal descargable.

## Usuarios y permisos
- AdminTotal, AdminCasino, Gerencia, Finanzas, Cocina y Bodega.
- Usuario histórico `admin` migra a AdminTotal sin cambiar contraseña.
- AdminTotal puede crear/actualizar usuarios, activar/desactivar cuentas, cambiar roles y permisos específicos.
- Permisos principales de Cocina/Bodega/Finanzas se aplican en ejecución.

## Seguridad de cambios
- Sin borrado de tablas/columnas existentes.
- Descuento definitivo de Bodega sigue desactivado.
- Automatización de las 17:00 queda pendiente de implementación externa.
