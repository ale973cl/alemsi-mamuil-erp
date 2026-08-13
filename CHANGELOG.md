# ALEMSI v2.1.3.33 — Estabilización para pruebas reales

## Correcciones incorporadas
- Finanzas: refresco controlado después de validar/observar/rechazar y avance al siguiente comprobante disponible.
- Finanzas: OBSERVADO y RECHAZADO notifican por correo al comensal con la misma referencia y el botón **Subir nuevo comprobante**.
- Comensal: se elimina el botón global **Cerrar sesión**; el cierre del flujo se denomina únicamente **Finalizar**.
- Gerencia / Reportes: se restaura una vista de **Minuta vigente** separada del reporte de platos solicitados.
- Minutas: se elimina la caché de 20 s en la vista mensual para que una carga manual se refleje inmediatamente.
- Minutas: copia entre meses optimizada evitando consultas SELECT por cada fila; se añade mensaje de proceso y resumen final.
- AdminTotal: nuevo módulo **Actividad** con registro de login, cierre, intentos fallidos, IP/contexto técnico y auditoría de acciones.
- Respaldo lógico: incorpora el registro de login.

## Reglas preservadas
- Reserva no descuenta Bodega.
- El descuento de insumos ocurre al iniciar producción.
- OBSERVAR/RECHAZAR comprobante no altera la reserva ni crea una nueva referencia.
- Minutas y maestros se mantienen al depurar datos transaccionales de prueba.
- Los módulos de Compras/OCR/Costos permanecen fuera de esta versión hasta terminar la estabilización.


# v2.1.3.32 — Candidata Ingeniería

- Finanzas: validación de comprobantes sin rerun por cambio de Validar/Observar/Rechazar; refresco inmediato tras guardar.
- Finanzas/AdminTotal: editor único de datos de transferencia, banco y tipo de cuenta controlados.
- Usuarios: login normalizado a minúsculas y herramienta temporal de contraseña común para QA desde AdminTotal.
- Infraestructura: keep-alive HTTP sin commits/push del bot.

# v2.1.3.12 — Login Recovery Fix

- Recuperación: primero envía el correo y solo después actualiza la contraseña temporal.
- Si SMTP falla, la contraseña existente permanece intacta.
- Mensaje de prueba confirma envío real a correo parcialmente oculto.
- No modifica reservas, Cocina, Minutas ni Finanzas.

# ALEMSI v2.1.3.11 — Login Recovery

- Login único de personal conservado.
- Recuperación de contraseña por correo asociado al usuario.
- Contraseña temporal con cambio obligatorio al siguiente ingreso.
- Correo agregado a usuarios creados desde Admin Total.
- Bootstrap Admin Total requiere correo de recuperación.
- No se agregan usuarios ni contraseñas predeterminadas al código.
- No se modifica el circuito de reservas/comensal en esta candidata.

## v2.1.3.19_FINANZAS_COLORES_COMPROBANTES
- Portal de comprobante actualizado en la misma ventana hacia encuesta Casino (prioritaria) y APP (secundaria).
- Persistencia separada de evaluaciones en PostgreSQL.
- Hotfix import Path para carga a Drive.
- GRAF-02: colores consistentes centralizados, nombres horizontales y máximo 7 instituciones por fila.
- Visualización real de comprobantes preservada desde Drive/PostgreSQL.

## v2.1.3.20_USUARIOS_NOTIFICACION_CORREO
- AUTH-03: creación de usuarios desde Administración con contraseña temporal segura generada por la APP.
- AUTH-03: envío automático al correo registrado con usuario, contraseña temporal, perfil y enlace de ingreso.
- AUTH-03: primer ingreso mantiene cambio obligatorio de contraseña.
- AUTH-04: restablecer/reenviar acceso genera una nueva contraseña temporal y la notifica desde la APP.
- AUTH-04: si falla el correo de restablecimiento, la contraseña vigente no se modifica.
- Se mantienen intactos reservas, comprobantes, Finanzas, encuestas, Cocina, Bodega y Gerencia.

## v2.1.3.21_HOTFIX_NOTIFICACION_INGRESO
- Administración Total: nuevo botón **Notificar ingreso** para reenviar usuario y enlace al portal sin modificar la contraseña existente.
- Auditoría de notificación mediante evento `NOTIFICAR_INGRESO`.
- Corrección de identidad interna de versión a `v2.1.3.21`.

## v2.1.3.22_MINUTAS_SEMANA_COMPACTA
- Hotfix de rendimiento/visualización en Administración Total > Minutas.
- Calendario mensual compacto en filas semanales Lunes→Domingo.
- Cada día resume servicios y opciones sin tablas verticales gigantes.
- Se evita consultar Producción una vez por día al renderizar el calendario.

## v2.1.3.23_FINANZAS_MODALIDADES_UNIFICADAS
- FIN-MOD-01: normalización visual de modalidades históricas sin alterar PostgreSQL.
- FIN-MOD-02: distribución por modalidad en formato horizontal compacto y legible.
- FIN-MOD-03: filtros y tablas de Finanzas usan las mismas etiquetas normalizadas.
