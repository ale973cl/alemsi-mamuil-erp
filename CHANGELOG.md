# v2.1.3.40 — CIERRE DE ARQUITECTURA

## Corregido en código
- Regla transversal de selectores: helper neutro `— Seleccione —` para registros individuales; se retiran precargas automáticas de personas/reservas/comprobantes en Finanzas y Gerencia.
- Comensal: RUT chileno, correo obligatorio normalizado con validación estructural + resolución de dominio, y teléfono móvil chileno normalizado a `+56 9 XXXX XXXX`.
- Reservas: clave lógica activa `RUT + fecha + servicio` reforzada con índice único parcial PostgreSQL; duplicados históricos activos se inactivan sin borrar; edición conserva referencia y cancelación es no destructiva.
- Excepción de reserva: AdminCasino puede autorizar rango temporal por RUT y motivo. Solo habilita la reserva normal; no crea raciones ni valida pagos.
- Finanzas: decisión operativa única `APROBADO / RECHAZADO`; rechazo exige motivo, ambos requieren confirmación y generan correo; reingreso de comprobante conserva referencia e historial.
- AdminCasino: se elimina la validación base de pagos. Arquitectura de módulos pasa a `ROL BASE + PERMISOS EXTRAORDINARIOS` mediante overrides explícitos de AdminTotal.
- Gerencia: perfil base de consulta/análisis; dashboard agregado, reporte ejecutivo por institución y ranking de platos con filtro de período, sin detalle personal inicial ni controles operativos.
- Minutas: rango libre, maestro universal para Opción 1/Opción 2, Tipo R disponible por servicio, auditoría preventiva de conflictos y flujo `BORRADOR → AUDITADA → PUBLICABLE`.
- Producción: conteo solo de reservas activas deduplicadas, resumen por servicio/opción/plato, listado nominal ALEMSI y PDF Carta corporativo como salida principal.
- Reportes: PDF Carta corporativo para Finanzas, Gerencia, AdminCasino y Producción; CSV/Excel quedan como exportación técnica secundaria.
- Interfaz: autoscroll al inicio al cambiar de módulo.
- Seguridad: depuración destructiva de producción deshabilitada en v40; no quedan sentencias `DELETE FROM` en código Python operativo.
- Coordinación continúa deshabilitada para esta entrega y se mantiene únicamente como propuesta de Etapa 2.

## Validación estática
- `py_compile` y AST aprobados en `streamlit_app.py`, `common.py` y job de recordatorio.
- Suite estática v40: 29/29 comprobaciones aprobadas.
- Conciliación conceptual: 10 reservas = 4 Opción 1 + 3 Opción 2 + 3 Hipocalórico; duplicar la misma clave mantiene una sola ración válida.

## Pendiente de prueba real
- Ejecución de migraciones e índice único sobre PostgreSQL/Supabase real con respaldo previo.
- Flujo completo Streamlit con datos productivos, permisos reales y concurrencia.
- Envío SMTP real de aprobación/rechazo y validación DNS desde el hosting.
- Visualización/impresión de PDFs en dispositivo/impresora real y verificación del activo gráfico oficial del logo.

# v2.1.3.37 — Coordinación, permisos y calidad

- Coordinación incorpora revisión de Recetas (Aprobar/Observar) sin modificar la receta oficial.
- Reporte consolidado de observaciones de recetas para Cocina/Administración.
- Satisfacción, comentarios y reclamos quedan disponibles mediante permisos independientes.
- Catálogo de permisos de AdminTotal ampliado para módulos administrativos.
- Depuración reforzada: conserva Usuarios/contraseñas, permisos, Minutas, Platos, Recetas, Instituciones y configuración.

# v2.1.3.36 CANDIDATA CIERRE OPERATIVO

