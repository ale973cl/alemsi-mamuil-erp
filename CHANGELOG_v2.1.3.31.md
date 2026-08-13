# v2.1.3.31_PRUEBA_OPTIMIZACION_UI

Versión candidata de prueba, construida de forma incremental sobre v2.1.3.30.

## Cambios seguros incluidos
- Dashboard pasa a ser el primer módulo de Administración/Gerencia/Admin Casino/Admin Total.
- Detalle de reservas por fecha/servicio queda oculto bajo “Ver detalle”; el gráfico principal permanece visible.
- Calendario móvil reforzado para mantener 7 columnas usando un marcador CSS dentro de cada fila real del calendario.
- Tras confirmar una reserva ya no se vuelve automáticamente al calendario: se muestran “Hacer otra reserva” y “Finalizar / Cerrar sesión”.
- “Finalizar / Cerrar sesión” limpia el RUT y el estado temporal y vuelve al inicio.
- Se elimina `__pycache__` del paquete a subir a GitHub.

## No modificado
- Reglas protegidas de reserva y ventana de modificación.
- PostgreSQL/Supabase y estructura de persistencia existente.
- Cálculo de precios, comprobantes, correos y referencias.
- Flujos funcionales de Cocina, Bodega, Inventario y Finanzas no incluidos expresamente arriba.

## Pendiente de prueba / siguiente iteración
- Optimización profunda del arranque (línea base 103 s).
- Reducir reruns de validación de comprobantes en Finanzas sin alterar trazabilidad.
- Persistencia entre recarga real de navegador/modo móvil-escritorio (requiere estrategia de sesión segura, no exponer RUT en URL).
- Minuta unificada Completa/Semana/Día para Cocina y Admin Casino.
- Ruta guiada de tarea de inventario por sector/ubicación/familia/producto y caducidad obligatoria según maestro.
