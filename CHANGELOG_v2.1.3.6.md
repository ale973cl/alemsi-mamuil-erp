# ALEMSI v2.1.3.6 — cierre Reserva/Comprobante

Base: v2.1.3.5 candidato usuarios + hotfix Cocina.

## Cambios incrementales
- Conservado hotfix de jornada: conflicto por fecha + servicio + tipo_opcion + plato.
- Correo de reserva con detalle tabulado por día (Día/Fecha, Servicio/Plato).
- PDF de reserva adjunto con tablas corporativas ALEMSI.
- Token personal por reserva y enlace de carga de comprobante.
- Portal público de carga PDF/JPG/PNG hasta 10 MB.
- Comprobante almacenado en PostgreSQL y estado "Comprobante recibido".
- Finanzas puede descargar el comprobante y luego validar/observar/pagar.
- El pago sigue sin ser condición previa al consumo.
- Nueva dependencia: reportlab.

## Configuración requerida
En Streamlit Secrets agregar:
[app]
public_url = "https://TU-APP.streamlit.app"

No incluir / al final. El sistema genera /?pago_token=... automáticamente.
