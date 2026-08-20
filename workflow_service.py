"""Servicios persistentes para circuitos entre perfiles.

No depende de Streamlit: cada operación recibe una sesión SQLAlchemy y confirma
primero el estado de negocio junto con notificación/outbox. El envío SMTP se
procesa después y nunca participa de la transacción de negocio.
"""
from datetime import datetime
from html import escape

from common import execute_sql


def _ahora():
    return datetime.now().isoformat()


def asunto_evento(evento, objeto):
    return f"ALEMSI | {evento} | {objeto} | Mamuil Malal"


def crear_notificacion(session, *, evento, rol_destino, titulo, mensaje, entidad="", entidad_id="", usuario="", email_destino=""):
    ahora = _ahora()
    notificacion_id = execute_sql(session, """
        INSERT INTO notificaciones_internas
        (evento,rol_destino,titulo,mensaje,entidad,entidad_id,creado_por,creado_at,estado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDIENTE') RETURNING id
    """, (evento,rol_destino,titulo,mensaje,entidad,str(entidad_id),usuario,ahora)).first()[0]
    correo_id = None
    if str(email_destino or '').strip():
        correo_id = execute_sql(session, """
            INSERT INTO correo_outbox
            (evento,destino,asunto,cuerpo_html,entidad,entidad_id,estado,intentos,creado_at)
            VALUES (%s,%s,%s,%s,%s,%s,'PENDIENTE',0,%s) RETURNING id
        """, (evento,email_destino,asunto_evento(evento, entidad_id),
              f"<h2>{escape(titulo)}</h2><p>{escape(mensaje)}</p>",entidad,str(entidad_id),ahora)).first()[0]
    return int(notificacion_id), int(correo_id) if correo_id else None


def procesar_correo(session, correo_id, sender):
    """Intenta un correo ya persistido; el fallo sólo actualiza el outbox."""
    row = execute_sql(session, "SELECT destino,asunto,cuerpo_html FROM correo_outbox WHERE id=%s", (correo_id,)).first()
    if not row:
        return False, "Correo inexistente"
    try:
        ok, detalle = sender(row[0], row[1], row[2])
    except Exception as exc:
        ok, detalle = False, str(exc)
    execute_sql(session, """
        UPDATE correo_outbox SET estado=%s,intentos=COALESCE(intentos,0)+1,
        ultimo_intento_at=%s,error=%s,enviado_at=%s WHERE id=%s
    """, ('ENVIADO' if ok else 'ERROR', _ahora(), '' if ok else str(detalle)[:1000], _ahora() if ok else None, correo_id))
    return bool(ok), str(detalle)


def guardar_revision_item(session, *, flujo_id, fecha, servicio, opcion, plato, decision, comentario, usuario):
    decision = str(decision).upper()
    if decision not in {'CONFORME', 'OBSERVADO'}:
        raise ValueError('Decisión inválida')
    if decision == 'OBSERVADO' and not str(comentario or '').strip():
        raise ValueError('La observación requiere comentario')
    execute_sql(session, """
        INSERT INTO minuta_revision_coordinacion
        (flujo_id,fecha,servicio,tipo_opcion,plato_actual,accion,observacion,usuario,fecha_accion,estado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'VIGENTE')
        ON CONFLICT (flujo_id,fecha,servicio,tipo_opcion) DO UPDATE SET
        plato_actual=EXCLUDED.plato_actual,accion=EXCLUDED.accion,
        observacion=EXCLUDED.observacion,usuario=EXCLUDED.usuario,
        fecha_accion=EXCLUDED.fecha_accion,estado='VIGENTE'
    """, (flujo_id,fecha,servicio,opcion,plato,decision,str(comentario or '').strip(),usuario,_ahora()))


def crear_envio_minuta(session, *, fecha_desde, fecha_hasta, usuario, coordinacion_email=""):
    """Crea una versión inmutable nueva y entrega trabajo al Coordinador."""
    anterior = execute_sql(session, """
        SELECT COALESCE(MAX(version),0) FROM minuta_flujo_coordinacion
        WHERE fecha_desde=%s AND fecha_hasta=%s
    """, (fecha_desde,fecha_hasta)).first()
    version = int(anterior[0] or 0)+1
    flujo_id = execute_sql(session, """
        INSERT INTO minuta_flujo_coordinacion
        (fecha_desde,fecha_hasta,version,estado,observacion,enviado_por,enviado_at,activo)
        VALUES (%s,%s,%s,'EN_REVISION','',%s,%s,1) RETURNING id
    """, (fecha_desde,fecha_hasta,version,usuario,_ahora())).first()[0]
    evento = 'MINUTA_ENVIADA_COORDINADOR' if version==1 else 'MINUTA_REENVIADA'
    _,correo_id = crear_notificacion(session,evento=evento,rol_destino='Coordinacion',
        titulo='Minuta enviada para revisión' if version==1 else 'Minuta corregida y reenviada',
        mensaje=f'Período {fecha_desde} a {fecha_hasta}; versión {version}.',
        entidad='minuta_flujo_coordinacion',entidad_id=flujo_id,usuario=usuario,
        email_destino=coordinacion_email)
    return int(flujo_id),version,correo_id