- Auditoría estática/estructural completa del código antes de la prueba real.
- Nuevo **Maestro de Platos** visible y reutilizable desde Minutas, con búsqueda, filtros, descarga CSV y alta/clasificación básica.
- Sincronización idempotente: platos históricos de `minutas` pasan al maestro sin alterar costos ni recetas.
- Normalización de variantes históricas `Opción 1 / Opción 2 / Hipocalórico` para corregir precarga de fechas antiguas, visualización y edición.
- Producción usa una sola fuente de conteo y deduplica por **RUT + fecha + servicio**, tomando el registro más reciente.
- Reportes reutilizan el mismo conteo de Producción por servicio/plato y agregan listado nominal ALEMSI para control de entrega.
- Selección ALEMSI conserva `tipo_opcion` en la reserva interna para trazabilidad de Opción 1 / Hipocalórico.
- Regla de Bodega reforzada: reserva no mueve stock; solo `Iniciar jornada` puede descontar, una vez.
- Eventualidad sin minuta: se registra Producción pero **no** se descuenta Bodega automáticamente.
- Recetas en BORRADOR ya no descuentan inventario; solo recetas ACTIVA/APROBADA.
- Helper histórico `descontar_bodega()` queda neutralizado para impedir descuentos fuera de Producción.
- Actividad AdminTotal mantiene fecha y hora completa.
- Coordinación mantiene acceso privado de solo revisión: ver, aprobar, observar y proponer cambio; no edita minuta oficial.
- Finanzas conserva ruta Observado/Rechazado -> notificación -> misma referencia -> nuevo comprobante.
- Compras/OCR/Costos de Cocina continúan fuera de esta candidata y no bloquean el demo.

# v2.1.3.35 CANDIDATA PRODUCCION DEMO

- ALEMSI se separa en **ALEMSI Paso Fronterizo** y **ALEMSI Administrativos**.
- Paso Fronterizo: solo Opción 1 o Hipocalórico; sin selección explícita no existe ración.
- Administrativos: solo Almuerzo y puede escoger cualquiera de las opciones disponibles del día; sin selección no existe ración.
- Reservas internas ALEMSI siguen sin cobro y suman exclusivamente las selecciones válidas a Producción.
- Cocina muestra listado nominal del personal ALEMSI reservado, con grupo, servicio y plato.
- Inicio de Producción queda protegido contra doble ejecución y descuenta Bodega una sola vez según recetas disponibles.
- Si un plato no tiene receta, Producción no se bloquea: se registra y se advierte que no hubo descuento automático para ese plato.
- Si falta stock, la jornada queda registrada y se informa el faltante para ajuste operativo.
- Coordinadores: consumo valorizado para control financiero, sin cobro; conserva correo de reserva.
- AdminTotal > Actividad muestra fecha y hora completa con segundos.
- Coordinación mantiene panel privado y agrega vista de sus días observados/pendientes; no edita Minuta oficial.
- Bodega reutiliza el mismo módulo administrativo de Minutas, evitando una pantalla paralela.
- Correo de transferencia reorganiza datos en líneas independientes y bloque listo para copiar/pegar.
- AdminTotal > Usuarios agrega notificación masiva de acceso sin modificar contraseñas.
- Depuración de producción exige respaldo generado en la sesión y conserva Minutas/maestros.
- Respaldo lógico incluye revisión de Coordinación y datos transaccionales adicionales.
- Compras/OCR/Costos de Cocina permanecen fuera de esta candidata; se activarán junto al módulo completo de Bodega.

# v2.1.3.34 CANDIDATA DEMO COORDINACION

- Nuevo rol Coordinacion por login principal.
- Panel privado: ver, aprobar, observar y proponer cambios de minuta sin editar la minuta oficial.
- Trazabilidad de revisiones de Coordinacion.
- Revision preventiva orientativa de repeticiones de proteina y preparaciones humedas/caldo.
- Editor de minuta por fecha ahora muestra la minuta existente y precarga el plato actual por servicio/opcion.
- Maestro de Platos se consolida desde minutas historicas sin borrar platos ni alterar costos existentes.
- Nuevos platos escritos desde el editor se agregan al maestro con valor 0 para posterior parametrizacion.
- Mantiene reglas protegidas de Reserva, Finanzas, Produccion y Bodega de v33.

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

## v2.1.3.39 — Cierre funcional para revisión
- AdminCasino recupera módulos operativos base: Dashboard, Reportes, Reservas, Bodega, Minutas, Satisfacción, Excepciones e Instituciones.
- Bienvenida estandarizada por perfil.
- Reportes: conciliación de comensales/estado de pago, histórico de pagados y ranking de platos.
- Coordinación queda identificada como propuesta de etapa posterior y no como rol habilitable en esta entrega.
- Se mantiene la arquitectura de Bodega/Inventario como expansión posterior; no se presenta como alcance operativo cerrado.
