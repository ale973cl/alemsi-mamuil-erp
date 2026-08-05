# Mamuil Malal ERP v1.0.1

Demo desplegable en GitHub + Streamlit Community Cloud + Supabase PostgreSQL.

## Archivos principales
- `streamlit_app.py`: punto de entrada oficial.
- `common.py`: conexión, esquema, utilidades y correo.
- `app.py`: copia sincronizada de respaldo.
- `PROJECT_RULES.md`: reglas permanentes del proyecto.

## Secrets de Streamlit

```toml
[connections.postgresql]
dialect = "postgresql"
host = "aws-0-sa-east-1.pooler.supabase.com"
port = 5432
database = "postgres"
username = "postgres.tksrtwpyfaebmkgcdjiq"
password = "CONTRASENA_DE_LA_BASE"

[email]
smtp_server = "smtp.gmail.com"
smtp_port = 587
email_user = "correo@gmail.com"
email_pass = "CLAVE_DE_APLICACION"
```

La sección `[email]` puede omitirse durante las primeras pruebas; las reservas se guardarán, pero el correo no se enviará.

## Despliegue
1. Reemplazar en GitHub los archivos de la raíz con los de este paquete.
2. Configurar `streamlit_app.py` como Main file path.
3. Guardar los Secrets.
4. Reiniciar la aplicación.

## Corrección principal de v1.0.1
Todas las lecturas parametrizadas con `conn.query()` utilizan marcadores nombrados compatibles con pandas y SQLAlchemy 2.x. Las escrituras utilizan `execute_sql()`.


## Minuta oficial de agosto 2026
El archivo `minuta_agosto_2026.csv` contiene 168 alternativas extraídas de la minuta ALEMSI: almuerzo y cena, cada uno con Opción 1, Opción 2 e Hipocalórico, para el 1 al 28 de agosto de 2026. La carga es automática e idempotente al iniciar la aplicación.

## Correos demo
- Reservas: comprobante al correo registrado del comensal y copia/notificación a Cocina.
- Reclamos, sugerencias y felicitaciones: `ale973@gmail.com` y `araucaniashop@gmail.com`.
- El envío requiere la sección `[email]` en Streamlit Secrets con una clave de aplicación de Gmail.
