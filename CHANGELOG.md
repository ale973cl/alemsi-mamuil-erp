# CHANGELOG v2.1.3.10 — AUTH + PAGOS · PRUEBA

- Eliminados usuarios y contraseñas predeterminados del código.
- init_db ya no crea, reactiva ni sobrescribe cuentas.
- Bootstrap seguro del primer Administrador Total mediante Streamlit Secrets.
- Gestión de usuarios exclusiva de Admin Total.
- Crear usuario y editar usuario separados.
- Rol, estado y permisos se guardan en una sola operación.
- Comprobantes asociados a referencia de reserva + RUT + token.
- Validación de comprobantes registra responsable, fecha y observación.
- Hotfix Cocina ON CONFLICT(fecha,servicio,tipo_opcion,plato) preservado.

Estado: CANDIDATA DE PRUEBA. No declarar estable hasta validar rutas admin/gerencia/finanzas/cocina.
