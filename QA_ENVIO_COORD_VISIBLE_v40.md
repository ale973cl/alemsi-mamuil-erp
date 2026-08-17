# QA v40 — Envío de minuta a Coordinación visible

## Corregido
- AdminCasino → Minutas muestra una sección fija “Validación por Coordinación”.
- “Enviar a Coordinación” aparece claramente cuando el período contiene una minuta.
- Si la minuta fue observada o requiere nueva validación, cambia a “Reenviar a Coordinación”.
- El envío audita automáticamente filas BORRADOR/PUBLICABLE sin alterar platos.
- Publicar sigue bloqueado hasta que Coordinación autorice.
- Si ya está EN_REVISION/AUTORIZADA/PUBLICADA, el envío queda bloqueado con explicación.

## Sin cambios
- No se modifican Reservas, Finanzas, Cocina, Gerencia, Bodega ni la lógica de correo.
- No se modifican los platos ni el contenido de la minuta al auditar/enviar.

## Validado
- streamlit_app.py compila correctamente.
