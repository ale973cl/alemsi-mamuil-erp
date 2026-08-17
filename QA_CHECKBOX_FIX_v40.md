# QA v40 — Confirmaciones Finanzas / Producción

## Corregido
- Finanzas: radio, observación y casilla de confirmación ya no están dentro de `st.form`.
- El botón “Confirmar revisión” se habilita de forma reactiva.
- Aprobar requiere: comprobante disponible + confirmación.
- Rechazar requiere: comprobante disponible + motivo + confirmación.
- Producción: “INICIAR JORNADA” ya no depende de un botón visualmente deshabilitado.
- Si se pulsa sin marcar la casilla, muestra advertencia y no ejecuta.
- Si la casilla está marcada, inicia la lógica existente de jornada.

## Sin cambios
- No se modifican consultas, deduplicación, cancelaciones, conteos, Coordinación, Minutas, Bodega, Gerencia ni AdminCasino.

## Validado
- `streamlit_app.py` compila correctamente.

## Prueba real
1. Finanzas → Validar comprobantes → Aprobar → marcar confirmación → confirmar.
2. Finanzas → Rechazar → escribir motivo → marcar confirmación → confirmar.
3. Cocina → Jornada de producción → marcar confirmación → iniciar.
