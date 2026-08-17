# ALEMSI v2.1.3.40_CIERRE_ARQUITECTURA - cierre funcional, permisos y conciliación
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date, timedelta, datetime
import calendar
from html import escape
import json
import secrets
from sqlalchemy import text
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT, execute_sql, get_minutas_rango, get_correos, limpiar_cache_correos, gen_referencia_reserva, reserva_modificable, normalizar_correo, validar_correo_estructura, dominio_correo_resuelve, normalizar_telefono_chile, telefono_movil_chile_valido

# ================================================================
# ANCLA DE CAMBIO SEGURO
# Esta versión solo admite mejoras incrementales. No reescribir ni
# reemplazar el circuito Reserva -> PostgreSQL -> comprobante -> correo
# salvo corrección explícita, documentada y con prueba de regresión.
# ================================================================

def _url_carga_comprobante(token):
    """URL pública del portal de comprobantes.
    Se prioriza Secrets y se usa la URL productiva conocida como respaldo.
    """
    try:
        base = str(st.secrets.get("app", {}).get("public_url", "")).strip().rstrip("/")
    except Exception:
        base = ""
    if not base:
        base = "https://alemsi-mamuil-erp.streamlit.app"
    return f"{base}/?pago_token={token}"


@st.cache_data(ttl=120, show_spinner=False)
def get_config_bancaria():
    try:
        conn = get_conn()
        df = conn.query(
            "SELECT titular,rut,banco,tipo_cuenta,numero_cuenta,correo_comprobantes,activo "
            "FROM configuracion_bancaria WHERE id=1 AND COALESCE(activo,1)=1",
            ttl=120,
        )
        if not df.empty:
            return {k: str(df.iloc[0].get(k) or "").strip() for k in [
                "titular","rut","banco","tipo_cuenta","numero_cuenta","correo_comprobantes"
            ]}
    except Exception:
        pass
    return {}


def limpiar_cache_banco():
    get_config_bancaria.clear()


def _drive_service():
    """Cliente privado de Google Drive. Las credenciales viven en Streamlit Secrets."""
    cfg = st.secrets.get("gcp_service_account", {})
    if not cfg:
        return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        dict(cfg), scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive_get_or_create_folder(service, parent_id, nombre):
    safe = str(nombre).replace("'", "\\'")
    q = (
        f"'{parent_id}' in parents and name='{safe}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    r = service.files().list(q=q, spaces="drive", fields="files(id,name)", pageSize=10).execute()
    files = r.get("files", [])
    if files:
        return files[0]["id"]
    body = {"name": nombre, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    return service.files().create(body=body, fields="id").execute()["id"]


def subir_comprobante_drive(nombre_original, mime_type, contenido, referencia):
    """Guarda el archivo sin usar RUT en nombres ni carpetas.
    Estructura: raíz configurada / año / mes / referencia.
    """
    try:
        cfg = st.secrets.get("comprobantes", {})
        raiz = str(cfg.get("folder_id", "")).strip()
        service = _drive_service()
        if not raiz or service is None:
            return False, None, None, "Google Drive de comprobantes no está configurado."

        hoy = datetime.now()
        folder_ano = _drive_get_or_create_folder(service, raiz, str(hoy.year))
        folder_mes = _drive_get_or_create_folder(service, folder_ano, f"{hoy.month:02d}")
        folder_ref = _drive_get_or_create_folder(service, folder_mes, str(referencia))

        ext = Path(nombre_original).suffix.lower()
        nombre_drive = f"COMPROBANTE_{referencia}_{hoy.strftime('%Y%m%d_%H%M%S')}{ext}"

        from googleapiclient.http import MediaIoBaseUpload
        media = MediaIoBaseUpload(BytesIO(contenido), mimetype=mime_type or "application/octet-stream", resumable=False)
        body = {"name": nombre_drive, "parents": [folder_ref]}
        creado = service.files().create(
            body=body, media_body=media, fields="id,name,webViewLink"
        ).execute()
        return True, creado.get("id"), creado.get("webViewLink"), creado.get("name")
    except Exception as exc:
        return False, None, None, str(exc)


def descargar_comprobante_drive(file_id):
    service = _drive_service()
    if service is None or not file_id:
        return None
    try:
        from googleapiclient.http import MediaIoBaseDownload
        salida = BytesIO()
        request = service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(salida, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return salida.getvalue()
    except Exception:
        return None


def _obtener_bytes_comprobante(conn, comprobante):
    """FIN-09: obtiene el archivo real desde Drive o PostgreSQL."""
    if comprobante is None:
        return None
    try:
        drive_id = str(comprobante.get("drive_file_id") or "").strip()
    except Exception:
        drive_id = ""
    if drive_id and "descargar_comprobante_drive" in globals():
        archivo = descargar_comprobante_drive(drive_id)
        if archivo:
            return archivo
    try:
        comprobante_id = int(comprobante.get("id"))
    except Exception:
        return None
    try:
        with conn.session as ses:
            fila = ses.execute(
                text("SELECT contenido FROM comprobantes_pago WHERE id=:id"),
                {"id": comprobante_id},
            ).fetchone()
        if fila is not None and fila[0] is not None:
            return bytes(fila[0])
    except Exception:
        return None
    return None


def _render_comprobante_finanzas(conn, comprobante, key_prefix="fin_comp"):
    """FIN-10: muestra el comprobante real sin importar su almacenamiento."""
    if comprobante is None:
        st.info("No existe un comprobante asociado a esta reserva.")
        return False

    archivo = _obtener_bytes_comprobante(conn, comprobante)
    nombre = str(comprobante.get("nombre_archivo") or f"comprobante_{comprobante.get('id','')}")
    mime = str(comprobante.get("mime_type") or "application/octet-stream").lower()

    if not archivo:
        st.warning(
            "El comprobante figura como recibido, pero el archivo no está disponible "
            "en PostgreSQL ni en Google Drive. Debe revisarse la sincronización del almacenamiento."
        )
        return False

    st.markdown("###### Archivo comprobante")
    if mime.startswith("image/") or nombre.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        st.image(archivo, caption=nombre, use_container_width=True)
    elif mime == "application/pdf" or nombre.lower().endswith(".pdf"):
        # Streamlit no siempre incrusta PDF de forma nativa de manera estable.
        st.caption("PDF disponible para revisión.")
    else:
        st.caption(f"Archivo disponible: {nombre}")

    st.download_button(
        "⬇️ Abrir / descargar comprobante",
        data=archivo,
        file_name=nombre,
        mime=mime,
        use_container_width=True,
        key=f"{key_prefix}_download_{comprobante.get('id','')}",
    )
    return True


def refrescar_vista_persistente(*limpiadores):
    """Actualiza la vista sin cerrar sesión ni cambiar el portal/módulo actual."""
    for fn in limpiadores:
        try:
            fn()
        except Exception:
            pass
    st.rerun()

def _detalle_html_por_dia(detalle):
    bloques=[]
    for fecha_iso in sorted({x[0] for x in detalle}):
        f=date.fromisoformat(fecha_iso)
        dia=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f.weekday()]
        filas=[x for x in detalle if x[0]==fecha_iso]
        rows="".join(f"<tr><td style='border:1px solid #9bb6a5;padding:7px'>{serv}</td><td style='border:1px solid #9bb6a5;padding:7px'>{plato}</td></tr>" for _,_,serv,plato,*_ in filas)
        bloques.append(f"""<table style='border-collapse:collapse;width:100%;margin:12px 0'><tr><th style='border:1px solid #0A2F6B;background:#086b37;color:white;padding:8px;text-align:left'>{dia}</th><th style='border:1px solid #0A2F6B;background:#0A2F6B;color:white;padding:8px'>{f.strftime('%d-%m-%Y')}</th></tr><tr><th style='border:1px solid #9bb6a5;padding:7px'>Servicio</th><th style='border:1px solid #9bb6a5;padding:7px'>Plato</th></tr>{rows}</table>""")
    return "".join(bloques)

def generar_pdf_reserva(nombre, rut, institucion, referencia, detalle, precio_dia, total_real, metodo, url_comprobante):
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=14*mm,bottomMargin=14*mm)
    styles=getSampleStyleSheet()
    titulo=ParagraphStyle('titulo',parent=styles['Heading1'],textColor=colors.HexColor('#0A2F6B'),alignment=TA_CENTER,fontSize=18,spaceAfter=8)
    normal=styles['BodyText']
    story=[Paragraph('ALEMSI · CASINO MAMUIL',titulo),Paragraph('DETALLE DE RESERVA',titulo)]
    info=[[Paragraph('<b>Referencia</b>',normal),referencia,Paragraph('<b>Comensal</b>',normal),nombre],[Paragraph('<b>RUT</b>',normal),rut,Paragraph('<b>Institución</b>',normal),institucion]]
    t=Table(info,colWidths=[28*mm,55*mm,28*mm,55*mm]); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.6,colors.HexColor('#B7C7BD')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#F1F6F3')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#F1F6F3')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('PADDING',(0,0),(-1,-1),6)])); story += [t,Spacer(1,7*mm)]
    for fecha_iso in sorted({x[0] for x in detalle}):
        f=date.fromisoformat(fecha_iso); dia=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f.weekday()]
        filas=[[dia,f.strftime('%d-%m-%Y')],['Servicio','Plato']] + [[x[2],x[3]] for x in detalle if x[0]==fecha_iso]
        tb=Table(filas,colWidths=[82*mm,82*mm],repeatRows=2)
        tb.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.7,colors.HexColor('#5E8C72')),('BACKGROUND',(0,0),(0,0),colors.HexColor('#086B37')),('BACKGROUND',(1,0),(1,0),colors.HexColor('#0A2F6B')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,1),'Helvetica-Bold'),('ALIGN',(1,0),(1,0),'CENTER'),('ALIGN',(0,1),(-1,1),'CENTER'),('PADDING',(0,0),(-1,-1),6)]))
        story += [KeepTogether([tb,Spacer(1,4*mm)])]
    resumen=Table([['Días reservados',str(len({x[0] for x in detalle})),'Valor diario',formato_clp(precio_dia)],['Total a pagar',formato_clp(total_real),'Estado','Pendiente'],['Método de pago',metodo,'','']],colWidths=[35*mm,47*mm,35*mm,47*mm])
    resumen.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.6,colors.HexColor('#B7C7BD')),('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTNAME',(0,0),(0,-1),'Helvetica-Bold'),('FONTNAME',(2,0),(2,-1),'Helvetica-Bold'),('PADDING',(0,0),(-1,-1),6)])); story += [Spacer(1,3*mm),resumen,Spacer(1,5*mm)]
    if url_comprobante: story += [Paragraph('<b>Subir comprobante de pago:</b>',normal),Paragraph(url_comprobante,normal),Spacer(1,2*mm)]
    story += [Paragraph('El pago no es obligatorio antes del consumo. El enlace facilita el envío del comprobante cuando corresponda.',normal)]
    doc.build(story); return buf.getvalue()

# ================================================================
# RESPALDOS Y CONTINUIDAD
# Genera una copia lógica portable sin alterar los datos operativos.
# La integración con Google Drive es opcional y se activa solo por Secrets.
# ================================================================
BACKUP_TABLES = [
    "comensales", "solicitudes", "comprobantes_pago", "ajustes_financieros",
    "jornadas_produccion", "jornada_detalle", "minutas", "platos", "recetas",
    "bodega_inventario", "mermas", "inventarios_fisicos", "instituciones",
    "excepciones_personas", "modalidades_pago", "usuarios", "usuarios_permisos",
    "auditoria_acciones", "registro_login", "configuracion_correos", "configuracion_bancaria",
    "reclamos_sugerencias", "encuestas_satisfaccion", "tareas_inventario_cocina",
    "inventarios_aleatorios", "minuta_revision_coordinacion", "receta_revision_coordinacion"
]

def generar_respaldo_logico(tipo="MANUAL"):
    conn = get_conn()
    buf = BytesIO()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = {
        "sistema": "ALEMSI Mamuil Malal",
        "version": "v2.1.3.37",
        "fecha_hora": datetime.now().isoformat(),
        "tipo": tipo,
        "tablas": [],
        "errores": [],
    }
    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for tabla in BACKUP_TABLES:
            try:
                df = conn.query(f"SELECT * FROM {tabla}", ttl=0)
                # BYTEA no se serializa de forma útil a CSV; se conserva metadata del comprobante.
                if tabla == "comprobantes_pago" and "contenido" in df.columns:
                    df = df.drop(columns=["contenido"])
                zf.writestr(f"datos/{tabla}.csv", df.to_csv(index=False).encode("utf-8-sig"))
                meta["tablas"].append({"tabla": tabla, "registros": int(len(df))})
            except Exception as exc:
                meta["errores"].append({"tabla": tabla, "error": str(exc)[:240]})
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return f"ALEMSI_BACKUP_{tipo}_{sello}.zip", buf.getvalue(), meta

