# QA Coordinación — ALEMSI v2.1.3.40

## Activado
- Rol `Coordinacion` disponible en el portal operativo.
- Ingreso por el login principal.
- AdminTotal puede crear/asignar usuarios con rol Coordinación.
- Se reutiliza el módulo `render_coordinacion()` ya existente.

## Alcance funcional preservado
- Revisión de minutas.
- Revisión de recetas.
- APROBAR / OBSERVAR / PROPONER CAMBIO.
- Propuesta desde Maestro de Platos o texto libre.
- Historial y auditoría.
- Coordinación no modifica directamente la minuta ni receta oficial.

## Sin acceso
- Finanzas.
- Producción.
- Bodega.
- Gestión de usuarios.

## Validado estáticamente
- `streamlit_app.py` compila correctamente.

## Pendiente prueba real
- Crear/asignar usuario Coordinación.
- Ingresar por login principal.
- Confirmar vista de Minutas y Recetas.
- Registrar una observación/propuesta y verificar auditoría.