def finalizar_revision(session, *, flujo_id, usuario, admin_email=""):
    conteo = execute_sql(session, """
        SELECT COUNT(*) FILTER (WHERE accion='OBSERVADO') AS observadas,
               COUNT(*) AS revisadas FROM minuta_revision_coordinacion
        WHERE flujo_id=%s AND estado='VIGENTE'
    """, (flujo_id,)).first()
    observadas, revisadas = int(conteo[0] or 0), int(conteo[1] or 0)
    if revisadas == 0:
        raise ValueError('No hay opciones revisadas')
    estado = 'OBSERVADA' if observadas else 'AUTORIZADA'
    flujo = execute_sql(session, """
        UPDATE minuta_flujo_coordinacion SET estado=%s,coordinador=%s,coordinacion_at=%s
        WHERE id=%s AND estado='EN_REVISION'
        RETURNING fecha_desde,fecha_hasta,version
    """, (estado,usuario,_ahora(),flujo_id)).first()
    if not flujo:
        raise ValueError('La minuta ya no está en revisión')
    periodo = f"{flujo[0]}..{flujo[1]} v{flujo[2]}"
    evento = 'MINUTA_OBSERVADA' if observadas else 'MINUTA_AUTORIZADA'
    _, correo_id = crear_notificacion(session, evento=evento, rol_destino='AdminCasino',
        titulo='Minuta observada por Coordinador' if observadas else 'Minuta autorizada por Coordinador',
        mensaje=f'{periodo}; {observadas} observación(es), {revisadas} opción(es) revisadas.',
        entidad='minuta_flujo_coordinacion', entidad_id=flujo_id, usuario=usuario,email_destino=admin_email)
    return estado, correo_id


def registrar_opinion(session, *, tipo, fecha, identificacion, servicio, comentario, usuario="", responsable="", email_destino=""):
    tipo = str(tipo).strip().upper()
    if tipo not in {'RECLAMO','SUGERENCIA','FELICITACIÓN'}:
        raise ValueError('Tipo de opinión inválido')
    if not str(comentario or '').strip():
        raise ValueError('El comentario es obligatorio')
    estado = {'RECLAMO':'RECIBIDO','SUGERENCIA':'EN_REVISION','FELICITACIÓN':'REGISTRADA'}[tipo]
    opinion_id = execute_sql(session, """
        INSERT INTO opiniones_experiencia
        (tipo,fecha,identificacion,servicio,comentario,responsable,estado,creado_por,creado_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (tipo,str(fecha),identificacion,servicio,comentario,responsable,estado,usuario,_ahora())).first()[0]
    crear_notificacion(session, evento='RECLAMO_RECIBIDO' if tipo=='RECLAMO' else f'OPINION_{tipo}',
        rol_destino='AdminCasino',titulo=f'{tipo.title()} recibida',mensaje=str(comentario),
        entidad='opiniones_experiencia',entidad_id=opinion_id,usuario=usuario,
        email_destino=email_destino if tipo=='RECLAMO' else '')
    return int(opinion_id), estado


def solicitar_excepcion_cancelacion(session, *, referencia, rut, fecha, servicio, motivo, usuario=""):
    if not str(motivo or '').strip():
        raise ValueError('El motivo es obligatorio')
    solicitud_id=execute_sql(session,"""INSERT INTO solicitudes_excepcion_cancelacion
        (referencia_reserva,rut,fecha,servicio,motivo,estado,solicitado_at)
        VALUES (%s,%s,%s,%s,%s,'PENDIENTE',%s) RETURNING id""",
        (referencia,rut,fecha,servicio,motivo,_ahora())).first()[0]
    crear_notificacion(session,evento='EXCEPCION_SOLICITADA',rol_destino='AdminCasino',
        titulo='Solicitud de excepción de cancelación',mensaje=f'{referencia} · {fecha} · {servicio}',
        entidad='solicitudes_excepcion_cancelacion',entidad_id=solicitud_id,usuario=usuario or rut)
    return int(solicitud_id)


def resolver_excepcion_cancelacion(session, *, solicitud_id, aprobar, resolucion, usuario, finanzas_email=""):
    estado='APROBADA' if aprobar else 'RECHAZADA'
    fila=execute_sql(session,"""UPDATE solicitudes_excepcion_cancelacion SET estado=%s,
        resuelto_por=%s,resuelto_at=%s,resolucion=%s,impacto_economico=%s
        WHERE id=%s AND estado='PENDIENTE' RETURNING referencia_reserva,rut,fecha,servicio""",
        (estado,usuario,_ahora(),resolucion,1 if aprobar else 0,solicitud_id)).first()
    if not fila:
        raise ValueError('La solicitud ya fue resuelta o no existe')
    if aprobar:
        execute_sql(session,"""UPDATE solicitudes SET estado_reserva='CANCELADA_EXCEPCION',
            fecha_modificacion=%s,modificado_por=%s WHERE referencia_reserva=%s AND rut=%s
            AND fecha=%s AND servicio=%s AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA'""",
            (_ahora(),usuario,fila[0],fila[1],fila[2],fila[3]))
        crear_notificacion(session,evento='EXCEPCION_APROBADA',rol_destino='Finanzas',
            titulo='Excepción aprobada con impacto económico',mensaje=f'{fila[0]} · {fila[2]} · {fila[3]}',
            entidad='solicitudes_excepcion_cancelacion',entidad_id=solicitud_id,usuario=usuario,
            email_destino=finanzas_email)
    return estado