def subir_respaldo_drive(nombre_archivo, contenido):
    """Sube a Drive solo si existe configuración segura en st.secrets.
    Requiere [backup] folder_id y [gcp_service_account].
    """
    try:
        cfg = st.secrets.get("backup", {})
        folder_id = str(cfg.get("folder_id", "")).strip()
        sa = st.secrets.get("gcp_service_account", {})
        if not folder_id or not sa:
            return False, "Google Drive no configurado; respaldo disponible para descarga manual."
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        creds = service_account.Credentials.from_service_account_info(
            dict(sa), scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        media = MediaIoBaseUpload(BytesIO(contenido), mimetype="application/zip", resumable=False)
        body = {"name": nombre_archivo, "parents": [folder_id]}
        archivo = service.files().create(body=body, media_body=media, fields="id,name").execute()
        return True, f"Respaldo guardado en Drive: {archivo.get('name')}"
    except Exception as exc:
        return False, f"No fue posible subir a Drive: {exc}"

@st.cache_data(ttl=60, show_spinner=False)
def cargar_usuarios_admin():
    conn = get_conn()
    return conn.query(
        "SELECT username,nombre,correo,rol,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password,fecha_creacion FROM usuarios ORDER BY activo DESC,username",
        ttl=60,
    )

@st.cache_data(ttl=60, show_spinner=False)
def cargar_permisos_usuario(username):
    conn = get_conn()
    return conn.query(
        "SELECT permiso,activo FROM usuarios_permisos WHERE username=:u ORDER BY permiso",
        params={"u": username}, ttl=60
    )

def limpiar_cache_usuarios():
    cargar_usuarios_admin.clear()
    cargar_permisos_usuario.clear()
    try:
        _permiso_habilitado_db.clear()
    except Exception:
        pass
    st.session_state.pop("_permisos_sesion", None)

def generar_clave_temporal(largo=12):
    """Genera una clave temporal segura y legible para primer acceso."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#"
    return "".join(secrets.choice(alfabeto) for _ in range(max(10, int(largo))))

def enviar_acceso_usuario(correo, nombre, username, clave_temporal, rol):
    """AUTH-03: notifica credenciales temporales desde la propia APP."""
    try:
        base = str(st.secrets.get("app", {}).get("public_url", "")).strip().rstrip("/")
    except Exception:
        base = ""
    if not base:
        base = "https://alemsi-mamuil-erp.streamlit.app"
    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:680px;margin:auto;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden'>
      <div style='background:#0A2F6B;color:white;padding:20px 24px'>
        <h2 style='margin:0'>Acceso habilitado · ALEMSI Mamuil Malal</h2>
      </div>
      <div style='padding:24px'>
        <p>Hola <b>{nombre}</b>,</p>
        <p>Tu acceso a la aplicación ALEMSI Mamuil Malal fue habilitado para el perfil <b>{rol}</b>.</p>
        <div style='background:#f8fafc;border-radius:10px;padding:16px;margin:18px 0'>
          <p style='margin:4px 0'><b>Usuario:</b> {username}</p>
          <p style='margin:4px 0'><b>Contraseña temporal:</b> {clave_temporal}</p>
        </div>
        <p>Por seguridad, al ingresar deberás reemplazar esta contraseña temporal por una personal.</p>
        <p><a href='{base}' style='display:inline-block;background:#0A2F6B;color:white;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:bold'>Ingresar a la aplicación</a></p>
        <p style='font-size:12px;color:#64748b'>Este mensaje fue generado automáticamente por ALEMSI. No compartas tu contraseña.</p>
      </div>
    </div>
    """
    return enviar_email(str(correo).strip().lower(), "Acceso habilitado · ALEMSI Mamuil Malal", html)

def notificar_ingreso_usuario(correo, nombre, username, rol):
    """AUTH-04: reenvía usuario + enlace al portal sin modificar contraseña."""
    try:
        base = str(st.secrets.get("app", {}).get("public_url", "")).strip().rstrip("/")
    except Exception:
        base = ""
    if not base:
        base = "https://alemsi-mamuil-erp.streamlit.app"
    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:680px;margin:auto;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden'>
      <div style='background:#0A2F6B;color:white;padding:20px 24px'>
        <h2 style='margin:0'>Recordatorio de acceso · ALEMSI Mamuil Malal</h2>
      </div>
      <div style='padding:24px'>
        <p>Hola <b>{nombre}</b>,</p>
        <p>Te recordamos que tienes acceso habilitado a ALEMSI Mamuil Malal con el perfil <b>{rol}</b>.</p>
        <div style='background:#f8fafc;border-radius:10px;padding:16px;margin:18px 0'>
          <p style='margin:4px 0'><b>Usuario:</b> {username}</p>
        </div>
        <p>Tu contraseña actual no ha sido modificada.</p>
        <p><a href='{base}' style='display:inline-block;background:#0A2F6B;color:white;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:bold'>Ingresar a la aplicación</a></p>
        <p style='font-size:12px;color:#64748b'>Si no recuerdas tu contraseña, solicita un restablecimiento al Administrador Total.</p>
      </div>
    </div>
    """
    return enviar_email(str(correo).strip().lower(), "Recordatorio de acceso · ALEMSI Mamuil Malal", html)

PERMISOS_DISPONIBLES = {
    # Operación por perfil
    "ver_cocina": "Cocina · operar producción",
    "ver_bodega": "Bodega / inventario",
    "cargar_inventario": "Bodega · cargar / ajustar inventario",
    "ver_finanzas": "Finanzas",
    "modificar_montos": "Finanzas · modificar montos",
    "validar_pagos": "Finanzas · validar comprobantes",
    "ver_gerencia": "Gerencia / control de gestión",

    # Módulos administrativos visibles desde el maestro
    "ver_dashboard": "Administración · Dashboard",
    "ver_reportes": "Administración · Reportes",
    "ver_planilla_reservas": "Administración · Planilla de Reservas",
    "editar_minuta": "Administración · Minutas / Maestro de Platos",
    "gestionar_excepciones": "Administración · Excepciones",
    "gestionar_instituciones": "Administración · Instituciones",
    "gestionar_modalidades_pago": "Administración · Modalidades de pago",
    "gestionar_correos": "Administración · Correos",
    "gestionar_datos_transferencia": "Administración · Datos de transferencia",
    "gestionar_usuarios": "AdminTotal · Usuarios y permisos",
    "ver_actividad": "AdminTotal · Registro de actividad",
    "depurar_datos": "AdminTotal · Depuración de datos de prueba",
    "generar_respaldos": "AdminTotal · Respaldos",

    # Calidad / satisfacción
    "ver_satisfaccion": "Calidad · Dashboard de satisfacción",
    "ver_comentarios_satisfaccion": "Calidad · Comentarios de encuestas",
    "ver_reclamos": "Calidad · Reclamos / sugerencias / felicitaciones",

    # Coordinación: acceso deliberadamente limitado
    "coord_revisar_minutas": "PROPUESTA ETAPA POSTERIOR · Coordinación · Revisar Minutas",
    "coord_revisar_recetas": "PROPUESTA ETAPA POSTERIOR · Coordinación · Revisar Recetas",
}

def _render_encuestas_portal(conn, token, referencia, rut, institucion):
    """ENC-01: una misma ventana, Casino primero y APP debajo."""
    st.divider()
    st.markdown("## ⭐ Tu opinión nos ayuda a mejorar")
    st.caption("Gracias por utilizar Mamuil Malal. Las evaluaciones de Casino y APP se guardan por separado.")

    existente_casino = conn.query(
        "SELECT id FROM encuestas_satisfaccion WHERE pago_token=:t AND tipo='CASINO' LIMIT 1",
        params={"t":token}, ttl=0
    )
    st.markdown("### 🍽️ Califica el servicio de Casino Mamuil Malal")
    st.caption("Esta evaluación tiene prioridad y nos permite detectar oportunidades de mejora del servicio.")
    if not existente_casino.empty:
        st.success("Gracias. Tu evaluación del Casino ya fue registrada.")
    else:
        with st.form(f"enc_casino_{referencia}"):
            general = st.select_slider("Satisfacción general", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            comida = st.select_slider("Calidad de la comida", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            atencion = st.select_slider("Atención", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            limpieza = st.select_slider("Limpieza", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            variedad = st.select_slider("Variedad", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            comentario = st.text_area("Comentario (opcional)", key=f"coment_casino_{referencia}")
            if st.form_submit_button("Enviar evaluación del Casino", type="primary", use_container_width=True):
                with conn.session as ses:
                    execute_sql(ses, "INSERT INTO encuestas_satisfaccion (tipo,pago_token,referencia_reserva,rut,institucion,puntaje_general,puntaje_comida,puntaje_atencion,puntaje_limpieza,puntaje_variedad,comentario,fecha_respuesta) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ("CASINO",token,referencia,rut,institucion,int(general),int(comida),int(atencion),int(limpieza),int(variedad),comentario.strip(),datetime.now().isoformat()))
                    ses.commit()
                st.success("Gracias por evaluar el servicio de Casino Mamuil Malal.")
                st.rerun()

    st.markdown("### 📱 Califica la APP ALEMSI")
    st.caption("Evaluación independiente de la interfaz y facilidad de uso de la aplicación.")
    existente_app = conn.query(
        "SELECT id FROM encuestas_satisfaccion WHERE pago_token=:t AND tipo='APP' LIMIT 1",
        params={"t":token}, ttl=0
    )
    if not existente_app.empty:
        st.success("Gracias. Tu evaluación de la APP ya fue registrada.")
    else:
        with st.form(f"enc_app_{referencia}"):
            general_app = st.select_slider("Experiencia general con la APP", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            facilidad = st.select_slider("Facilidad de uso", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            claridad = st.select_slider("Claridad de la información", options=[1,2,3,4,5], value=5, format_func=lambda x: "⭐"*x)
            comentario_app = st.text_area("Comentario sobre la APP (opcional)", key=f"coment_app_{referencia}")
            if st.form_submit_button("Enviar evaluación de la APP", use_container_width=True):
                with conn.session as ses:
                    execute_sql(ses, "INSERT INTO encuestas_satisfaccion (tipo,pago_token,referencia_reserva,rut,institucion,puntaje_general,puntaje_facilidad,puntaje_claridad,comentario,fecha_respuesta) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", ("APP",token,referencia,rut,institucion,int(general_app),int(facilidad),int(claridad),comentario_app.strip(),datetime.now().isoformat()))
                    ses.commit()
                st.success("Gracias por ayudarnos a mejorar la APP ALEMSI.")
                st.rerun()


def _render_satisfaccion_gestion(usuario, key_prefix="sat"):
    """Vista reutilizable de calidad. Promedios primero; comentarios solo con permiso explícito."""
    conn=get_conn()
    st.markdown("### ⭐ Calidad y satisfacción")
    df=conn.query("""
        SELECT tipo,institucion,puntaje_general,puntaje_comida,puntaje_atencion,
               puntaje_limpieza,puntaje_variedad,puntaje_facilidad,puntaje_claridad,
               comentario,fecha_respuesta
        FROM encuestas_satisfaccion
        ORDER BY fecha_respuesta DESC
    """,ttl=0)
    if df.empty:
        st.info("Todavía no existen evaluaciones registradas.")
    else:
        total=len(df)
        general=pd.to_numeric(df["puntaje_general"],errors="coerce").mean()
        casino=df[df["tipo"].astype(str)=="CASINO"]
        app_df=df[df["tipo"].astype(str)=="APP"]
        c1,c2,c3=st.columns(3)
        c1.metric("Evaluaciones",total)
        c2.metric("Promedio general",f"{general:.2f} / 5" if pd.notna(general) else "—")
        c3.metric("Casino / APP",f"{len(casino)} / {len(app_df)}")
        resumen=(df.groupby("tipo",dropna=False).agg(
            Respuestas=("tipo","size"),
            Promedio=("puntaje_general",lambda s: pd.to_numeric(s,errors="coerce").mean())
        ).reset_index())
        resumen["Promedio"]=resumen["Promedio"].round(2)
        st.dataframe(resumen.rename(columns={"tipo":"Tipo"}),use_container_width=True,hide_index=True)
        if permiso_habilitado(usuario.get("username"),"ver_comentarios_satisfaccion",False) or usuario.get("rol")=="AdminTotal":
            comentarios=df[df["comentario"].fillna("").astype(str).str.strip()!=""].copy()
            if not comentarios.empty:
                with st.expander(f"💬 Comentarios de encuestas · {len(comentarios)}"):
                    st.dataframe(_tabla_visible(comentarios,{"fecha_respuesta":"Fecha / hora","tipo":"Tipo","institucion":"Institución","puntaje_general":"Puntaje","comentario":"Comentario"},["fecha_respuesta"]),use_container_width=True,hide_index=True)
    if permiso_habilitado(usuario.get("username"),"ver_reclamos",False) or usuario.get("rol")=="AdminTotal":
        rec=conn.query("SELECT fecha,nombre,tipo,categoria,mensaje,estado FROM reclamos_sugerencias ORDER BY fecha DESC",ttl=0)
        st.markdown("#### 🗣️ Reclamos, sugerencias y felicitaciones")
        if rec.empty: st.caption("Sin registros.")
        else: st.dataframe(_tabla_visible(rec,{"fecha":"Fecha / hora","nombre":"Comensal","tipo":"Tipo","categoria":"Categoría","mensaje":"Mensaje","estado":"Estado"},["fecha"]),use_container_width=True,hide_index=True)


st.set_page_config(page_title="Mamuil Malal · Reserva de Alimentación", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

try: apply_alemsi_style()
except: pass

@st.cache_resource(show_spinner="Inicializando base de datos...")
def initialize_database():
    init_db()
    return True

try:
    initialize_database()
except Exception as e:
    st.error("No fue posible conectar con el servicio de datos. Intenta nuevamente en unos minutos o contacta al administrador.")
    st.stop()

# Portal público de carga de comprobante, accesible desde el enlace enviado por correo.
try:
    token_q = st.query_params.get("pago_token", "")
except Exception:
    token_q = ""
if token_q:
    conn=get_conn()
    df_token=conn.query("SELECT referencia_reserva,rut,institucion,correo,estado_pago FROM solicitudes WHERE pago_token=:t ORDER BY fecha LIMIT 1", params={"t":token_q}, ttl=0)
    if df_token.empty:
        st.error("El enlace de comprobante no es válido o ya no está disponible.")
        st.stop()
    ref=str(df_token.iloc[0]['referencia_reserva'])
    st.markdown(f"### 📎 Portal de pago y evaluación · {ref}")
    df_comp_existente = conn.query("SELECT id FROM comprobantes_pago WHERE pago_token=:t ORDER BY id DESC LIMIT 1", params={"t":token_q}, ttl=0)
    comprobante_cargado = not df_comp_existente.empty
    if not comprobante_cargado:
        st.info("Carga tu comprobante de pago. Finanzas lo revisará; la carga no equivale a validación del pago.")
        archivo=st.file_uploader("Comprobante (PDF, JPG o PNG · máximo 10 MB)", type=["pdf","jpg","jpeg","png"])
    else:
        archivo=None
        st.success("✅ Comprobante recibido. Finanzas realizará la validación.")
    if archivo is not None and archivo.size > 10*1024*1024:
        st.error("El archivo supera el máximo de 10 MB.")
    elif archivo is not None and st.button("Enviar comprobante", type="primary", use_container_width=True):
        contenido=archivo.getvalue()
        ok_drive, drive_id, drive_url, drive_nombre = subir_comprobante_drive(
            archivo.name, archivo.type, contenido, ref
        )
        storage = "GOOGLE_DRIVE" if ok_drive else "POSTGRESQL_FALLBACK"

        with conn.session as ses:
            execute_sql(
                ses,
                "INSERT INTO comprobantes_pago "
                "(referencia_reserva,pago_token,rut,nombre_archivo,mime_type,contenido,fecha_carga,estado,drive_file_id,drive_url,storage_provider) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    ref, token_q, str(df_token.iloc[0]['rut']),
                    drive_nombre if ok_drive else archivo.name,
                    archivo.type,
                    None if ok_drive else contenido,
                    datetime.now().isoformat(),
                    "RECIBIDO",
                    drive_id,
                    drive_url,
                    storage,
                ),
            )
            execute_sql(
                ses,
                "UPDATE solicitudes SET comprobante_url=%s,estado_pago=%s,motivo_estado_pago=%s WHERE pago_token=%s",
                (
                    f"DRIVE:{drive_id}" if ok_drive else f"DB:{ref}",
                    "Comprobante recibido",
                    "Pendiente de validación por Finanzas",
                    token_q,
                ),
            )
            ses.commit()

        for destino in get_correos("finanzas"):
            enviar_email(
                destino,
                f"[COMPROBANTE RECIBIDO] {ref}",
                f"<p>Se recibió un comprobante para la reserva <b>{ref}</b>. "
                "Debe ser revisado y validado por Finanzas.</p>",
            )

        if ok_drive:
            st.success("Comprobante recibido y almacenado en Google Drive. Finanzas realizará la validación.")
        else:
            st.warning(
                "Comprobante recibido. Google Drive no estaba disponible/configurado, "
                "por lo que se guardó temporalmente en PostgreSQL para no perder la carga."
            )
        st.rerun()
    if comprobante_cargado:
        _render_encuestas_portal(conn, token_q, ref, str(df_token.iloc[0]['rut']), str(df_token.iloc[0]['institucion']))
    st.stop()

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}
if "portal_actual" not in st.session_state: st.session_state.portal_actual="inicio"


def registrar_auditoria(usuario, accion, entidad, referencia="", anterior="", nuevo="", motivo=""):
    try:
        conn = get_conn()
        with conn.session as ses:
            execute_sql(ses, "INSERT INTO auditoria_acciones (fecha,usuario,accion,entidad,referencia,valor_anterior,valor_nuevo,motivo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (datetime.now().isoformat(), usuario, accion, entidad, referencia, str(anterior), str(nuevo), str(motivo)))
            ses.commit()
    except Exception:
        pass

def _contexto_cliente():
    """Contexto técnico de la sesión para auditoría. No se usa como mecanismo de seguridad."""
    ip = ""
    zona = ""
    locale = ""
    user_agent = ""
    try:
        ip = str(getattr(st.context, "ip_address", "") or "")
        zona = str(getattr(st.context, "timezone", "") or "")
        locale = str(getattr(st.context, "locale", "") or "")
        headers = getattr(st.context, "headers", {}) or {}
        user_agent = str(headers.get("User-Agent", "") if hasattr(headers, "get") else "")
    except Exception:
        pass
    return ip, zona, locale, user_agent

def registrar_evento_login(usuario, rol="", evento="INICIO", resultado="OK", detalle=""):
    """LOG-33: registro de accesos, cierres e intentos fallidos para AdminTotal."""
    try:
        ip, zona, locale, user_agent = _contexto_cliente()
        conn = get_conn()
        with conn.session as ses:
            execute_sql(
                ses,
                "INSERT INTO registro_login "
                "(fecha,usuario,rol,evento,resultado,ip,zona_horaria,locale,user_agent,detalle) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    datetime.now().isoformat(),
                    str(usuario or "").strip().lower(),
                    str(rol or ""),
                    str(evento or ""),
                    str(resultado or ""),
                    ip, zona, locale, user_agent, str(detalle or ""),
                ),
            )
            ses.commit()
    except Exception:
        pass

@st.cache_data(ttl=60, show_spinner=False)
def _permiso_habilitado_db(username, permiso):
    """PERF-30: consulta breve y cacheada; evita repetir SQL en cada rerun."""
    conn = get_conn()
    return conn.query(
        "SELECT activo FROM usuarios_permisos WHERE username=:u AND permiso=:p",
        params={"u": username, "p": permiso},
        ttl=60,
    )

def permiso_extraordinario_activo(username, permiso):
    """Devuelve True solo cuando AdminTotal dejó un override explícito activo.

    A diferencia de permiso_habilitado(), no aplica defaults del rol. Esto permite
    componer ROL BASE + PERMISOS EXTRAORDINARIOS sin convertir permisos heredados
    en capacidades operativas accidentales.
    """
    try:
        dfp = _permiso_habilitado_db(username, permiso)
        return (not dfp.empty) and bool(int(dfp.iloc[0]["activo"]))
    except Exception:
        return False

def permiso_habilitado(username, permiso, default=True):
    # Caché de sesión: durante la navegación normal no se vuelve a consultar
    # el mismo permiso. AdminTotal limpia esta caché al editar permisos.
    cache = st.session_state.setdefault("_permisos_sesion", {})
    clave = (str(username or ""), str(permiso or ""))
    if clave in cache:
        return bool(cache[clave])
    try:
        dfp = _permiso_habilitado_db(username, permiso)
        valor = bool(int(dfp.iloc[0]["activo"])) if not dfp.empty else bool(default)
    except Exception:
        valor = bool(default)
    cache[clave] = valor
    return valor

st.markdown('''
<div class="main-header">
  <div class="alemsi-topbar">
    <div class="alemsi-brand">
      <div class="alemsi-mark"><span></span><span></span><span></span><span></span></div>
      <div class="alemsi-brandcopy"><strong>ALEMSI</strong><small>Servicios de Higiene y Desinfección</small></div>
    </div>
    <div class="alemsi-secure">✓ Sistema de reserva segura</div>
  </div>
  <div class="alemsi-hero">
    <div class="alemsi-place">Complejo Fronterizo · Araucanía</div>
    <h1>Reserva de Alimentación<br><em>Mamuil Malal</em></h1>
    <p>Selecciona tus fechas y servicios de alimentación. La operación de reservas mantiene intactas sus reglas, comprobantes y notificaciones.</p>
  </div>
</div>
''', unsafe_allow_html=True)

if st.session_state.usuario or st.session_state.rut_actual:
    if st.session_state.usuario:
        col1,col2 = st.columns([4,1])
        with col1:
            st.success(f"{st.session_state.usuario['nombre']} - {st.session_state.usuario['rol']}")
        with col2:
            if st.button("Cerrar sesión", use_container_width=True):
                registrar_evento_login(
                    st.session_state.usuario.get("username"),
                    st.session_state.usuario.get("rol"),
                    "CIERRE",
                    "OK",
                    "Cierre voluntario desde la aplicación",
                )
                st.session_state.usuario=None; st.session_state.rut_actual=None; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.session_state.portal_actual="inicio"; st.rerun()
    elif st.session_state.rut_actual:
        st.success(f"Comensal: {st.session_state.rut_actual}")



# ===== MODULOS AISLADOS: NO REESCRIBIR LOGICA PROTEGIDA =====
def selector_neutro(label, opciones, *, key, format_func=None, placeholder="— Seleccione —", disabled=False):
    """Selector para registros provenientes de BD: nunca autoselecciona el primer elemento."""
    lista = list(opciones or [])
    return st.selectbox(label, lista, index=None, placeholder=placeholder, key=key, format_func=format_func, disabled=disabled)

def _excepcion_reserva_activa(rut, fecha_iso):
    """Solo amplía la ventana de reserva; no crea raciones ni valida pagos."""
    try:
        df = get_conn().query(
            "SELECT id FROM excepciones_reserva WHERE rut=:rut AND activa=1 AND fecha_desde<=:f AND fecha_hasta>=:f ORDER BY id DESC LIMIT 1",
            params={"rut": normalizar_rut_db(rut), "f": str(fecha_iso)}, ttl=0,
        )
        return not df.empty
    except Exception:
        return False

def _reserva_modificable_v40(rut, fecha_iso, servicio):
    return reserva_modificable(fecha_iso, servicio) or _excepcion_reserva_activa(rut, fecha_iso)

def _scroll_top():
    """Evita que widgets inferiores conserven foco/scroll al cambiar de módulo."""
    components.html("<script>window.parent.scrollTo({top:0,left:0,behavior:'instant'});</script>", height=0)

def fecha_visible(valor):
    """Formato de fecha visible estándar ALEMSI: DD/MM/AAAA."""
    if valor is None or str(valor).strip()=="": return ""
    try: return pd.to_datetime(valor).strftime("%d/%m/%Y")
    except Exception: return str(valor)

def _opciones_comensales_por_institucion(df, institucion="Todas"):
    """PLAN-02: devuelve solo comensales pertenecientes a la institución seleccionada."""
    if df is None or df.empty or "rut" not in df.columns:
        return [("Todos", "Todos")]
    vista = df.copy()
    if institucion and institucion != "Todas" and "institucion" in vista.columns:
        vista = vista[vista["institucion"].astype(str) == str(institucion)]
    columnas = ["rut"] + (["nombre"] if "nombre" in vista.columns else [])
    personas = vista[columnas].drop_duplicates()
    salida = [("Todos", "Todos")]
    for _, fila in personas.sort_values(columnas[-1]).iterrows():
        rut = str(fila["rut"])
        nombre = str(fila["nombre"]) if "nombre" in personas.columns else rut
        salida.append((rut, f"{nombre} · {rut}"))
    return salida


def _normalizar_modalidad_pago(valor):
    """FIN-MOD-01: unifica etiquetas históricas solo para visualización/filtros; no reescribe PostgreSQL."""
    txt = str(valor or "").strip()
    clave = txt.casefold()
    equivalencias = {
        "transferencia": "Transferencia bancaria",
        "transferencia bancaria": "Transferencia bancaria",
        "transferencia bancaría": "Transferencia bancaria",
        "débito en local": "Débito en la instalación",
        "debito en local": "Débito en la instalación",
        "débito en la instalación": "Débito en la instalación",
        "debito en la instalación": "Débito en la instalación",
        "debito en la instalacion": "Débito en la instalación",
        "interno alemsi": "Interno ALEMSI",
    }
    return equivalencias.get(clave, txt if txt else "Sin modalidad")


def _modalidades_visibles_por_institucion(institucion):
    """Interno ALEMSI solo corresponde a personal ALEMSI."""
    if str(institucion or "").strip().casefold() == "alemsi":
        return ["Interno ALEMSI", "Transferencia bancaria", "Débito en la instalación"]
    if institucion == "Todas":
        return ["Todas", "Transferencia bancaria", "Débito en la instalación", "Interno ALEMSI"]
    return ["Todas", "Transferencia bancaria", "Débito en la instalación"]


def _grafico_modalidades_pago(df):
    """FIN-MOD-02: resumen compacto horizontal, agrupando nombres históricos equivalentes."""
    if df is None or df.empty or "metodo_pago" not in df.columns:
        return
    datos = df.copy()
    datos["modalidad_visible"] = datos["metodo_pago"].apply(_normalizar_modalidad_pago)
    if "monto_final" not in datos.columns:
        datos["monto_final"] = pd.to_numeric(datos.get("precio_aplicado", 0), errors="coerce").fillna(0)
    datos["monto_final"] = pd.to_numeric(datos["monto_final"], errors="coerce").fillna(0)
    resumen = (datos.groupby("modalidad_visible", as_index=False)["monto_final"].sum()
               .sort_values("monto_final", ascending=False))
    total = float(resumen["monto_final"].sum()) or 1.0
    for _, fila in resumen.iterrows():
        nombre = str(fila["modalidad_visible"])
        monto = float(fila["monto_final"])
        pct = max(0.0, min(100.0, monto / total * 100.0))
        st.markdown(
            f"<div style='margin:8px 0 12px 0'>"
            f"<div style='display:flex;justify-content:space-between;gap:12px;align-items:center'>"
            f"<b>{nombre}</b><span>{formato_clp(monto)} · {pct:.1f}%</span></div>"
            f"<div style='height:12px;background:#E9ECEF;border-radius:999px;overflow:hidden;margin-top:5px'>"
            f"<div style='width:{pct:.2f}%;height:100%;background:#0A2F6B;border-radius:999px'></div></div></div>",
            unsafe_allow_html=True,
        )


def _tabla_visible(df, mapa=None, fechas=None):
    if df is None: return pd.DataFrame()
    out=df.copy()
    if "metodo_pago" in out.columns:
        out["metodo_pago"] = out["metodo_pago"].apply(_normalizar_modalidad_pago)
    for col in (fechas or []):
        if col in out.columns: out[col]=out[col].apply(fecha_visible)
    if mapa: out=out.rename(columns=mapa)
    return out

def _detalle_reserva_agrupada(conn, referencia):
    """FIN-GER-02: obtiene el detalle interno de una sola reserva."""
    if not referencia:
        return pd.DataFrame()
    return conn.query(
        """
        SELECT fecha, servicio, COALESCE(plato_reservado,plato) AS plato,
               metodo_pago, estado_pago, precio_aplicado
        FROM solicitudes
        WHERE referencia_reserva=:ref
        ORDER BY fecha,
                 CASE servicio
                   WHEN 'Desayuno' THEN 1
                   WHEN 'Almuerzo' THEN 2
                   WHEN 'Once' THEN 3
                   WHEN 'Cena' THEN 4
                   ELSE 5
                 END,
                 servicio
        """,
        params={"ref": str(referencia)},
        ttl=0,
    )


def _render_detalle_reserva_por_fecha(df_detalle):
    """Visual: Fecha -> Servicios de esa fecha, dentro de una misma reserva."""
    if df_detalle is None or df_detalle.empty:
        st.caption("Sin detalle de fechas y servicios para esta reserva.")
        return
    for fecha_ref, grupo_fecha in df_detalle.groupby("fecha", sort=True):
        st.markdown(f"**{fecha_visible(fecha_ref)}**")
        vista = grupo_fecha[["servicio","plato"]].copy()
        st.dataframe(
            vista.rename(columns={"servicio":"Servicio","plato":"Plato"}),
            use_container_width=True,
            hide_index=True,
        )


# GRAF-02: paleta única de visualización por institución.
# Se mantiene centralizada para que cada institución conserve el mismo color
# en toda la plataforma. Los tonos son de la interfaz ALEMSI; no se publicitan
# como códigos oficiales de terceros mientras no exista manual de marca validado.
COLORES_INSTITUCION = {
    "ALEMSI": "#0A2F6B",
    "Carabineros": "#2E6B3A",
    "PDI": "#245A8D",
    "SAG": "#5E7D32",
    "Aduana": "#365F7D",
    "Chofer de Aduana": "#5A7890",
    "Coordinadores": "#7A5C9E",
    "Vialidad": "#B46A2A",
    "Visitas": "#6C757D",
}

def _color_institucion(nombre):
    return COLORES_INSTITUCION.get(str(nombre or "").strip(), "#6C757D")

def _grafico_instituciones_linea(df, institucion_col="institucion", valor_col="monto"):
    """GRAF-02: nombres horizontales; hasta 7 instituciones por fila."""
    if df is None or df.empty:
        return
    datos = df.copy()
    datos[valor_col] = pd.to_numeric(datos[valor_col], errors="coerce").fillna(0)
    datos = (datos.groupby(institucion_col, as_index=False)[valor_col].sum()
             .sort_values(valor_col, ascending=False))
    if datos.empty:
        return
    total = float(datos[valor_col].sum()) or 1.0
    registros = list(datos.iterrows())
    for inicio in range(0, len(registros), 7):
        bloque = registros[inicio:inicio+7]
        columnas = st.columns(len(bloque))
        for col, (_, fila) in zip(columnas, bloque):
            nombre = str(fila[institucion_col])
            valor = float(fila[valor_col])
            porcentaje = valor / total * 100.0
            color = _color_institucion(nombre)
            with col:
                st.markdown(
                    f"<div style='border-top:6px solid {color};padding-top:6px;min-height:72px'>"
                    f"<b style='white-space:nowrap'>{nombre}</b><br>"
                    f"<span style='font-size:1.15rem'>{formato_clp(valor)}</span><br>"
                    f"<span style='font-size:.78rem;color:#666'>{porcentaje:.1f}% del total</span></div>",
                    unsafe_allow_html=True,
                )


def _dashboard_financiero(df, titulo="Resumen financiero"):
    st.markdown(f"### {titulo}")
    if df is None or df.empty:
        st.info("No hay información disponible para los filtros seleccionados."); return
    d=df.copy()
    if 'monto_final' not in d.columns: d['monto_final']=pd.to_numeric(d.get('precio_aplicado',0),errors='coerce').fillna(0)
    d['monto_final']=pd.to_numeric(d['monto_final'],errors='coerce').fillna(0)
    estado=d.get('estado_pago',pd.Series(['Pendiente']*len(d),index=d.index)).fillna('Pendiente').astype(str)
    pagado=d[estado.str.lower().eq('pagado')]; pendiente=d[~estado.str.lower().eq('pagado')]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Monto total",formato_clp(d['monto_final'].sum())); c2.metric("Pagado",formato_clp(pagado['monto_final'].sum() if not pagado.empty else 0)); c3.metric("Pendiente",formato_clp(pendiente['monto_final'].sum() if not pendiente.empty else 0)); c4.metric("Registros",len(d))
    if 'institucion' in d.columns:
        deuda=d.assign(_pend=~estado.str.lower().eq('pagado')).groupby('institucion',dropna=False).agg(Monto=('monto_final','sum'),Pendientes=('_pend','sum')).reset_index()
        deuda['Estado']=deuda['Pendientes'].apply(lambda x:'Al día' if int(x)==0 else 'Con pendiente')
        st.markdown("#### Estado por institución"); _grafico_instituciones_linea(deuda.rename(columns={"Monto":"monto"}), "institucion", "monto"); st.dataframe(deuda.rename(columns={'institucion':'Institución'}),use_container_width=True,hide_index=True)
    if 'metodo_pago' in d.columns:
        st.markdown("#### Distribución por modalidad de pago")
        _grafico_modalidades_pago(d)

@st.cache_data(ttl=30, show_spinner=False)
def _cargar_reservas_finanzas():
    """FIN-PERF-32: fotografía cacheada de reservas financieras.

    La consulta SQL interna no mantiene TTL propio; la caché se controla aquí y se
    invalida explícitamente después de cada validación. Así evitamos reconstruir
    toda la bandeja en cada interacción y, a la vez, el estado cambia de inmediato
    después de guardar.
    """
    conn = get_conn()
    return conn.query("""
        SELECT
            s.referencia_reserva,
            s.rut,
            MAX(c.nombre) AS nombre,
            MAX(c.correo) AS correo,
            MAX(c.institucion) AS institucion,
            MIN(s.fecha) AS fecha_inicio,
            MAX(s.fecha) AS fecha_fin,
            COUNT(DISTINCT s.fecha) AS fechas_reservadas,
            COUNT(*) AS servicios_reservados,
            SUM(COALESCE(s.precio_aplicado,0)) AS monto_reserva,
            MAX(s.metodo_pago) AS metodo_pago,
            MAX(s.estado_pago) AS estado_pago,
            MAX(s.pago_token) AS pago_token,
            MAX(cp.id) AS comprobante_id,
            MAX(cp.estado) AS estado_comprobante,
            MAX(cp.fecha_carga) AS fecha_carga_comprobante
        FROM solicitudes s
        LEFT JOIN comensales c ON c.rut=s.rut
        LEFT JOIN comprobantes_pago cp ON cp.referencia_reserva=s.referencia_reserva
        WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
          AND COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA'
          AND COALESCE(NULLIF(s.referencia_reserva,''),'') <> ''
        GROUP BY s.referencia_reserva,s.rut
        ORDER BY MAX(c.institucion),MAX(c.nombre),MIN(s.fecha),s.referencia_reserva
    """, ttl=0)


def _refrescar_finanzas(mensaje=None, nivel="success", referencia_procesada=None):
    """FIN-PERF-33: invalida datos, libera selector y permite avanzar al siguiente comprobante."""
    try:
        _cargar_reservas_finanzas.clear()
    except Exception:
        pass
    if referencia_procesada:
        st.session_state["_fin_ultimo_procesado"] = str(referencia_procesada)
    st.session_state.pop("fin_validar_referencia", None)
    if mensaje:
        st.session_state["_flash_finanzas"] = (str(nivel), str(mensaje))
    st.rerun()


def _mostrar_flash_finanzas():
    flash = st.session_state.pop("_flash_finanzas", None)
    if not flash:
        return
    nivel, mensaje = flash
    fn = getattr(st, nivel, st.info)
    fn(mensaje)


BANCOS_CHILE = [
    # Catálogo CMF revisado 13-08-2026. Mantener centralizado; no escribir bancos a mano.
    "Banco de Chile", "Banco Internacional", "Scotiabank Chile",
    "Banco de Crédito e Inversiones (BCI)", "Banco BICE", "HSBC Bank (Chile)",
    "Banco Santander-Chile", "Banco Itaú Chile", "Banco Falabella", "Banco Ripley",
    "Banco Consorcio", "Banco BTG Pactual Chile", "Tanner Banco Digital",
    "Tenpo Bank Chile", "Banco del Estado de Chile (BancoEstado)",
    "JP Morgan Chase Bank, N.A.", "China Construction Bank, Agencia en Chile",
    "Bank of China, Agencia en Chile", "Otro"
]
TIPOS_CUENTA_CHILE = [
    "Cuenta Corriente", "Cuenta Vista", "Cuenta RUT", "Cuenta de Ahorro", "Otra"
]

def _render_datos_transferencia(usuario, key_prefix="datos_transferencia"):
    """FIN-CFG-32: editor único reutilizado por Finanzas y AdminTotal."""
    st.markdown("#### 🏦 Datos para transferencia bancaria")
    st.caption("Fuente maestra utilizada en correos, comprobantes e instrucciones de pago.")
    conn = get_conn()
    actual = get_config_bancaria()
    banco_actual = str(actual.get("banco", "") or "").strip()
    tipo_actual = str(actual.get("tipo_cuenta", "Cuenta Corriente") or "Cuenta Corriente").strip()
    banco_base = banco_actual if banco_actual in BANCOS_CHILE else ("Otro" if banco_actual else "Banco de Chile")
    tipo_base = tipo_actual if tipo_actual in TIPOS_CUENTA_CHILE else ("Otra" if tipo_actual else "Cuenta Corriente")
    with st.form(f"{key_prefix}_form"):
        c1,c2 = st.columns(2)
        with c1:
            titular_b = st.text_input("Nombre / Razón Social*", value=actual.get("titular", ""), key=f"{key_prefix}_titular")
            rut_b = st.text_input("RUT*", value=actual.get("rut", ""), key=f"{key_prefix}_rut")
            banco_sel = st.selectbox("Banco*", BANCOS_CHILE, index=BANCOS_CHILE.index(banco_base), key=f"{key_prefix}_banco")
            banco_otro = st.text_input("Otro banco", value=banco_actual if banco_base == "Otro" else "", disabled=banco_sel != "Otro", key=f"{key_prefix}_banco_otro")
        with c2:
            tipo_sel = st.selectbox("Tipo de cuenta*", TIPOS_CUENTA_CHILE, index=TIPOS_CUENTA_CHILE.index(tipo_base), key=f"{key_prefix}_tipo")
            tipo_otro = st.text_input("Otro tipo de cuenta", value=tipo_actual if tipo_base == "Otra" else "", disabled=tipo_sel != "Otra", key=f"{key_prefix}_tipo_otro")
            numero_b = st.text_input("N.º de cuenta*", value=actual.get("numero_cuenta", ""), key=f"{key_prefix}_numero")
            correo_b = st.text_input("Correo electrónico*", value=actual.get("correo_comprobantes", ""), key=f"{key_prefix}_correo")
        guardar_banco = st.form_submit_button("Guardar datos bancarios", type="primary", use_container_width=True)
    if not guardar_banco:
        return
    banco_final = banco_otro.strip() if banco_sel == "Otro" else banco_sel
    tipo_final = tipo_otro.strip() if tipo_sel == "Otra" else tipo_sel
    campos = [titular_b, rut_b, banco_final, tipo_final, numero_b, correo_b]
    if not all(str(x).strip() for x in campos) or "@" not in correo_b:
        st.error("Completa todos los datos bancarios e ingresa un correo válido.")
        return
    with conn.session as ses:
        execute_sql(
            ses,
            "INSERT INTO configuracion_bancaria "
            "(id,titular,rut,banco,tipo_cuenta,numero_cuenta,correo_comprobantes,activo,actualizado_at,actualizado_por) "
            "VALUES (1,%s,%s,%s,%s,%s,%s,1,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET titular=EXCLUDED.titular,rut=EXCLUDED.rut,banco=EXCLUDED.banco,"
            "tipo_cuenta=EXCLUDED.tipo_cuenta,numero_cuenta=EXCLUDED.numero_cuenta,"
            "correo_comprobantes=EXCLUDED.correo_comprobantes,activo=1,"
            "actualizado_at=EXCLUDED.actualizado_at,actualizado_por=EXCLUDED.actualizado_por",
            (titular_b.strip(), rut_b.strip(), banco_final, tipo_final, numero_b.strip(), correo_b.strip().lower(),
             datetime.now().isoformat(), usuario.get("username")),
        )
        ses.commit()
    registrar_auditoria(usuario.get("username"), "ACTUALIZAR_DATOS_BANCARIOS", "configuracion_bancaria", "1", "", "actualizado", "Configuración bancaria maestra")
    limpiar_cache_banco()
    st.success("Datos bancarios guardados.")


def _toggle_fecha_calendario(fecha_iso):
    """CAL-02: alterna una fecha sin consultar la base ni perder selecciones previas."""
    actuales = set(st.session_state.get("fechas_calendario", []))
    if fecha_iso in actuales:
        actuales.remove(fecha_iso)
    else:
        actuales.add(fecha_iso)
    st.session_state.fechas_calendario = sorted(actuales)


def _semana_lunes_domingo(fecha_base):
    """MIN-VIS-02: la semana oficial de minuta siempre es lunes a domingo."""
    if isinstance(fecha_base, str):
        fecha_base = date.fromisoformat(fecha_base)
    lunes = fecha_base - timedelta(days=fecha_base.weekday())
    return lunes, lunes + timedelta(days=6)



def _render_minuta_semanal(df_minuta, fecha_base=None, titulo=True, fechas_visibles=None, titulo_personalizado=None):
    """MIN-VIS-GLOBAL-01: una sola visual de minuta para todos los perfiles autorizados."""
    if df_minuta is None or df_minuta.empty:
        st.info("No hay minuta cargada para este período.")
        return

    datos = df_minuta.copy()
    datos["fecha_dt"] = pd.to_datetime(datos["fecha"], errors="coerce").dt.date
    datos = datos.dropna(subset=["fecha_dt"]).copy()
    if datos.empty:
        st.info("No hay fechas válidas en la minuta.")
        return

    nombres = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    orden_servicios = ["Desayuno", "Almuerzo", "Once", "Cena"]
    orden_opciones = ["OPCION 1", "OPCION 2", "HIPOCALORICO", "TIPO R"]
    opcion_lbl = {"OPCION 1":"Opción 1","OPCION 2":"Opción 2","HIPOCALORICO":"Hipocalórico","TIPO R":"Tipo R"}

    # Los servicios solo aparecen si realmente vienen informados en la minuta.
    servicios_presentes = [str(x) for x in datos["servicio"].dropna().astype(str).unique().tolist() if str(x).strip()]
    servicios = [x for x in orden_servicios if x in servicios_presentes]
    servicios += sorted([x for x in servicios_presentes if x not in servicios])

    # Mismo criterio para las opciones: no reservar espacio para opciones inexistentes.
    opciones_presentes = [str(x).upper() for x in datos["tipo_opcion"].dropna().astype(str).tolist() if str(x).strip()]
    opciones_presentes = list(dict.fromkeys(opciones_presentes))
    opciones = [x for x in orden_opciones if x in opciones_presentes]
    opciones += [x for x in opciones_presentes if x not in opciones]
    if not opciones:
        opciones = ["OPCION 1"]

    if fechas_visibles:
        fechas = []
        for f in fechas_visibles:
            if isinstance(f, str):
                try:
                    f = date.fromisoformat(f)
                except Exception:
                    continue
            if f not in fechas:
                fechas.append(f)
        fechas = sorted(fechas)
    else:
        if fecha_base is None:
            fecha_base = min(datos["fecha_dt"])
        lunes, domingo = _semana_lunes_domingo(fecha_base)
        fechas = [lunes + timedelta(days=i) for i in range(7)]

    if not fechas:
        st.info("No hay fechas seleccionadas.")
        return

    if titulo:
        if titulo_personalizado:
            st.markdown(f"#### {titulo_personalizado}")
        elif fechas_visibles:
            st.markdown("#### 📅 Minuta de tus fechas seleccionadas")
        else:
            st.markdown(f"#### 📅 Semana {fechas[0].strftime('%d/%m/%Y')} → {fechas[-1].strftime('%d/%m/%Y')}")

    def texto_plato(fecha_dia, servicio, opcion):
        gd = datos[
            (datos["fecha_dt"] == fecha_dia)
            & (datos["servicio"].astype(str) == servicio)
            & (datos["tipo_opcion"].fillna("").astype(str).str.upper() == opcion.upper())
        ]
        if gd.empty:
            return "—"
        valores = [str(x).strip() for x in gd["plato"].dropna().tolist() if str(x).strip()]
        valores = list(dict.fromkeys(valores))
        return " / ".join(valores) if valores else "—"

    # Para no deformar pantalla, si el comensal seleccionó más de 7 días,
    # se muestran bloques consecutivos de máximo 7 columnas.
    bloques = [fechas[i:i+7] for i in range(0, len(fechas), 7)]

    st.markdown("""
    <style>
      .alemsi-minuta-wrap{width:100%;overflow-x:auto;margin:8px 0 14px 0;}
      table.alemsi-minuta-grid{width:100%;border-collapse:collapse;table-layout:fixed;background:#fff;font-size:11px;line-height:1.2}
      .alemsi-minuta-grid th,.alemsi-minuta-grid td{border:1px solid #AEBBC7;padding:6px 5px;vertical-align:middle;text-align:center;word-break:break-word}
      .alemsi-minuta-grid th{background:#F3F6F8;color:#17324D;font-size:11px;font-weight:700}
      .alemsi-minuta-grid .servicio{width:72px;font-weight:700;color:#17324D}
      .alemsi-minuta-grid .opcion{width:76px;font-weight:600;color:#334E68}
      .alemsi-minuta-grid .almuerzo{background:#EDF8F1}
      .alemsi-minuta-grid .cena{background:#EEF4FB}
      .alemsi-minuta-grid .desayuno{background:#FFF7E8}
      .alemsi-minuta-grid .once{background:#F7F0FA}
      @media(max-width:900px){
        table.alemsi-minuta-grid{font-size:10px}
        .alemsi-minuta-grid th,.alemsi-minuta-grid td{padding:4px 3px}
      }
    </style>
    """, unsafe_allow_html=True)

    clase_servicio = {"Desayuno":"desayuno","Almuerzo":"almuerzo","Once":"once","Cena":"cena"}

    for bloque in bloques:
        html = '<div class="alemsi-minuta-wrap"><table class="alemsi-minuta-grid"><thead><tr><th colspan="2">Servicio</th>'
        for dia in bloque:
            html += f"<th>{escape(nombres[dia.weekday()])}<br>{dia.strftime('%d/%m')}</th>"
        html += "</tr></thead><tbody>"

        for servicio in servicios:
            # Solo opciones que realmente existen para este servicio en el período visible.
            datos_serv = datos[
                (datos["servicio"].astype(str) == servicio)
                & (datos["fecha_dt"].isin(bloque))
            ]
            if datos_serv.empty:
                continue
            ops_serv_presentes = [str(x).upper() for x in datos_serv["tipo_opcion"].dropna().astype(str).tolist() if str(x).strip()]
            ops_serv_presentes = list(dict.fromkeys(ops_serv_presentes))
            ops_serv = [x for x in opciones if x in ops_serv_presentes]
            if not ops_serv:
                ops_serv = ["OPCION 1"]

            clase = clase_servicio.get(servicio, "")
            for idx, opcion in enumerate(ops_serv):
                html += "<tr>"
                if idx == 0:
                    html += f'<td class="servicio {clase}" rowspan="{len(ops_serv)}">{escape(servicio.upper())}</td>'
                etiqueta = opcion_lbl.get(opcion, opcion.title())
                html += f'<td class="opcion {clase}">{escape(etiqueta)}</td>'
                for dia in bloque:
                    html += f"<td>{escape(texto_plato(dia, servicio, opcion))}</td>"
                html += "</tr>"

        html += "</tbody></table></div>"
        st.markdown(html, unsafe_allow_html=True)


def render_comensal():
    if st.session_state.rut_actual:
        rut=st.session_state.rut_actual
        conn=get_conn()
        com=conn.query("SELECT * FROM comensales WHERE rut=:rut", params={"rut": rut}, ttl=0)
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        tab_reserva, tab_mis_reservas, tab_reclamos = st.tabs(["📅 Reservar","🗂️ Mis reservas","💬 Reclamos"])

        with tab_reserva:
            inst_cf = str(institucion or "").strip().casefold()
            tipo_alemsi = (
                "paso" if inst_cf in {"alemsi", "alemsi paso fronterizo"}
                else "administrativos" if inst_cf == "alemsi administrativos"
                else ""
            )
            es_alemsi = bool(tipo_alemsi)
            es_coordinador_comensal = inst_cf == "coordinadores"
            resultado_anterior = st.session_state.get("resultado_reserva")
            if resultado_anterior:
                if resultado_anterior.get("ok"):
                    st.success(resultado_anterior["mensaje"])
                else:
                    st.warning(resultado_anterior["mensaje"])
                if resultado_anterior.get("referencia"):
                    st.info(f"Referencia de consulta: {resultado_anterior['referencia']}")
                st.markdown("#### Reserva finalizada")
                st.caption("Para terminar este flujo y volver al inicio, utiliza Finalizar.")
                if st.button("✅ Finalizar", type="primary", use_container_width=True, key="cerrar_post_confirmacion"):
                    st.session_state.usuario = None
                    st.session_state.rut_actual = None
                    st.session_state.dias_sel = []
                    st.session_state.pedidos = {}
                    st.session_state.wizard_idx = 0
                    st.session_state.portal_actual = "inicio"
                    st.session_state.fechas_calendario = []
                    st.session_state.pop("resultado_reserva", None)
                    st.rerun()
                st.stop()

            if es_alemsi:
                if tipo_alemsi == "paso":
                    st.info(
                        "ALEMSI Paso Fronterizo: solo se genera ración cuando existe una selección explícita. "
                        "Puedes elegir Opción 1 o Hipocalórico según la minuta disponible. Sin selección = sin ración."
                    )
                else:
                    st.info(
                        "ALEMSI Administrativos: reserva interna sin cobro, normalmente solo Almuerzo. "
                        "Puedes elegir cualquiera de las opciones disponibles del Almuerzo. Sin selección = sin ración."
                    )

            if not st.session_state.dias_sel:
                st.markdown("""
<style>
/* CAL-02: calendario de reserva compacto. */
div[data-testid="stHorizontalBlock"] div[data-testid="column"] button[kind="secondary"],
div[data-testid="stHorizontalBlock"] div[data-testid="column"] button[kind="primary"] {
    min-height: 2.05rem;
}
</style>
""", unsafe_allow_html=True)
                st.markdown("#### 📅 Paso 1: Selecciona las fechas")
                hoy = date.today()
                primer_dia = date(hoy.year, hoy.month, 1)
                ultimo_numero = calendar.monthrange(hoy.year, hoy.month)[1]
                ultimo_dia = date(hoy.year, hoy.month, ultimo_numero)

                # Una lectura cacheada permite mostrar como disponibles solo fechas con minuta real.
                df_disponibilidad = get_minutas_rango(primer_dia.isoformat(), ultimo_dia.isoformat())
                fechas_con_minuta = set(df_disponibilidad["fecha"].astype(str).tolist()) if not df_disponibilidad.empty else set()

                st.markdown(f"### {primer_dia.strftime('%B %Y').capitalize()}")
                st.markdown("""
                <style>
                @media (max-width: 768px) {
                  /* CAL-MOVIL-01: Streamlit apila st.columns por defecto.
                     En el selector de reservas forzamos cada fila calendario a 7 columnas. */
                  div[data-testid="stHorizontalBlock"]:has(.alemsi-cal-cell) {
                      display:grid !important;
                      grid-template-columns:repeat(7,minmax(0,1fr)) !important;
                      gap:3px !important;
                      width:100% !important;
                  }
                  div[data-testid="stHorizontalBlock"]:has(.alemsi-cal-cell) > div[data-testid="column"] {
                      width:auto !important;
                      min-width:0 !important;
                      flex:none !important;
                      padding:0 !important;
                  }
                  div[data-testid="stHorizontalBlock"]:has(.alemsi-cal-cell) button {
                      width:100% !important;
                      min-width:0 !important;
                      min-height:38px !important;
                      padding:2px 0 !important;
                      border-radius:8px !important;
                  }
                  div[data-testid="stHorizontalBlock"]:has(.alemsi-cal-cell) p,
                  div[data-testid="stHorizontalBlock"]:has(.alemsi-cal-cell) button p {
                      font-size:11px !important;
                      line-height:1.05 !important;
                      text-align:center !important;
                      white-space:nowrap !important;
                      margin:0 !important;
                  }
                  .alemsi-cal-disabled {
                      text-align:center;
                      color:#8A98A5;
                      padding:4px 0;
                      font-size:10px;
                      line-height:1.05;
                      min-height:38px;
                  }
                  .alemsi-cal-disabled b {font-size:12px;}
                }
                </style>
                """, unsafe_allow_html=True)
                st.caption(
                    "Puedes elegir un día, fechas consecutivas o fechas intercaladas. "
                    "Los días pasados y los días sin minuta no están disponibles."
                )

                if "fechas_calendario" not in st.session_state:
                    st.session_state.fechas_calendario = []

                seleccion_actual = set(st.session_state.fechas_calendario)
                st.markdown('<span class="alemsi-cal-row"></span>', unsafe_allow_html=True)
                encabezados = st.columns(7)
                for col, titulo in zip(encabezados, ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]):
                    with col:
                        st.markdown('<span class="alemsi-cal-cell"></span>', unsafe_allow_html=True)
                        st.markdown(f"<div style='text-align:center;font-weight:700'>{titulo}</div>", unsafe_allow_html=True)

                semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(hoy.year, hoy.month)
                for semana in semanas:
                    st.markdown('<span class="alemsi-cal-row"></span>', unsafe_allow_html=True)
                    columnas = st.columns(7)
                    for columna, dia in zip(columnas, semana):
                        with columna:
                            st.markdown('<span class="alemsi-cal-cell"></span>', unsafe_allow_html=True)
                            pertenece_mes = dia.month == hoy.month
                            disponible = pertenece_mes and dia >= hoy and (
                                not fechas_con_minuta or dia.isoformat() in fechas_con_minuta
                            )
                            if not pertenece_mes:
                                st.markdown("&nbsp;", unsafe_allow_html=True)
                            elif disponible:
                                fecha_iso = dia.isoformat()
                                seleccionado = fecha_iso in seleccion_actual
                                etiqueta = f"✓ {dia.day}" if seleccionado else str(dia.day)
                                st.button(
                                    etiqueta,
                                    key=f"cal_dia_{fecha_iso}",
                                    use_container_width=True,
                                    type="primary" if seleccionado else "secondary",
                                    on_click=_toggle_fecha_calendario,
                                    args=(fecha_iso,),
                                )
                            else:
                                motivo = "Pasado" if dia < hoy else "Sin minuta"
                                st.markdown(
                                    f"<div class='alemsi-cal-disabled'>"
                                    f"<b>{dia.day}</b><br><small>{motivo}</small></div>",
                                    unsafe_allow_html=True,
                                )

                st.caption(
                    f"Valor de referencia: {formato_clp(precio_dia)} por día. "
                    "El total se calcula al confirmar las fechas."
                    if not es_alemsi else
                    "ALEMSI: sin cobro; las fechas se usan para declarar consumo."
                )

                seleccion = sorted(st.session_state.fechas_calendario)
                if seleccion:
                    st.success(f"{len(seleccion)} fecha(s) seleccionada(s).")

                continuar = st.button(
                    "Elegir menú →" if not es_alemsi else "Declarar consumo →",
                    type="primary",
                    use_container_width=True,
                )

                if continuar:
                    if not seleccion:
                        st.error("Selecciona al menos una fecha disponible para continuar.")
                    else:
                        st.session_state.dias_sel = seleccion
                        st.session_state.pedidos = {dia: {} for dia in seleccion}
                        st.session_state.reserva_revisar = False
                        st.session_state.fechas_calendario = []
                        st.rerun()
            else:
                dias = sorted(st.session_state.dias_sel)
                st.session_state.pedidos = st.session_state.get("pedidos", {}) or {}
                for dia_iso in dias:
                    st.session_state.pedidos.setdefault(dia_iso, {})

                df_minutas = get_minutas_rango(dias[0], dias[-1])
                if not df_minutas.empty:
                    df_minutas = df_minutas[df_minutas["fecha"].astype(str).isin(dias)].copy()

                if not st.session_state.get("reserva_revisar", False):
                    titulo_paso = "🍽️ Paso 2: Declara tu consumo" if es_alemsi else "🍽️ Paso 2: Elige la minuta"
                    st.markdown(f"#### {titulo_paso}")
                    if not df_minutas.empty:
                        _render_minuta_semanal(
                            df_minutas,
                            fechas_visibles=dias,
                            titulo=True,
                            titulo_personalizado="📅 Minuta de las fechas seleccionadas",
                        )
                    if es_alemsi:
                        st.caption("Avanza día por día. Para cada fecha declara los servicios internos disponibles.")
                    else:
                        st.caption(
                            "Avanza día por día. Cada fecha debe tener al menos un servicio seleccionado. "
                            f"El valor del día es {formato_clp(precio_dia)}, independiente de la cantidad de servicios elegidos."
                        )

                    idx = int(st.session_state.get("wizard_idx", 0) or 0)
                    idx = max(0, min(idx, len(dias)-1))
                    st.session_state.wizard_idx = idx
                    f_iso = dias[idx]
                    f_obj = date.fromisoformat(f_iso)
                    dnom = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                    filas_fecha = df_minutas[df_minutas["fecha"].astype(str) == f_iso] if not df_minutas.empty else pd.DataFrame()
                    st.markdown(f"### Día {idx+1} de {len(dias)} · {dnom} {f_obj.strftime('%d/%m/%Y')}")

                    elecciones_dia = {}
                    with st.form(f"menu_dia_{f_iso}", clear_on_submit=False):
                        if es_alemsi:
                            # PROD-35: toda ración interna ALEMSI requiere selección explícita.
                            # Paso Fronterizo: Opción 1 o Hipocalórico. Administrativos: cualquiera de las 3 opciones del Almuerzo.
                            orden_servicios_int = ["Desayuno", "Almuerzo", "Once", "Cena"]
                            servicios_internos = ["Almuerzo"] if tipo_alemsi == "administrativos" else orden_servicios_int
                            tipos_permitidos = {"OPCION 1", "OPCIÓN 1", "HIPOCALORICO", "HIPOCALÓRICO", "TIPO R"} if tipo_alemsi == "paso" else {"OPCION 1", "OPCIÓN 1", "OPCION 2", "OPCIÓN 2", "HIPOCALORICO", "HIPOCALÓRICO", "TIPO R"}
                            disponibles = 0
                            for servicio in servicios_internos:
                                grupo = filas_fecha[filas_fecha["servicio"].astype(str) == servicio].copy() if not filas_fecha.empty else pd.DataFrame()
                                if grupo.empty:
                                    continue
                                grupo["tipo_norm"] = grupo["tipo_opcion"].fillna("").astype(str).str.strip().str.upper()
                                grupo = grupo[grupo["tipo_norm"].isin(tipos_permitidos)]
                                if grupo.empty:
                                    continue
                                disponibles += 1
                                tokens = [""]
                                etiquetas = {"": f"— No reservar {servicio.lower()} —"}
                                mapa = {}
                                for pos, (_, rr) in enumerate(grupo.iterrows()):
                                    tipo = str(rr.get("tipo_opcion") or "").strip()
                                    plato = str(rr.get("plato") or "").strip()
                                    token = f"{pos}|{tipo}|{plato}"
                                    tokens.append(token); mapa[token] = {"plato": plato, "tipo_opcion": tipo, "estado": "Consumirá"}
                                    etiquetas[token] = f"{tipo}: {plato}"
                                actual = st.session_state.pedidos.get(f_iso, {}).get(servicio, {})
                                actual_plato = actual.get("plato", "") if isinstance(actual, dict) else ""
                                indice = 0
                                for it, tok in enumerate(tokens):
                                    if tok and tok.split("|", 2)[2] == actual_plato:
                                        indice = it; break
                                st.markdown(f"**{servicio}**")
                                elegido = st.selectbox(
                                    f"Selecciona tu opción de {servicio}", tokens, index=indice,
                                    format_func=lambda tok, labels=etiquetas: labels.get(tok, tok),
                                    key=f"alemsi_menu_{tipo_alemsi}_{f_iso}_{servicio}",
                                )
                                if elegido:
                                    elecciones_dia[servicio] = mapa[elegido]
                            if disponibles == 0:
                                st.warning("No existen opciones habilitadas para este perfil ALEMSI en esta fecha.")
                        else:
                            orden_servicios = ["Desayuno", "Almuerzo", "Once", "Cena"]
                            iconos_servicio = {"Desayuno":"🍳", "Almuerzo":"🍽️", "Once":"☕", "Cena":"🌙"}
                            opciones_por_servicio = {}
                            if not filas_fecha.empty:
                                for servicio, grupo in filas_fecha.groupby("servicio", sort=False):
                                    nombre_servicio = str(servicio)
                                    opciones_por_servicio[nombre_servicio] = [
                                        {"plato": str(row["plato"]), "tipo": str(row.get("tipo_opcion") or "").strip()}
                                        for _, row in grupo.iterrows()
                                    ]
                            if not opciones_por_servicio:
                                st.warning("No existe minuta configurada para esta fecha.")
                            servicios_visibles = [x for x in orden_servicios if opciones_por_servicio.get(x)]
                            servicios_visibles += sorted([x for x in opciones_por_servicio if x not in servicios_visibles])
                            for servicio in servicios_visibles:
                                registros = opciones_por_servicio.get(servicio, [])
                                icono = iconos_servicio.get(servicio, "🍴")
                                with st.expander(f"{icono} {servicio}", expanded=False):
                                    tokens = [""]
                                    etiquetas = {"": f"— No reservar {servicio.lower()} —"}
                                    for pos, registro in enumerate(registros):
                                        token = f"{pos}|{registro['tipo']}|{registro['plato']}"
                                        tokens.append(token)
                                        prefijo = f"{registro['tipo']}: " if registro['tipo'] else ""
                                        etiquetas[token] = f"{prefijo}{registro['plato']}"
                                    actual = st.session_state.pedidos.get(f_iso, {}).get(servicio, "")
                                    indice = 0
                                    if actual:
                                        for idx_token, token in enumerate(tokens):
                                            if token and token.split("|", 2)[2] == actual:
                                                indice = idx_token
                                                break
                                    elegido = st.selectbox(
                                        f"Selecciona una opción de {servicio}", tokens, index=indice,
                                        format_func=lambda token, mapa=etiquetas: mapa[token],
                                        key=f"menu_v2132_{f_iso}_{servicio}",
                                    )
                                    if elegido:
                                        elecciones_dia[servicio] = elegido.split("|", 2)[2]

                        st.divider()
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            cambiar = st.form_submit_button("← Cambiar fechas", use_container_width=True)
                        with c2:
                            anterior = st.form_submit_button("← Día anterior", use_container_width=True, disabled=idx==0)
                        with c3:
                            etiqueta = "Revisar reserva →" if idx == len(dias)-1 else "Siguiente día →"
                            siguiente = st.form_submit_button(etiqueta, type="primary", use_container_width=True)

                    if cambiar:
                        st.session_state.dias_sel = []
                        st.session_state.pedidos = {}
                        st.session_state.wizard_idx = 0
                        st.session_state.reserva_revisar = False
                        st.rerun()
                    if anterior:
                        if elecciones_dia:
                            st.session_state.pedidos[f_iso] = elecciones_dia
                        st.session_state.wizard_idx = max(0, idx-1)
                        st.rerun()
                    if siguiente:
                        if es_alemsi:
                            if not elecciones_dia:
                                st.error("Selecciona al menos una ración para este día. Sin selección no se genera producción.")
                            else:
                                st.session_state.pedidos[f_iso] = elecciones_dia
                                if idx < len(dias)-1:
                                    st.session_state.wizard_idx = idx+1
                                else:
                                    st.session_state.reserva_revisar = True
                                st.rerun()
                        else:
                            if not elecciones_dia:
                                st.error("Selecciona al menos un servicio para este día antes de continuar.")
                            else:
                                st.session_state.pedidos[f_iso] = elecciones_dia
                                if idx < len(dias)-1:
                                    st.session_state.wizard_idx = idx+1
                                else:
                                    dias_sin = [d for d in dias if not st.session_state.pedidos.get(d)]
                                    if dias_sin:
                                        st.error("Faltan selecciones en: " + ", ".join(date.fromisoformat(d).strftime('%d/%m') for d in dias_sin))
                                    else:
                                        st.session_state.reserva_revisar = True
                                st.rerun()
                else:
                    st.markdown("#### ✅ Paso 3: Revisa y confirma")
                    detalle = []
                    for f_iso in dias:
                        f_obj = date.fromisoformat(f_iso)
                        dnom = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                        for servicio, seleccion_servicio in st.session_state.pedidos.get(f_iso, {}).items():
                            if es_alemsi:
                                detalle.append((f_iso, dnom, servicio, seleccion_servicio["plato"], seleccion_servicio.get("tipo_opcion", "")))
                            else:
                                detalle.append((f_iso, dnom, servicio, seleccion_servicio, get_precio(seleccion_servicio, servicio)))

                    if not detalle:
                        st.error("No hay datos seleccionados.")
                        st.session_state.reserva_revisar = False
                        st.stop()

                    if es_alemsi:
                        df_detalle = pd.DataFrame(detalle, columns=["Fecha", "Día", "Servicio", "Plato", "Opción"])
                        st.dataframe(df_detalle, use_container_width=True, hide_index=True)
                        st.metric("Raciones reservadas", len(df_detalle))
                        st.caption("Solo las selecciones mostradas sumarán a Producción. No genera cobro ni comprobante de pago.")
                        with st.form("confirmar_consumo_alemsi_v21"):
                            c1, c2 = st.columns(2)
                            with c1:
                                editar = st.form_submit_button("← Editar", use_container_width=True)
                            with c2:
                                confirmar = st.form_submit_button("Guardar declaración", type="primary", use_container_width=True)
                    else:
                        df_detalle = pd.DataFrame(
                            [(f, d, serv, plato) for f, d, serv, plato, _ in detalle],
                            columns=["Fecha", "Día", "Servicio", "Plato"],
                        )
                        total_real = len(dias) * precio_dia
                        st.dataframe(df_detalle, use_container_width=True, hide_index=True)
                        st.caption(f"Tarifa aplicada: {formato_clp(precio_dia)} por día, independiente de la cantidad de servicios seleccionados.")
                        c1, c2 = st.columns(2)
                        with c1:
                            st.metric("Días reservados", len(dias))
                        with c2:
                            st.metric("Valor referencial" if es_coordinador_comensal else "Total a pagar", formato_clp(total_real))
                        with st.form("confirmar_reserva_comercial_v21"):
                            if es_coordinador_comensal:
                                metodo = "Costo asumido · Coordinadores"
                                st.info("Coordinadores: el consumo se valoriza para control financiero, pero no genera cobro ni bloquea futuras reservas.")
                            else:
                                metodo = st.selectbox("Método de pago*", ["Transferencia bancaria", "Débito en la instalación"])
                            aceptar = st.checkbox("Confirmo que las fechas, servicios y platos son correctos.")
                            c1, c2 = st.columns(2)
                            with c1:
                                editar = st.form_submit_button("← Editar menús", use_container_width=True)
                            with c2:
                                confirmar = st.form_submit_button("Confirmar reserva", type="primary", use_container_width=True)

                    if editar:
                        st.session_state.reserva_revisar = False
                        st.rerun()

                    if confirmar:
                        if not es_alemsi and not aceptar:
                            st.error("Debes confirmar que revisaste la reserva.")
                            st.stop()

                        conn = get_conn()
                        vouchers = []
                        referencia_reserva = gen_referencia_reserva(rut)
                        correo_cli = str(com.iloc[0].get("correo") or "").strip()
                        try:
                            with conn.session as sesion:
                                if es_alemsi:
                                    for f_iso, dnom, servicio, plato, tipo_opcion_int in detalle:
                                        estado_bd = "Consumirá"
                                        clave_bloqueo = f"{rut}|{f_iso}|{servicio}"
                                        execute_sql(sesion, "SELECT pg_advisory_xact_lock(hashtext(%s))", (clave_bloqueo,))
                                        existente = execute_sql(
                                            sesion,
                                            "SELECT id,referencia_reserva FROM solicitudes WHERE rut=%s AND fecha=%s AND servicio=%s AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA' ORDER BY id DESC LIMIT 1 FOR UPDATE",
                                            (rut, f_iso, servicio),
                                        ).mappings().first()
                                        ahora_iso = datetime.now().isoformat()
                                        if existente:
                                            referencia_reserva = str(existente.get("referencia_reserva") or referencia_reserva)
                                            if not _reserva_modificable_v40(rut, f_iso, servicio):
                                                raise ValueError(f"{servicio} del {date.fromisoformat(f_iso).strftime('%d/%m/%Y')} ya no puede modificarse porque faltan menos de 48 horas.")
                                            execute_sql(
                                                sesion,
                                                "UPDATE solicitudes SET plato=%s,plato_reservado=%s,tipo_opcion=%s,precio=%s,precio_aplicado=%s,institucion=%s,correo=%s,metodo_pago=%s,estado_pago=%s,estado_consumo=%s,fecha_modificacion=%s,modificado_por=%s,referencia_reserva=%s,tipo_registro=%s,estado_reserva='ACTIVA' WHERE id=%s",
                                                (plato, plato, tipo_opcion_int, 0, 0, institucion, correo_cli, "Interno ALEMSI", "No aplica", estado_bd, ahora_iso, rut, referencia_reserva, "CONSUMO_INTERNO", existente["id"]),
                                            )
                                        else:
                                            execute_sql(
                                                sesion,
                                                "INSERT INTO solicitudes "
                                                "(rut,fecha,servicio,plato,plato_reservado,tipo_opcion,codigo,precio,precio_aplicado,institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion,fecha_modificacion,modificado_por,referencia_reserva,tipo_registro) "
                                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                                (rut, f_iso, servicio, plato, plato, tipo_opcion_int, None, 0, 0, institucion, correo_cli, "Interno ALEMSI", "No aplica", estado_bd, ahora_iso, ahora_iso, rut, referencia_reserva, "CONSUMO_INTERNO"),
                                            )
                                else:
                                    precio_por_linea = {}
                                    for f_iso in dias:
                                        lineas_dia = [linea for linea in detalle if linea[0] == f_iso]
                                        base_linea, resto = divmod(int(precio_dia), len(lineas_dia))
                                        for pos, linea in enumerate(lineas_dia):
                                            precio_por_linea[(linea[0], linea[2], linea[3])] = base_linea + (1 if pos < resto else 0)
                                    for f_iso, dnom, servicio, plato, precio_ref in detalle:
                                        codigo = gen_codigo(rut, servicio, date.fromisoformat(f_iso))
                                        clave_bloqueo = f"{rut}|{f_iso}|{servicio}"
                                        execute_sql(sesion, "SELECT pg_advisory_xact_lock(hashtext(%s))", (clave_bloqueo,))
                                        existente = execute_sql(
                                            sesion,
                                            "SELECT id,codigo,referencia_reserva FROM solicitudes WHERE rut=%s AND fecha=%s AND servicio=%s AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA' ORDER BY id DESC LIMIT 1 FOR UPDATE",
                                            (rut, f_iso, servicio),
                                        ).mappings().first()
                                        ahora_iso = datetime.now().isoformat()
                                        if existente:
                                            referencia_reserva = str(existente.get("referencia_reserva") or referencia_reserva)
                                            if not _reserva_modificable_v40(rut, f_iso, servicio):
                                                raise ValueError(f"{servicio} del {date.fromisoformat(f_iso).strftime('%d/%m/%Y')} ya no puede modificarse porque faltan menos de 48 horas.")
                                            codigo = existente.get("codigo") or codigo
                                            execute_sql(
                                                sesion,
                                                "UPDATE solicitudes SET plato=%s,plato_reservado=%s,precio=%s,precio_aplicado=%s,institucion=%s,correo=%s,metodo_pago=%s,estado_pago=%s,estado_consumo=%s,fecha_modificacion=%s,modificado_por=%s,referencia_reserva=%s,tipo_registro=%s,estado_reserva='ACTIVA' WHERE id=%s",
                                                (plato, plato, precio_por_linea[(f_iso, servicio, plato)], precio_por_linea[(f_iso, servicio, plato)], institucion, correo_cli, metodo, "Costo asumido" if es_coordinador_comensal else "Pendiente", "Pendiente", ahora_iso, rut, referencia_reserva, "CONSUMO_COORDINADOR" if es_coordinador_comensal else "RESERVA_COMERCIAL", existente["id"]),
                                            )
                                        else:
                                            execute_sql(
                                                sesion,
                                                "INSERT INTO solicitudes "
                                                "(rut,fecha,servicio,plato,plato_reservado,codigo,precio,precio_aplicado,institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion,fecha_modificacion,modificado_por,referencia_reserva,tipo_registro) "
                                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                                (rut, f_iso, servicio, plato, plato, codigo, precio_por_linea[(f_iso, servicio, plato)], precio_por_linea[(f_iso, servicio, plato)], institucion, correo_cli, metodo, "Costo asumido" if es_coordinador_comensal else "Pendiente", "Pendiente", ahora_iso, ahora_iso, rut, referencia_reserva, "CONSUMO_COORDINADOR" if es_coordinador_comensal else "RESERVA_COMERCIAL"),
                                            )
                                        vouchers.append(codigo)
                                sesion.commit()
                        except Exception as error_guardado:
                            st.error(f"No fue posible guardar. No se enviaron correos. Detalle: {error_guardado}")
                            st.stop()

                        if es_alemsi:
                            # Bodega NO se descuenta por reservar/declarar. El movimiento se
                            # realizará al iniciar producción en Cocina, tras validar el flujo.
                            mensaje_resultado = "Declaración ALEMSI guardada correctamente."
                            ok_resultado = True
                        else:
                            # Bodega NO se descuenta al crear la reserva.
                            total_real = len(dias) * precio_dia
                            resumen_fechas = ", ".join(
                                f"{['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'][date.fromisoformat(f).weekday()]} {date.fromisoformat(f).strftime('%d/%m')}"
                                for f in dias
                            )
                            if es_coordinador_comensal:
                                pago_token = ""
                                url_comprobante = ""
                                bloque_link = "<p style='margin:18px 0;background:#eef6ff;padding:12px;border-radius:8px'><b>Consumo valorizado para control interno.</b> No requiere pago ni comprobante.</p>"
                                banco_cfg = {}
                            else:
                                pago_token = secrets.token_urlsafe(32)
                                with conn.session as sesion_token:
                                    execute_sql(sesion_token, "UPDATE solicitudes SET pago_token=%s WHERE referencia_reserva=%s", (pago_token, referencia_reserva))
                                    sesion_token.commit()
                                url_comprobante = _url_carga_comprobante(pago_token)
                                bloque_link = f"<p style='margin:18px 0'><a href='{url_comprobante}' style='background:#086B37;color:white;padding:12px 18px;text-decoration:none;border-radius:8px;font-weight:bold'>SUBIR COMPROBANTE DE PAGO</a></p>"
                                banco_cfg = get_config_bancaria() if str(metodo).strip().casefold() == "transferencia bancaria".casefold() else {}
                            detalle_html = _detalle_html_por_dia(detalle)
                            pdf_reserva = generar_pdf_reserva(nombre,rut,institucion,referencia_reserva,detalle,precio_dia,total_real,metodo,url_comprobante)
                            if banco_cfg:
                                bloque_banco = f"""
                                <div style='background:#f7fbfa;border:1px solid #cfe3df;padding:14px;border-radius:10px;margin:14px 0'>
                                  <h3 style='margin-top:0;color:#0A2F6B'>Datos para transferencia</h3>
                                  <p style='font-size:12px;color:#666'>Cada dato está en una línea independiente para copiarlo fácilmente desde el teléfono.</p>
                                  <div style='font-size:15px;line-height:1.75'>
                                    <div><b>Titular:</b><br><span style='font-family:monospace'>{banco_cfg.get('titular','')}</span></div>
                                    <div><b>RUT:</b><br><span style='font-family:monospace'>{banco_cfg.get('rut','')}</span></div>
                                    <div><b>Banco:</b><br><span style='font-family:monospace'>{banco_cfg.get('banco','')}</span></div>
                                    <div><b>Tipo de cuenta:</b><br><span style='font-family:monospace'>{banco_cfg.get('tipo_cuenta','')}</span></div>
                                    <div><b>N° de cuenta:</b><br><span style='font-family:monospace'>{banco_cfg.get('numero_cuenta','')}</span></div>
                                    <div><b>Correo:</b><br><span style='font-family:monospace'>{banco_cfg.get('correo_comprobantes','')}</span></div>
                                    <div><b>Monto:</b><br><span style='font-family:monospace'>{formato_clp(total_real)}</span></div>
                                    <div><b>Referencia:</b><br><span style='font-family:monospace'>{referencia_reserva}</span></div>
                                  </div>
                                  <div style='margin-top:12px;padding:10px;background:#fff;border:1px dashed #b9d2ca;border-radius:8px;font-family:monospace;white-space:pre-line'>Titular: {banco_cfg.get('titular','')}
RUT: {banco_cfg.get('rut','')}
Banco: {banco_cfg.get('banco','')}
Tipo: {banco_cfg.get('tipo_cuenta','')}
Cuenta: {banco_cfg.get('numero_cuenta','')}
Correo: {banco_cfg.get('correo_comprobantes','')}
Monto: {formato_clp(total_real)}
Referencia: {referencia_reserva}</div>
                                </div>
                                """
                            else:
                                bloque_banco = ""
                            html_comprobante = f"""
                            <div style="font-family:Arial,sans-serif;padding:24px;border:2px solid #0A2F6B;border-radius:16px;max-width:760px">
                              <div style="background:#0A2F6B;padding:20px;border-radius:12px;color:white;text-align:center"><h1 style="margin:0;color:white">🍽️ Mamuil Malal</h1><p>Comprobante de reserva</p></div>
                              <h2 style="color:#0A2F6B">Hola {nombre}</h2>
                              <p style="font-size:18px"><b>Referencia:</b> {referencia_reserva}</p>
                              <p><b>RUT:</b> {rut} · <b>Institución:</b> {institucion}</p>
                              <p><b>Fecha de emisión:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                              <p><b>Días:</b> {len(dias)} · <b>Valor total de la reserva:</b> {formato_clp(total_real)}</p>
                              <p><b>Modalidad:</b> {metodo} · <b>Estado:</b> {'Costo asumido / no cobrable' if es_coordinador_comensal else 'Pendiente'}</p>
                              {bloque_banco}
                              <p><b>Fechas:</b> {resumen_fechas}</p>
                              <h3 style="color:#0A2F6B">Detalle de reserva</h3>{detalle_html}
                              <div style="background:#F1F6F3;padding:14px;border-radius:10px;margin-top:14px"><b>Sube tu comprobante aquí</b>{bloque_link}<span style="font-size:13px">El pago no es obligatorio antes del consumo. Puedes utilizar este mismo enlace cuando corresponda.</span><p style="margin-bottom:0"><b>Gracias por utilizar nuestra aplicación.</b> Después de cargar tu comprobante, esta misma ventana se actualizará para que puedas calificar primero el servicio de Casino Mamuil Malal y, debajo, la APP ALEMSI.</p></div>
                            </div>"""
                            adjuntos=[(f"Reserva_{referencia_reserva}.pdf",pdf_reserva,"pdf")]
                            correo_ok, correo_msg = enviar_email(correo_cli, f"Reserva {referencia_reserva} · Mamuil Malal", html_comprobante, adjuntos=adjuntos)
                            # MAIL-02: al confirmar se notifica solo al comensal.
                            # Cocina recibirá posteriormente un resumen consolidado de producción,
                            # evitando un correo individual por cada reserva.
                            mensaje_resultado = f"¡Felicitaciones! Tu reserva fue realizada con éxito. Te esperamos. Comprobante enviado a {correo_cli}." if correo_ok else f"Tu reserva fue realizada con éxito, referencia {referencia_reserva}, pero el comprobante no pudo enviarse: {correo_msg}"
                            ok_resultado = correo_ok

                        st.session_state.dias_sel = []
                        st.session_state.pedidos = {}
                        st.session_state.reserva_revisar = False
                        st.session_state.resultado_reserva = {"ok": ok_resultado, "mensaje": mensaje_resultado, "vouchers": vouchers, "referencia": referencia_reserva}
                        st.rerun()

        with tab_mis_reservas:
            st.markdown("#### 🗂️ Mis reservas activas")
            df_mis = conn.query("""
                SELECT referencia_reserva, MIN(fecha) AS desde, MAX(fecha) AS hasta,
                       COUNT(*) AS servicios, MAX(COALESCE(estado_pago,'Pendiente')) AS estado_pago
                FROM solicitudes
                WHERE rut=:rut AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA'
                  AND COALESCE(NULLIF(referencia_reserva,''),'')<>''
                GROUP BY referencia_reserva
                ORDER BY MIN(fecha) DESC
            """, params={"rut": rut}, ttl=0)
            if df_mis.empty:
                st.info("No tienes reservas activas registradas.")
            else:
                st.dataframe(_tabla_visible(df_mis,{"referencia_reserva":"Referencia","desde":"Desde","hasta":"Hasta","servicios":"Servicios","estado_pago":"Estado pago"},["desde","hasta"]),use_container_width=True,hide_index=True)
                ref_cancel = selector_neutro("Reserva a cancelar", df_mis["referencia_reserva"].astype(str).tolist(), key="comensal_cancel_ref")
                if ref_cancel:
                    lineas_cancel = conn.query("SELECT id,fecha,servicio,plato_reservado FROM solicitudes WHERE rut=:rut AND referencia_reserva=:ref AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA' ORDER BY fecha,servicio",params={"rut":rut,"ref":ref_cancel},ttl=0)
                    st.dataframe(_tabla_visible(lineas_cancel,{"fecha":"Fecha","servicio":"Servicio","plato_reservado":"Plato"},["fecha"]),use_container_width=True,hide_index=True)
                    bloqueadas=[]
                    for _,lr in lineas_cancel.iterrows():
                        if not _reserva_modificable_v40(rut,str(lr["fecha"]),str(lr["servicio"])):
                            bloqueadas.append(f"{fecha_visible(lr['fecha'])} · {lr['servicio']}")
                    if bloqueadas:
                        st.warning("No se puede cancelar esta reserva porque contiene servicios fuera de la ventana permitida: " + ", ".join(bloqueadas))
                    else:
                        confirmar_cancel=st.checkbox("Confirmo que deseo cancelar esta reserva",key=f"cancel_ok_{ref_cancel}")
                        if st.button("Cancelar reserva",type="primary",use_container_width=True,disabled=not confirmar_cancel,key=f"cancel_btn_{ref_cancel}"):
                            ahora_cancel=datetime.now().isoformat()
                            with conn.session as ses_cancel:
                                execute_sql(ses_cancel,"UPDATE solicitudes SET estado_reserva='CANCELADA',fecha_modificacion=%s,modificado_por=%s WHERE rut=%s AND referencia_reserva=%s AND COALESCE(estado_reserva,'ACTIVA')='ACTIVA'",(ahora_cancel,rut,rut,ref_cancel))
                                ses_cancel.commit()
                            registrar_auditoria(rut,'CANCELAR_RESERVA','solicitudes',ref_cancel,'ACTIVA','CANCELADA','Cancelación solicitada por el comensal; histórico conservado')
                            st.success("Reserva cancelada sin borrar historial. Producción ya no la considerará.")
                            st.rerun()

        with tab_reclamos:
            with st.form("reclamo"):
                tipo=st.selectbox("Tipo", ["Reclamo","Sugerencia","Felicitación"])
                categoria=st.selectbox("Categoría", ["Comida","Atención","Higiene","Infraestructura","Otro"])
                mensaje=st.text_area("Mensaje*")
                if st.form_submit_button("Enviar", type="primary", use_container_width=True):
                    if mensaje:
                        conn=get_conn()
                        fecha_envio = datetime.now()
                        with conn.session as s:
                            execute_sql(s, "INSERT INTO reclamos_sugerencias (rut,nombre,tipo,categoria,mensaje,fecha,estado) VALUES (%s,%s,%s,%s,%s,%s,%s)", (rut,nombre,tipo,categoria,mensaje, fecha_envio.isoformat(),"Pendiente"))
                            s.commit()
                        html_reclamo = f"""
                        <div style="font-family:Arial,sans-serif;max-width:680px;padding:20px;border:1px solid #ddd;border-radius:12px">
                          <h2 style="color:#0A2F6B">{tipo} recibido - Mamuil Malal</h2>
                          <p><b>Fecha:</b> {fecha_envio.strftime('%d/%m/%Y %H:%M')}</p>
                          <p><b>Comensal:</b> {nombre}</p><p><b>RUT:</b> {rut}</p>
                          <p><b>Categoría:</b> {categoria}</p>
                          <div style="background:#f7f7f7;padding:14px;border-radius:8px"><b>Mensaje:</b><br>{mensaje}</div>
                        </div>
                        """
                        resultados = []
                        for destino in get_correos("reclamos"):
                            resultados.append(enviar_email(destino, f"[{tipo.upper()}] {categoria} - {nombre}", html_reclamo))
                        enviados = sum(1 for ok, _ in resultados if ok)
                        if enviados:
                            st.success(f"Enviado y notificado por correo ({enviados} destinatario(s) demo).")
                        else:
                            detalle_error = resultados[0][1] if resultados else "Sin destinatarios configurados"
                            st.warning(f"Guardado en el sistema, pero no se pudo enviar el correo: {detalle_error}")
    else:
        st.markdown("### Reserva de alimentación")
        rut_raw=st.text_input("RUT", placeholder="Ej.: 12.345.678-5")
        if rut_raw:
            if not validar_rut_m11(rut_raw):
                st.error("RUT inválido")
            else:
                rn=normalizar_rut_db(rut_raw); rv=normalizar_rut(rut_raw)
                conn=get_conn()
                df=conn.query("SELECT * FROM comensales WHERE rut=:rut", params={"rut": rn}, ttl=0)
                if not df.empty:
                    st.success(f"Hola {df.iloc[0]['nombre']} - {rv}")
                    if st.button("Entrar", type="primary", use_container_width=True):
                        st.session_state.rut_actual=rn; st.rerun()
                else:
                    st.info(f"Primera vez - {rv}")
                    instit_list = get_instituciones()
                    with st.form("reg"):
                        c1,c2=st.columns(2)
                        with c1:
                            nombre=st.text_input("Nombre*"); tel=st.text_input("Teléfono*")
                        with c2:
                            correo=st.text_input("Correo*"); institucion=selector_neutro("Institución*", instit_list, key="registro_institucion")
                        if st.form_submit_button("Registrarme", type="primary", use_container_width=True):
                            correo_norm = normalizar_correo(correo)
                            telefono_norm = normalizar_telefono_chile(tel)
                            if not nombre.strip() or not institucion:
                                st.error("Completa nombre e institución.")
                            elif not validar_correo_estructura(correo_norm):
                                st.error("Ingresa un correo con estructura válida.")
                            elif not dominio_correo_resuelve(correo_norm):
                                st.error("El dominio del correo no existe o no pudo resolverse. Revisa la dirección.")
                            elif not telefono_movil_chile_valido(tel):
                                st.error("Ingresa un móvil chileno válido, por ejemplo +56 9 1234 5678.")
                            else:
                                conn=get_conn()
                                with conn.session as ses_reg:
                                    execute_sql(ses_reg, "INSERT INTO comensales (rut,nombre,telefono,correo,institucion,fecha_registro) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (rut) DO UPDATE SET nombre=%s, telefono=%s, correo=%s, institucion=%s", (rn,nombre.strip(),telefono_norm,correo_norm,institucion, datetime.now().isoformat(), nombre.strip(), telefono_norm, correo_norm, institucion))
                                    ses_reg.commit()
                                st.session_state.rut_actual=rn; st.rerun()


def _normalizar_carga_bodega(df):
    """BOD-04: estructura única para CSV/Excel, inventario y pedidos."""
    if df is None or df.empty:
        return pd.DataFrame()
    mapa = {}
    for columna in df.columns:
        clave = str(columna).strip().casefold()
        if clave in ["codigo", "código", "codigo_insumo", "sku"]:
            mapa[columna] = "codigo_insumo"
        elif clave in ["familia", "categoria", "categoría"]:
            mapa[columna] = "familia"
        elif clave in ["articulo", "artículo", "nombre", "nombre_articulo", "producto"]:
            mapa[columna] = "nombre_articulo"
        elif clave in ["unidad", "unidad_medida", "u.m."]:
            mapa[columna] = "unidad"
        elif clave in ["seccion", "sección", "ubicacion", "ubicación"]:
            mapa[columna] = "seccion"
        elif clave in ["stock", "cantidad", "stock_inicial"]:
            mapa[columna] = "stock"
        elif clave in ["critico", "crítico", "stock_critico", "stock crítico"]:
            mapa[columna] = "critico"
        elif clave in ["precio", "valor"]:
            mapa[columna] = "precio"
        elif clave in ["caduca", "vencimiento", "fecha_vencimiento"]:
            mapa[columna] = "caduca"
    salida = df.rename(columns=mapa).copy()
    orden = [
        "codigo_insumo", "familia", "nombre_articulo", "unidad",
        "seccion", "stock", "critico", "precio", "caduca",
    ]
    for columna in orden:
        if columna not in salida.columns:
            salida[columna] = None
    return salida[orden]


def _render_platos_tres_columnas(df, plato_col="plato", valor_col="porciones"):
    """COC-VIS-01: ranking legible en tres columnas con cantidad y porcentaje."""
    if df is None or df.empty:
        st.info("No hay producción para visualizar.")
        return
    datos = df.copy()
    datos[valor_col] = pd.to_numeric(datos[valor_col], errors="coerce").fillna(0)
    datos = (
        datos.groupby(plato_col, as_index=False)[valor_col]
        .sum()
        .sort_values(valor_col, ascending=False)
        .reset_index(drop=True)
    )
    total = float(datos[valor_col].sum()) or 1.0
    datos["porcentaje"] = datos[valor_col] / total * 100.0
    columnas = st.columns(3)
    for indice, (_, fila) in enumerate(datos.iterrows()):
        with columnas[indice % 3]:
            cantidad = float(fila[valor_col])
            cantidad_txt = str(int(cantidad)) if cantidad.is_integer() else f"{cantidad:.1f}"
            st.markdown(
                "**{}**<br>{} porciones · {:.1f}%".format(
                    fila[plato_col], cantidad_txt, float(fila["porcentaje"])
                ),
                unsafe_allow_html=True,
            )
            st.progress(min(max(float(fila["porcentaje"]) / 100.0, 0.0), 1.0))


def _asegurar_revision_coordinacion():
    """Estructura incremental: no altera la minuta oficial; guarda solo revisión/propuestas."""
    conn = get_conn()
    with conn.session as ses:
        execute_sql(ses, """
            CREATE TABLE IF NOT EXISTS minuta_revision_coordinacion (
                id SERIAL PRIMARY KEY, fecha TEXT NOT NULL, servicio TEXT NOT NULL,
                tipo_opcion TEXT NOT NULL, plato_actual TEXT, accion TEXT NOT NULL,
                observacion TEXT, plato_propuesto TEXT, usuario TEXT,
                fecha_accion TEXT, estado TEXT DEFAULT 'Pendiente'
            )
        """)
        execute_sql(ses, """
            CREATE TABLE IF NOT EXISTS receta_revision_coordinacion (
                id SERIAL PRIMARY KEY, plato TEXT NOT NULL, version_receta INTEGER,
                accion TEXT NOT NULL, observacion TEXT, usuario TEXT,
                fecha_accion TEXT, estado TEXT DEFAULT 'Pendiente'
            )
        """)
        ses.commit()


def _sincronizar_maestro_platos():
    """Agrega al maestro nombres históricos de minutas sin borrar ni cambiar costos existentes."""
    conn = get_conn()
    with conn.session as ses:
        execute_sql(ses, """
            INSERT INTO platos (nombre,servicio,valor,activo,descripcion,tipo_plato)
            SELECT DISTINCT TRIM(m.plato), m.servicio, 0, 1, 'Importado desde minuta histórica',
                   CASE WHEN UPPER(TRIM(COALESCE(m.tipo_opcion,'')))='HIPOCALORICO' THEN 'Hipocalórico' ELSE NULL END
            FROM minutas m
            WHERE COALESCE(m.activo,1)=1 AND TRIM(COALESCE(m.plato,''))<>''
              AND NOT EXISTS (
                SELECT 1 FROM platos p
                WHERE LOWER(TRIM(p.nombre))=LOWER(TRIM(m.plato))
              )
        """)
        ses.commit()


def _alertas_preventivas_minuta(df):
    """Semáforo orientativo; nunca bloquea la minuta."""
    if df is None or df.empty: return []
    alertas=[]
    prot={"pollo":"pollo","cerdo":"cerdo","vacuno":"vacuno","carne":"vacuno","pescado":"pescado","atún":"pescado","atun":"pescado","pavo":"pavo"}
    for fecha, grp in df.groupby('fecha'):
        hall=[]
        for plato in grp['plato'].astype(str):
            low=plato.lower()
            for k,v in prot.items():
                if k in low: hall.append(v); break
        reps=sorted({x for x in hall if hall.count(x)>1})
        if reps: alertas.append(f"{fecha}: proteína repetida ({', '.join(reps)}).")
        caldos=sum(any(k in str(x).lower() for k in ['sopa','caldo','carbonada','cazuela','valdiviano']) for x in grp['plato'])
        if caldos>=2: alertas.append(f"{fecha}: revisar concentración de preparaciones húmedas/caldo.")
    return alertas


def _cargar_demanda_produccion_fecha(fecha_iso):
    """Fuente única de verdad para conteo operativo por fecha.

    Deduplica por RUT+fecha+servicio tomando el registro más reciente, evitando
    que una corrección o reintento histórico sume una segunda ración.
    """
    conn = get_conn()
    df_prod = conn.query(
        """
        WITH base AS (
            SELECT DISTINCT ON (s.rut,s.fecha,s.servicio)
                   s.id,s.rut,s.fecha,s.servicio,s.institucion,s.tipo_registro,s.estado_consumo,
                   COALESCE(s.plato_reservado,s.plato) AS plato,
                   COALESCE(NULLIF(TRIM(s.tipo_opcion),''),
                       (SELECT m.tipo_opcion FROM minutas m
                        WHERE m.fecha=s.fecha AND m.servicio=s.servicio AND m.activo=1 AND COALESCE(m.estado,'PUBLICABLE')='PUBLICABLE'
                          AND UPPER(TRIM(m.plato))=UPPER(TRIM(COALESCE(s.plato_reservado,s.plato)))
                        ORDER BY m.id DESC LIMIT 1), '') AS tipo_opcion
            FROM solicitudes s
            WHERE s.fecha=:fecha
              AND COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA'
              AND (COALESCE(s.tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO'
                   OR s.estado_consumo='Consumirá')
            ORDER BY s.rut,s.fecha,s.servicio,s.id DESC
        )
        SELECT servicio,tipo_opcion,plato,COUNT(*) AS reservadas
        FROM base
        GROUP BY servicio,tipo_opcion,plato
        ORDER BY CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,
                 tipo_opcion,plato
        """, params={"fecha":fecha_iso}, ttl=0
    )
    df_alemsi = conn.query(
        """
        WITH base AS (
            SELECT DISTINCT ON (s.rut,s.fecha,s.servicio)
                   s.id,s.rut,s.fecha,s.servicio,s.institucion,s.estado_consumo,
                   COALESCE(s.plato_reservado,s.plato) AS plato,
                   COALESCE(NULLIF(TRIM(s.tipo_opcion),''),
                       (SELECT m.tipo_opcion FROM minutas m
                        WHERE m.fecha=s.fecha AND m.servicio=s.servicio AND m.activo=1 AND COALESCE(m.estado,'PUBLICABLE')='PUBLICABLE'
                          AND UPPER(TRIM(m.plato))=UPPER(TRIM(COALESCE(s.plato_reservado,s.plato)))
                        ORDER BY m.id DESC LIMIT 1), '') AS tipo_opcion
            FROM solicitudes s
            WHERE s.fecha=:fecha AND COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA' AND COALESCE(s.tipo_registro,'')='CONSUMO_INTERNO'
              AND s.estado_consumo='Consumirá'
            ORDER BY s.rut,s.fecha,s.servicio,s.id DESC
        )
        SELECT COALESCE(c.nombre,base.rut) AS nombre,base.rut,base.institucion,base.servicio,base.tipo_opcion,base.plato
        FROM base LEFT JOIN comensales c ON c.rut=base.rut
        ORDER BY base.institucion,nombre,base.servicio
        """, params={"fecha":fecha_iso}, ttl=0
    )
    return df_prod, df_alemsi


def _render_reporte_produccion_fecha(fecha_iso, titulo=True, mostrar_nominal=True):
    """Reporte reutilizable por Cocina, Administración, Gerencia y AdminTotal."""
    df_prod, df_alemsi = _cargar_demanda_produccion_fecha(fecha_iso)
    if titulo:
        st.markdown(f"#### 🍽️ Producción reservada · {date.fromisoformat(fecha_iso).strftime('%d/%m/%Y')}")
    if df_prod.empty:
        st.info("No hay raciones válidas registradas para esta fecha.")
        return df_prod, df_alemsi
    total=0
    for servicio in ["Desayuno","Almuerzo","Once","Cena"]:
        g=df_prod[df_prod["servicio"].astype(str)==servicio].copy()
        if g.empty: continue
        subtotal=int(g["reservadas"].sum()); total += subtotal
        st.markdown(f"**{servicio} · {subtotal} raciones**")
        g["Opción"] = g["tipo_opcion"].replace({"OPCION 1":"1","OPCION 2":"2","OPCION 3":"3","HIPOCALORICO":"Hipocalórico","":"—"})
        st.dataframe(g[["Opción","plato","reservadas"]].rename(columns={"plato":"Plato","reservadas":"Cantidad"}),use_container_width=True,hide_index=True)
    st.metric("TOTAL RACIONES DEL DÍA", total)
    if mostrar_nominal and not df_alemsi.empty:
        nominal=df_alemsi.copy()
        nominal["Entrega"]="☐"
        st.markdown("##### 👥 Personal ALEMSI · control de entrega")
        st.dataframe(nominal[["Entrega","nombre","rut","institucion","servicio","tipo_opcion","plato"]].rename(columns={
            "nombre":"Nombre","rut":"RUT","institucion":"Grupo","servicio":"Servicio",
            "tipo_opcion":"Opción","plato":"Plato reservado"}),use_container_width=True,hide_index=True)
        st.download_button("⬇️ Descargar listado ALEMSI CSV",nominal.to_csv(index=False).encode("utf-8"),f"alemsi_entrega_{fecha_iso}.csv","text/csv",key=f"csv_alemsi_{fecha_iso}")
    return df_prod, df_alemsi


def render_coordinacion():
    _asegurar_revision_coordinacion(); _sincronizar_maestro_platos()
    conn=get_conn(); usuario=st.session_state.usuario
    st.markdown("### 🤝 Coordinación")
    st.caption("Acceso privado de revisión. Coordinación no modifica directamente Minutas ni Recetas oficiales.")
    vistas=[]
    if permiso_habilitado(usuario.get("username"),"coord_revisar_minutas",True): vistas.append("🍽️ Revisar Minutas")
    if permiso_habilitado(usuario.get("username"),"coord_revisar_recetas",True): vistas.append("📖 Revisar Recetas")
    if permiso_habilitado(usuario.get("username"),"ver_satisfaccion",False): vistas.append("⭐ Satisfacción")
    if not vistas:
        st.warning("Tu perfil no tiene funciones de Coordinación habilitadas. Contacta a AdminTotal."); return
    vista=st.radio("Función",vistas,horizontal=True,key="coord_vista",label_visibility="collapsed")
    if vista=="⭐ Satisfacción":
        _render_satisfaccion_gestion(usuario,key_prefix="coord_sat"); return
    if vista=="📖 Revisar Recetas":
        st.markdown("#### 📖 Revisión de Recetas")
        recetas=conn.query("""
            SELECT plato,MAX(COALESCE(version,1)) AS version_receta,
                   MAX(COALESCE(estado,'BORRADOR')) AS estado_receta
            FROM recetas WHERE TRIM(COALESCE(plato,''))<>''
            GROUP BY plato ORDER BY plato
        """,ttl=0)
        if recetas.empty:
            st.info("No existen recetas cargadas para revisar."); return
        hist_r=conn.query("SELECT plato,version_receta,accion,observacion,fecha_accion,estado FROM receta_revision_coordinacion WHERE usuario=:u ORDER BY fecha_accion DESC,id DESC",params={"u":str(usuario.get("username"))},ttl=0)
        if not hist_r.empty:
            pend_r=hist_r[hist_r["accion"].astype(str)=="OBSERVAR"].copy()
            if not pend_r.empty:
                with st.expander(f"📝 Mis recetas observadas · {len(pend_r)}",expanded=True):
                    st.dataframe(_tabla_visible(pend_r,{"plato":"Plato","version_receta":"Versión","accion":"Acción","observacion":"Observación","fecha_accion":"Fecha / hora","estado":"Estado"},["fecha_accion"]),use_container_width=True,hide_index=True)
        plato_r=st.selectbox("Plato / receta",recetas["plato"].astype(str).tolist(),key="coord_receta_plato")
        cab=recetas[recetas["plato"].astype(str)==plato_r].iloc[0]
        det=conn.query("SELECT insumo,cantidad,unidad,instrucciones,estado,version,merma_pct,margen_produccion_pct FROM recetas WHERE plato=:p ORDER BY insumo",params={"p":plato_r},ttl=0)
        st.caption(f"Versión {int(cab['version_receta'] or 1)} · Estado receta: {cab['estado_receta']}")
        st.dataframe(det.rename(columns={"insumo":"Insumo","cantidad":"Cantidad","unidad":"Unidad","instrucciones":"Instrucciones","estado":"Estado","version":"Versión","merma_pct":"Merma %","margen_produccion_pct":"Margen producción %"}),use_container_width=True,hide_index=True)
        accion_r=st.radio("Decisión",["APROBAR","OBSERVAR"],horizontal=True,key="coord_receta_accion")
        obs_r=st.text_area("Comentario / observación",key="coord_receta_obs",placeholder="Si observas la receta, indica exactamente qué debe revisarse.")
        if st.button("Guardar revisión de receta",type="primary",use_container_width=True,key="coord_receta_guardar"):
            if accion_r=="OBSERVAR" and not obs_r.strip():
                st.error("La observación es obligatoria cuando la receta no se aprueba.")
            else:
                with conn.session as ses:
                    execute_sql(ses,"INSERT INTO receta_revision_coordinacion (plato,version_receta,accion,observacion,usuario,fecha_accion,estado) VALUES (%s,%s,%s,%s,%s,%s,%s)",(plato_r,int(cab['version_receta'] or 1),accion_r,obs_r.strip(),str(usuario.get('username')),datetime.now().isoformat(),'Aprobado' if accion_r=='APROBAR' else 'Pendiente'))
                    ses.commit()
                registrar_auditoria(usuario.get('username'),'REVISION_RECETA_COORDINACION','recetas',plato_r,str(cab['estado_receta']),accion_r,obs_r.strip())
                st.success("Revisión registrada. La receta oficial no fue modificada."); st.rerun()
        return
    st.markdown("#### 🍽️ Revisión de Minutas")
    st.caption("Puedes recorrer el mes completo o elegir un día. Aprobar, observar o proponer cambio no modifica la minuta oficial.")
    mes=st.date_input("Mes a revisar", value=date.today().replace(day=1), key="coord_mes")
    ini=mes.replace(day=1); fin=(ini+timedelta(days=32)).replace(day=1)-timedelta(days=1)
    df=conn.query("SELECT fecha,servicio,tipo_opcion,plato FROM minutas WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha,servicio,tipo_opcion",params={"i":ini.isoformat(),"f":fin.isoformat()},ttl=0)
    if df.empty:
        st.info("No hay minutas cargadas para este período."); return

    # COORD-35: panel personal con la última observación/propuesta por día/servicio/opción.
    pendientes = conn.query(
        """
        SELECT DISTINCT ON (r.fecha,r.servicio,r.tipo_opcion)
               r.fecha,r.servicio,r.tipo_opcion,r.plato_actual,r.accion,r.observacion,r.plato_propuesto,r.fecha_accion,r.estado,
               m.plato AS plato_actual_minuta
        FROM minuta_revision_coordinacion r
        LEFT JOIN minutas m ON m.fecha=r.fecha AND m.servicio=r.servicio AND m.tipo_opcion=r.tipo_opcion AND m.activo=1
        WHERE r.usuario=:u AND r.fecha>=:i AND r.fecha<=:f
        ORDER BY r.fecha,r.servicio,r.tipo_opcion,r.fecha_accion DESC,r.id DESC
        """,
        params={"u":str(usuario.get("username")),"i":ini.isoformat(),"f":fin.isoformat()}, ttl=0
    )
    if not pendientes.empty:
        pendientes = pendientes[pendientes["accion"].astype(str)!="APROBAR"].copy()
        if not pendientes.empty:
            pendientes["Estado revisión"] = pendientes.apply(
                lambda r: "Corregido · pendiente nueva aprobación"
                if str(r.get("plato_actual_minuta") or "").strip() and str(r.get("plato_actual_minuta") or "").strip() != str(r.get("plato_actual") or "").strip()
                else "Pendiente de corrección", axis=1
            )
            with st.expander(f"📝 Mis días observados / pendientes · {len(pendientes)}", expanded=True):
                st.dataframe(
                    pendientes[["fecha","servicio","tipo_opcion","plato_actual","plato_actual_minuta","accion","observacion","plato_propuesto","Estado revisión","fecha_accion"]].rename(columns={
                        "fecha":"Fecha","servicio":"Servicio","tipo_opcion":"Opción","plato_actual":"Plato observado",
                        "plato_actual_minuta":"Plato vigente","accion":"Acción","observacion":"Observación",
                        "plato_propuesto":"Propuesta","fecha_accion":"Fecha / hora"
                    }), use_container_width=True, hide_index=True
                )

    alertas=_alertas_preventivas_minuta(df)
    if alertas:
        with st.expander(f"⚠️ Revisión preventiva · {len(alertas)} alerta(s)"):
            for a in alertas: st.warning(a)
    fechas=sorted(df['fecha'].astype(str).unique().tolist())
    fecha_sel=st.selectbox("Día",fechas,key="coord_fecha")
    dia=df[df['fecha'].astype(str)==fecha_sel].copy()
    st.dataframe(dia.rename(columns={'servicio':'Servicio','tipo_opcion':'Opción','plato':'Plato'}),use_container_width=True,hide_index=True)
    opciones=[f"{r.servicio} · {r.tipo_opcion} · {r.plato}" for r in dia.itertuples()]
    elegido=st.selectbox("Preparación a revisar",opciones,key="coord_item")
    idx=opciones.index(elegido); row=dia.iloc[idx]
    accion=st.radio("Decisión",["APROBAR","OBSERVAR","PROPONER CAMBIO"],horizontal=True,key="coord_accion")
    obs=st.text_area("Observación / solicitud",key="coord_obs",placeholder="Indica brevemente qué deseas cambiar o revisar.")
    platos=conn.query("SELECT nombre FROM platos WHERE COALESCE(activo,1)=1 AND (servicio=:s OR COALESCE(servicio,'')='') ORDER BY nombre",params={'s':str(row['servicio'])},ttl=0)
    propuesta=""
    if accion=="PROPONER CAMBIO":
        lista=['— Seleccionar de la base —'] + (platos['nombre'].dropna().astype(str).drop_duplicates().tolist() if not platos.empty else [])
        propuesta=st.selectbox("Propuesta desde Maestro de Platos",lista,key="coord_prop")
        libre=st.text_input("O sugerir otra preparación",key="coord_prop_libre")
        if libre.strip(): propuesta=libre.strip()
        elif propuesta.startswith('—'): propuesta=''
    if st.button("Guardar revisión",type="primary",use_container_width=True,key="coord_guardar"):
        if accion in ["OBSERVAR","PROPONER CAMBIO"] and not obs.strip():
            st.error("Escribe la observación o motivo del cambio.")
        elif accion=="PROPONER CAMBIO" and not propuesta:
            st.error("Selecciona o escribe una propuesta.")
        else:
            with conn.session as ses:
                execute_sql(ses,"INSERT INTO minuta_revision_coordinacion (fecha,servicio,tipo_opcion,plato_actual,accion,observacion,plato_propuesto,usuario,fecha_accion,estado) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(fecha_sel,str(row['servicio']),str(row['tipo_opcion']),str(row['plato']),accion,obs.strip(),propuesta,str(usuario.get('username')),datetime.now().isoformat(),'Aprobado' if accion=='APROBAR' else 'Pendiente'))
                ses.commit()
            registrar_auditoria(usuario.get('username'),'REVISION_MINUTA_COORDINACION','minuta_revision_coordinacion',fecha_sel,str(row['plato']),propuesta or accion,obs.strip())
            st.success("Revisión registrada. La minuta oficial no fue modificada."); st.rerun()
    hist=conn.query("SELECT fecha,servicio,tipo_opcion,plato_actual,accion,observacion,plato_propuesto,usuario,fecha_accion,estado FROM minuta_revision_coordinacion WHERE fecha>=:i AND fecha<=:f ORDER BY fecha_accion DESC",params={'i':ini.isoformat(),'f':fin.isoformat()},ttl=0)
    if not hist.empty:
        with st.expander("Historial de revisión"):
            st.dataframe(hist,use_container_width=True,hide_index=True)


def generar_pdf_jornada_alemsi(fecha_iso, df_prod, df_alemsi):
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=LETTER,rightMargin=14*mm,leftMargin=14*mm,topMargin=14*mm,bottomMargin=14*mm)
    estilos=getSampleStyleSheet(); elems=[]
    elems += [Paragraph("<b>ALEMSI · Jornada de Producción</b>", estilos["Title"]), Paragraph(f"Fecha: {date.fromisoformat(fecha_iso).strftime('%d/%m/%Y')}", estilos["Normal"]), Spacer(1,6*mm)]
    orden=["Desayuno","Almuerzo","Once","Cena"]
    servicios=list(df_prod["servicio"].dropna().astype(str).unique()) if not df_prod.empty else []
    servicios= [x for x in orden if x in servicios] + sorted([x for x in servicios if x not in orden])
    for serv in servicios:
        elems.append(Paragraph(f"<b>{serv}</b>", estilos["Heading2"]))
        g=df_prod[df_prod["servicio"].astype(str)==serv]
        data=[["Opción","Plato","Cantidad"]]+[[str(r.get("tipo_opcion") or "—"),str(r.get("plato") or ""),str(int(r.get("reservadas") or 0))] for _,r in g.iterrows()]
        data.append(["","TOTAL",str(int(g["reservadas"].sum()))])
        t=Table(data,colWidths=[35*mm,100*mm,25*mm],repeatRows=1); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF1F7')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(-1,1),(-1,-1),'CENTER')]))
        elems += [t,Spacer(1,4*mm)]
        if df_alemsi is not None and not df_alemsi.empty:
            nom=df_alemsi[df_alemsi["servicio"].astype(str)==serv]
            if not nom.empty:
                elems.append(Paragraph("<b>Listado nominal ALEMSI</b>",estilos["Heading3"]))
                nd=[["Check","Nombre","RUT","Plato"]]+[["[ ]",str(r.get("nombre") or ""),str(r.get("rut") or ""),str(r.get("plato") or "")] for _,r in nom.iterrows()]
                nt=Table(nd,colWidths=[10*mm,60*mm,35*mm,55*mm],repeatRows=1); nt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold')]))
                elems += [nt,Spacer(1,6*mm)]
    elems.append(Paragraph("Sistema ALEMSI · Documento operativo de producción",estilos["Italic"]))
    doc.build(elems); return buffer.getvalue()

def generar_pdf_tabla_alemsi(titulo, periodo, df, columnas=None, total_texto=""):
    """Reporte Carta corporativo para conciliación y vistas ejecutivas.
    El wordmark ALEMSI se dibuja en vector/texto para no depender de un archivo externo.
    """
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=LETTER,rightMargin=13*mm,leftMargin=13*mm,topMargin=13*mm,bottomMargin=13*mm)
    estilos=getSampleStyleSheet()
    elems=[
        Paragraph("<font color='#0A2F6B'><b>ALEMSI</b></font>",ParagraphStyle('alemsi_logo',parent=estilos['Title'],fontSize=22,leading=24,alignment=TA_CENTER)),
        Paragraph(escape(str(titulo)),ParagraphStyle('alemsi_titulo',parent=estilos['Heading1'],fontSize=15,leading=18,alignment=TA_CENTER)),
        Paragraph(f"Período / fecha: {escape(str(periodo))}",ParagraphStyle('alemsi_periodo',parent=estilos['Normal'],alignment=TA_CENTER)),
        Spacer(1,5*mm),
    ]
    datos=df.copy() if df is not None else pd.DataFrame()
    if columnas:
        presentes=[c for c in columnas if c in datos.columns]
        datos=datos[presentes]
    if datos.empty:
        elems.append(Paragraph("Sin registros para el período seleccionado.",estilos['Normal']))
    else:
        headers=[str(c) for c in datos.columns]
        cuerpo=[headers]
        for _,r in datos.head(500).iterrows():
            cuerpo.append([str(r.get(c,"")) if pd.notna(r.get(c,"")) else "" for c in datos.columns])
        ancho_util=LETTER[0]-26*mm
        colw=[ancho_util/max(1,len(headers))]*len(headers)
        tabla=Table(cuerpo,colWidths=colw,repeatRows=1)
        tabla.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0A2F6B')),
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
            ('FONTSIZE',(0,0),(-1,-1),7),('LEADING',(0,0),(-1,-1),8.5),
            ('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#AEBBC7')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F5F7F9')]),
        ]))
        elems.append(tabla)
    if total_texto:
        elems += [Spacer(1,4*mm),Paragraph(f"<b>{escape(str(total_texto))}</b>",estilos['Normal'])]
    elems += [Spacer(1,6*mm),Paragraph(f"Sistema ALEMSI · Generado {datetime.now().strftime('%d/%m/%Y %H:%M')}",estilos['Italic'])]
    doc.build(elems)
    return buffer.getvalue()

def render_casino():
    usuario = st.session_state.usuario
    roles_casino = ["Cocina", "Finanzas", "Bodega"]
    if usuario and usuario.get("rol") in roles_casino:
        rol = str(usuario["rol"])
        st.markdown(f'<div class="al-card"><h3>{"Coordinación" if rol=="Coordinacion" else rol}</h3><p>¡Buen día, {usuario.get("nombre") or "equipo"}! Hoy es {datetime.now().strftime("%d/%m/%Y")}. Que tengan una excelente jornada.</p></div>', unsafe_allow_html=True)

        if rol == "Coordinacion":
            render_coordinacion()

        elif rol == "Cocina":
            if not permiso_habilitado(usuario.get('username'),'ver_cocina',True):
                st.warning('Tu función Cocina está deshabilitada por el Administrador Total.')
                return
            # COORD-REC-37: reporte consolidado, sin hilos de correo ni modificación automática.
            try:
                obs_coord=get_conn().query("SELECT plato,version_receta,accion,observacion,usuario,fecha_accion,estado FROM receta_revision_coordinacion WHERE accion='OBSERVAR' ORDER BY fecha_accion DESC,id DESC",ttl=0)
                if not obs_coord.empty:
                    with st.expander(f"🤝 Observaciones de Coordinación sobre Recetas · {len(obs_coord)}",expanded=False):
                        st.dataframe(_tabla_visible(obs_coord,{"plato":"Plato","version_receta":"Versión","accion":"Acción","observacion":"Observación","usuario":"Coordinación","fecha_accion":"Fecha / hora","estado":"Estado"},["fecha_accion"]),use_container_width=True,hide_index=True)
                        st.download_button("⬇️ Descargar observaciones de recetas CSV",obs_coord.to_csv(index=False).encode("utf-8"),"observaciones_recetas_coordinacion.csv","text/csv",use_container_width=True,key="csv_obs_coord_recetas")
            except Exception:
                pass
            # INV-TAREA-01: bandeja de tareas ordenadas por Admin_Casino.
            conn_tareas = get_conn()
            df_tareas_cocina = conn_tareas.query(
                """
                SELECT id,fecha_creacion,fecha_programada,familia,seccion,detalle,prioridad,
                       estado,creado_por,fecha_inicio,resultado,fecha_completado
                FROM tareas_inventario_cocina
                WHERE estado IN ('Pendiente','En proceso','Enviado a revisión')
                ORDER BY
                    CASE prioridad WHEN 'Urgente' THEN 1 WHEN 'Alta' THEN 2 ELSE 3 END,
                    COALESCE(fecha_programada,fecha_creacion), id
                """,
                ttl=10,
            )
            if not df_tareas_cocina.empty:
                pendientes_n = int((df_tareas_cocina["estado"].astype(str) == "Pendiente").sum())
                st.warning(
                    f"🔔 Tareas de inventario: {len(df_tareas_cocina)} activa(s)"
                    + (f" · {pendientes_n} pendiente(s)" if pendientes_n else "")
                )
                with st.expander("📋 Ver tareas de inventario", expanded=False):
                    st.dataframe(
                        _tabla_visible(
                            df_tareas_cocina[
                                ["id","fecha_programada","familia","seccion","detalle","prioridad","estado","creado_por"]
                            ],
                            {
                                "id":"N.º",
                                "fecha_programada":"Fecha programada",
                                "familia":"Familia",
                                "seccion":"Sección",
                                "detalle":"Solicitud",
                                "prioridad":"Prioridad",
                                "estado":"Estado",
                                "creado_por":"Solicitado por",
                            },
                            ["fecha_programada"],
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                    tarea_ids = df_tareas_cocina["id"].astype(int).tolist()
                    tarea_id = selector_neutro(
                        "Tarea a gestionar",
                        tarea_ids,
                        format_func=lambda tid: (
                            f"#{tid} · "
                            f"{df_tareas_cocina[df_tareas_cocina['id'].astype(int)==int(tid)].iloc[0]['familia'] or 'Inventario'} · "
                            f"{df_tareas_cocina[df_tareas_cocina['id'].astype(int)==int(tid)].iloc[0]['estado']}"
                        ),
                        key="cocina_tarea_inventario_id",
                    )
                    if tarea_id is None:
                        st.info("Selecciona una tarea para gestionarla.")
                        return
                    tarea_sel = df_tareas_cocina[
                        df_tareas_cocina["id"].astype(int) == int(tarea_id)
                    ].iloc[0]
                    st.caption(
                        f"Solicitud: {tarea_sel.get('detalle') or 'Inventario solicitado'}"
                    )
                    tc1, tc2 = st.columns(2)
                    with tc1:
                        if str(tarea_sel["estado"]) == "Pendiente":
                            if st.button(
                                "▶️ Iniciar tarea",
                                use_container_width=True,
                                key=f"iniciar_tarea_inv_{tarea_id}",
                            ):
                                ahora_t = datetime.now().isoformat()
                                with conn_tareas.session as ses_t:
                                    execute_sql(
                                        ses_t,
                                        "UPDATE tareas_inventario_cocina "
                                        "SET estado='En proceso',iniciado_por=%s,fecha_inicio=%s WHERE id=%s",
                                        (usuario.get("username"), ahora_t, int(tarea_id)),
                                    )
                                    ses_t.commit()
                                registrar_auditoria(
                                    usuario.get("username"),
                                    "INICIAR_TAREA_INVENTARIO",
                                    "tareas_inventario_cocina",
                                    str(tarea_id),
                                    "Pendiente",
                                    "En proceso",
                                    "",
                                )
                                st.success("Tarea iniciada.")
                                st.rerun()
                    with tc2:
                        resultado_t = st.text_area(
                            "Resultado / conteo / observaciones",
                            value=str(tarea_sel.get("resultado") or ""),
                            key=f"resultado_tarea_inv_{tarea_id}",
                            placeholder="Registra el resultado del inventario. Esto no modifica el stock oficial.",
                        )
                        if st.button(
                            "📤 Enviar a revisión",
                            type="primary",
                            use_container_width=True,
                            disabled=(str(tarea_sel["estado"]) == "Pendiente" or not resultado_t.strip()),
                            key=f"enviar_tarea_inv_{tarea_id}",
                        ):
                            ahora_t = datetime.now().isoformat()
                            with conn_tareas.session as ses_t:
                                execute_sql(
                                    ses_t,
                                    "UPDATE tareas_inventario_cocina "
                                    "SET estado='Enviado a revisión',resultado=%s,completado_por=%s,fecha_completado=%s "
                                    "WHERE id=%s",
                                    (
                                        resultado_t.strip(),
                                        usuario.get("username"),
                                        ahora_t,
                                        int(tarea_id),
                                    ),
                                )
                                ses_t.commit()
                            registrar_auditoria(
                                usuario.get("username"),
                                "ENVIAR_TAREA_INVENTARIO_REVISION",
                                "tareas_inventario_cocina",
                                str(tarea_id),
                                str(tarea_sel["estado"]),
                                "Enviado a revisión",
                                resultado_t.strip(),
                            )
                            st.success("Resultado enviado a Administración Casino para revisión.")
                            st.rerun()

            modulo_cocina = st.radio(
                "Sección",
                ["📅 Ver minuta", "▶️ Jornada de producción", "📖 Recetas", "📦 Bodega operativa"],
                horizontal=True, key="modulo_cocina_activo", label_visibility="collapsed"
            )
            if st.session_state.get("_ultimo_modulo_cocina") != modulo_cocina:
                st.session_state["_ultimo_modulo_cocina"] = modulo_cocina
                _scroll_top()

            if modulo_cocina == "📅 Ver minuta":
                st.markdown("#### 📅 Minuta por período")
                mc1, mc2 = st.columns(2)
                with mc1:
                    min_desde = st.date_input("Desde", value=date.today(), key="fecha_minuta_cocina_desde")
                with mc2:
                    min_hasta = st.date_input("Hasta", value=date.today()+timedelta(days=6), key="fecha_minuta_cocina_hasta")
                if min_hasta < min_desde:
                    st.error("La fecha hasta no puede ser anterior a la fecha desde.")
                else:
                    df_semana = get_minutas_rango(min_desde.isoformat(), min_hasta.isoformat())
                    fechas_vis = [min_desde + timedelta(days=i) for i in range((min_hasta-min_desde).days+1)]
                    _render_minuta_semanal(df_semana, fechas_visibles=fechas_vis, titulo_personalizado=f"📅 {min_desde.strftime('%d/%m/%Y')} → {min_hasta.strftime('%d/%m/%Y')}")
                st.caption("Cocina visualiza la minuta en modo solo lectura. La gestión de minuta y recetas corresponde a perfiles autorizados.")

            if modulo_cocina == "▶️ Jornada de producción":
                st.markdown("#### Jornada completa de producción")
                st.caption("Visualizar no modifica stock. Iniciar jornada crea una fotografía de lo reservado para todos los servicios del día.")
                fecha_j = st.date_input("Día de producción", value=date.today(), key="fecha_jornada_cocina")
                fecha_iso = fecha_j.isoformat()
                conn = get_conn()
                df_prod, df_alemsi_personas = _cargar_demanda_produccion_fecha(fecha_iso)
                if not df_prod.empty:
                    pdf_jornada=generar_pdf_jornada_alemsi(fecha_iso,df_prod,df_alemsi_personas)
                    st.download_button("🖨️ PDF corporativo · jornada completa",pdf_jornada,file_name=f"ALEMSI_Jornada_{fecha_iso}.pdf",mime="application/pdf",use_container_width=True,key="pdf_jornada_completa")

                estado_j = conn.query("SELECT * FROM jornadas_produccion WHERE fecha=:f", params={"f":fecha_iso}, ttl=0)
                estado = str(estado_j.iloc[0]["estado"]) if not estado_j.empty else "Pendiente"
                st.info(f"Estado de la jornada: **{estado}**")

                def mostrar_bloques(df):
                    if df.empty:
                        st.warning("No hay reservas registradas para esta fecha.")
                        return
                    total_dia = 0
                    for servicio in ["Desayuno","Almuerzo","Once","Cena"]:
                        g = df[df["servicio"].astype(str)==servicio].copy()
                        if g.empty: continue
                        total_s = int(g["reservadas"].sum())
                        total_dia += total_s
                        st.markdown(f"### {servicio} · {total_s} porciones")
                        g["Opción"] = g["tipo_opcion"].replace({"OPCION 1":"1","OPCION 2":"2","HIPOCALORICO":"Hipocalórico","TIPO R":"Tipo R","":"—"})
                        st.dataframe(g[["Opción","plato","reservadas"]].rename(columns={"plato":"Plato","reservadas":"Reservadas"}), use_container_width=True, hide_index=True)
                    st.metric("TOTAL JORNADA RESERVADA", total_dia)
                    if not df_alemsi_personas.empty:
                        st.markdown("### 👥 Personal ALEMSI reservado")
                        st.caption("Listado nominal para entrega controlada. Solo aparecen personas con una selección válida.")
                        st.dataframe(
                            df_alemsi_personas.rename(columns={
                                "nombre":"Nombre","rut":"RUT","institucion":"Grupo",
                                "servicio":"Servicio","plato":"Plato reservado"
                            }),
                            use_container_width=True, hide_index=True
                        )

                if st.button("👁️ Visualizar jornada completa", use_container_width=True):
                    st.session_state["ver_jornada"] = fecha_iso
                if st.session_state.get("ver_jornada") == fecha_iso:
                    _render_reporte_produccion_fecha(fecha_iso, titulo=False, mostrar_nominal=True)

                if estado == "Pendiente":
                    confirmar = st.checkbox(f"Confirmo iniciar la jornada completa del {fecha_j.strftime('%d/%m/%Y')}", key=f"conf_ini_j_{fecha_iso}")
                    if st.button("▶️ INICIAR JORNADA", type="primary", use_container_width=True, disabled=not confirmar):
                        sin_receta = []
                        sin_minuta = []
                        faltantes_stock = []
                        ya_iniciada = False
                        with conn.session as ses:
                            # PROD-35: bloqueo transaccional para impedir doble inicio/doble descuento.
                            execute_sql(ses, "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"PRODUCCION|{fecha_iso}",))
                            existente_j = execute_sql(ses, "SELECT estado FROM jornadas_produccion WHERE fecha=%s FOR UPDATE", (fecha_iso,)).first()
                            if existente_j and str(existente_j[0]) != "Pendiente":
                                ya_iniciada = True
                            else:
                                execute_sql(ses, "INSERT INTO jornadas_produccion (fecha,estado,inicio_at,usuario_inicio) VALUES (%s,'En producción',%s,%s) ON CONFLICT (fecha) DO UPDATE SET estado='En producción',inicio_at=EXCLUDED.inicio_at,usuario_inicio=EXCLUDED.usuario_inicio", (fecha_iso,datetime.now().isoformat(),usuario.get('username')))
                                for _,r in df_prod.iterrows():
                                    plato_prod = str(r['plato'])
                                    porciones = int(r['reservadas'])
                                    execute_sql(ses, "INSERT INTO jornada_detalle (fecha,servicio,tipo_opcion,plato,reservadas,producidas,entregadas) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fecha,servicio,tipo_opcion,plato) DO UPDATE SET reservadas=EXCLUDED.reservadas", (fecha_iso,str(r['servicio']),str(r['tipo_opcion']),plato_prod,porciones,porciones,0))

                                    minuta_activa = execute_sql(
                                        ses,
                                        "SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND activo=1 AND COALESCE(estado,'PUBLICABLE')='PUBLICABLE' AND LOWER(TRIM(plato))=LOWER(TRIM(%s)) LIMIT 1",
                                        (fecha_iso,str(r['servicio']),plato_prod),
                                    ).first()
                                    if not minuta_activa:
                                        # Regla de oro: una eventualidad sin minuta se produce y registra,
                                        # pero no genera un descuento automático de inventario.
                                        sin_minuta.append(plato_prod)
                                        continue
                                    recetas = execute_sql(
                                        ses,
                                        "SELECT insumo,cantidad FROM recetas WHERE LOWER(TRIM(plato))=LOWER(TRIM(%s)) "
                                        "AND UPPER(TRIM(COALESCE(estado,''))) IN ('ACTIVA','ACTIVO','APROBADA','APROBADO')",
                                        (plato_prod,),
                                    ).mappings().all()
                                    if not recetas:
                                        sin_receta.append(plato_prod)
                                        continue
                                    for rec in recetas:
                                        requerido = float(rec['cantidad'] or 0) * porciones
                                        if requerido <= 0:
                                            continue
                                        lotes = execute_sql(ses, "SELECT id,stock,nombre_articulo FROM bodega_inventario WHERE nombre_articulo ILIKE %s AND COALESCE(stock,0)>0 ORDER BY caduca ASC NULLS LAST,id ASC FOR UPDATE", (f"%{rec['insumo']}%",)).mappings().all()
                                        pendiente = requerido
                                        for lote in lotes:
                                            if pendiente <= 0: break
                                            disponible = float(lote['stock'] or 0)
                                            uso = min(disponible, pendiente)
                                            execute_sql(ses, "UPDATE bodega_inventario SET stock=GREATEST(COALESCE(stock,0)-%s,0) WHERE id=%s", (uso,lote['id']))
                                            pendiente -= uso
                                        if pendiente > 0.0001:
                                            faltantes_stock.append(f"{rec['insumo']} ({pendiente:.2f} pendiente)")
                                ses.commit()
                        if ya_iniciada:
                            st.warning("La jornada ya había sido iniciada. No se realizó un segundo descuento de Bodega.")
                        else:
                            detalle_alerta = []
                            if sin_minuta:
                                detalle_alerta.append("sin minuta: " + ", ".join(sorted(set(sin_minuta))))
                            if sin_receta:
                                detalle_alerta.append("sin receta aprobada: " + ", ".join(sorted(set(sin_receta))))
                            if faltantes_stock:
                                detalle_alerta.append("stock insuficiente: " + ", ".join(sorted(set(faltantes_stock))))
                            registrar_auditoria(usuario.get('username'),'INICIAR_JORNADA','jornadas_produccion',fecha_iso,'Pendiente','En producción','; '.join(detalle_alerta))
                            st.success("Jornada iniciada. Se congeló la producción y se descontó Bodega según las recetas disponibles, una sola vez.")
                            if sin_minuta:
                                st.warning("Producción registrada sin descuento de Bodega porque no existe minuta vigente para: " + ", ".join(sorted(set(sin_minuta))))
                            if sin_receta:
                                st.warning("Producción registrada sin descuento automático porque falta una receta aprobada para: " + ", ".join(sorted(set(sin_receta))))
                            if faltantes_stock:
                                st.warning("La producción quedó registrada, pero hubo faltantes de stock para: " + ", ".join(sorted(set(faltantes_stock))))
                        st.rerun()

                elif estado == "En producción":
                    dfd = conn.query("SELECT id,servicio,tipo_opcion,plato,reservadas,producidas,entregadas,motivo_diferencia,observaciones FROM jornada_detalle WHERE fecha=:f ORDER BY CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,id", params={"f":fecha_iso}, ttl=0)
                    cierres=[]
                    st.markdown("### Cierre de jornada")
                    for servicio in ["Desayuno","Almuerzo","Once","Cena"]:
                        g=dfd[dfd['servicio'].astype(str)==servicio] if not dfd.empty else pd.DataFrame()
                        if g.empty: continue
                        st.markdown(f"#### {servicio}")
                        for _,r in g.iterrows():
                            op=str(r['tipo_opcion'] or '').replace('OPCION 1','1').replace('OPCION 2','2').replace('HIPOCALORICO','Hipocalórico') or '—'
                            st.markdown(f"**Opción {op} · {r['plato']}** — Reservadas: **{int(r['reservadas'])}**")
                            prod=int(r['producidas'] or r['reservadas'])
                            c1,c2,c3=st.columns(3)
                            with c1: st.metric("Reservadas",int(r['reservadas']))
                            with c2: st.metric("Producidas",prod)
                            with c3: ent=st.number_input("Entregadas",min_value=0,value=int(r['entregadas'] or r['reservadas']),step=1,key=f"je_{r['id']}")
                            motivo=""
                            if int(prod)!=int(r['reservadas']) or int(ent)!=int(r['reservadas']): motivo=st.text_input("Motivo obligatorio de la diferencia",key=f"jm_{r['id']}")
                            cierres.append((int(r['id']),int(r['reservadas']),int(prod),int(ent),motivo))
                    novedades=st.text_area("Novedades generales de la jornada (quiebres, reemplazos, ausencias, producción extra, etc.)", key=f"jn_{fecha_iso}")
                    faltan=[x for x in cierres if (x[2]!=x[1] or x[3]!=x[1]) and not str(x[4]).strip()]
                    if faltan:
                        st.warning("Hay diferencias sin motivo. Debes justificarlas antes de cerrar la jornada.")
                    confirmar_fin=st.checkbox("Confirmo que revisé producción, entregas, diferencias y novedades", key=f"conf_fin_j_{fecha_iso}")
                    if st.button("✅ FINALIZAR JORNADA", type="primary", use_container_width=True, disabled=(not confirmar_fin or bool(faltan))):
                        with conn.session as ses:
                            for idd,res,prod,ent,mot in cierres:
                                execute_sql(ses,"UPDATE jornada_detalle SET producidas=%s,entregadas=%s,motivo_diferencia=%s WHERE id=%s",(prod,ent,mot,idd))
                            execute_sql(ses,"UPDATE jornadas_produccion SET estado='Finalizado',fin_at=%s,usuario_fin=%s,novedades=%s WHERE fecha=%s",(datetime.now().isoformat(),usuario.get('username'),novedades,fecha_iso))
                            ses.commit()
                        # Reporte de cierre a Administración Casino. Un fallo de correo no revierte el cierre.
                        df_rep=conn.query("SELECT servicio,tipo_opcion,plato,reservadas,producidas,entregadas,(producidas-reservadas) AS dif_produccion,(entregadas-reservadas) AS dif_entrega,motivo_diferencia FROM jornada_detalle WHERE fecha=:f ORDER BY servicio,id",params={"f":fecha_iso},ttl=0)
                        html=f"<h2>Reporte Diario Cocina · {fecha_j.strftime('%d/%m/%Y')}</h2>{df_rep.to_html(index=False)}<p><b>Novedades:</b> {novedades or 'Sin novedades'}</p><p><b>Responsable:</b> {usuario.get('nombre')}</p>"
                        resultados=[enviar_email(dest,f"[CIERRE COCINA] {fecha_j.strftime('%d/%m/%Y')}",html) for dest in get_correos('admin_casino')]
                        enviado=any(ok for ok,_ in resultados)
                        with conn.session as ses:
                            execute_sql(ses,"UPDATE jornadas_produccion SET reporte_enviado_at=%s,reporte_estado=%s WHERE fecha=%s",(datetime.now().isoformat() if enviado else None,'Enviado' if enviado else 'Pendiente de envío',fecha_iso))
                            ses.commit()
                        registrar_auditoria(usuario.get('username'),'FINALIZAR_JORNADA','jornadas_produccion',fecha_iso,'En producción','Finalizado',novedades)
                        st.success("Jornada finalizada y guardada. " + ("Reporte enviado a Administración Casino." if enviado else "El cierre quedó guardado; el correo quedó pendiente de envío."))
                        st.rerun()
                else:
                    st.success("Jornada finalizada.")
                    dfd=conn.query("SELECT servicio,tipo_opcion,plato,reservadas,producidas,entregadas,(producidas-reservadas) AS dif_produccion,(entregadas-reservadas) AS dif_entrega,motivo_diferencia FROM jornada_detalle WHERE fecha=:f ORDER BY servicio,id",params={"f":fecha_iso},ttl=10)
                    st.dataframe(dfd,use_container_width=True,hide_index=True)
                    if not estado_j.empty:
                        st.caption(f"Novedades: {estado_j.iloc[0].get('novedades') or 'Sin novedades'} · Reporte: {estado_j.iloc[0].get('reporte_estado') or 'Sin estado'}")

            if modulo_cocina == "📖 Recetas":
                st.markdown("#### 📖 Recetas")
                st.caption("Cocina visualiza recetas en modo solo lectura.")
                conn=get_conn()
                dfr=conn.query("SELECT plato,insumo,cantidad,unidad,merma_pct,margen_produccion_pct,estado,version,instrucciones FROM recetas ORDER BY plato,insumo",ttl=30)
                if dfr.empty:
                    st.info("No hay recetas registradas.")
                else:
                    platos = sorted(dfr["plato"].dropna().astype(str).unique().tolist())
                    seleccionado = st.session_state.get("receta_cocina_plato")
                    if seleccionado and seleccionado in platos:
                        if st.button("← Volver a recetas", key="volver_recetas_cocina"):
                            st.session_state.pop("receta_cocina_plato", None)
                            st.rerun()
                        detalle = dfr[dfr["plato"].astype(str) == seleccionado].copy()
                        estado = str(detalle.iloc[0].get("estado") or "Sin estado")
                        version_r = str(detalle.iloc[0].get("version") or "—")
                        st.markdown(f"### {seleccionado}")
                        st.caption(f"Estado: {estado} · Versión: {version_r}")
                        st.dataframe(
                            detalle[[c for c in ["insumo","cantidad","unidad","merma_pct","margen_produccion_pct","instrucciones"] if c in detalle.columns]]
                            .rename(columns={"insumo":"Ingrediente","cantidad":"Cantidad por persona","unidad":"Unidad","merma_pct":"Merma %","margen_produccion_pct":"Margen producción %","instrucciones":"Instrucciones"}),
                            use_container_width=True, hide_index=True
                        )
                    else:
                        st.markdown("##### Platos")
                        cols = st.columns(4)
                        for i, plato_r in enumerate(platos):
                            g = dfr[dfr["plato"].astype(str) == plato_r]
                            estado = str(g.iloc[0].get("estado") or "Sin receta")
                            version_r = str(g.iloc[0].get("version") or "—")
                            with cols[i % 4]:
                                st.markdown(f"**{plato_r}**")
                                st.caption(f"{estado} · v{version_r}")
                                if st.button("Abrir receta", key=f"abrir_receta_{i}", use_container_width=True):
                                    st.session_state["receta_cocina_plato"] = plato_r
                                    st.rerun()
                st.caption("Visualizar o consultar una receta no descuenta Bodega. El consumo teórico nace al pasar efectivamente a Producción.")

            if modulo_cocina == "📦 Bodega operativa":
                st.markdown("#### 📦 Bodega operativa")
                conn=get_conn()
                tb1,tb2,tb3,tb4=st.tabs(["Stock","Carga individual","Carga masiva CSV","Inventario físico"])
                with tb1:
                    dfb=conn.query("SELECT codigo_insumo,nombre_articulo,unidad,stock,critico,caduca,seccion FROM bodega_inventario ORDER BY nombre_articulo LIMIT 300",ttl=30)
                    st.dataframe(_tabla_visible(dfb,{"codigo_insumo":"Código","nombre_articulo":"Producto","unidad":"Unidad","stock":"Stock teórico","critico":"Stock crítico","caduca":"Vencimiento","seccion":"Sección"},["caduca"]),use_container_width=True,hide_index=True)
                with tb2:
                    with st.form("carga_individual_bodega"):
                        c1,c2=st.columns(2)
                        with c1: cod=st.text_input("Código"); prod=st.text_input("Producto*"); unidad=st.text_input("Unidad",value="kg")
                        with c2: stock=st.number_input("Stock",min_value=0.0,value=0.0,step=0.1); crit=st.number_input("Stock crítico",min_value=0.0,value=0.0,step=0.1); sec=st.text_input("Sección",value="General")
                        guardar_b=st.form_submit_button("Guardar producto / stock",use_container_width=True)
                    if guardar_b and prod.strip():
                        with conn.session as ses:
                            ex=execute_sql(ses,"SELECT id FROM bodega_inventario WHERE COALESCE(codigo_insumo,'')=%s OR UPPER(nombre_articulo)=UPPER(%s) ORDER BY id LIMIT 1",(cod.strip(),prod.strip())).first()
                            if ex: execute_sql(ses,"UPDATE bodega_inventario SET codigo_insumo=%s,nombre_articulo=%s,unidad=%s,stock=%s,critico=%s,seccion=%s WHERE id=%s",(cod.strip(),prod.strip(),unidad,float(stock),float(crit),sec,ex[0]))
                            else: execute_sql(ses,"INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,critico,seccion) VALUES (%s,%s,%s,%s,%s,%s)",(cod.strip(),prod.strip(),unidad,float(stock),float(crit),sec))
                            ses.commit()
                        registrar_auditoria(usuario.get('username'),'CARGA_BODEGA','bodega_inventario',cod.strip(),'','stock='+str(stock),'Carga individual'); st.success("Producto actualizado."); st.rerun()
                with tb3:
                    st.caption("Columnas recomendadas: codigo_insumo, nombre_articulo, unidad, stock, critico, seccion")
                    arc=st.file_uploader("Archivo CSV de inventario",type=["csv"],key="csv_bodega_cocina")
                    if arc is not None:
                        try:
                            v=pd.read_csv(arc); st.dataframe(v.head(30),use_container_width=True,hide_index=True)
                            if st.button("Confirmar carga de inventario",key="confirmar_csv_bodega"):
                                req={'nombre_articulo','stock'}
                                if not req.issubset(v.columns): st.error("El archivo debe incluir al menos nombre_articulo y stock.")
                                else:
                                    with conn.session as ses:
                                        for _,rr in v.iterrows():
                                            codv=str(rr.get('codigo_insumo','') or ''); nomv=str(rr['nombre_articulo']); univ=str(rr.get('unidad','unidad') or 'unidad'); stkv=float(rr.get('stock',0) or 0); criv=float(rr.get('critico',0) or 0); secv=str(rr.get('seccion','General') or 'General')
                                            ex=execute_sql(ses,"SELECT id FROM bodega_inventario WHERE COALESCE(codigo_insumo,'')=%s OR UPPER(nombre_articulo)=UPPER(%s) ORDER BY id LIMIT 1",(codv,nomv)).first()
                                            if ex: execute_sql(ses,"UPDATE bodega_inventario SET codigo_insumo=%s,nombre_articulo=%s,unidad=%s,stock=%s,critico=%s,seccion=%s WHERE id=%s",(codv,nomv,univ,stkv,criv,secv,ex[0]))
                                            else: execute_sql(ses,"INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,critico,seccion) VALUES (%s,%s,%s,%s,%s,%s)",(codv,nomv,univ,stkv,criv,secv))
                                        ses.commit()
                                    registrar_auditoria(usuario.get('username'),'CARGA_MASIVA_BODEGA','bodega_inventario','','',str(len(v))+' filas','CSV'); st.success("Carga masiva completada."); st.rerun()
                        except Exception as e: st.error(f"No fue posible leer el CSV: {e}")
                with tb4:
                    inv=conn.query("SELECT id,codigo_insumo,nombre_articulo,unidad,stock FROM bodega_inventario ORDER BY nombre_articulo",ttl=0)
                    if inv.empty: st.info("No hay productos para inventariar.")
                    else:
                        producto_inv=selector_neutro("Producto",inv['id'].tolist(),format_func=lambda x: str(inv[inv['id']==x].iloc[0]['nombre_articulo']),key="inv_prod_cocina")
                        if producto_inv is None:
                            st.info("Selecciona un producto para registrar inventario físico.")
                            return
                        fila=inv[inv['id']==producto_inv].iloc[0]; teorico=float(fila['stock'] or 0)
                        st.metric("Stock teórico",f"{teorico:g} {fila['unidad'] or ''}")
                        real=st.number_input("Stock real contado",min_value=0.0,value=teorico,step=0.1,key="inv_real_cocina")
                        dif=float(real)-teorico; st.metric("Diferencia",f"{dif:+.2f}")
                        obs=st.text_input("Observación / motivo",key="inv_obs_cocina")
                        if st.button("Registrar inventario físico",type="primary",use_container_width=True,disabled=(abs(dif)>0.0001 and not obs.strip())):
                            with conn.session as ses:
                                execute_sql(ses,"INSERT INTO inventarios_fisicos (fecha,codigo_insumo,nombre_articulo,stock_teorico,stock_real,diferencia,responsable,observacion,creado_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",(date.today().isoformat(),str(fila['codigo_insumo'] or ''),str(fila['nombre_articulo']),teorico,float(real),dif,usuario.get('username'),obs,datetime.now().isoformat()))
                                execute_sql(ses,"UPDATE bodega_inventario SET stock=%s WHERE id=%s",(float(real),int(producto_inv))); ses.commit()
                            registrar_auditoria(usuario.get('username'),'INVENTARIO_FISICO','bodega_inventario',str(fila['codigo_insumo'] or fila['nombre_articulo']),teorico,real,obs); st.success("Inventario registrado con responsable y trazabilidad."); st.rerun()

        elif rol == "Bodega":
            if not permiso_habilitado(usuario.get('username'),'ver_bodega',True):
                st.warning('Tu función Bodega está deshabilitada por el Administrador Total.')
                return
            st.markdown("#### 📦 Bodega")
            conn=get_conn(); df=conn.query("SELECT * FROM bodega_inventario ORDER BY nombre_articulo LIMIT 300",ttl=20)
            st.dataframe(df,use_container_width=True)

        elif rol == "Finanzas":
            if not permiso_habilitado(usuario.get('username'),'ver_finanzas',True):
                st.warning('Tu función Finanzas está deshabilitada por el Administrador Total.')
                return

            conn = get_conn()
            opciones_finanzas = ["📊 Dashboard", "📋 Resumen", "🏢 Por institución", "🧾 Validar comprobantes"]
            if permiso_habilitado(usuario.get("username"), "gestionar_datos_transferencia", True):
                opciones_finanzas.append("🏦 Datos de transferencia")
            if permiso_habilitado(usuario.get("username"), "ver_satisfaccion", False):
                opciones_finanzas.append("⭐ Satisfacción")
            vista_finanzas = st.radio(
                "Sección Finanzas", opciones_finanzas,
                horizontal=True, key="vista_finanzas_activa", label_visibility="collapsed",
            )
            _mostrar_flash_finanzas()

            if vista_finanzas == "🏦 Datos de transferencia":
                _render_datos_transferencia(usuario, key_prefix="finanzas_datos_transferencia")
                return
            if vista_finanzas == "⭐ Satisfacción":
                _render_satisfaccion_gestion(usuario,key_prefix="fin_sat")
                return

            df_reservas = _cargar_reservas_finanzas()

            if df_reservas.empty:
                st.info("No hay reservas comerciales registradas.")
                return

            df_reservas["monto_reserva"] = pd.to_numeric(
                df_reservas["monto_reserva"], errors="coerce"
            ).fillna(0)

            if vista_finanzas == "📊 Dashboard":
                df_fin_dash = df_reservas.rename(columns={"monto_reserva": "monto_final"}).copy()
                _dashboard_financiero(df_fin_dash, "Dashboard de Finanzas")
                st.caption("Vista ejecutiva sin alterar validación de pagos ni comprobantes.")
                return

            if vista_finanzas == "📋 Resumen":
                st.markdown("#### Resumen por institución")
                resumen = (
                    df_reservas.groupby("institucion", dropna=False)
                    .agg(
                        Reservas=("referencia_reserva","nunique"),
                        Comensales=("rut","nunique"),
                        Monto=("monto_reserva","sum"),
                        Pendientes=("estado_pago", lambda s: int((s.astype(str)!="Pagado").sum())),
                        Comprobantes_por_validar=(
                            "estado_comprobante",
                            lambda s: int(s.fillna("").astype(str).isin(["RECIBIDO"]).sum())
                        ),
                    )
                    .reset_index()
                )
                resumen["Estado"] = resumen["Pendientes"].apply(
                    lambda n: "Al día" if int(n)==0 else "Con pendientes"
                )
                st.dataframe(
                    resumen.rename(columns={"institucion":"Institución"}),
                    use_container_width=True,
                    hide_index=True,
                )
                _grafico_instituciones_linea(resumen.rename(columns={"Monto":"monto"}), "institucion", "monto")
                rep_fin=resumen.rename(columns={"institucion":"Institución","Comprobantes_por_validar":"Comprobantes por validar"}).copy()
                pdf_fin=generar_pdf_tabla_alemsi(
                    "Conciliación financiera por institución",
                    "Estado acumulado al " + date.today().strftime("%d/%m/%Y"),
                    rep_fin,
                    total_texto=f"Monto total: {formato_clp(resumen['Monto'].sum())} · Reservas: {int(resumen['Reservas'].sum())}",
                )
                st.download_button("🖨️ PDF corporativo · conciliación financiera",pdf_fin,file_name=f"ALEMSI_Conciliacion_Financiera_{date.today().isoformat()}.pdf",mime="application/pdf",use_container_width=True,key="pdf_fin_conciliacion")
                return

            if vista_finanzas == "🧾 Validar comprobantes":
                st.markdown("#### 🧾 Bandeja de comprobantes pendientes de revisión")
                st.caption(
                    "Solo se muestran reservas que ya tienen un comprobante cargado y requieren trabajo de Finanzas. "
                    "Las reservas sin comprobante permanecen en el control de pagos pendientes."
                )

                pendientes_comp = df_reservas[
                    df_reservas["comprobante_id"].notna()
                    & df_reservas["estado_comprobante"].fillna("RECIBIDO").astype(str).isin(
                        ["RECIBIDO"]
                    )
                ].copy()

                if pendientes_comp.empty:
                    st.success("✅ No hay comprobantes pendientes de revisión.")
                    return

                instituciones_val = ["Todas"] + sorted(
                    [x for x in pendientes_comp["institucion"].dropna().astype(str).unique().tolist() if x]
                )
                f1, f2 = st.columns(2)
                with f1:
                    institucion_val = st.selectbox(
                        "Institución",
                        instituciones_val,
                        key="fin_validar_institucion",
                    )
                with f2:
                    estado_val = st.selectbox(
                        "Estado de revisión",
                        ["Todos", "RECIBIDO"],
                        key="fin_validar_estado",
                    )

                vista_pend = pendientes_comp.copy()
                if institucion_val != "Todas":
                    vista_pend = vista_pend[
                        vista_pend["institucion"].astype(str) == str(institucion_val)
                    ].copy()
                if estado_val != "Todos":
                    vista_pend = vista_pend[
                        vista_pend["estado_comprobante"].fillna("RECIBIDO").astype(str) == estado_val
                    ].copy()

                if vista_pend.empty:
                    st.info("No hay comprobantes para los filtros seleccionados.")
                    return

                m1, m2, m3 = st.columns(3)
                m1.metric("Pendientes visibles", int(len(vista_pend)))
                m2.metric(
                    "Recibidos",
                    int((vista_pend["estado_comprobante"].fillna("RECIBIDO").astype(str) == "RECIBIDO").sum()),
                )
                m3.metric("Monto visible", formato_clp(vista_pend["monto_reserva"].sum()))

                tabla_bandeja = vista_pend[
                    [
                        "institucion", "nombre", "referencia_reserva",
                        "fecha_carga_comprobante", "monto_reserva",
                        "estado_comprobante", "estado_pago"
                    ]
                ].copy()
                st.dataframe(
                    _tabla_visible(
                        tabla_bandeja,
                        {
                            "institucion": "Institución",
                            "nombre": "Comensal",
                            "referencia_reserva": "Reserva",
                            "fecha_carga_comprobante": "Fecha carga",
                            "monto_reserva": "Monto",
                            "estado_comprobante": "Estado comprobante",
                            "estado_pago": "Estado pago",
                        },
                        ["fecha_carga_comprobante"],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                referencias_val = vista_pend["referencia_reserva"].astype(str).tolist()
                ultimo_fin = st.session_state.pop("_fin_ultimo_procesado", None)
                indice_fin = 0
                if ultimo_fin in referencias_val and len(referencias_val) > 1:
                    indice_actual = referencias_val.index(ultimo_fin)
                    indice_fin = (indice_actual + 1) % len(referencias_val)
                ref_val = selector_neutro(
                    "Comprobante a revisar",
                    referencias_val,
                    key="fin_validar_referencia",
                    format_func=lambda r: (
                        f"{vista_pend[vista_pend['referencia_reserva'].astype(str)==str(r)].iloc[0]['institucion']} · "
                        f"{vista_pend[vista_pend['referencia_reserva'].astype(str)==str(r)].iloc[0]['nombre']} · {r}"
                    ),
                )
                if not ref_val:
                    st.info("Selecciona explícitamente un comprobante para revisar su detalle.")
                    return

                reserva_val = vista_pend[
                    vista_pend["referencia_reserva"].astype(str) == str(ref_val)
                ].iloc[0]

                df_comp_val = conn.query("""
                    SELECT id,nombre_archivo,mime_type,fecha_carga,estado,
                           validado_por,fecha_validacion,observacion_validacion,
                           drive_file_id,drive_url,storage_provider
                    FROM comprobantes_pago
                    WHERE referencia_reserva=:ref
                    ORDER BY fecha_carga DESC,id DESC
                    LIMIT 1
                """, params={"ref": ref_val}, ttl=0)

                if df_comp_val.empty:
                    st.warning("El registro indica comprobante, pero no fue posible recuperar su ficha.")
                    return

                comp_val = df_comp_val.iloc[0]
                st.divider()
                st.markdown(
                    f"### {reserva_val['nombre']} · {reserva_val['institucion']}"
                )
                st.caption(
                    f"Reserva {ref_val} · Monto {formato_clp(reserva_val['monto_reserva'])} · "
                    f"Cargado {fecha_visible(comp_val['fecha_carga'])}"
                )

                visor_col, accion_col = st.columns([3, 2], gap="large")
                with visor_col:
                    archivo_disponible = _render_comprobante_finanzas(
                        conn,
                        comp_val,
                        key_prefix=f"fin_bandeja_{ref_val}",
                    )

                with accion_col:
                    st.markdown("##### Resultado de revisión")
                    # FIN-PERF-32: radio + observación viven dentro de un form. Cambiar
                    # APROBAR/RECHAZAR no dispara un rerun completo hasta confirmar ni vuelve
                    # a descargar/renderizar el comprobante. Solo Confirmar ejecuta.
                    with st.form(f"fin_form_revision_{ref_val}", clear_on_submit=False):
                        nuevo_val = st.radio(
                            "Acción",
                            ["APROBADO", "RECHAZADO"],
                            format_func=lambda x: {
                                "APROBADO": "✅ Aprobar",
                                "RECHAZADO": "❌ Rechazar",
                            }[x],
                            key=f"fin_accion_{ref_val}",
                        )
                        obs_val = st.text_area(
                            "Observación",
                            value=str(comp_val.get("observacion_validacion") or ""),
                            placeholder="Obligatoria para rechazar.",
                            key=f"fin_obs_bandeja_{ref_val}",
                        )
                        requiere_obs_val = nuevo_val == "RECHAZADO"
                        decision_confirmada = st.checkbox(
                            "Confirmo esta decisión financiera",
                            value=False,
                            key=f"fin_confirmar_decision_{ref_val}",
                        )
                        confirmar_revision = st.form_submit_button(
                            "Confirmar revisión", type="primary", use_container_width=True,
                            disabled=(not archivo_disponible or not decision_confirmada or (requiere_obs_val and not obs_val.strip())),
                        )

                    if confirmar_revision:
                        if requiere_obs_val and not obs_val.strip():
                            st.error("Debes ingresar el motivo del rechazo.")
                            return
                        estado_pago_destino = {
                            "APROBADO": "Pagado",
                            "RECHAZADO": "Rechazado",
                        }[nuevo_val]
                        ahora_val = datetime.now().isoformat()

                        with conn.session as ses_val:
                            execute_sql(
                                ses_val,
                                "UPDATE comprobantes_pago "
                                "SET estado=%s,validado_por=%s,fecha_validacion=%s,observacion_validacion=%s "
                                "WHERE referencia_reserva=%s",
                                (
                                    nuevo_val,
                                    usuario.get("username"),
                                    ahora_val,
                                    obs_val.strip() or None,
                                    ref_val,
                                ),
                            )
                            execute_sql(
                                ses_val,
                                "UPDATE solicitudes SET estado_pago=%s,motivo_estado_pago=%s "
                                "WHERE referencia_reserva=%s",
                                (
                                    estado_pago_destino,
                                    obs_val.strip() or None,
                                    ref_val,
                                ),
                            )
                            ses_val.commit()

                        registrar_auditoria(
                            usuario.get("username"),
                            "VALIDAR_COMPROBANTE_BANDEJA",
                            "comprobantes_pago",
                            ref_val,
                            str(comp_val.get("estado") or "RECIBIDO"),
                            nuevo_val,
                            obs_val,
                        )
                        aviso_correo = ""
                        correo_destino = normalizar_correo(str(reserva_val.get("correo") or ""))
                        token_pago = str(reserva_val.get("pago_token") or "").strip()
                        if nuevo_val == "RECHAZADO":
                            url_nuevo = _url_carga_comprobante(token_pago) if token_pago else ""
                            asunto_notif = f"Comprobante rechazado · Reserva {ref_val}"
                            titulo_notif = "Comprobante rechazado"
                            detalle_notif = (
                                f"<p><b>Motivo:</b> {escape(obs_val.strip())}</p>"
                                "<p>Puedes ingresar un nuevo comprobante utilizando el mismo enlace asociado a tu reserva.</p>"
                            )
                            boton_notif = (
                                f"<p style='margin:18px 0'><a href='{url_nuevo}' "
                                "style='background:#168c8e;color:white;padding:12px 18px;text-decoration:none;"
                                "border-radius:8px;font-weight:bold'>SUBIR NUEVO COMPROBANTE</a></p>"
                                if url_nuevo else ""
                            )
                        else:
                            asunto_notif = f"Pago aprobado · Reserva {ref_val}"
                            titulo_notif = "Pago aprobado"
                            detalle_notif = "<p>Finanzas aprobó tu comprobante. La reserva quedó registrada como <b>PAGADA</b> y habilitada.</p>"
                            boton_notif = ""
                        html_notif = f"""
                        <div style='font-family:Arial,sans-serif;max-width:680px;padding:22px;border:1px solid #d8e6e2;border-radius:12px'>
                          <h2 style='color:#0A2F6B'>{titulo_notif}</h2>
                          <p><b>Referencia:</b> {ref_val}</p>
                          {detalle_notif}
                          {boton_notif}
                          <p>La reserva original y su referencia se mantienen sin cambios.</p>
                        </div>
                        """
                        if correo_destino:
                            ok_mail, msg_mail = enviar_email(correo_destino, asunto_notif, html_notif)
                            aviso_correo = " · Notificación enviada al comensal." if ok_mail else f" · Aviso: no se pudo enviar el correo ({msg_mail})."
                        else:
                            aviso_correo = " · Aviso: la reserva no tiene correo de contacto."

                        if nuevo_val == "APROBADO":
                            mensaje_fin, nivel_fin = "✅ Comprobante aprobado. La reserva quedó PAGADA y salió de pendientes." + aviso_correo, "success"
                        else:
                            mensaje_fin, nivel_fin = "❌ Comprobante rechazado. Se conserva el historial y se habilita reingreso." + aviso_correo, "error"
                        _refrescar_finanzas(mensaje_fin, nivel_fin, ref_val)
                return

            if vista_finanzas == "🏢 Por institución":
                st.markdown("#### Gestión financiera por institución")
                st.caption(
                    "Orden de revisión: Institución → Comensal → Reserva → Fecha → Servicio → Estado → Comprobante → Validación. "
                    "El pago y el comprobante se validan sobre la reserva completa."
                )

                instituciones = sorted(
                    [x for x in df_reservas["institucion"].dropna().astype(str).unique().tolist() if x]
                )
                institucion_sel = selector_neutro("Institución", instituciones, key="fin_inst_agrupada")
                if not institucion_sel:
                    _dashboard_financiero(df_reservas.rename(columns={"monto_reserva":"monto_final"}), "Totalizadores generales")
                    st.info("Selecciona una institución para consultar personas y reservas.")
                    return
                df_inst = df_reservas[
                    df_reservas["institucion"].astype(str)==institucion_sel
                ].copy()

                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Reservas", int(df_inst["referencia_reserva"].nunique()))
                c2.metric("Comensales", int(df_inst["rut"].nunique()))
                c3.metric("Monto", formato_clp(df_inst["monto_reserva"].sum()))
                c4.metric(
                    "Pendientes",
                    int((df_inst["estado_pago"].astype(str)!="Pagado").sum()),
                )

                personas = (
                    df_inst[["rut","nombre"]]
                    .drop_duplicates()
                    .sort_values(["nombre","rut"])
                )
                persona_sel = selector_neutro(
                    "Comensal",
                    personas["rut"].astype(str).tolist(),
                    key="fin_persona_agrupada",
                    format_func=lambda r: (
                        f"{personas[personas['rut'].astype(str)==str(r)].iloc[0]['nombre']} · {r}"
                    ),
                )
                if not persona_sel:
                    st.info("Selecciona un comensal para continuar.")
                    return

                df_persona = df_inst[
                    df_inst["rut"].astype(str)==str(persona_sel)
                ].copy()

                refs = df_persona["referencia_reserva"].astype(str).tolist()
                ref_sel = selector_neutro(
                    "Reserva",
                    refs,
                    key="fin_ref_agrupada",
                    format_func=lambda r: (
                        f"{r} · "
                        f"{fecha_visible(df_persona[df_persona['referencia_reserva'].astype(str)==str(r)].iloc[0]['fecha_inicio'])}"
                        f" → "
                        f"{fecha_visible(df_persona[df_persona['referencia_reserva'].astype(str)==str(r)].iloc[0]['fecha_fin'])}"
                    ),
                )
                if not ref_sel:
                    st.info("Selecciona una reserva para ver detalle y comprobante.")
                    return

                reserva = df_persona[
                    df_persona["referencia_reserva"].astype(str)==str(ref_sel)
                ].iloc[0]

                st.markdown(f"### {reserva['nombre']}")
                st.markdown(
                    f"**Reserva:** {ref_sel} · **RUT:** {reserva['rut']} · "
                    f"**Institución:** {reserva['institucion']}"
                )

                r1,r2,r3,r4 = st.columns(4)
                r1.metric("Fechas", int(reserva["fechas_reservadas"] or 0))
                r2.metric("Servicios", int(reserva["servicios_reservados"] or 0))
                r3.metric("Monto reserva", formato_clp(reserva["monto_reserva"]))
                r4.metric("Estado pago", str(reserva["estado_pago"] or "Pendiente"))

                detalle = _detalle_reserva_agrupada(conn, ref_sel)
                _render_detalle_reserva_por_fecha(detalle)

                st.divider()
                st.markdown("##### Comprobante y validación")

                df_comp = conn.query("""
                    SELECT id,nombre_archivo,mime_type,fecha_carga,estado,
                           validado_por,fecha_validacion,observacion_validacion,
                           drive_file_id,drive_url,storage_provider
                    FROM comprobantes_pago
                    WHERE referencia_reserva=:ref
                    ORDER BY fecha_carga DESC,id DESC
                    LIMIT 1
                """, params={"ref": ref_sel}, ttl=0)

                if df_comp.empty:
                    st.info("Esta reserva aún no tiene comprobante cargado.")
                    return

                comp = df_comp.iloc[0]
                st.success(
                    f"Comprobante cargado · {fecha_visible(comp['fecha_carga'])} · "
                    f"Estado: {comp['estado'] or 'RECIBIDO'}"
                )


                archivo_disponible = _render_comprobante_finanzas(

                    conn,

                    comp,

                    key_prefix=f"fin_reserva_{ref_sel}",

                )

                st.info("La vista por institución es de consulta. Para aprobar o rechazar comprobantes utiliza ‘🧾 Validar comprobantes’, que es la única bandeja operativa de Finanzas.")
                return

            # Comprobantes: misma agrupación y misma referencia de reserva.
            st.markdown("#### 📎 Comprobantes por institución y reserva")
            st.caption(
                "Cada comprobante representa una reserva completa. "
                "Las fechas y servicios permanecen agrupados dentro de esa reserva."
            )

            df_comp_res = df_reservas[df_reservas["comprobante_id"].notna()].copy()
            if df_comp_res.empty:
                st.info("No hay comprobantes cargados.")
                return

            instituciones_comp = sorted(
                [x for x in df_comp_res["institucion"].dropna().astype(str).unique().tolist() if x]
            )
            inst_comp = selector_neutro("Institución", instituciones_comp, key="fin_comp_inst_agrupada")
            if not inst_comp:
                st.info("Selecciona una institución para consultar comprobantes.")
                return
            vista_comp = df_comp_res[df_comp_res["institucion"].astype(str)==inst_comp].copy()

            st.dataframe(
                _tabla_visible(
                    vista_comp[
                        [
                            "referencia_reserva","rut","nombre",
                            "fecha_inicio","fecha_fin","fechas_reservadas",
                            "monto_reserva","estado_pago","estado_comprobante"
                        ]
                    ],
                    {
                        "referencia_reserva":"Reserva",
                        "rut":"RUT",
                        "nombre":"Comensal",
                        "fecha_inicio":"Desde",
                        "fecha_fin":"Hasta",
                        "fechas_reservadas":"Fechas",
                        "monto_reserva":"Monto",
                        "estado_pago":"Estado pago",
                        "estado_comprobante":"Estado comprobante",
                    },
                    ["fecha_inicio","fecha_fin"],
                ),
                use_container_width=True,
                hide_index=True,
            )

            ref_comp = selector_neutro("Reserva a revisar", vista_comp["referencia_reserva"].astype(str).tolist(), key="fin_comp_ref_agrupada")
            if not ref_comp:
                st.info("Selecciona una reserva para ver su detalle.")
                return
            fila_comp = vista_comp[
                vista_comp["referencia_reserva"].astype(str)==str(ref_comp)
            ].iloc[0]
            st.markdown(
                f"**{fila_comp['nombre']} · {fila_comp['rut']} · {fila_comp['institucion']}**"
            )
            _render_detalle_reserva_por_fecha(
                _detalle_reserva_agrupada(conn, ref_comp)
            )
            st.info(
                "La validación se realiza en “Por institución”, "
                "donde una sola acción actualiza el comprobante y toda la reserva."
            )
            return

    else:
        st.markdown("### 👨‍🍳 Personal de Casino")
        with st.form("login_casino"):
            u=st.text_input("Usuario",key="u_casino"); p=st.text_input("Contraseña",type="password",key="p_casino")
            if st.form_submit_button("Ingresar",type="primary",use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd",params={"username":str(u).strip().lower(),"pwd":hash_pwd(str(p).strip())},ttl=0)
                if not df.empty and int(df.iloc[0]['activo'])==1 and df.iloc[0]['rol'] in roles_casino:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre'],"debe_cambiar_password":int(df.iloc[0]['debe_cambiar_password'])}; st.session_state.portal_actual="casino"; st.rerun()
                else: st.error("Usuario no válido, deshabilitado o sin permiso para Personal de Casino.")

def render_admin():
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["AdminTotal","AdminCasino","Operaciones","Gerencia","Bodega"]:
        rol_admin = str(st.session_state.usuario.get("rol", ""))
        nombre_perfil = {"AdminCasino":"Administrador de Casino","AdminTotal":"Administrador Total"}.get(rol_admin, rol_admin)
        st.markdown(f'<div class="al-card"><h3>Hola, bienvenido/a</h3><p><b>Perfil: {nombre_perfil}</b></p></div>', unsafe_allow_html=True)
        usuario_admin = st.session_state.usuario.get("username")
        mapa_modulos = [
            ("📈 Dashboard","ver_dashboard",True),
            ("📊 Reportes","ver_reportes",True),
            ("📋 Planilla de Reservas","ver_planilla_reservas",True),
            ("📦 Inventario y Bodega","ver_bodega",True),
            ("🍽️ Minutas","editar_minuta",True),
            ("⭐ Satisfacción","ver_satisfaccion",False),
            ("⚖️ Excepciones","gestionar_excepciones",True),
            ("🏢 Instituciones","gestionar_instituciones",True),
            ("💳 Modalidades de Pago","gestionar_modalidades_pago",True),
            ("📧 Correos","gestionar_correos",True),
        ]
        if rol_admin == "Bodega":
            base_bodega={"📦 Inventario y Bodega","🍽️ Minutas"}
            modulos_admin=[m for m,p,d in mapa_modulos if m in base_bodega or permiso_extraordinario_activo(usuario_admin,p)]
        elif rol_admin == "AdminTotal":
            modulos_admin=[m for m,_,_ in mapa_modulos]
            modulos_admin += ["🏦 Datos transferencia","👥 Usuarios","🧭 Actividad","🧹 Depuración","🛡️ Respaldo"]
        elif rol_admin == "AdminCasino":
            # Perfil operacional base. Finanzas conserva la validación de pagos; los
            # demás módulos pueden ampliarse mediante override explícito de AdminTotal.
            base_casino={"📈 Dashboard","📊 Reportes","📋 Planilla de Reservas","📦 Inventario y Bodega","🍽️ Minutas","⭐ Satisfacción","⚖️ Excepciones","🏢 Instituciones"}
            modulos_admin=[m for m,p,d in mapa_modulos if m in base_casino or permiso_extraordinario_activo(usuario_admin,p)]
        elif rol_admin == "Gerencia":
            # ROL BASE = consulta/análisis. Solo un override explícito de AdminTotal
            # puede sumar un módulo; nunca se heredan capacidades por default.
            base_gerencia={"📈 Dashboard","📊 Reportes","⭐ Satisfacción"}
            modulos_admin=[m for m,p,d in mapa_modulos if m in base_gerencia or permiso_extraordinario_activo(usuario_admin,p)]
        else:
            modulos_admin=[m for m,p,d in mapa_modulos if permiso_habilitado(usuario_admin,p,d)]
        if not modulos_admin:
            st.warning("No tienes módulos administrativos habilitados. Solicita permisos a AdminTotal."); return
        modulo_admin = st.radio("Módulo", modulos_admin, horizontal=True, key="modulo_admin_activo", label_visibility="collapsed")
        if st.session_state.get("_ultimo_modulo_admin") != modulo_admin:
            st.session_state["_ultimo_modulo_admin"] = modulo_admin
            _scroll_top()

        # Solo se consulta/renderiza el módulo elegido. Esto evita ejecutar todas las consultas en cada interacción.
        if modulo_admin == "⭐ Satisfacción":
            _render_satisfaccion_gestion(st.session_state.usuario,key_prefix="admin_sat")

        if modulo_admin == "📊 Reportes":
            st.markdown("### 📊 Reportes de Gestión")
            conn=get_conn()
            if rol_admin == "Gerencia":
                st.caption("Reporte ejecutivo agregado. No contiene RUT, personas, comprobantes ni controles operacionales.")
                rg1,rg2=st.columns(2)
                with rg1: rg_desde=st.date_input("Desde",value=date.today()-timedelta(days=30),key="rep_ger_desde")
                with rg2: rg_hasta=st.date_input("Hasta",value=date.today()+timedelta(days=14),key="rep_ger_hasta")
                if rg_hasta < rg_desde:
                    st.error("La fecha hasta no puede ser anterior a la fecha desde.")
                    return
                rep_ger=conn.query("""
                    WITH base AS (
                      SELECT DISTINCT ON (s.rut,s.fecha,s.servicio)
                             s.rut,s.fecha,s.servicio,s.referencia_reserva,s.estado_pago,
                             COALESCE(s.precio_aplicado,0) AS monto,c.institucion
                      FROM solicitudes s LEFT JOIN comensales c ON c.rut=s.rut
                      WHERE COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA'
                        AND s.fecha>=:d AND s.fecha<=:h
                        AND COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
                      ORDER BY s.rut,s.fecha,s.servicio,s.id DESC
                    )
                    SELECT institucion,COUNT(DISTINCT referencia_reserva) AS reservas,
                           COUNT(*) FILTER (WHERE estado_pago='Pagado') AS pagadas,
                           COUNT(*) FILTER (WHERE estado_pago<>'Pagado' OR estado_pago IS NULL) AS pendientes,
                           SUM(monto) AS valorizacion
                    FROM base GROUP BY institucion ORDER BY reservas DESC,institucion
                """,params={"d":rg_desde.isoformat(),"h":rg_hasta.isoformat()},ttl=0)
                if rep_ger.empty:
                    st.info("No hay reservas activas en el período.")
                    return
                st.dataframe(rep_ger.rename(columns={"institucion":"Institución","reservas":"Reservas","pagadas":"Pagadas","pendientes":"Pendientes","valorizacion":"Valorización"}),use_container_width=True,hide_index=True)
                rgk1,rgk2,rgk3=st.columns(3)
                rgk1.metric("Reservas",int(rep_ger["reservas"].sum()))
                rgk2.metric("Pendientes",int(rep_ger["pendientes"].sum()))
                rgk3.metric("Valorización",formato_clp(pd.to_numeric(rep_ger["valorizacion"],errors="coerce").fillna(0).sum()))
                pdf_rg=generar_pdf_tabla_alemsi("Reporte ejecutivo de Gerencia",f"{rg_desde.strftime('%d/%m/%Y')} → {rg_hasta.strftime('%d/%m/%Y')}",rep_ger.rename(columns={"institucion":"Institución","reservas":"Reservas","pagadas":"Pagadas","pendientes":"Pendientes","valorizacion":"Valorización"}),total_texto=f"Valorización total: {formato_clp(pd.to_numeric(rep_ger['valorizacion'],errors='coerce').fillna(0).sum())}")
                st.download_button("🖨️ PDF corporativo · reporte ejecutivo",pdf_rg,file_name=f"ALEMSI_Gerencia_Ejecutivo_{rg_desde.isoformat()}_{rg_hasta.isoformat()}.pdf",mime="application/pdf",use_container_width=True,key="pdf_gerencia_reportes")
                return
            st.caption("Información consolidada para seguimiento financiero, reservas y producción.")

            # 1. Pagos Pendientes
            st.markdown("#### 1️⃣ Pagos Pendientes de Validación")
            df_pend = conn.query("""
                SELECT s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.precio_aplicado, s.codigo, s.estado_pago 
                FROM solicitudes s 
                JOIN comensales c ON s.rut=c.rut 
                WHERE s.estado_pago=:estado_pago 
                ORDER BY s.fecha DESC
            """, params={"estado_pago": "Pendiente"}, ttl=0)
            st.dataframe(_tabla_visible(df_pend,{"fecha":"Fecha","rut":"RUT","nombre":"Nombre","institucion":"Institución","plato_reservado":"Plato reservado","metodo_pago":"Modalidad de pago","precio_aplicado":"Monto","codigo":"Código","estado_pago":"Estado de pago"},["fecha"]),use_container_width=True,hide_index=True)
            c1,c2=st.columns(2)
            with c1: st.metric("Total registros pendientes", len(df_pend))
            with c2: st.metric("Monto total pendiente", formato_clp(df_pend['precio_aplicado'].sum() if not df_pend.empty else 0))
            st.download_button("📎 Exportación técnica CSV · pagos pendientes", df_pend.to_csv(index=False).encode('utf-8'), "pagos_pendientes.csv", "text/csv")

            # CIERRE-39: conciliación simple de comensales y pagos, con histórico de pagados.
            st.markdown("#### Comensales y estado de pago")
            df_conc = conn.query("""
                SELECT s.referencia_reserva, MIN(s.fecha) AS fecha, s.rut, MAX(c.nombre) AS nombre,
                       MAX(c.institucion) AS institucion, SUM(COALESCE(s.precio_aplicado,0)) AS monto,
                       MAX(COALESCE(s.estado_pago,'Pendiente')) AS estado_pago
                FROM solicitudes s LEFT JOIN comensales c ON c.rut=s.rut
                WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO'
                GROUP BY s.referencia_reserva,s.rut ORDER BY MIN(s.fecha) DESC
            """, ttl=0)
            if not df_conc.empty:
                estados = df_conc['estado_pago'].fillna('Pendiente').astype(str)
                pag = df_conc[estados.str.lower().eq('pagado')]
                pend = df_conc[~estados.str.lower().eq('pagado')]
                k1,k2,k3,k4=st.columns(4)
                k1.metric("Reservas",len(df_conc)); k2.metric("Pagadas",len(pag)); k3.metric("Por cobrar",len(pend)); k4.metric("Valorización",formato_clp(df_conc['monto'].sum()))
                vista_conc=df_conc[['nombre','institucion','fecha','estado_pago','monto']].rename(columns={'nombre':'Comensal','institucion':'Institución','fecha':'Fecha','estado_pago':'Estado','monto':'Monto'})
                st.dataframe(vista_conc,use_container_width=True,hide_index=True)
                st.download_button("📎 Exportación técnica CSV · conciliación",df_conc.to_csv(index=False).encode('utf-8'),"alemsi_conciliacion_pagos.csv","text/csv",use_container_width=True)
                with st.expander("Pagos ya validados"):
                    st.dataframe(pag[['nombre','institucion','fecha','monto','referencia_reserva']].rename(columns={'nombre':'Comensal','institucion':'Institución','fecha':'Fecha','monto':'Monto','referencia_reserva':'Referencia'}),use_container_width=True,hide_index=True)

            st.markdown("#### Ranking de platos solicitados")
            df_rank = conn.query("""
                WITH base AS (SELECT DISTINCT ON (rut,fecha,servicio) rut,fecha,servicio,plato_reservado FROM solicitudes
                WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA' AND COALESCE(plato_reservado,'')<>'' ORDER BY rut,fecha,servicio,id DESC)
                SELECT plato_reservado AS plato, servicio, COUNT(*) AS reservas FROM base
                GROUP BY plato_reservado,servicio ORDER BY reservas DESC,plato_reservado
            """,ttl=0)
            if not df_rank.empty:
                st.dataframe(df_rank.rename(columns={'plato':'Plato','servicio':'Servicio','reservas':'Reservas'}),use_container_width=True,hide_index=True)
                st.caption(f"Más solicitado: {df_rank.iloc[0]['plato']} · {int(df_rank.iloc[0]['reservas'])} reserva(s). Menos solicitado: {df_rank.iloc[-1]['plato']} · {int(df_rank.iloc[-1]['reservas'])} reserva(s).")

            st.divider()

            # 2. Minuta vigente (vista aprobada) + demanda real separada
            st.markdown("#### 2️⃣ Minuta vigente")
            st.caption("La minuta planificada se muestra separada de la demanda/reservas para no confundir planificación con producción.")
            hoy_rep = date.today()
            inicio_sem_rep = hoy_rep - timedelta(days=hoy_rep.weekday())
            fin_sem_rep = inicio_sem_rep + timedelta(days=6)
            df_min_rep = conn.query(
                "SELECT fecha,dia_semana,servicio,tipo_opcion,plato FROM minutas "
                "WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha,id",
                params={"i":inicio_sem_rep.isoformat(),"f":fin_sem_rep.isoformat()},
                ttl=0,
            )
            _render_minuta_semanal(
                df_min_rep,
                fecha_base=inicio_sem_rep,
                titulo=True,
                titulo_personalizado=f"📅 Semana {inicio_sem_rep.strftime('%d/%m')} → {fin_sem_rep.strftime('%d/%m')}",
            )

            st.markdown("#### 3️⃣ Producción y conteo por servicio")
            fecha_prod_rep = st.date_input("Fecha del reporte de producción", value=date.today(), key="reporte_prod_fecha")
            _render_reporte_produccion_fecha(fecha_prod_rep.isoformat(), titulo=False, mostrar_nominal=True)
            with st.expander("Histórico agregado de platos solicitados"):
                df_platos_dia = conn.query("""
                    WITH base AS (
                        SELECT DISTINCT ON (rut,fecha,servicio) id,rut,fecha,servicio,plato_reservado,precio_aplicado,tipo_registro,estado_consumo
                        FROM solicitudes
                        WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA' AND (COALESCE(tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR estado_consumo='Consumirá')
                        ORDER BY rut,fecha,servicio,id DESC
                    )
                    SELECT fecha, plato_reservado, servicio, COUNT(*) as total_solicitado, SUM(precio_aplicado) as monto_total
                    FROM base
                    GROUP BY fecha, plato_reservado, servicio
                    ORDER BY fecha ASC, servicio, plato_reservado
                """, ttl=0)
                st.dataframe(_tabla_visible(df_platos_dia,{"fecha":"Fecha","plato_reservado":"Plato","servicio":"Servicio","total_solicitado":"Porciones reservadas","monto_total":"Monto"},["fecha"]),use_container_width=True,hide_index=True)
                if not df_platos_dia.empty:
                    st.download_button("📎 Exportación técnica CSV · histórico de platos", df_platos_dia.to_csv(index=False).encode('utf-8'), "platos_por_dia.csv", "text/csv")

            st.divider()

            # 4. Control General de Reservas
            st.markdown("#### 4️⃣ Control general de reservas")
            df_control = conn.query("SELECT s.id, s.referencia_reserva, s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.estado_pago, s.estado_consumo, s.precio_aplicado, s.codigo FROM solicitudes s LEFT JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 500", ttl=0)
            st.dataframe(_tabla_visible(df_control,{"referencia_reserva":"Referencia","fecha":"Fecha","rut":"RUT","nombre":"Nombre","institucion":"Institución","plato_reservado":"Plato","metodo_pago":"Modalidad de pago","estado_pago":"Estado de pago","estado_consumo":"Estado de consumo","precio_aplicado":"Monto","codigo":"Código"},["fecha"]),use_container_width=True,hide_index=True)
            st.metric("Total reservas históricas", len(df_control))
            pdf_control=generar_pdf_tabla_alemsi(
                "Control operativo de reservas",
                "Acumulado al " + date.today().strftime("%d/%m/%Y"),
                df_control[["fecha","institucion","plato_reservado","estado_pago","precio_aplicado"]].rename(columns={"fecha":"Fecha","institucion":"Institución","plato_reservado":"Plato","estado_pago":"Estado","precio_aplicado":"Monto"}),
                total_texto=f"Registros visibles: {len(df_control)}",
            )
            st.download_button("🖨️ PDF corporativo · control operativo",pdf_control,file_name=f"ALEMSI_Control_Operativo_{date.today().isoformat()}.pdf",mime="application/pdf",use_container_width=True,key="pdf_control_operativo")
            st.download_button("📎 Exportación técnica CSV · control general", df_control.to_csv(index=False).encode('utf-8'), "control_reservas.csv", "text/csv")

            st.divider()
            st.markdown("##### 🔄 Análisis ejecutivo")
            if rol_admin == "Gerencia":
                st.caption("Vista ejecutiva: las acciones operativas de pago y Bodega se gestionan en sus módulos autorizados.")
            else:
                st.caption("Los pagos se aprueban o rechazan exclusivamente en Finanzas. AdminCasino mantiene consulta operativa; cualquier capacidad extraordinaria debe otorgarse desde permisos por AdminTotal.")
                st.markdown("**Valorización bodega**")
                df_bod = conn.query("SELECT SUM(stock*precio) as valorizado FROM bodega_inventario", ttl=0)
                st.metric("Bodega valorizada", formato_clp(df_bod.iloc[0]['valorizado'] if not df_bod.empty and df_bod.iloc[0]['valorizado'] else 0))

        if modulo_admin == "📋 Planilla de Reservas":
            st.markdown("### Planilla de reservas")
            st.caption("Cada fila corresponde a un servicio reservado. La referencia agrupa toda la operación del comensal.")
            conn = get_conn()
            df_planilla = conn.query("""
                SELECT s.referencia_reserva AS referencia, s.fecha, s.servicio, s.rut, c.nombre, c.institucion, c.correo, s.plato_reservado AS plato, s.precio_aplicado, s.metodo_pago, s.estado_pago, s.estado_consumo, s.codigo, s.fecha_creacion, s.fecha_modificacion, s.tipo_registro
                FROM solicitudes s LEFT JOIN comensales c ON c.rut=s.rut ORDER BY s.fecha DESC, s.referencia_reserva, s.servicio
            """,ttl=10)
            st.markdown("#### Filtros")
            f1,f2,f3,f4=st.columns(4)
            with f1: filtro_persona=st.selectbox("Funcionario / comensal",["Todos"]+sorted(df_planilla['nombre'].dropna().astype(str).unique().tolist()) if not df_planilla.empty else ["Todos"])
            with f2: filtro_inst=st.selectbox("Institución",["Todas"]+sorted(df_planilla['institucion'].dropna().astype(str).unique().tolist()) if not df_planilla.empty else ["Todas"])
            modalidades_planilla = (["Todas"] + sorted(df_planilla['metodo_pago'].dropna().apply(_normalizar_modalidad_pago).unique().tolist())) if not df_planilla.empty else ["Todas"]
            with f3: filtro_met=st.selectbox("Modalidad de pago", modalidades_planilla)
            with f4: filtro_est=st.selectbox("Estado de pago",["Todos"]+sorted(df_planilla['estado_pago'].dropna().astype(str).unique().tolist()) if not df_planilla.empty else ["Todos"])
            d1,d2=st.columns(2)
            with d1: fecha_desde=st.date_input("Desde",value=date.today()-timedelta(days=30),key="planilla_desde")
            with d2: fecha_hasta=st.date_input("Hasta",value=date.today()+timedelta(days=30),key="planilla_hasta")
            if not df_planilla.empty:
                fp=df_planilla.copy(); fd=pd.to_datetime(fp['fecha'],errors='coerce').dt.date; fp=fp[(fd>=fecha_desde)&(fd<=fecha_hasta)]
                if filtro_persona!="Todos": fp=fp[fp['nombre'].astype(str)==filtro_persona]
                if filtro_inst!="Todas": fp=fp[fp['institucion'].astype(str)==filtro_inst]
                if filtro_met!="Todas": fp=fp[fp['metodo_pago'].apply(_normalizar_modalidad_pago)==filtro_met]
                if filtro_est!="Todos": fp=fp[fp['estado_pago'].astype(str)==filtro_est]
                df_planilla=fp
            st.dataframe(_tabla_visible(df_planilla,{"referencia":"Referencia","fecha":"Fecha","servicio":"Servicio","rut":"RUT","nombre":"Nombre","institucion":"Institución","correo":"Correo","plato":"Plato","precio_aplicado":"Monto","metodo_pago":"Modalidad de pago","estado_pago":"Estado de pago","estado_consumo":"Estado de consumo","codigo":"Código"},["fecha","fecha_creacion","fecha_modificacion"]),use_container_width=True,hide_index=True)
            if not df_planilla.empty:
                total_planilla = pd.to_numeric(df_planilla["precio_aplicado"], errors="coerce").fillna(0).sum()
                c1, c2 = st.columns(2)
                with c1:
                    st.metric("Registros", len(df_planilla))
                with c2:
                    st.metric("Valor total", formato_clp(total_planilla))
                salida_excel = BytesIO()
                with pd.ExcelWriter(salida_excel, engine="openpyxl") as writer:
                    df_planilla.to_excel(writer, sheet_name="Reservas", index=False)
                st.download_button(
                    "📎 Exportación técnica Excel · planilla de reservas",
                    data=salida_excel.getvalue(),
                    file_name=f"planilla_reservas_{date.today().isoformat()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        if modulo_admin == "📈 Dashboard":
            conn=get_conn(); st.markdown("### Dashboard integral")
            df_dash=conn.query("SELECT s.referencia_reserva,s.fecha,s.servicio,s.rut,c.nombre,c.institucion,s.metodo_pago,s.estado_pago,s.precio_aplicado FROM solicitudes s LEFT JOIN comensales c ON c.rut=s.rut WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL' AND COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA'",ttl=10)
            if not df_dash.empty: df_dash['monto_final']=pd.to_numeric(df_dash['precio_aplicado'],errors='coerce').fillna(0)
            _dashboard_financiero(df_dash,"Resumen financiero y operacional")
            df_turnos=conn.query("SELECT fecha,servicio,COUNT(*) AS comensales FROM solicitudes WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA' AND (COALESCE(tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR estado_consumo='Consumirá') GROUP BY fecha,servicio ORDER BY fecha, CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END",ttl=10)
            if not df_turnos.empty:
                st.markdown("#### Comensales por servicio")
                st.bar_chart(df_turnos.groupby('servicio')['comensales'].sum())
                with st.expander("Ver detalle de reservas por fecha y servicio", expanded=False):
                    st.dataframe(
                        _tabla_visible(df_turnos,{"fecha":"Fecha","servicio":"Servicio","comensales":"Comensales"},["fecha"]),
                        use_container_width=True,
                        hide_index=True,
                    )

            st.divider()
            st.markdown("#### Vista agrupada por institución y reserva")
            st.caption(
                "Gerencia analiza demanda, valorización y tendencias por institución. El detalle personal y los comprobantes no forman parte de la vista ejecutiva."
            )
            df_ger_res = conn.query("""
                SELECT
                    s.referencia_reserva,
                    s.rut,
                    MAX(c.nombre) AS nombre,
                    MAX(c.institucion) AS institucion,
                    MIN(s.fecha) AS fecha_inicio,
                    MAX(s.fecha) AS fecha_fin,
                    COUNT(DISTINCT s.fecha) AS fechas,
                    COUNT(*) AS servicios,
                    SUM(COALESCE(s.precio_aplicado,0)) AS monto,
                    MAX(s.estado_pago) AS estado_pago,
                    MAX(cp.estado) AS estado_comprobante
                FROM solicitudes s
                LEFT JOIN comensales c ON c.rut=s.rut
                LEFT JOIN comprobantes_pago cp ON cp.referencia_reserva=s.referencia_reserva
                WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
                  AND COALESCE(s.estado_reserva,'ACTIVA')='ACTIVA'
                  AND COALESCE(NULLIF(s.referencia_reserva,''),'') <> ''
                GROUP BY s.referencia_reserva,s.rut
                ORDER BY MAX(c.institucion),MAX(c.nombre),MIN(s.fecha)
            """, ttl=10)

            if not df_ger_res.empty:
                instituciones_ger = sorted(
                    [x for x in df_ger_res["institucion"].dropna().astype(str).unique().tolist() if x]
                )
                inst_ger = selector_neutro("Institución a analizar", instituciones_ger, key="ger_inst_agrupada")
                vista_ger = df_ger_res.copy()
                if inst_ger:
                    vista_ger = vista_ger[
                        vista_ger["institucion"].astype(str)==inst_ger
                    ].copy()

                resumen_ger = (
                    vista_ger.groupby("institucion", dropna=False)
                    .agg(
                        Reservas=("referencia_reserva","nunique"),
                        Comensales=("rut","nunique"),
                        Monto=("monto","sum"),
                        Pendientes=("estado_pago", lambda s: int((s.astype(str)!="Pagado").sum())),
                    )
                    .reset_index()
                )
                st.dataframe(
                    resumen_ger.rename(columns={"institucion":"Institución"}),
                    use_container_width=True,
                    hide_index=True,
                )
                _grafico_instituciones_linea(resumen_ger.rename(columns={"Monto":"monto"}), "institucion", "monto")
                st.caption("Gerencia consulta indicadores agregados; no se muestran comprobantes ni datos personales individuales por defecto.")
                gp1,gp2=st.columns(2)
                with gp1: periodo_desde=st.date_input("Período desde",value=date.today()-timedelta(days=30),key="ger_rank_desde")
                with gp2: periodo_hasta=st.date_input("Período hasta",value=date.today()+timedelta(days=14),key="ger_rank_hasta")
                if periodo_hasta < periodo_desde:
                    st.error("El período hasta no puede ser anterior al período desde.")
                    return
                gk1,gk2,gk3,gk4 = st.columns(4)
                gk1.metric("Reservas", int(df_ger_res["referencia_reserva"].nunique()))
                gk2.metric("Pagadas", int((df_ger_res["estado_pago"].astype(str)=="Pagado").sum()))
                gk3.metric("Por pagar", int((df_ger_res["estado_pago"].astype(str)!="Pagado").sum()))
                gk4.metric("Valorización", formato_clp(pd.to_numeric(df_ger_res["monto"],errors="coerce").fillna(0).sum()))
                df_rank = conn.query("""
                    WITH base AS (
                      SELECT DISTINCT ON (rut,fecha,servicio) rut,fecha,servicio,COALESCE(plato_reservado,plato) plato,id
                      FROM solicitudes
                      WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA' AND fecha>=:d AND fecha<=:h
                      ORDER BY rut,fecha,servicio,id DESC
                    )
                    SELECT plato,COUNT(*) cantidad FROM base GROUP BY plato ORDER BY cantidad DESC,plato
                """,params={"d":periodo_desde.isoformat(),"h":periodo_hasta.isoformat()},ttl=0)
                if not df_rank.empty:
                    total_rank=max(1,int(df_rank["cantidad"].sum()))
                    df_rank["participacion_pct"]=(df_rank["cantidad"]*100/total_rank).round(1)
                    st.markdown("#### Ranking ejecutivo de platos")
                    st.bar_chart(df_rank.set_index("plato")["cantidad"])
                    rc1,rc2=st.columns(2)
                    with rc1: st.dataframe(df_rank.head(5).rename(columns={"plato":"Más solicitados","cantidad":"Cantidad","participacion_pct":"%"}),use_container_width=True,hide_index=True)
                    with rc2: st.dataframe(df_rank.tail(5).sort_values("cantidad").rename(columns={"plato":"Menos solicitados","cantidad":"Cantidad","participacion_pct":"%"}),use_container_width=True,hide_index=True)
                    pdf_ger=generar_pdf_tabla_alemsi(
                        "Reporte ejecutivo de Gerencia · demanda por institución",
                        f"{periodo_desde.strftime('%d/%m/%Y')} → {periodo_hasta.strftime('%d/%m/%Y')}",
                        resumen_ger.rename(columns={"institucion":"Institución"}),
                        total_texto=f"Reservas activas: {int(df_ger_res['referencia_reserva'].nunique())} · Valorización: {formato_clp(pd.to_numeric(df_ger_res['monto'],errors='coerce').fillna(0).sum())}",
                    )
                    st.download_button("🖨️ PDF corporativo · reporte ejecutivo",pdf_ger,file_name=f"ALEMSI_Gerencia_{periodo_desde.isoformat()}_{periodo_hasta.isoformat()}.pdf",mime="application/pdf",use_container_width=True,key="pdf_gerencia_ejecutivo")

        if modulo_admin == "📦 Inventario y Bodega":
            st.markdown("#### 📦 Inventario y Bodega")
            conn=get_conn(); df_inv=conn.query("SELECT id,codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion FROM bodega_inventario ORDER BY nombre_articulo",ttl=20)
            st.dataframe(_tabla_visible(df_inv,{"codigo_insumo":"Código","nombre_articulo":"Producto","unidad":"Unidad","stock":"Stock teórico","precio":"Valor unitario","critico":"Stock crítico","caduca":"Vencimiento","seccion":"Sección"},["caduca"]),use_container_width=True,hide_index=True)

            # INV-TAREA-02: Admin_Casino/AdminTotal ordenan inventario a Cocina.
            if rol_admin in ["AdminCasino", "AdminTotal"]:
                st.divider()
                st.markdown("##### 📋 Tareas de inventario para Cocina")
                ta1, ta2 = st.tabs(["➕ Ordenar inventario", "🗂️ Seguimiento"])

                with ta1:
                    familias_disp = sorted(
                        [x for x in df_inv.get("familia", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if x]
                    ) if "familia" in df_inv.columns else []
                    secciones_disp = sorted(
                        [x for x in df_inv.get("seccion", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if x]
                    ) if "seccion" in df_inv.columns else []

                    with st.form("admin_casino_orden_inventario"):
                        c1, c2 = st.columns(2)
                        with c1:
                            fecha_programada = st.date_input(
                                "Fecha para realizar inventario",
                                value=date.today(),
                                key="orden_inv_fecha",
                            )
                            prioridad = st.selectbox(
                                "Prioridad",
                                ["Normal", "Alta", "Urgente"],
                                key="orden_inv_prioridad",
                            )
                        with c2:
                            familia_t = st.selectbox(
                                "Familia",
                                ["Todas"] + familias_disp,
                                key="orden_inv_familia",
                            )
                            seccion_t = st.selectbox(
                                "Sección",
                                ["Todas"] + secciones_disp,
                                key="orden_inv_seccion",
                            )
                        detalle_t = st.text_area(
                            "Instrucción para Cocina",
                            placeholder="Ej.: realizar conteo físico de productos refrigerados y registrar diferencias.",
                            key="orden_inv_detalle",
                        )
                        crear_t = st.form_submit_button(
                            "📌 Crear tarea pendiente para Cocina",
                            type="primary",
                            use_container_width=True,
                        )

                    if crear_t:
                        detalle_final = detalle_t.strip() or "Realizar inventario físico solicitado por Administración Casino."
                        ahora_t = datetime.now().isoformat()
                        with conn.session as ses_t:
                            execute_sql(
                                ses_t,
                                """
                                INSERT INTO tareas_inventario_cocina
                                (fecha_creacion,creado_por,asignado_a,fecha_programada,familia,seccion,detalle,prioridad,estado)
                                VALUES (%s,%s,'Cocina',%s,%s,%s,%s,%s,'Pendiente')
                                """,
                                (
                                    ahora_t,
                                    st.session_state.usuario.get("username"),
                                    fecha_programada.isoformat(),
                                    None if familia_t == "Todas" else familia_t,
                                    None if seccion_t == "Todas" else seccion_t,
                                    detalle_final,
                                    prioridad,
                                ),
                            )
                            ses_t.commit()
                        registrar_auditoria(
                            st.session_state.usuario.get("username"),
                            "CREAR_TAREA_INVENTARIO_COCINA",
                            "tareas_inventario_cocina",
                            fecha_programada.isoformat(),
                            "",
                            "Pendiente",
                            detalle_final,
                        )
                        st.success("✅ Tarea creada. Cocina la verá como pendiente al ingresar.")
                        st.rerun()

                with ta2:
                    df_tareas_admin = conn.query(
                        """
                        SELECT id,fecha_creacion,fecha_programada,familia,seccion,detalle,prioridad,
                               estado,creado_por,iniciado_por,fecha_inicio,resultado,
                               completado_por,fecha_completado,revisado_por,fecha_revision
                        FROM tareas_inventario_cocina
                        ORDER BY id DESC
                        LIMIT 100
                        """,
                        ttl=10,
                    )
                    if df_tareas_admin.empty:
                        st.info("No hay tareas de inventario registradas.")
                    else:
                        st.dataframe(
                            _tabla_visible(
                                df_tareas_admin[
                                    ["id","fecha_programada","familia","seccion","prioridad","estado",
                                     "creado_por","completado_por","fecha_completado","resultado"]
                                ],
                                {
                                    "id":"N.º",
                                    "fecha_programada":"Programada",
                                    "familia":"Familia",
                                    "seccion":"Sección",
                                    "prioridad":"Prioridad",
                                    "estado":"Estado",
                                    "creado_por":"Ordenada por",
                                    "completado_por":"Realizada por",
                                    "fecha_completado":"Enviada",
                                    "resultado":"Resultado",
                                },
                                ["fecha_programada","fecha_completado"],
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                        revisar_ids = df_tareas_admin[
                            df_tareas_admin["estado"].astype(str) == "Enviado a revisión"
                        ]["id"].astype(int).tolist()
                        if revisar_ids:
                            rid = selector_neutro("Tarea enviada a revisión", revisar_ids, key="admin_revision_tarea_inv")
                            if rid is None:
                                st.info("Selecciona una tarea para revisar su resultado.")
                                return
                            rr = df_tareas_admin[
                                df_tareas_admin["id"].astype(int) == int(rid)
                            ].iloc[0]
                            st.info(str(rr.get("resultado") or "Sin resultado informado."))
                            if st.button(
                                "✅ Cerrar tarea revisada",
                                type="primary",
                                use_container_width=True,
                                key=f"cerrar_tarea_inv_{rid}",
                            ):
                                ahora_r = datetime.now().isoformat()
                                with conn.session as ses_r:
                                    execute_sql(
                                        ses_r,
                                        "UPDATE tareas_inventario_cocina "
                                        "SET estado='Cerrado',revisado_por=%s,fecha_revision=%s WHERE id=%s",
                                        (
                                            st.session_state.usuario.get("username"),
                                            ahora_r,
                                            int(rid),
                                        ),
                                    )
                                    ses_r.commit()
                                registrar_auditoria(
                                    st.session_state.usuario.get("username"),
                                    "CERRAR_TAREA_INVENTARIO_COCINA",
                                    "tareas_inventario_cocina",
                                    str(rid),
                                    "Enviado a revisión",
                                    "Cerrado",
                                    "",
                                )
                                st.success("Tarea cerrada. El registro queda en la trazabilidad.")
                                st.rerun()

        if modulo_admin == "🍽️ Minutas":
            flash_minuta = st.session_state.pop("_flash_minuta", None)
            if flash_minuta: st.success(flash_minuta)
            try:
                obs_rec= get_conn().query("SELECT plato,version_receta,accion,observacion,usuario,fecha_accion,estado FROM receta_revision_coordinacion WHERE accion='OBSERVAR' ORDER BY fecha_accion DESC,id DESC",ttl=0)
                if not obs_rec.empty:
                    with st.expander(f"🤝 Coordinación · observaciones de recetas · {len(obs_rec)}",expanded=False):
                        st.dataframe(_tabla_visible(obs_rec,{"plato":"Plato","version_receta":"Versión","accion":"Acción","observacion":"Observación","usuario":"Usuario","fecha_accion":"Fecha / hora","estado":"Estado"},["fecha_accion"]),use_container_width=True,hide_index=True)
            except Exception:
                pass
            st.markdown("#### 🍽️ Calendario de minutas por período")
            st.caption("El usuario define libremente el rango que desea visualizar.")
            conn=get_conn()
            ca1,ca2=st.columns(2)
            with ca1: ini=st.date_input("Desde",value=date.today(),key="minuta_admin_desde")
            with ca2: fin=st.date_input("Hasta",value=date.today()+timedelta(days=13),key="minuta_admin_hasta")
            if fin < ini:
                st.error("La fecha hasta no puede ser anterior a la fecha desde.")
                df_min=pd.DataFrame()
            else:
                df_min=conn.query("SELECT id,fecha,dia_semana,servicio,tipo_opcion,plato,activo,COALESCE(estado,'PUBLICABLE') AS estado FROM minutas WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha, CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,id",params={"i":ini.isoformat(),"f":fin.isoformat()},ttl=0)
                if df_min.empty:
                    st.info("No hay minutas cargadas para el período seleccionado.")
                else:
                    fechas_vis=[ini+timedelta(days=i) for i in range((fin-ini).days+1)]
                    _render_minuta_semanal(df_min,fechas_visibles=fechas_vis,titulo_personalizado=f"📅 {ini.strftime('%d/%m/%Y')} → {fin.strftime('%d/%m/%Y')}")
                    st.dataframe(df_min[["fecha","servicio","tipo_opcion","plato","estado"]].rename(columns={"fecha":"Fecha","servicio":"Servicio","tipo_opcion":"Opción","plato":"Plato","estado":"Estado"}),use_container_width=True,hide_index=True)

                    conflictos=[]
                    for (fconf,sconf),grp in df_min.groupby(["fecha","servicio"]):
                        mapa={str(r["tipo_opcion"]).strip().upper():str(r["plato"]).strip() for _,r in grp.iterrows()}
                        p1=mapa.get("OPCION 1",""); p2=mapa.get("OPCION 2","")
                        if p1 and p2 and p1.casefold()==p2.casefold():
                            conflictos.append({"Fecha":fconf,"Servicio":sconf,"Opciones":"Opción 1 / Opción 2","Plato":p1})
                    if conflictos:
                        st.error("Conflicto de minuta: Opción 1 y Opción 2 repiten el mismo plato. Debe corregirse antes de publicar.")
                        st.dataframe(pd.DataFrame(conflictos),use_container_width=True,hide_index=True)
                    else:
                        ab1,ab2=st.columns(2)
                        with ab1:
                            if st.button("🔎 Auditar período",use_container_width=True,key="auditar_minuta_periodo"):
                                with conn.session as ses:
                                    execute_sql(ses,"UPDATE minutas SET estado='AUDITADA' WHERE activo=1 AND fecha>=%s AND fecha<=%s AND COALESCE(estado,'PUBLICABLE')='BORRADOR'",(ini.isoformat(),fin.isoformat()))
                                    ses.commit()
                                registrar_auditoria(st.session_state.usuario.get('username'),'AUDITAR_MINUTA','minutas',f"{ini.isoformat()}..{fin.isoformat()}",'BORRADOR','AUDITADA','Sin conflictos Opción 1/Opción 2')
                                st.session_state["_flash_minuta"]="✅ Minuta auditada sin conflictos."; st.rerun()
                        with ab2:
                            auditadas=int((df_min["estado"].astype(str)=="AUDITADA").sum())
                            if st.button("✅ Publicar período",use_container_width=True,key="publicar_minuta_periodo",disabled=(auditadas==0)):
                                with conn.session as ses:
                                    execute_sql(ses,"UPDATE minutas SET estado='PUBLICABLE' WHERE activo=1 AND fecha>=%s AND fecha<=%s AND estado='AUDITADA'",(ini.isoformat(),fin.isoformat()))
                                    ses.commit()
                                registrar_auditoria(st.session_state.usuario.get('username'),'PUBLICAR_MINUTA','minutas',f"{ini.isoformat()}..{fin.isoformat()}",'AUDITADA','PUBLICABLE','Publicación posterior a auditoría')
                                get_minutas_rango.clear(); st.session_state["_flash_minuta"]="✅ Minuta publicada para reservas."; st.rerun()
            _sincronizar_maestro_platos()
            with st.expander("📚 Maestro de Platos · catálogo reutilizable", expanded=False):
                st.caption("Fuente única para crear minutas. Los platos históricos de Minutas se incorporan al maestro sin modificar costos ni recetas.")
                mp1,mp2,mp3=st.columns(3)
                with mp1:
                    buscar_mp=st.text_input("Buscar plato",key="mp_buscar").strip()
                with mp2:
                    servicio_mp=st.selectbox("Servicio",["Todos","Desayuno","Almuerzo","Once","Cena"],key="mp_servicio")
                with mp3:
                    tipo_mp=st.selectbox("Tipo",["Todos","Seco","Húmedo/Guiso","Caldo/Sopa","Hipocalórico","Sin clasificar"],key="mp_tipo")
                sql_mp="SELECT id,nombre,servicio,tipo_plato,proteina_principal,temporada,activo,descripcion FROM platos WHERE 1=1"
                params_mp={}
                if buscar_mp:
                    sql_mp += " AND LOWER(nombre) LIKE :q"; params_mp["q"]="%"+buscar_mp.lower()+"%"
                if servicio_mp!="Todos":
                    sql_mp += " AND COALESCE(servicio,'')=:s"; params_mp["s"]=servicio_mp
                if tipo_mp=="Sin clasificar":
                    sql_mp += " AND TRIM(COALESCE(tipo_plato,''))=''"
                elif tipo_mp!="Todos":
                    sql_mp += " AND COALESCE(tipo_plato,'')=:t"; params_mp["t"]=tipo_mp
                sql_mp += " ORDER BY nombre,servicio LIMIT 1000"
                df_mp=conn.query(sql_mp,params=params_mp,ttl=0)
                st.dataframe(df_mp.rename(columns={"nombre":"Plato","servicio":"Servicio","tipo_plato":"Tipo","proteina_principal":"Proteína","temporada":"Temporada","activo":"Activo","descripcion":"Descripción"}),use_container_width=True,hide_index=True)
                if not df_mp.empty:
                    st.download_button("📎 Exportación técnica CSV · maestro de platos",df_mp.to_csv(index=False).encode("utf-8"),"maestro_platos.csv","text/csv",use_container_width=True)
                st.markdown("##### Agregar / completar plato")
                with st.form("form_maestro_plato"):
                    m1,m2=st.columns(2)
                    with m1:
                        nombre_mp=st.text_input("Nombre del plato*")
                        serv_mp=st.selectbox("Servicio habitual",["","Desayuno","Almuerzo","Once","Cena"])
                        tipo_n_mp=st.selectbox("Tipo de plato",["","Seco","Húmedo/Guiso","Caldo/Sopa","Hipocalórico"])
                    with m2:
                        prot_mp=st.text_input("Proteína principal")
                        temp_mp=st.text_input("Temporada / referencia")
                        desc_mp=st.text_input("Descripción")
                    guardar_mp=st.form_submit_button("Guardar en Maestro",type="primary",use_container_width=True)
                if guardar_mp:
                    if not nombre_mp.strip():
                        st.error("Ingresa el nombre del plato.")
                    else:
                        with conn.session as ses:
                            ex_mp=execute_sql(ses,"SELECT id FROM platos WHERE LOWER(TRIM(nombre))=LOWER(TRIM(%s)) ORDER BY id LIMIT 1",(nombre_mp.strip(),)).first()
                            if ex_mp:
                                execute_sql(ses,"UPDATE platos SET tipo_plato=%s,proteina_principal=%s,temporada=%s,descripcion=COALESCE(NULLIF(%s,''),descripcion),activo=1 WHERE id=%s",(tipo_n_mp or None,prot_mp.strip() or None,temp_mp.strip() or None,desc_mp.strip(),ex_mp[0]))
                                accion_mp="ACTUALIZAR_PLATO_MAESTRO"
                            else:
                                execute_sql(ses,"INSERT INTO platos (nombre,servicio,valor,activo,descripcion,tipo_plato,proteina_principal,temporada) VALUES (%s,%s,0,1,%s,%s,%s,%s)",(nombre_mp.strip(),serv_mp,desc_mp.strip(),tipo_n_mp or None,prot_mp.strip() or None,temp_mp.strip() or None))
                                accion_mp="CREAR_PLATO_MAESTRO"
                            ses.commit()
                        registrar_auditoria(st.session_state.usuario.get('username'),accion_mp,'platos',nombre_mp.strip(),'','catálogo actualizado',serv_mp)
                        st.session_state["_flash_minuta"]="✅ Maestro de Platos actualizado."
                        st.rerun()

            with st.expander("Agregar o editar minuta por fecha"):
                _sincronizar_maestro_platos()
                fecha_n=st.date_input("Fecha",value=date.today(),key="min_fecha")
                existentes_fecha=conn.query("SELECT servicio,tipo_opcion,plato FROM minutas WHERE activo=1 AND fecha=:f ORDER BY servicio,tipo_opcion",params={"f":fecha_n.isoformat()},ttl=0)
                if not existentes_fecha.empty:
                    st.caption("Minuta actualmente cargada para la fecha seleccionada")
                    st.dataframe(existentes_fecha.rename(columns={"servicio":"Servicio","tipo_opcion":"Opción","plato":"Plato"}),use_container_width=True,hide_index=True)
                else:
                    st.info("No existe minuta cargada para este día. Puedes crearla desde el Maestro de Platos.")
                serv=st.selectbox("Servicio",["Desayuno","Almuerzo","Once","Cena"],key="min_serv")
                opcion=st.selectbox("Opción",["OPCION 1","OPCION 2","HIPOCALORICO","TIPO R"],key="min_op")
                actual=""
                if not existentes_fecha.empty:
                    m=existentes_fecha[(existentes_fecha['servicio'].astype(str)==serv)&(existentes_fecha['tipo_opcion'].astype(str)==opcion)]
                    if not m.empty: actual=str(m.iloc[0]['plato'] or '')
                maestro=conn.query(
                    "SELECT DISTINCT nombre FROM platos WHERE COALESCE(activo,1)=1 "
                    + ("AND LOWER(COALESCE(tipo_plato,'')) LIKE '%hipocal%' " if opcion=="HIPOCALORICO" else "")
                    + "ORDER BY nombre", ttl=0)
                nombres=maestro['nombre'].dropna().astype(str).drop_duplicates().tolist() if not maestro.empty else []
                opciones_plato=['— Seleccionar plato —']+nombres
                idx_actual=opciones_plato.index(actual) if actual in opciones_plato else 0
                plato_sel=st.selectbox("Plato desde Maestro",opciones_plato,index=idx_actual,key=f"min_plato_{fecha_n.isoformat()}_{serv}_{opcion}")
                plato_libre=st.text_input("O escribir / corregir nombre",value="" if actual in nombres else actual,key=f"min_libre_{fecha_n.isoformat()}_{serv}_{opcion}")
                st.caption(f"Valor actual: {actual or 'Sin plato cargado'}")
                if st.button("Guardar minuta",type="primary",use_container_width=True,key="guardar_minuta_fecha"):
                    plato=(plato_libre.strip() or (plato_sel if not plato_sel.startswith('—') else '')).strip()
                    if not plato:
                        st.error("Selecciona o escribe un plato.")
                    else:
                        dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][fecha_n.weekday()]
                        with conn.session as ses:
                            ex=execute_sql(ses,"SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s ORDER BY id LIMIT 1",(fecha_n.isoformat(),serv,opcion)).first()
                            if ex: execute_sql(ses,"UPDATE minutas SET plato=%s,dia_semana=%s,activo=1,estado='BORRADOR' WHERE id=%s",(plato,dnom,ex[0]))
                            else: execute_sql(ses,"INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo,estado) VALUES (%s,%s,%s,%s,%s,1,'BORRADOR')",(fecha_n.isoformat(),dnom,serv,opcion,plato))
                            execute_sql(ses,"INSERT INTO platos (nombre,servicio,valor,activo,descripcion,tipo_plato) SELECT %s,%s,0,1,'Creado desde editor de minuta',CASE WHEN %s='HIPOCALORICO' THEN 'Hipocalórico' ELSE NULL END WHERE NOT EXISTS (SELECT 1 FROM platos WHERE LOWER(TRIM(nombre))=LOWER(TRIM(%s)))",(plato,serv,opcion,plato))
                            ses.commit()
                        registrar_auditoria(st.session_state.usuario.get('username'),'EDITAR_MINUTA','minutas',fecha_n.isoformat(),actual,plato,f'{serv} · {opcion}')
                        get_minutas_rango.clear()
                        st.session_state["_flash_minuta"] = "✅ Minuta guardada como BORRADOR. Audítala antes de publicar."
                        st.rerun()
            with st.expander("Carga masiva CSV"):
                st.caption("Columnas: fecha, servicio, tipo_opcion, plato"); archivo_csv=st.file_uploader("Archivo CSV",type=["csv"],key="minuta_csv_admin")
                if archivo_csv is not None:
                    try:
                        vista=pd.read_csv(archivo_csv); st.dataframe(vista.head(30),use_container_width=True,hide_index=True)
                        if st.button("Confirmar carga masiva",key="confirmar_csv_minuta"):
                            req={'fecha','servicio','tipo_opcion','plato'}
                            if not req.issubset(vista.columns): st.error("Faltan columnas requeridas.")
                            else:
                                with conn.session as ses:
                                    for _,rr in vista.iterrows():
                                        fi=pd.to_datetime(rr['fecha']).date(); dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][fi.weekday()]; ex=execute_sql(ses,"SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s ORDER BY id LIMIT 1",(fi.isoformat(),str(rr['servicio']),str(rr['tipo_opcion']))).first()
                                        if ex: execute_sql(ses,"UPDATE minutas SET plato=%s,dia_semana=%s,activo=1,estado='BORRADOR' WHERE id=%s",(str(rr['plato']),dnom,ex[0]))
                                        else: execute_sql(ses,"INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo,estado) VALUES (%s,%s,%s,%s,%s,1,'BORRADOR')",(fi.isoformat(),dnom,str(rr['servicio']),str(rr['tipo_opcion']),str(rr['plato'])))
                                    ses.commit()
                                _sincronizar_maestro_platos()
                                st.success("Carga masiva completada y Maestro de Platos sincronizado."); st.rerun()
                    except Exception as e: st.error(f"No fue posible leer el CSV: {e}")
            with st.expander("Copiar minuta entre meses"):
                c1,c2=st.columns(2)
                with c1: origen=st.date_input("Mes origen",value=ini,key="min_origen")
                with c2: destino=st.date_input("Mes destino",value=(ini+timedelta(days=32)).replace(day=1),key="min_destino")
                if st.button("Copiar mes como base",key="copiar_mes_minuta"):
                    o=origen.replace(day=1)
                    of=(o+timedelta(days=32)).replace(day=1)-timedelta(days=1)
                    d=destino.replace(day=1)
                    src=conn.query(
                        "SELECT fecha,servicio,tipo_opcion,plato FROM minutas "
                        "WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha,id",
                        params={"i":o.isoformat(),"f":of.isoformat()},ttl=0
                    )
                    if src.empty:
                        st.warning("El mes origen no tiene minutas.")
                    else:
                        st.info(
                            "⏳ Copiando minuta. Estamos procesando la copia completa al período seleccionado. "
                            "Según la cantidad de registros puede tardar algunos minutos. "
                            "Por favor no cierres esta ventana ni vuelvas a presionar el botón."
                        )
                        ultimo_dest = (d+timedelta(days=32)).replace(day=1)-timedelta(days=1)
                        existentes = conn.query(
                            "SELECT id,fecha,servicio,tipo_opcion FROM minutas "
                            "WHERE fecha>=:i AND fecha<=:f ORDER BY id",
                            params={"i":d.isoformat(),"f":ultimo_dest.isoformat()},ttl=0
                        )
                        mapa_existentes = {}
                        if not existentes.empty:
                            for _,exr in existentes.iterrows():
                                clave=(str(exr["fecha"]),str(exr["servicio"]),str(exr["tipo_opcion"]))
                                mapa_existentes.setdefault(clave,int(exr["id"]))
                        creados=0
                        actualizados=0
                        with conn.session as ses:
                            for _,rr in src.iterrows():
                                fo=pd.to_datetime(rr["fecha"]).date()
                                fd=date(d.year,d.month,min(fo.day,calendar.monthrange(d.year,d.month)[1]))
                                dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][fd.weekday()]
                                clave=(fd.isoformat(),str(rr["servicio"]),str(rr["tipo_opcion"]))
                                ex_id=mapa_existentes.get(clave)
                                if ex_id:
                                    execute_sql(
                                        ses,
                                        "UPDATE minutas SET plato=%s,dia_semana=%s,activo=1,estado='BORRADOR' WHERE id=%s",
                                        (str(rr["plato"]),dnom,ex_id),
                                    )
                                    actualizados += 1
                                else:
                                    res_ins=execute_sql(
                                        ses,
                                        "INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo,estado) "
                                        "VALUES (%s,%s,%s,%s,%s,1,'BORRADOR') RETURNING id",
                                        (fd.isoformat(),dnom,str(rr["servicio"]),str(rr["tipo_opcion"]),str(rr["plato"])),
                                    ).first()
                                    if res_ins:
                                        mapa_existentes[clave]=int(res_ins[0])
                                    creados += 1
                            ses.commit()
                        st.session_state["_flash_minuta"] = (
                            f"✅ Copia completada: {creados} registros nuevos y {actualizados} actualizados. "
                            "El mes origen no fue modificado."
                        )
                        st.rerun()

        if modulo_admin == "⚖️ Excepciones":
            conn=get_conn()
            st.markdown("#### ⏱️ Excepción de reserva")
            st.caption("Abre temporalmente la ventana de reserva normal. No crea raciones, no valida pagos y no genera una estructura paralela.")
            rut_exc_raw=st.text_input("RUT del comensal",placeholder="Ej.: 12.345.678-5",key="exc_res_rut")
            rut_exc=normalizar_rut(rut_exc_raw) if rut_exc_raw.strip() else ""
            com_exc=pd.DataFrame()
            if rut_exc_raw.strip():
                if not validar_rut_m11(rut_exc_raw):
                    st.error("RUT chileno no válido.")
                else:
                    com_exc=conn.query("SELECT rut,nombre,correo,institucion FROM comensales WHERE rut=:r LIMIT 1",params={"r":rut_exc},ttl=0)
                    if com_exc.empty:
                        st.warning("No existe un comensal registrado con ese RUT.")
                    else:
                        rr=com_exc.iloc[0]
                        st.info(f"Comensal: {rr.get('nombre','—')} · Institución: {rr.get('institucion','—')} · RUT: {rr.get('rut','—')}")
            ex1,ex2=st.columns(2)
            with ex1: exc_desde=st.date_input("Fecha desde",value=date.today(),key="exc_res_desde")
            with ex2: exc_hasta=st.date_input("Fecha hasta",value=date.today(),key="exc_res_hasta")
            exc_motivo=st.text_area("Motivo de la excepción",key="exc_res_motivo")
            if st.button("Autorizar excepción de reserva",type="primary",use_container_width=True,disabled=com_exc.empty):
                if exc_hasta < exc_desde:
                    st.error("La fecha hasta no puede ser anterior a la fecha desde.")
                elif not exc_motivo.strip():
                    st.error("El motivo es obligatorio.")
                else:
                    usuario_exc=st.session_state.usuario.get("username")
                    with conn.session as ses:
                        execute_sql(ses,"INSERT INTO excepciones_reserva (rut,fecha_desde,fecha_hasta,motivo,autorizado_por,autorizado_at,activa) VALUES (%s,%s,%s,%s,%s,%s,1)",(rut_exc,exc_desde.isoformat(),exc_hasta.isoformat(),exc_motivo.strip(),usuario_exc,datetime.now().isoformat()))
                        ses.commit()
                    registrar_auditoria(usuario_exc,"AUTORIZAR_EXCEPCION_RESERVA","excepciones_reserva",rut_exc,"",f"{exc_desde.isoformat()} → {exc_hasta.isoformat()}",exc_motivo.strip())
                    st.success("Excepción autorizada. El comensal debe ingresar a su reserva normal y elegir sus servicios/platos.")
                    st.rerun()
            hist_exc=conn.query("SELECT id,rut,fecha_desde,fecha_hasta,motivo,autorizado_por,autorizado_at,activa FROM excepciones_reserva ORDER BY id DESC LIMIT 200",ttl=0)
            if not hist_exc.empty:
                st.markdown("##### Historial de excepciones")
                st.dataframe(hist_exc,use_container_width=True,hide_index=True)
                ids_exc=[int(x) for x in hist_exc.loc[hist_exc['activa'].astype(int)==1,'id'].tolist()]
                if ids_exc:
                    id_exc=selector_neutro("Excepción activa a desactivar",ids_exc,key="exc_res_desactivar",format_func=lambda x:f"#{x} · {hist_exc.loc[hist_exc['id']==x,'rut'].iloc[0]}")
                    if id_exc is not None and st.button("Desactivar excepción seleccionada",use_container_width=True):
                        with conn.session as ses:
                            execute_sql(ses,"UPDATE excepciones_reserva SET activa=0 WHERE id=%s",(int(id_exc),))
                            ses.commit()
                        registrar_auditoria(st.session_state.usuario.get("username"),"DESACTIVAR_EXCEPCION_RESERVA","excepciones_reserva",str(id_exc),"activa=1","activa=0","Cierre manual")
                        st.success("Excepción desactivada sin borrar historial.")
                        st.rerun()

            st.divider()
            st.markdown("#### ⚖️ Excepciones de precio institucional")
            st.caption("Función histórica separada de la excepción temporal de reserva.")
            df_inst_all=conn.query("SELECT nombre, precio_dia, precio_especial, regla_activa, descripcion FROM instituciones ORDER BY nombre", ttl=0)
            st.dataframe(df_inst_all, use_container_width=True)
            with st.form("form_reglas_casilla"):
                st.markdown("**Selecciona instituciones con precio especial (casilla):**")
                cols = st.columns(2)
                seleccionadas = {}
                for idx, row in df_inst_all.iterrows():
                    col = cols[idx % 2]
                    with col:
                        activa_actual = bool(row['regla_activa'])
                        check = st.checkbox(f"{row['nombre']} - Actual: {formato_clp(row['precio_especial']) if row['precio_especial'] else 'Estándar'} {'✅' if activa_actual else ''}", value=activa_actual, key=f"chk_{row['nombre']}")
                        seleccionadas[row['nombre']] = check
                st.divider()
                c1,c2=st.columns(2)
                with c1: precio_especial_global=st.number_input("Precio especial a aplicar", value=3400, step=100)
                with c2: motivo_global=st.text_input("Motivo", value="Precio especial según criterio admin")
                if st.form_submit_button("💾 Guardar precios especiales", type="primary", use_container_width=True):
                    conn=get_conn()
                    with conn.session as s:
                        for nombre, marcado in seleccionadas.items():
                            if marcado:
                                execute_sql(s, "UPDATE instituciones SET precio_especial=%s, regla_activa=1, descripcion=%s WHERE nombre=%s", (precio_especial_global, motivo_global, nombre))
                            else:
                                execute_sql(s, "UPDATE instituciones SET regla_activa=0 WHERE nombre=%s", (nombre,))
                        s.commit()
                    st.success("Reglas actualizadas"); st.rerun()

        if modulo_admin == "🏢 Instituciones":
            st.markdown("#### 🏢 Instituciones")
            conn=get_conn(); dfi=conn.query("SELECT nombre,precio_dia,precio_especial,regla_activa,activa,descripcion FROM instituciones ORDER BY nombre",ttl=30); st.dataframe(dfi.rename(columns={'nombre':'Institución','precio_dia':'Valor día','precio_especial':'Valor especial','regla_activa':'Regla especial','activa':'Activa','descripcion':'Descripción'}),use_container_width=True,hide_index=True)
            if st.session_state.usuario.get('rol') == 'AdminTotal':
                with st.form('institucion_nueva'):
                    c1,c2=st.columns(2)
                    with c1: nom_i=st.text_input('Institución'); valor_i=st.number_input('Valor día',min_value=0,value=6400,step=100)
                    with c2: desc_i=st.text_input('Descripción'); act_i=st.checkbox('Activa',value=True)
                    add_i=st.form_submit_button('Guardar institución',use_container_width=True)
                if add_i and nom_i.strip():
                    with conn.session as ses: execute_sql(ses,"INSERT INTO instituciones (nombre,precio_dia,regla_activa,activa,descripcion) VALUES (%s,%s,0,%s,%s) ON CONFLICT (nombre) DO UPDATE SET precio_dia=EXCLUDED.precio_dia,activa=EXCLUDED.activa,descripcion=EXCLUDED.descripcion",(nom_i.strip(),int(valor_i),1 if act_i else 0,desc_i)); ses.commit()
                    st.success('Institución guardada.'); st.rerun()
                if not dfi.empty:
                    sel_i=selector_neutro('Institución a activar/desactivar',dfi['nombre'].astype(str).tolist(),key='inst_sel_estado');
                    if sel_i is None: st.info('Selecciona una institución para administrarla.'); return
                    fila_i=dfi[dfi['nombre'].astype(str)==sel_i].iloc[0]; est_i=st.selectbox('Estado',[1,0],index=0 if int(fila_i['activa']) else 1,format_func=lambda z:'Activa' if z else 'Desactivada',key='inst_estado')
                    if st.button('Actualizar estado de institución',use_container_width=True):
                        with conn.session as ses: execute_sql(ses,"UPDATE instituciones SET activa=%s WHERE nombre=%s",(est_i,sel_i)); ses.commit()
                        st.success('Estado actualizado sin borrar historial.'); st.rerun()

        if modulo_admin == "💳 Modalidades de Pago":
            st.markdown("#### 💳 Modalidades de Pago")
            conn=get_conn(); dfm=conn.query("SELECT id,nombre,activo,descripcion FROM modalidades_pago ORDER BY nombre",ttl=30); st.dataframe(dfm.rename(columns={'nombre':'Modalidad','activo':'Activa','descripcion':'Descripción'}),use_container_width=True,hide_index=True)
            if st.session_state.usuario.get('rol')=='AdminTotal':
                with st.form('modalidad_pago_add'):
                    nm=st.text_input('Nueva modalidad'); dm=st.text_input('Descripción'); am=st.checkbox('Activa',value=True,key='modalidad_activa'); gm=st.form_submit_button('Guardar modalidad',use_container_width=True)
                if gm and nm.strip():
                    with conn.session as ses: execute_sql(ses,"INSERT INTO modalidades_pago (nombre,activo,descripcion) VALUES (%s,%s,%s) ON CONFLICT (nombre) DO UPDATE SET activo=EXCLUDED.activo,descripcion=EXCLUDED.descripcion",(nm.strip(),1 if am else 0,dm)); ses.commit()
                    st.success('Modalidad guardada.'); st.rerun()
                if not dfm.empty:
                    sm=selector_neutro('Modalidad a administrar',dfm['nombre'].astype(str).tolist(),key='mod_pago_sel');
                    if sm is None: st.info('Selecciona una modalidad para administrarla.'); return
                    rm=dfm[dfm['nombre'].astype(str)==sm].iloc[0]; em=st.selectbox('Estado modalidad',[1,0],index=0 if int(rm['activo']) else 1,format_func=lambda z:'Activa' if z else 'Desactivada',key='mod_pago_estado')
                    if st.button('Actualizar modalidad',use_container_width=True):
                        with conn.session as ses: execute_sql(ses,"UPDATE modalidades_pago SET activo=%s WHERE nombre=%s",(em,sm)); ses.commit()
                        st.success('Modalidad actualizada sin borrar historial.'); st.rerun()

        if modulo_admin == "📧 Correos":
            st.markdown("#### 📧 Destinatarios de correos")
            st.caption("Administra los correos receptores sin modificar el código ni los Secrets SMTP.")
            conn=get_conn()
            df_correos=conn.query("SELECT id,tipo,correo,descripcion,activo,fecha_creacion FROM configuracion_correos ORDER BY tipo,correo", ttl=0)
            st.dataframe(df_correos, use_container_width=True)

            with st.form("agregar_correo_config"):
                c1,c2=st.columns(2)
                with c1:
                    tipo_correo=st.selectbox("Tipo", ["reclamos","cocina","finanzas","gerencia","bodega"])
                    nuevo_correo=st.text_input("Correo destinatario*")
                with c2:
                    descripcion_correo=st.text_input("Descripción", value="Destinatario configurado desde Administración")
                    activo_correo=st.checkbox("Activo", value=True)
                if st.form_submit_button("Guardar destinatario", type="primary", use_container_width=True):
                    correo_limpio=nuevo_correo.strip().lower()
                    correo_valido="@" in correo_limpio and "." in correo_limpio.rsplit("@",1)[-1]
                    if not correo_valido:
                        st.error("Ingresa un correo válido.")
                    else:
                        with conn.session as ses:
                            execute_sql(ses, "INSERT INTO configuracion_correos (tipo,correo,descripcion,activo,fecha_creacion) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tipo,correo) DO UPDATE SET descripcion=EXCLUDED.descripcion, activo=EXCLUDED.activo", (tipo_correo,correo_limpio,descripcion_correo,1 if activo_correo else 0,datetime.now().isoformat()))
                            ses.commit()
                        st.success("Destinatario guardado.")
                        refrescar_vista_persistente(limpiar_cache_correos)

            if not df_correos.empty:
                st.divider()
                id_correo=selector_neutro("Destinatario a activar/desactivar", df_correos["id"].tolist(), format_func=lambda x: f"{df_correos[df_correos['id']==x].iloc[0]['tipo']} · {df_correos[df_correos['id']==x].iloc[0]['correo']}", key="correo_estado_sel")
                if id_correo is None: st.info("Selecciona un destinatario para administrarlo."); return
                estado_actual=int(df_correos[df_correos['id']==id_correo].iloc[0]['activo'] or 0)
                nuevo_estado=st.selectbox("Estado", [1,0], index=0 if estado_actual else 1, format_func=lambda x: "Activo" if x else "Inactivo")
                if st.button("Actualizar estado del destinatario", use_container_width=True):
                    with conn.session as ses:
                        execute_sql(ses, "UPDATE configuracion_correos SET activo=%s WHERE id=%s", (nuevo_estado,id_correo))
                        ses.commit()
                    st.success("Estado actualizado.")
                    refrescar_vista_persistente(limpiar_cache_correos)

        if modulo_admin == "🏦 Datos transferencia":
            if st.session_state.usuario.get("rol") != "AdminTotal":
                st.error("Acceso exclusivo del Administrador Total.")
                return
            _render_datos_transferencia(st.session_state.usuario, key_prefix="admintotal_datos_transferencia")

        if modulo_admin == "👥 Usuarios":
            if st.session_state.usuario.get("rol") != "AdminTotal":
                st.error("Acceso exclusivo del Administrador Total.")
                return
            conn = get_conn()
            dfu = cargar_usuarios_admin()
            st.markdown("#### 👥 Gestión de usuarios y permisos")
            st.caption("Los cambios de rol, estado y permisos se guardan juntos. Seleccionar opciones no recarga la página.")

            if not dfu.empty:
                vista_usuarios = dfu.copy()
                vista_usuarios["Estado"] = vista_usuarios["activo"].apply(lambda x: "Activo" if int(x or 0) == 1 else "Deshabilitado")
                vista_usuarios["Cambio contraseña"] = vista_usuarios["debe_cambiar_password"].apply(lambda x: "Pendiente" if int(x or 0) == 1 else "No")
                st.dataframe(vista_usuarios[["username","nombre","correo","rol","Estado","Cambio contraseña","fecha_creacion"]].rename(columns={"username":"Usuario","nombre":"Nombre","correo":"Correo","rol":"Perfil","fecha_creacion":"Fecha de creación"}), use_container_width=True, hide_index=True)

                with st.expander("📨 Notificación masiva de acceso", expanded=False):
                    st.caption("Envía a cada usuario activo con correo válido su usuario, perfil y enlace de ingreso. No modifica ni revela contraseñas.")
                    candidatos = dfu[(dfu["activo"].astype(int)==1) & dfu["correo"].fillna("").astype(str).str.contains("@", regex=False)].copy()
                    st.write(f"Usuarios notificables: {len(candidatos)}")
                    confirmar_masivo = st.checkbox("Confirmo el envío de recordatorios de acceso", key="confirmar_notif_masiva")
                    if st.button("Enviar accesos al personal", use_container_width=True, disabled=not confirmar_masivo, key="enviar_notif_masiva"):
                        enviados=0; fallidos=[]
                        for _,ru in candidatos.iterrows():
                            ok,msg = notificar_ingreso_usuario(str(ru.get("correo") or ""), str(ru.get("nombre") or ru.get("username")), str(ru.get("username")), str(ru.get("rol")))
                            if ok: enviados += 1
                            else: fallidos.append(f"{ru.get('username')}: {msg}")
                        registrar_auditoria(st.session_state.usuario.get("username"),"NOTIFICACION_MASIVA_ACCESO","usuarios","",str(len(candidatos)),str(enviados),"; ".join(fallidos[:10]))
                        if enviados: st.success(f"Recordatorio enviado a {enviados} usuario(s).")
                        if fallidos:
                            st.warning(f"{len(fallidos)} envío(s) fallaron. Revisa correo/SMTP antes de repetir.")
                            st.code("\n".join(fallidos[:20]))

                with st.expander("🧪 Modo pruebas · contraseña común", expanded=False):
                    st.warning("Uso temporal de QA. No debe mantenerse en producción. Conserva usernames, roles y permisos; solo cambia la contraseña de las cuentas seleccionadas.")
                    usuarios_activos = dfu[dfu["activo"].astype(int) == 1]["username"].astype(str).tolist()
                    with st.form("qa_password_comun"):
                        usuarios_qa = st.multiselect("Usuarios de prueba", usuarios_activos, default=usuarios_activos)
                        clave_qa = st.text_input("Contraseña común temporal", type="password")
                        confirmar_qa = st.checkbox("Confirmo que es una contraseña temporal para pruebas")
                        aplicar_qa = st.form_submit_button("Aplicar contraseña común", type="primary", use_container_width=True, disabled=not confirmar_qa)
                    if aplicar_qa:
                        clave_limpia = str(clave_qa or "").strip()
                        if len(clave_limpia) < 6 or clave_limpia.lower() != clave_limpia:
                            st.error("La contraseña temporal debe tener al menos 6 caracteres y, para esta prueba, estar completamente en minúsculas.")
                        elif not usuarios_qa:
                            st.error("Selecciona al menos un usuario.")
                        else:
                            with conn.session as ses:
                                for username_qa in usuarios_qa:
                                    execute_sql(ses, "UPDATE usuarios SET pwd=%s,debe_cambiar_password=0 WHERE username=%s", (hash_pwd(clave_limpia), username_qa))
                                ses.commit()
                            registrar_auditoria(st.session_state.usuario.get("username"), "QA_PASSWORD_COMUN", "usuarios", ",".join(usuarios_qa), "", "hash actualizado", "Contraseña común temporal de pruebas")
                            limpiar_cache_usuarios()
                            st.success(f"Contraseña temporal aplicada a {len(usuarios_qa)} usuario(s) activos.")

            with st.expander("➕ Crear usuario nuevo", expanded=dfu.empty):
                with st.form("crear_usuario_total_nuevo", clear_on_submit=True):
                    c1,c2 = st.columns(2)
                    with c1:
                        nu = st.text_input("Usuario nuevo*").strip().lower()
                        nn = st.text_input("Nombre*")
                        ne = st.text_input("Correo de recuperación*")
                    with c2:
                        nr = st.selectbox("Rol*", ["Cocina","Finanzas","Gerencia","AdminCasino","Bodega","AdminTotal"])
                        st.info("La APP generará una contraseña temporal y enviará el acceso al correo registrado.")
                    crear = st.form_submit_button("Crear usuario y enviar acceso", type="primary", use_container_width=True)
                if crear:
                    if not nu.strip() or not nn.strip() or "@" not in ne:
                        st.error("Completa usuario, nombre y un correo válido.")
                    elif not dfu.empty and nu.strip() in dfu["username"].astype(str).tolist():
                        st.error("Ese usuario ya existe. Utiliza Editar usuario para modificarlo.")
                    else:
                        clave_temp = generar_clave_temporal()
                        with conn.session as ses:
                            execute_sql(ses,"INSERT INTO usuarios (username,pwd,rol,nombre,correo,activo,fecha_creacion,debe_cambiar_password) VALUES (%s,%s,%s,%s,%s,1,%s,1)",(nu.strip(),hash_pwd(clave_temp),nr,nn.strip(),ne.strip().lower(),datetime.now().isoformat()))
                            ses.commit()
                        ok_mail, msg_mail = enviar_acceso_usuario(ne, nn.strip(), nu.strip(), clave_temp, nr)
                        registrar_auditoria(st.session_state.usuario.get('username'),'CREAR_USUARIO','usuarios',nu.strip(),'',nr,'Acceso automático por correo' if ok_mail else f'Usuario creado; correo falló: {msg_mail}')
                        limpiar_cache_usuarios()
                        if ok_mail:
                            st.success("Usuario creado y acceso enviado automáticamente al correo registrado.")
                        else:
                            st.warning(f"Usuario creado, pero no fue posible enviar el correo: {msg_mail}. Puedes reenviar el acceso desde Editar usuario.")
                        refrescar_vista_persistente(limpiar_cache_usuarios)

            if not dfu.empty:
                st.divider()
                st.markdown("##### ✏️ Editar usuario")
                selu = selector_neutro("Selecciona usuario", dfu['username'].astype(str).tolist(), key="adm_u_sel_v2")
                if selu is None:
                    st.info("Selecciona un usuario para editarlo o asignarle permisos extraordinarios.")
                    return
                rowu = dfu[dfu['username'].astype(str) == selu].iloc[0]
                permisos_df = cargar_permisos_usuario(selu)
                permisos_activos = set(permisos_df[permisos_df['activo'].astype(int) == 1]['permiso'].astype(str).tolist()) if not permisos_df.empty else set()
                with st.form(f"editar_usuario_{selu}"):
                    c1,c2 = st.columns(2)
                    with c1:
                        nombre_n = st.text_input("Nombre", value=str(rowu['nombre'] or ''))
                        correo_n = st.text_input("Correo de recuperación", value=str(rowu.get('correo') or ''))
                        roles = ["Cocina","Finanzas","Gerencia","AdminCasino","Bodega","AdminTotal"]
                        rol_actual = str(rowu['rol']) if str(rowu['rol']) in roles else "Cocina"
                        rol_n = st.selectbox("Rol", roles, index=roles.index(rol_actual))
                    with c2:
                        activo_n = st.selectbox("Estado", [1,0], index=0 if int(rowu['activo'] or 0) else 1, format_func=lambda x: "Activo" if x else "Deshabilitado")
                        seleccion_permisos = st.multiselect("Permisos", options=list(PERMISOS_DISPONIBLES.keys()), default=[p for p in PERMISOS_DISPONIBLES if p in permisos_activos], format_func=lambda p: PERMISOS_DISPONIBLES[p])
                    guardar_usuario = st.form_submit_button("Guardar cambios", type="primary", use_container_width=True)
                if guardar_usuario:
                    if selu == st.session_state.usuario.get('username') and activo_n == 0:
                        st.error("No puedes deshabilitar tu propia cuenta mientras estás conectado.")
                    else:
                        with conn.session as ses:
                            execute_sql(ses,"UPDATE usuarios SET nombre=%s,correo=%s,activo=%s,rol=%s WHERE username=%s",(nombre_n.strip(),correo_n.strip().lower(),activo_n,rol_n,selu))
                            for permiso in PERMISOS_DISPONIBLES:
                                execute_sql(ses,"INSERT INTO usuarios_permisos (username,permiso,activo) VALUES (%s,%s,%s) ON CONFLICT (username,permiso) DO UPDATE SET activo=EXCLUDED.activo",(selu,permiso,1 if permiso in seleccion_permisos else 0))
                            ses.commit()
                        registrar_auditoria(st.session_state.usuario.get('username'),'MODIFICAR_USUARIO','usuarios',selu,f"{rowu['rol']}/{rowu['activo']}",f"{rol_n}/{activo_n}",'Edición consolidada de usuario y permisos')
                        st.success("Usuario y permisos actualizados."); refrescar_vista_persistente(limpiar_cache_usuarios)

                with st.expander("🔑 Restablecer / reenviar acceso"):
                    st.caption("La APP genera una nueva contraseña temporal y la envía al correo registrado del usuario.")
                    with st.form(f"reset_password_{selu}"):
                        motivo_reset = st.text_input("Motivo del restablecimiento*")
                        do_reset = st.form_submit_button("Generar y enviar nuevo acceso", use_container_width=True)
                    if do_reset:
                        correo_reset = str(rowu.get('correo') or '').strip().lower()
                        if not motivo_reset.strip():
                            st.error("Debes indicar un motivo.")
                        elif not correo_reset or "@" not in correo_reset:
                            st.error("Este usuario no tiene un correo válido registrado.")
                        else:
                            temp = generar_clave_temporal()
                            ok_mail, msg_mail = enviar_acceso_usuario(correo_reset, str(rowu.get('nombre') or selu), selu, temp, str(rowu.get('rol') or 'Usuario'))
                            if ok_mail:
                                with conn.session as ses:
                                    execute_sql(ses,"UPDATE usuarios SET pwd=%s,debe_cambiar_password=1 WHERE username=%s",(hash_pwd(temp),selu)); ses.commit()
                                registrar_auditoria(st.session_state.usuario.get('username'),'RESET_PASSWORD','usuarios',selu,'','hash temporal',motivo_reset + ' · enviado por correo')
                                limpiar_cache_usuarios(); st.success("Nuevo acceso enviado. El usuario deberá cambiar la contraseña temporal al ingresar.")
                            else:
                                st.error(f"No fue posible enviar el correo. La contraseña actual NO fue modificada. Detalle: {msg_mail}")

                with st.expander("📨 Notificar ingreso sin cambiar contraseña"):
                    st.caption("Reenvía el usuario y el enlace al portal. No modifica ni revela la contraseña actual.")
                    if st.button("Notificar ingreso", key=f"notificar_ingreso_{selu}", use_container_width=True):
                        correo_notif = str(rowu.get('correo') or '').strip().lower()
                        if not correo_notif or "@" not in correo_notif:
                            st.error("Este usuario no tiene un correo válido registrado.")
                        else:
                            ok_mail, msg_mail = notificar_ingreso_usuario(
                                correo_notif,
                                str(rowu.get('nombre') or selu),
                                selu,
                                str(rowu.get('rol') or 'Usuario'),
                            )
                            if ok_mail:
                                registrar_auditoria(
                                    st.session_state.usuario.get('username'),
                                    'NOTIFICAR_INGRESO',
                                    'usuarios',
                                    selu,
                                    '',
                                    'correo enviado',
                                    'Recordatorio de acceso sin cambio de contraseña',
                                )
                                st.success("Notificación enviada. La contraseña actual del usuario no fue modificada.")
                            else:
                                st.error(f"No fue posible enviar la notificación. Detalle: {msg_mail}")


        if modulo_admin == "🧭 Actividad":
            if st.session_state.usuario.get("rol") != "AdminTotal":
                st.error("Función exclusiva de Administrador Total.")
            else:
                st.markdown("#### 🧭 Registro de login y actividad")
                st.caption("Auditoría de accesos y acciones. La IP es un dato técnico de contexto y no se utiliza como autenticación.")
                conn=get_conn()
                a1,a2=st.columns(2)
                with a1:
                    dias_act=st.selectbox("Período", [1,7,30,90], index=1, format_func=lambda x:f"Últimos {x} días", key="act_dias")
                with a2:
                    usuario_act=st.text_input("Filtrar usuario", key="act_usuario").strip().lower()
                fecha_desde=(datetime.now()-timedelta(days=int(dias_act))).isoformat()
                params_login={"desde":fecha_desde}
                sql_login=(
                    "SELECT fecha,usuario,rol,evento,resultado,ip,zona_horaria,locale,detalle "
                    "FROM registro_login WHERE fecha>=:desde"
                )
                if usuario_act:
                    sql_login += " AND LOWER(usuario)=:usuario"
                    params_login["usuario"]=usuario_act
                sql_login += " ORDER BY id DESC LIMIT 1000"
                df_login=conn.query(sql_login,params=params_login,ttl=0)
                c1,c2,c3=st.columns(3)
                c1.metric("Eventos de acceso",len(df_login))
                c2.metric("Inicios OK",int((df_login["evento"].astype(str).eq("INICIO") & df_login["resultado"].astype(str).eq("OK")).sum()) if not df_login.empty else 0)
                c3.metric("Intentos fallidos",int(df_login["resultado"].astype(str).eq("FALLIDO").sum()) if not df_login.empty else 0)
                if not df_login.empty:
                    df_login = df_login.copy()
                    df_login["fecha"] = pd.to_datetime(df_login["fecha"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M:%S").fillna(df_login["fecha"].astype(str))
                st.dataframe(_tabla_visible(df_login,{
                    "fecha":"Fecha / hora","usuario":"Usuario","rol":"Perfil","evento":"Evento","resultado":"Resultado",
                    "ip":"IP","zona_horaria":"Zona horaria","locale":"Locale","detalle":"Detalle"
                }),use_container_width=True,hide_index=True)

                st.markdown("##### Acciones auditadas")
                params_aud={"desde":fecha_desde}
                sql_aud=(
                    "SELECT fecha,usuario,accion,entidad,referencia,valor_anterior,valor_nuevo,motivo "
                    "FROM auditoria_acciones WHERE fecha>=:desde"
                )
                if usuario_act:
                    sql_aud += " AND LOWER(usuario)=:usuario"
                    params_aud["usuario"]=usuario_act
                sql_aud += " ORDER BY id DESC LIMIT 1000"
                df_aud=conn.query(sql_aud,params=params_aud,ttl=0)
                if not df_aud.empty:
                    df_aud = df_aud.copy()
                    df_aud["fecha"] = pd.to_datetime(df_aud["fecha"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M:%S").fillna(df_aud["fecha"].astype(str))
                st.dataframe(_tabla_visible(df_aud,{
                    "fecha":"Fecha / hora","usuario":"Usuario","accion":"Acción","entidad":"Entidad",
                    "referencia":"Referencia","valor_anterior":"Anterior","valor_nuevo":"Nuevo","motivo":"Motivo"
                }),use_container_width=True,hide_index=True)
                if not df_login.empty:
                    st.download_button(
                        "⬇️ Descargar registro de login CSV",
                        df_login.to_csv(index=False).encode("utf-8"),
                        "registro_login.csv","text/csv",use_container_width=True,
                    )

        if modulo_admin == "🧹 Depuración":
            st.markdown("#### 🧹 Depuración segura · v40")
            if st.session_state.usuario.get('rol')!='AdminTotal':
                st.info("Esta herramienta es exclusiva del Administrador Total.")
            else:
                st.warning("CIERRE v40: la depuración destructiva quedó deshabilitada. La versión de presentación no ejecuta DELETE sobre reservas, comensales, comprobantes, auditoría ni históricos.")
                st.caption("Para preparar una base limpia se debe usar un entorno de staging/restauración controlada o una migración específica, nunca borrar históricos desde la interfaz productiva.")
                conn=get_conn()
                nr=conn.query("SELECT COUNT(*) AS n FROM solicitudes",ttl=0)
                nc=conn.query("SELECT COUNT(*) AS n FROM comensales",ttl=0)
                c1,c2=st.columns(2)
                c1.metric('Registros de reserva',int(nr.iloc[0]['n']) if not nr.empty else 0)
                c2.metric('Comensales',int(nc.iloc[0]['n']) if not nc.empty else 0)
                st.button("Depuración destructiva deshabilitada en v40",disabled=True,use_container_width=True)

        if modulo_admin == "🛡️ Respaldo":
            st.markdown("#### 🛡️ Respaldo total de emergencia")
            st.caption("Genera una copia lógica de los datos antes de una mantención, migración o nueva versión. No modifica la base de datos.")
            if st.session_state.usuario.get('rol') != 'AdminTotal':
                st.error("Función exclusiva de Administrador Total.")
            else:
                if st.button("Generar respaldo ahora", type="primary", use_container_width=True):
                    with st.spinner("Generando respaldo verificable..."):
                        nombre_backup, contenido_backup, meta_backup = generar_respaldo_logico("MANUAL")
                        st.session_state["ultimo_backup_nombre"] = nombre_backup
                        st.session_state["ultimo_backup_bytes"] = contenido_backup
                        st.session_state["ultimo_backup_meta"] = meta_backup
                        ok_drive, msg_drive = subir_respaldo_drive(nombre_backup, contenido_backup)
                        registrar_auditoria(st.session_state.usuario.get('username'),'GENERAR_RESPALDO','sistema',nombre_backup,'','generado',msg_drive)
                        if ok_drive: st.success(msg_drive)
                        else: st.info(msg_drive)
                if st.session_state.get("ultimo_backup_bytes"):
                    meta_backup = st.session_state.get("ultimo_backup_meta", {})
                    c1,c2,c3=st.columns(3)
                    c1.metric("Tablas respaldadas", len(meta_backup.get("tablas", [])))
                    c2.metric("Errores", len(meta_backup.get("errores", [])))
                    c3.metric("Versión", meta_backup.get("version", "v2.1.3.15"))
                    st.download_button("⬇️ Descargar último respaldo", st.session_state["ultimo_backup_bytes"], file_name=st.session_state["ultimo_backup_nombre"], mime="application/zip", use_container_width=True)
                    if meta_backup.get("errores"):
                        st.warning("El respaldo se generó con observaciones. Revísalas antes de usarlo como copia de recuperación.")
                        st.dataframe(pd.DataFrame(meta_backup["errores"]), use_container_width=True, hide_index=True)

    else:
        st.markdown("### 🏢 Acceso administrativo")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username": str(u).strip().lower(), "pwd": hash_pwd(str(p).strip())}, ttl=0)
                if not df.empty and int(df.iloc[0]['activo'])==1 and df.iloc[0]['rol'] in ["AdminTotal","AdminCasino","Operaciones","Gerencia"]:
                    registrar_evento_login(df.iloc[0]['username'],df.iloc[0]['rol'],"INICIO","OK","Acceso administrativo")
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre'],"debe_cambiar_password":int(df.iloc[0]['debe_cambiar_password'])}; st.session_state.portal_actual="administracion"; st.rerun()
                else:
                    registrar_evento_login(str(u).strip().lower(),"","INICIO","FALLIDO","Credenciales inválidas o perfil sin acceso administrativo")
                    st.error("Usuario no válido, deshabilitado o sin acceso administrativo.")


# ===== BOOTSTRAP SEGURO DEL PRIMER ADMINISTRADOR =====
def _hay_admin_total():
    try:
        conn = get_conn()
        df = conn.query("SELECT COUNT(*) AS n FROM usuarios WHERE rol='AdminTotal' AND COALESCE(activo,1)=1", ttl=0)
        return (not df.empty) and int(df.iloc[0]['n'] or 0) > 0
    except Exception:
        return False

def render_bootstrap_admin():
    st.markdown("### 🛡️ Configuración inicial del Administrador Total")
    st.info("No existe un Administrador Total activo. Crea la primera cuenta para iniciar las pruebas. No hay usuarios ni contraseñas predeterminadas en el código.")
    try:
        bootstrap_key = str(st.secrets.get("security", {}).get("bootstrap_key", "")).strip()
    except Exception:
        bootstrap_key = ""
    if not bootstrap_key:
        st.error("Falta configurar [security].bootstrap_key en Streamlit Secrets antes de crear el primer administrador.")
        st.code('[security]\nbootstrap_key = "UNA_CLAVE_LARGA_Y_PRIVADA"', language="toml")
        return
    with st.form("bootstrap_admin_form"):
        usuario = st.text_input("Usuario administrador*")
        nombre = st.text_input("Nombre*", value="Administrador Total")
        correo = st.text_input("Correo de recuperación*")
        clave = st.text_input("Contraseña inicial*", type="password")
        repetir = st.text_input("Repite contraseña*", type="password")
        llave = st.text_input("Clave de inicialización*", type="password")
        crear = st.form_submit_button("Crear Administrador Total", type="primary", use_container_width=True)
    if crear:
        if llave != bootstrap_key:
            st.error("Clave de inicialización incorrecta.")
        elif not usuario.strip() or not nombre.strip() or "@" not in correo or len(clave) < 10:
            st.error("Completa usuario, nombre y correo válido. La contraseña inicial debe tener al menos 10 caracteres.")
        elif clave != repetir:
            st.error("Las contraseñas no coinciden.")
        else:
            conn = get_conn()
            with conn.session as ses:
                execute_sql(ses,"INSERT INTO usuarios (username,pwd,rol,nombre,correo,activo,fecha_creacion,debe_cambiar_password) VALUES (%s,%s,'AdminTotal',%s,%s,1,%s,0)",(usuario.strip(),hash_pwd(clave),nombre.strip(),correo.strip().lower(),datetime.now().isoformat()))
                ses.commit()
            registrar_auditoria(usuario.strip(),'BOOTSTRAP_ADMIN','usuarios',usuario.strip(),'','AdminTotal','Creación inicial segura')
            limpiar_cache_usuarios()
            st.success("Administrador Total creado. Ya puedes ingresar con esa cuenta.")
            st.rerun()

# ===== ACCESO ÚNICO DEL PERSONAL =====
def render_login_personal():
    st.markdown("### 👥 Acceso de personal ALEMSI")
    st.caption("El sistema identifica tu perfil y abre automáticamente el módulo autorizado.")
    with st.form("login_personal_unificado"):
        u=st.text_input("Usuario", key="u_personal_unificado")
        p=st.text_input("Contraseña", type="password", key="p_personal_unificado")
        ingresar=st.form_submit_button("Ingresar", type="primary", use_container_width=True)
    if ingresar:
        conn=get_conn()
        df=conn.query("SELECT username,rol,nombre,correo,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username":str(u).strip().lower(),"pwd":hash_pwd(str(p).strip())}, ttl=0)
        if df.empty or int(df.iloc[0]["activo"]) != 1:
            registrar_evento_login(str(u).strip().lower(),"","INICIO","FALLIDO","Usuario/contraseña inválidos o cuenta deshabilitada")
            st.error("Usuario o contraseña no válidos, o cuenta deshabilitada.")
        else:
            fila=df.iloc[0]
            registrar_evento_login(fila["username"],fila["rol"],"INICIO","OK","Acceso unificado de personal")
            st.session_state.usuario={"username":fila["username"],"rol":fila["rol"],"nombre":fila["nombre"],"correo":fila.get("correo", ""),"debe_cambiar_password":int(fila["debe_cambiar_password"])}
            st.session_state.portal_actual="administracion" if str(fila["rol"]) in ["AdminTotal","AdminCasino","Operaciones","Gerencia","Bodega"] else "casino"
            st.rerun()

    with st.expander("🔑 ¿Olvidaste tu contraseña? Recuperar acceso"):
        st.caption(
            "Ingresa tu usuario. Si la cuenta está activa y tiene un correo "
            "de recuperación registrado, enviaremos allí una contraseña temporal."
        )
        with st.form("recuperar_password_personal"):
            usuario_rec = st.text_input("Usuario", key="usuario_recuperacion")
            recuperar = st.form_submit_button("Enviar recuperación al correo", use_container_width=True)

        if recuperar:
            usuario_rec = usuario_rec.strip()

            if not usuario_rec:
                st.error("Ingresa tu usuario.")
            else:
                conn = get_conn()
                dfu = conn.query(
                    """
                    SELECT username,nombre,correo,COALESCE(activo,1) AS activo
                    FROM usuarios
                    WHERE username=:u
                    """,
                    params={"u": usuario_rec},
                    ttl=0,
                )

                if dfu.empty or int(dfu.iloc[0]["activo"]) != 1:
                    st.warning(
                        "No fue posible iniciar la recuperación. "
                        "Verifica tu usuario o contacta al Administrador Total."
                    )
                else:
                    correo_rec = str(dfu.iloc[0].get("correo") or "").strip().lower()

                    if not correo_rec or "@" not in correo_rec:
                        st.warning(
                            "Esta cuenta no tiene un correo de recuperación registrado. "
                            "El Administrador Total debe asociarlo antes de recuperar la contraseña."
                        )
                    else:
                        temporal = secrets.token_urlsafe(9)
                        html = f"""
                        <div style='font-family:Arial,sans-serif;max-width:620px;margin:auto;border:1px solid #d7e2dc;border-radius:14px;padding:22px'>
                          <h2 style='color:#0A2F6B'>Recuperación de acceso ALEMSI</h2>
                          <p>Hola {dfu.iloc[0]['nombre'] or usuario_rec},</p>
                          <p>Se solicitó restablecer la contraseña de tu cuenta de personal.</p>
                          <p><b>Usuario:</b> {usuario_rec}</p>
                          <p><b>Contraseña temporal:</b> <span style='font-size:18px'>{temporal}</span></p>
                          <p>Ingresa con esta contraseña temporal. El sistema te pedirá crear una nueva contraseña antes de continuar.</p>
                          <p style='font-size:12px;color:#666'>Si no solicitaste este cambio, informa al Administrador Total.</p>
                        </div>
                        """

                        # Primero se confirma el envío; si falla, la contraseña actual no cambia.
                        ok, msg = enviar_email(
                            correo_rec,
                            "Recuperación de acceso ALEMSI",
                            html,
                        )

                        if not ok:
                            st.error(
                                "No fue posible enviar el correo de recuperación. "
                                "Tu contraseña actual no fue modificada."
                            )
                        else:
                            try:
                                with conn.session as ses:
                                    execute_sql(
                                        ses,
                                        "UPDATE usuarios SET pwd=%s,debe_cambiar_password=1 WHERE username=%s",
                                        (hash_pwd(temporal), usuario_rec),
                                    )
                                    ses.commit()

                                registrar_auditoria(
                                    usuario_rec,
                                    "RECUPERAR_PASSWORD",
                                    "usuarios",
                                    usuario_rec,
                                    "",
                                    "contraseña temporal emitida",
                                    "Recuperación por correo",
                                )

                                local, dominio = correo_rec.split("@", 1)
                                correo_oculto = local[:1] + "***@" + dominio
                                st.success(
                                    f"Correo de recuperación enviado correctamente a {correo_oculto}. "
                                    "Usa la contraseña temporal recibida para ingresar."
                                )
                            except Exception:
                                st.error(
                                    "El correo fue enviado, pero no fue posible activar la contraseña temporal. "
                                    "Contacta al Administrador Total antes de intentar ingresar."
                                )

# ===== SEGURIDAD DE USUARIOS INTERNOS =====
def render_cambio_password_obligatorio():
    usuario = st.session_state.usuario
    if not usuario or int(usuario.get("debe_cambiar_password", 0)) != 1:
        return False
    st.markdown("### 🔐 Cambio obligatorio de contraseña")
    st.info("Por seguridad, debes reemplazar la contraseña temporal antes de continuar.")
    with st.form("cambio_password_obligatorio"):
        nueva = st.text_input("Nueva contraseña", type="password")
        repetir = st.text_input("Repite la nueva contraseña", type="password")
        guardar = st.form_submit_button("Guardar nueva contraseña", type="primary", use_container_width=True)
    if guardar:
        if len(nueva) < 8:
            st.error("La contraseña debe tener al menos 8 caracteres.")
        elif nueva != repetir:
            st.error("Las contraseñas no coinciden.")
        else:
            conn = get_conn()
            with conn.session as ses:
                execute_sql(ses, "UPDATE usuarios SET pwd=%s,debe_cambiar_password=0 WHERE username=%s", (hash_pwd(nueva), usuario.get("username")))
                ses.commit()
            registrar_auditoria(usuario.get("username"), "CAMBIO_PASSWORD_PROPIO", "usuarios", usuario.get("username"), "", "hash actualizado", "Primer ingreso / cambio obligatorio")
            st.session_state.usuario["debe_cambiar_password"] = 0
            st.success("Contraseña actualizada. Ya puedes ingresar a tu módulo.")
            st.rerun()
    return True

if st.session_state.usuario and render_cambio_password_obligatorio():
    st.stop()

# ===== NAVEGACIÓN PERSISTENTE POR PERFIL =====
# La navegación es visual/operativa y NO altera la lógica de reservas, DB ni correo.
if st.session_state.usuario:
    rol_activo = str(st.session_state.usuario.get("rol", ""))
    st.session_state.portal_actual = "administracion" if rol_activo in ["AdminTotal", "AdminCasino", "Operaciones", "Gerencia", "Bodega"] else "casino"
elif st.session_state.rut_actual:
    st.session_state.portal_actual = "comensal"

def volver_inicio():
    st.session_state.portal_actual = "inicio"
    st.session_state.usuario = None
    st.session_state.rut_actual = None
    st.session_state.dias_sel = []
    st.session_state.pedidos = {}
    st.session_state.wizard_idx = 0

if st.session_state.portal_actual == "inicio":
    st.markdown("### ¿Cómo deseas ingresar?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🧑 Soy Comensal", type="primary", use_container_width=True):
            st.session_state.portal_actual = "comensal"
            st.rerun()
    with c2:
        if st.button("👥 Personal ALEMSI", use_container_width=True):
            st.session_state.portal_actual = "personal"
            st.rerun()
    st.caption("El personal utiliza un acceso único; el sistema abre el portal correspondiente según su perfil.")
elif st.session_state.portal_actual == "personal":
    if not st.session_state.usuario and st.button("← Volver al inicio"):
        volver_inicio(); st.rerun()
    if not _hay_admin_total():
        render_bootstrap_admin()
    else:
        render_login_personal()
elif st.session_state.portal_actual == "comensal":
    if not st.session_state.rut_actual and st.button("← Volver al inicio"):
        volver_inicio(); st.rerun()
    render_comensal()
elif st.session_state.portal_actual == "casino":
    if not st.session_state.usuario and st.button("← Volver al inicio"):
        volver_inicio(); st.rerun()
    render_casino()
elif st.session_state.portal_actual == "administracion":
    if not st.session_state.usuario and st.button("← Volver al inicio"):
        volver_inicio(); st.rerun()
    render_admin()

st.divider()
st.caption("© 2026 ALEMSI · Sistema de Alimentación Mamuil Malal")



def _v38_permiso_visible(usuario, permiso, rol=None):
    """Permiso efectivo para módulos delegables. AdminTotal siempre ve; otros dependen del permiso guardado."""
    if str(rol or "").strip().lower() == "admintotal":
        return True
    try:
        return bool(tiene_permiso(usuario, permiso))
    except Exception:
        return False

# === v38 COORDINACION FISCALIZADOR ===
# Regla de arquitectura:
# - Coordinacion es un perfil externo fiscalizador.
# - Entra por el login principal y se deriva a su panel privado.
# - No pertenece al dashboard administrativo ni ve Finanzas/Bodega/Produccion/Usuarios.
# - Sus capacidades delegables son revisar minutas y revisar recetas.
# - Puede aprobar, observar/objetar y proponer cambios; nunca edita la minuta/receta oficial directamente.
