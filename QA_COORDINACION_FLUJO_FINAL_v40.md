# QA — Coordinación / Minutas v40

## Implementado en código
- Coordinación queda exclusivamente para revisión de minutas.
- Coordinación no ve ni revisa Recetas, Finanzas, Producción, Bodega ni Usuarios.
- AdminCasino conserva el editor actual de Minutas.
- Nuevo panel en AdminCasino: “Minutas en revisión por Coordinación”.
- Flujo: BORRADOR → AUDITADA → EN_REVISION → OBSERVADA/AUTORIZADA → PUBLICADA.
- Si Coordinación observa, comentario obligatorio.
- AdminCasino corrige y puede reenviar una nueva versión.
- Si AdminCasino modifica una minuta enviada o autorizada, la autorización queda REQUIERE_REVALIDACION.
- Publicar queda habilitado únicamente cuando Coordinación deja la propuesta AUTORIZADA.
- No se borran minutas ni revisiones históricas.
- Cada envío/reenvío crea versión nueva del flujo de revisión.
- Auditoría registra envío, invalidación, decisión y publicación.

## Validación estática
- `streamlit_app.py` compila correctamente.

## Pendiente prueba real Streamlit/Supabase
1. AdminCasino: auditar período.
2. Enviar a Coordinación.
3. Coordinador: observar con comentario.
4. AdminCasino: ver observación y corregir.
5. Reenviar.
6. Coordinador: autorizar.
7. AdminCasino: publicar.
8. Confirmar que una edición posterior invalida autorización.
