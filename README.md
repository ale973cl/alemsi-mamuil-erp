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
