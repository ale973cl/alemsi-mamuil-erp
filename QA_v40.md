# QA v40 — Cierre de Arquitectura

**Versión:** ALEMSI v2.1.3.40_CIERRE_ARQUITECTURA  
**Base:** copia de `ALEMSI_v2.1.3.39_CIERRE_REVISION.zip`  
**Regla:** la v39 original no fue modificada.

## Estados de verificación

- **DETECTADO:** hallazgo comprobado en el código v39.
- **CORREGIDO EN CÓDIGO:** cambio implementado sobre la copia v40.
- **VALIDADO ESTÁTICAMENTE:** sintaxis/estructura/regla comprobada sin afirmar ejecución real contra producción.
- **PENDIENTE PRUEBA REAL:** requiere Streamlit, Supabase/PostgreSQL, SMTP, Drive o impresión real.

## Matriz de cierre

| Circuito | Detectado en v39 | Corregido en v40 | Validación estática | Prueba real pendiente |
|---|---|---|---|---|
| Selectores | Algunos selectores precargaban el primer registro | Selector neutro para registros individuales y retiro de precargas en Finanzas/Gerencia | Sí | Navegación Streamlit completa |
| Comensal | Placeholder/RUT y validaciones de contacto incompletas | RUT M11, correo obligatorio/minúscula/DNS, móvil chileno | Sí | Resolución DNS desde hosting |
| Reserva | Protección lógica dependía demasiado del flujo UI; cancelación no estaba cerrada | Índice único parcial activo, dedup no destructiva, edición estable, cancelación histórica | Sí | Concurrencia real PostgreSQL |
| Excepción reserva | No existía circuito operativo completo | RUT + rango + motivo + autor + activa/inactiva; solo habilita ventana | Sí | Flujo real con comensal |
| Finanzas | Existía OBSERVADO y caminos duplicados de decisión | Solo APROBADO/RECHAZADO, confirmación, motivo obligatorio, correo e historial | Sí | SMTP + datos reales |
| AdminCasino | Existían controles financieros heredados | Pago queda en Finanzas; módulo de excepción agregado | Sí | Prueba por rol |
| Permisos | Overrides existían pero no componían claramente el rol base | `ROL BASE + PERMISOS EXTRAORDINARIOS` para módulos administrativos | Sí | Prueba con usuarios reales |
| Gerencia | Había detalle/acciones no ejecutivas | Base solo Dashboard/Reportes/Satisfacción; agregado por institución y ranking | Sí | Revisión UX con gerencia |
| Minutas | Edición activa inmediata y conflicto tardío | BORRADOR→AUDITADA→PUBLICABLE; conflicto O1/O2 previo; rango libre | Sí | Publicación/reserva real |
| Producción | Riesgo de divergencias entre fuentes/estados | Activas + dedup última válida; resumen por servicio y PDF Carta | Sí | Jornada real + impresión |
| Bodega | Etapa aún parcial | Se mantiene arquitectura, sin sobredesarrollo | Sí | Etapa 2 |
| Reportes | CSV/planillas tenían protagonismo operacional | PDF corporativo principal; CSV/Excel técnico secundario | Sí | Impresión real + logo oficial |
| Autoscroll | Páginas largas podían conservar foco abajo | `window.parent.scrollTo(0,0)` al cambiar módulo | Sí | Navegadores/móvil |
| Seguridad | Depuración podía borrar históricos transaccionales | Depuración destructiva deshabilitada; sin `DELETE FROM` operativo | Sí | Revisión de políticas/RLS fuera de alcance v40 |
| Coordinación | Código histórico existía | No se habilita el rol en esta entrega | Sí | Etapa 2 |

## Prueba de conciliación v40

Caso: 10 comensales, mismo día/servicio, **4 Opción 1 + 3 Opción 2 + 3 Hipocalóricos**.

Resultado del modelo estático:
- Reservas activas: **10**.
- Producción esperada: **10**.
- Opción 1: **4**.
- Opción 2: **3**.
- Hipocalórico: **3**.
- Repetición de la misma clave `RUT + fecha + servicio`: **permanece 1 registro lógico activo**.
- Cambio de plato: actualiza la misma clave lógica, no suma otra ración.
- Cancelación: inactiva la reserva y conserva historial.
- Excepción: no crea ración por sí misma.
- Rechazo/reingreso/aprobación de pago: no altera la cantidad de raciones.

**Importante:** esta prueba valida el modelo y las invariantes del código. La igualdad exacta entre BD real, dashboard, Producción y PDF debe confirmarse con una ejecución controlada sobre Supabase/Streamlit antes de uso productivo.

## Validaciones técnicas ejecutadas

- `python -m py_compile streamlit_app.py common.py jobs/recordatorio_pago_17.py`: **APROBADO**.
- Parseo AST de los tres módulos Python: **APROBADO**.
- Suite estática de invariantes: **29/29 APROBADA**.
- Búsqueda de `DELETE FROM` en Python operativo: **0 coincidencias**.
- Coordinación ausente del selector de creación de roles: **APROBADO**.

## Pendientes obligatorios antes de declarar producción

1. Respaldar PostgreSQL/Supabase y ejecutar la migración v40 en un entorno controlado.
2. Verificar el índice único parcial con datos reales y concurrencia de dos sesiones.
3. Ejecutar la conciliación 10=4+3+3 en Streamlit y comparar BD/dashboard/Producción/PDF.
4. Probar aprobación, rechazo y reingreso con SMTP real, comprobando un solo correo por decisión.
5. Probar permisos con al menos AdminTotal, AdminCasino, Finanzas, Cocina, Gerencia y Bodega.
6. Verificar autoscroll en móvil y escritorio.
7. Revisar PDFs Carta en impresión real e incorporar/confirmar el archivo gráfico oficial del logo ALEMSI si se exige coincidencia exacta con papelería corporativa.
