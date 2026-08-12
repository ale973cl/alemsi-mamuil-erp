# v2.1.3.30_PERMISOS_RENDIMIENTO

- Base protegida: v2.1.3.29_CALENDARIO_MOVIL.
- PERM-30: permisos por usuario editables por AdminTotal conservando el rol como plantilla inicial.
- PERF-30: caché de permisos por sesión + consulta cacheada TTL 60 s para reducir reruns/SQL repetido.
- PERF-30: se conservan cachés de minutas/instituciones de 300 s existentes en common.py.
- FIN-30: Finanzas incorpora una vista Dashboard reutilizando el dashboard financiero existente.
- COMMON-30: helper `es_personal_alemsi()` centraliza la identificación de perfiles internos sin cambiar rutas.
- CAL-MOVIL-01: se conserva íntegramente calendario móvil Lun-Dom de 7 columnas, botones compactos y lógica de selección.
- No se modifica Reserva -> PostgreSQL -> comprobante -> correo.
