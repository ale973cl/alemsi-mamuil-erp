# Mamuil Malal ERP v2.0.0

Versión optimizada para GitHub, Streamlit Community Cloud y Supabase PostgreSQL.

## Flujo de reserva
1. Seleccionar varios días en un único formulario.
2. Elegir menús de todos los días mediante listas desplegables por servicio.
3. Revisar el resumen.
4. Confirmar: se guarda toda la reserva en una transacción.
5. Solo después del commit se genera el comprobante y se envían los correos.

## Archivos de despliegue
Subir a la raíz: `streamlit_app.py`, `app.py`, `common.py`, `requirements.txt`, `minuta_agosto_2026.csv`, `README.md`, `PROJECT_RULES.md`, `CHANGELOG.md` y `.gitignore`.

Los Secrets de Streamlit se mantienen sin cambios.
