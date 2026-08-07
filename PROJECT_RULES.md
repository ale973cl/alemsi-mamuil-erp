# Reglas del proyecto Mamuil Malal ERP

## Entorno objetivo
- Repositorio: GitHub.
- Aplicación: Streamlit Community Cloud.
- Base de datos: PostgreSQL alojado en Supabase.
- Acceso a datos: `st.connection("postgresql", type="sql")` y SQLAlchemy 2.x.
- Correo: SMTP configurado exclusivamente mediante `st.secrets`.

## Reglas de desarrollo
1. Mantener la funcionalidad existente antes de agregar mejoras.
2. Aplicar cambios incrementales y documentados; no reescribir el sistema completo.
3. `streamlit_app.py` es el punto de entrada oficial.
4. `app.py` debe mantenerse sincronizado con `streamlit_app.py` mientras exista.
5. Las consultas mediante `conn.query()` deben usar parámetros nombrados:
   `WHERE campo=:campo`, `params={"campo": valor}`.
6. Las escrituras dentro de `conn.session` deben ejecutarse mediante `execute_sql()` o `sqlalchemy.text()`.
7. No guardar contraseñas, claves de Supabase ni claves SMTP en GitHub.
8. Toda modificación de esquema debe ser idempotente y compatible con bases ya creadas.
9. Antes de publicar, ejecutar validación de sintaxis y buscar consultas incompatibles.
10. Conservar compatibilidad con GitHub, Streamlit Cloud y Supabase.

## Módulos funcionales que deben preservarse
- Registro y acceso de comensales.
- Reservas y minutas.
- Cocina y bodega.
- Finanzas y administración.
- Instituciones y excepciones de precios.
- Reportes, reclamos y correo electrónico.


## Ancla permanente de recuperación
- Toda versión nueva parte de la última versión aprobada.
- Las mejoras deben ser incrementales y reversibles.
- No reescribir módulos completos cuando baste un cambio localizado.
- El circuito `Reserva -> PostgreSQL -> comprobante -> correo` es zona protegida.
- Cocina, Bodega, Finanzas y Administración no deben impedir el circuito de reservas si presentan un error secundario.
- No activar integraciones futuras (Google Sheets, descuento automático de bodega u otras) sin configuración y aprobación explícitas.
- Una versión solo pasa de CANDIDATA a APROBADA después de prueba real; compilar no equivale a probar producción.
