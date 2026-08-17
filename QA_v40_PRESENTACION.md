# QA v40 — Candidata presentación Gerencia

## Corregido en código
- Perfil Cocina conserva tareas de inventario y vuelve a mostrar Minuta, Jornada de producción, Recetas y Bodega operativa.
- Jornada de Producción muestra resumen corporativo del día.
- Cada servicio muestra totales Instituciones + ALEMSI = Total.
- Nominal ALEMSI y recuadro de insumos aparecen lado a lado en pantalla.
- PDF separado por servicio en tamaño Carta.
- PDF consolidado de insumos del día.
- Cálculo de insumos usa cantidad por ración + merma + margen de producción.
- Recetas BORRADOR se pueden visualizar, pero no descuentan Bodega.
- AdminCasino puede editar recetas y guardar nueva versión sin borrar histórico.
- Botón Volver al inicio disponible después de identificar RUT.
- Bloqueo de nueva reserva cuando existe servicio comercial vencido impago/rechazado.
- El bloqueo excluye consumo interno ALEMSI y costo asumido/Coordinadores.
- Cancelación y deduplicación existentes no fueron reemplazadas.

## Validado estáticamente
- `streamlit_app.py` compila con Python sin errores.

## Pendiente prueba real
1. Cocina: módulos visibles con selector de tareas neutro.
2. Producción 19/08: Almuerzo y Cena, PDFs y consolidado de insumos.
3. Recetas BORRADOR: edición y versionado por AdminCasino.
4. Wilson Pérez: servicio vencido impago debe bloquear nueva reserva.
5. Finanzas marca Pagado: el mismo RUT debe quedar habilitado.
6. SMTP/correos todavía requieren prueba/configuración real.
