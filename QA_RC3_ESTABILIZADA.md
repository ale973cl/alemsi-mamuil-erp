# ALEMSI v2.1.3.40-RC3 — QA de estabilización

## Confirmaciones sensibles
- Finanzas conserva checkbox obligatorio. El botón no depende de `disabled`; el backend vuelve a verificar la casilla antes de aprobar/rechazar.
- Inicio de Producción conserva checkbox obligatorio y backend guard.
- Cierre de Jornada conserva checkbox obligatorio y backend guard. Diferencias sin motivo bloquean el cierre.
- Coordinación conserva checkbox obligatorio antes de Autorizar/Observar.

## Minutas / perfiles
- AdminCasino y AdminTotal: revisar/auditar, enviar/re-enviar a Coordinación y publicar tras autorización.
- Coordinación: únicamente revisar, observar o autorizar desde su perfil.
- Gerencia: consulta. Si recibe acceso extraordinario a Minutas, no puede editar/enviar/publicar.
- Bodega: no se modificó durante esta estabilización.

## Importación de minuta
- RC3 mantiene CSV estructurado como vía determinista de carga masiva.
- El PDF original se conserva como documento fuente.
- Recomendación de arquitectura: PDF directo → extracción automática → vista previa → confirmación humana → filas estructuradas. No publicar directamente desde OCR/IA sin revisión.

## Protección por hash
- common.py: intacto.
- Reservas/render_comensal: intacto.
- Perfil Bodega: intacto.
- Inventario y Bodega Admin: intacto.

## Validación estática
- Python compile: OK.
- AST parse: OK.
- ZIP integrity: OK.

## Prueba real requerida
1. Finanzas: marcar checkbox + Aprobar; repetir Rechazar con motivo.
2. Cocina: marcar checkbox + Iniciar jornada.
3. Cocina: cierre sin checkbox debe bloquear; con checkbox y sin diferencias debe cerrar.
4. Cocina: diferencia sin motivo debe bloquear aunque checkbox esté marcado.
5. AdminCasino: enviar minuta sin conflictos → Coordinación.
6. Coordinación: observar con checkbox; AdminCasino corrige/reenvía; Coordinación autoriza.
7. Gerencia: comprobar ausencia de acciones de mutación.
