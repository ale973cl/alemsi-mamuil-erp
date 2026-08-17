# QA Coordinación + Correos v40

## Conectado al servicio existente
- Reutiliza `enviar_email()` y `get_correos()`.
- Envía aviso a Coordinación al enviar/re-enviar una minuta.
- Envía aviso a AdminCasino al OBSERVAR o AUTORIZAR.
- Envía confirmación a Coordinación cuando AdminCasino publica.
- Combina destinatarios configurados + correos de usuarios activos del rol.
- AdminTotal → Correos ahora permite `admin_casino` y `coordinacion`.
- Fallo SMTP no revierte estados ni decisiones; queda auditado.

## Validado estáticamente
- streamlit_app.py compila correctamente.

## Pendiente prueba real
- SMTP/Secrets configurados.
- Usuario Coordinación con correo válido.
- AdminCasino con correo válido o destinatario configurado.
