# ALEMSI v2.1.3.40-RC2 — QA integrada

## Correcciones bloqueantes consolidadas
- Finanzas: eliminado el checkbox defectuoso. Aprobar/Rechazar funciona desde botón y valida requisitos al ejecutar.
- Producción: Inicio de Jornada usa confirmación de dos pasos mediante botones, sin checkbox.
- El cuerpo existente de producción y descuento teórico de Bodega no fue reescrito.
- Coordinación: Autorizar/Observar sin checkbox.
- AdminCasino → Minutas: “Validación por Coordinación” permanece visible aunque existan conflictos.
- Los conflictos de Opción 1/Opción 2 bloquean Auditar/Enviar/Publicar, pero no esconden el módulo.
- Coordinación queda exclusivamente para minutas; se retiró el residuo visual de observaciones de recetas.
- Una minuta PUBLICADA que sea modificada vuelve a requerir validación.

## Bloques congelados y comprobados por hash
- common.py: intacto.
- Reservas / render_comensal: intacto.
- Bodega perfil Casino: intacta.
- Inventario y Bodega Admin: intacto.
- Reportes Gerencia: intactos.

## Validación técnica
- Python compile: OK.
- AST parse: OK.
- ZIP integrity: OK.

## Prueba real obligatoria al desplegar
1. Finanzas: Aprobar comprobante → debe quedar Pagado.
2. Finanzas: Rechazar sin motivo → debe bloquear; con motivo → debe ejecutar.
3. Cocina: Iniciar Jornada → segunda confirmación → En producción.
4. Verificar que el descuento teórico de Bodega ocurre una sola vez.
5. AdminCasino: con conflictos, Coordinación visible pero envío bloqueado.
6. AdminCasino: sin conflictos, Enviar a Coordinación.
7. Coordinador: Observar → AdminCasino corrige → Reenviar → Autorizar.
8. AdminCasino: Publicar solo después de AUTORIZADA.
9. Bodega y Gerencia: prueba visual de regresión, sin cambios funcionales.
