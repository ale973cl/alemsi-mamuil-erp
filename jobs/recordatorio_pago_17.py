"""PAY-REM-01: recordatorio de pago del último día de una referencia_reserva."""
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg2
from psycopg2.extras import RealDictCursor

APP_URL = os.environ.get(
    "ALEMSI_APP_URL",
    "https://alemsi-mamuil-erp.streamlit.app",
).rstrip("/")


def enviar(destino, asunto, html):
    host = os.environ["ALEMSI_SMTP_SERVER"]
    port = int(os.environ.get("ALEMSI_SMTP_PORT", "587"))
    user = os.environ["ALEMSI_SMTP_USER"]
    password = os.environ["ALEMSI_SMTP_PASS"]
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = destino
    msg["Subject"] = asunto
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def main():
    conn = psycopg2.connect(
        os.environ["ALEMSI_DATABASE_URL"],
        cursor_factory=RealDictCursor,
    )
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.referencia_reserva,
            MAX(s.pago_token) AS pago_token,
            MAX(s.correo) AS correo,
            MAX(c.nombre) AS nombre,
            MAX(s.fecha) AS fecha_fin,
            MAX(s.estado_pago) AS estado_pago,
            MAX(cp.estado) AS estado_comprobante
        FROM solicitudes s
        LEFT JOIN comensales c ON c.rut=s.rut
        LEFT JOIN comprobantes_pago cp
          ON cp.referencia_reserva=s.referencia_reserva
        WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
          AND COALESCE(NULLIF(s.referencia_reserva,''),'') <> ''
        GROUP BY s.referencia_reserva
        HAVING MAX(s.fecha)=%s
        """,
        (date.today().isoformat(),),
    )
    for reserva in cur.fetchall():
        if str(reserva["estado_pago"] or "").casefold() == "pagado":
            continue
        correo = str(reserva["correo"] or "").strip()
        token = str(reserva["pago_token"] or "").strip()
        if not correo or not token:
            continue
        comprobante_en_revision = str(
            reserva["estado_comprobante"] or ""
        ).upper() in {"RECIBIDO", "OBSERVADO"}
        if comprobante_en_revision:
            nota = (
                "Si ya cargó su comprobante, puede omitir este recordatorio "
                "mientras Finanzas realiza la revisión."
            )
        else:
            nota = (
                "Puede cargar su comprobante de transferencia o voucher "
                "de débito mediante el siguiente enlace."
            )
        link = f"{APP_URL}/?pago_token={token}"
        html = (
            "<div style='font-family:Arial,sans-serif;max-width:680px'>"
            "<h2>Recordatorio de pago · ALEMSI Mamuil Malal</h2>"
            f"<p>Estimado/a {reserva['nombre'] or ''}, su último día de servicio "
            f"de la reserva <b>{reserva['referencia_reserva']}</b> finaliza hoy.</p>"
            f"<p>{nota}</p>"
            f"<p><a href='{link}'>Cargar comprobante de pago</a></p>"
            "</div>"
        )
        enviar(correo, "Recordatorio de pago · ALEMSI Mamuil Malal", html)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
