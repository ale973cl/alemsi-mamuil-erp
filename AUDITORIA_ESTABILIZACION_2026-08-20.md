# Auditoría de estabilización — 20-08-2026

## Entrada y alcance

- El entrypoint desplegable oficial es `streamlit_app.py`, según `PROJECT_RULES.md`.
- `streamlit_app (4).py` es una copia histórica y `streamlit_app_hotfix.py` un cargador de compatibilidad; ninguno debe configurarse como entrypoint.
- `streamlit_startup_test.py` es un diagnóstico de solo lectura.
- `recordatorio_pago_17.py` y `jobs/recordatorio_pago_17.py` son tareas programadas, no aplicaciones web.

## Mapa operativo verificado

`streamlit_app.py` concentra autenticación y portales Comensal, Coordinación, Cocina, Bodega, Finanzas, Gerencia y Administración. `common.py` concentra conexión, SQL compatible con SQLAlchemy, reglas de RUT/reserva, correo e inicialización del esquema. Las tablas `solicitudes`, `comprobantes_pago`, `minutas`, `minuta_revision_coordinacion`, `minuta_flujo_coordinacion`, `jornadas_produccion`, `jornada_detalle`, `bodega_inventario`, `reclamos_sugerencias`, `encuestas_satisfaccion` y `auditoria_acciones` sostienen los circuitos principales.

## Hallazgos y decisión incremental

1. Había `CREATE TABLE IF NOT EXISTS` ejecutado al abrir pantallas de Minutas, Coordinación y Gerencia. Las estructuras se trasladaron al inicializador versionado; las funciones históricas quedan como no-op de compatibilidad.
2. El inicializador completo ejecutaba normalizaciones e índices para cada proceso nuevo. Una marca en `migraciones_app` permite una comprobación ligera y conserva el fallback completo si la instalación está incompleta.
3. `referencia_reserva` se conserva sin alterar claves ni históricos; la interfaz la presenta como **Código de reserva**.
4. No se modificó Bodega, la escritura transaccional de reservas, la validación financiera, Producción ni los permisos.

## Límites de esta candidata

Las verificaciones automatizadas de este cambio son estáticas y unitarias sin datos productivos. La certificación de SMTP, Supabase, navegación completa por roles y circuitos integrados requiere un entorno de QA con secretos y una base PostgreSQL aislada; no debe ejecutarse contra datos productivos para simular escrituras.
