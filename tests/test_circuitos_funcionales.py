"""Smoke tests transaccionales sobre una base efímera; nunca usan producción."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from workflow_service import (
    crear_envio_minuta, finalizar_revision, guardar_revision_item, procesar_correo, registrar_opinion, solicitar_excepcion_cancelacion, resolver_excepcion_cancelacion,
)


def db():
    engine=create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as c:
        for ddl in [
            "CREATE TABLE minuta_flujo_coordinacion(id INTEGER PRIMARY KEY,fecha_desde TEXT,fecha_hasta TEXT,version INTEGER,estado TEXT,observacion TEXT,enviado_por TEXT,enviado_at TEXT,coordinador TEXT,coordinacion_at TEXT,activo INTEGER)",
            "CREATE TABLE minuta_revision_coordinacion(id INTEGER PRIMARY KEY AUTOINCREMENT,flujo_id INTEGER,fecha TEXT,servicio TEXT,tipo_opcion TEXT,plato_actual TEXT,accion TEXT,observacion TEXT,usuario TEXT,fecha_accion TEXT,estado TEXT,UNIQUE(flujo_id,fecha,servicio,tipo_opcion))",
            "CREATE TABLE notificaciones_internas(id INTEGER PRIMARY KEY AUTOINCREMENT,evento TEXT,rol_destino TEXT,usuario_destino TEXT,titulo TEXT,mensaje TEXT,entidad TEXT,entidad_id TEXT,creado_por TEXT,creado_at TEXT,leido_at TEXT,estado TEXT)",
            "CREATE TABLE correo_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,evento TEXT,destino TEXT,asunto TEXT,cuerpo_html TEXT,entidad TEXT,entidad_id TEXT,estado TEXT,intentos INTEGER,creado_at TEXT,ultimo_intento_at TEXT,enviado_at TEXT,error TEXT)",
            "CREATE TABLE opiniones_experiencia(id INTEGER PRIMARY KEY AUTOINCREMENT,tipo TEXT,fecha TEXT,identificacion TEXT,servicio TEXT,comentario TEXT,evidencia_nombre TEXT,evidencia BLOB,responsable TEXT,estado TEXT,resolucion TEXT,creado_por TEXT,creado_at TEXT,cerrado_por TEXT,cerrado_at TEXT)",
            "CREATE TABLE solicitudes_excepcion_cancelacion(id INTEGER PRIMARY KEY AUTOINCREMENT,referencia_reserva TEXT,rut TEXT,fecha TEXT,servicio TEXT,motivo TEXT,estado TEXT,solicitado_at TEXT,resuelto_por TEXT,resuelto_at TEXT,resolucion TEXT,impacto_economico INTEGER)",
            "CREATE TABLE solicitudes(id INTEGER PRIMARY KEY,referencia_reserva TEXT,rut TEXT,fecha TEXT,servicio TEXT,estado_reserva TEXT,fecha_modificacion TEXT,modificado_por TEXT)",
        ]: c.execute(text(ddl))
        c.execute(text("INSERT INTO solicitudes VALUES (1,'MM-1','1-9','2026-08-21','Almuerzo','ACTIVA',NULL,NULL)"))
        c.execute(text("INSERT INTO minuta_flujo_coordinacion VALUES (1,'2026-08-21','2026-08-27',1,'EN_REVISION','', 'admin','ahora',NULL,NULL,1)"))
    return engine


def scalar(session, sql):
    return session.execute(text(sql)).scalar()


def test_minuta_observada_crea_detalle_y_notificacion_admin():
    e=db()
    with Session(e) as s:
        guardar_revision_item(s,flujo_id=1,fecha='2026-08-21',servicio='Almuerzo',opcion='OPCION 1',plato='Cazuela',decision='OBSERVADO',comentario='Falta guarnición',usuario='coord')
        estado,correo=finalizar_revision(s,flujo_id=1,usuario='coord',admin_email='admin@example.test'); s.commit()
        assert estado=='OBSERVADA' and correo
        assert scalar(s,"SELECT estado FROM minuta_flujo_coordinacion WHERE id=1")=='OBSERVADA'
        assert scalar(s,"SELECT observacion FROM minuta_revision_coordinacion")=='Falta guarnición'
        assert scalar(s,"SELECT evento FROM notificaciones_internas")=='MINUTA_OBSERVADA'


def test_autorizacion_y_fallo_smtp_no_revierte_negocio():
    e=db()
    with Session(e) as s:
        guardar_revision_item(s,flujo_id=1,fecha='2026-08-21',servicio='Cena',opcion='OPCION 1',plato='Sopa',decision='CONFORME',comentario='',usuario='coord')
        estado,correo=finalizar_revision(s,flujo_id=1,usuario='coord',admin_email='admin@example.test'); s.commit()
        assert estado=='AUTORIZADA'
        ok,_=procesar_correo(s,correo,lambda *_:(False,'SMTP fuera de servicio')); s.commit()
        assert not ok
        assert scalar(s,"SELECT estado FROM minuta_flujo_coordinacion")=='AUTORIZADA'
        assert scalar(s,"SELECT estado FROM correo_outbox")=='ERROR'
        assert scalar(s,"SELECT evento FROM notificaciones_internas")=='MINUTA_AUTORIZADA'


def test_opiniones_persisten_con_tratamiento_diferenciado():
    e=db()
    with Session(e) as s:
        esperados={'Reclamo':'RECIBIDO','Sugerencia':'EN_REVISION','Felicitación':'REGISTRADA'}
        for tipo,estado in esperados.items():
            _,actual=registrar_opinion(s,tipo=tipo,fecha='2026-08-20',identificacion='RUT',servicio='Almuerzo',comentario='Detalle',usuario='persona')
            assert actual==estado
        s.commit()
        filas=s.execute(text('SELECT tipo,estado FROM opiniones_experiencia ORDER BY id')).all()
        assert filas==[('RECLAMO','RECIBIDO'),('SUGERENCIA','EN_REVISION'),('FELICITACIÓN','REGISTRADA')]


def test_reenvio_crea_version_dos_y_notifica_coordinador():
    e=db()
    with Session(e) as s:
        flujo,version,_=crear_envio_minuta(s,fecha_desde='2026-08-21',fecha_hasta='2026-08-27',usuario='admin')
        s.commit()
        assert flujo==2 and version==2
        assert scalar(s,"SELECT estado FROM minuta_flujo_coordinacion WHERE id=2")=='EN_REVISION'
        assert scalar(s,"SELECT evento FROM notificaciones_internas")=='MINUTA_REENVIADA'


def test_excepcion_aprobada_cancela_servicio_y_notifica_finanzas():
    e=db()
    with Session(e) as s:
        solicitud=solicitar_excepcion_cancelacion(s,referencia='MM-1',rut='1-9',fecha='2026-08-21',servicio='Almuerzo',motivo='Fuerza mayor',usuario='1-9')
        estado=resolver_excepcion_cancelacion(s,solicitud_id=solicitud,aprobar=True,resolucion='Acreditada',usuario='admin',finanzas_email='fin@example.test')
        s.commit()
        assert estado=='APROBADA'
        assert scalar(s,"SELECT estado_reserva FROM solicitudes")=='CANCELADA_EXCEPCION'
        assert scalar(s,"SELECT COUNT(*) FROM notificaciones_internas WHERE rol_destino='Finanzas'")==1
