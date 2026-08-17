# QA Cocina final — v40

## Corregido
- El menú de Cocina aparece inmediatamente al iniciar sesión.
- Las tareas/notificaciones quedan debajo y ya no controlan la aparición del menú.
- Se elimina el bloque antiguo “Visualizar jornada completa” que competía con la nueva presentación.
- Jornada de Producción queda separada por servicio en pantalla.
- Cada servicio disponible genera un PDF independiente.
- Se mantiene un PDF consolidado de insumos del día.
- Se conserva la misma fuente de datos: solicitudes, comensales, minutas y recetas.

## Validación estática
- streamlit_app.py compila correctamente.

## Prueba real sugerida
- Cocina → 19/08/2026.
- Debe verse Almuerzo y Cena como bloques separados.
- Deben aparecer PDF Almuerzo, PDF Cena y PDF de insumos del día.
