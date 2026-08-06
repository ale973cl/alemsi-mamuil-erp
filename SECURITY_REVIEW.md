# Revisión de seguridad preliminar

Esta versión es adecuada para una demo controlada, pero no debe considerarse todavía lista para producción con datos personales reales.

Pendientes prioritarios:
1. Reemplazar SHA-256 simple por Argon2id o bcrypt con sal.
2. Eliminar credenciales por defecto del código.
3. Incorporar autenticación fuerte para personal interno y administración.
4. Limitar intentos de login y registrar accesos.
5. Revisar permisos de base de datos con principio de mínimo privilegio.
6. Evitar mostrar excepciones técnicas o credenciales en pantalla.
7. Definir política de retención, respaldo y eliminación de datos personales.
8. Agregar auditoría de consultas y modificaciones.
