# QA Cocina — ALEMSI v2.1.3.40

- Detectado: con tareas de inventario activas, el selector neutro sin selección ejecutaba `return` y detenía `render_casino()` antes del menú principal.
- Corregido: el selector permanece neutro, pero no seleccionar una tarea ya no corta el perfil.
- Se conservan: tareas de inventario, Ver minuta, Jornada de producción, Recetas y Bodega operativa.
- Validación estática: `streamlit_app.py` compila correctamente.
- Pendiente: prueba real en Streamlit con usuario Cocina.
