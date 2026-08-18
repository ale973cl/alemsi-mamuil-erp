# RC7 — Minutas restauradas

Se corrigió la causa raíz: el estado de publicación de `minutas` ya no se usa para registrar auditoría o revisión.

- `minutas.estado`: BORRADOR / PUBLICABLE.
- `minuta_flujo_coordinacion.estado`: EN_REVISION / OBSERVADA / AUTORIZADA / PUBLICADA / REQUIERE_REVALIDACION.
- Auditar y Enviar a Coordinación no despublican la minuta.
- Publicar solo convierte BORRADOR a PUBLICABLE.
- La base real fue restaurada: las filas AUDITADA volvieron a PUBLICABLE.
