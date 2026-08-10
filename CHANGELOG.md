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
