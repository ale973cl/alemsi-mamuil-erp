import streamlit as st
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
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT, execute_sql, get_minutas_rango, get_correos, limpiar_cache_correos, gen_referencia_reserva, reserva_modificable

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
    "auditoria_acciones", "configuracion_correos", "configuracion_bancaria"
]

def generar_respaldo_logico(tipo="MANUAL"):
    conn = get_conn()
    buf = BytesIO()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = {
        "sistema": "ALEMSI Mamuil Malal",
        "version": "v2.1.3.23",
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
    "ver_cocina": "Cocina",
    "ver_bodega": "Bodega / inventario",
    "cargar_inventario": "Cargar inventario",
    "ver_finanzas": "Finanzas",
    "modificar_montos": "Modificar montos",
    "validar_pagos": "Validar pagos",
    "ver_gerencia": "Reportes de Gerencia",
    "editar_minuta": "Editar minutas",
    "gestionar_usuarios": "Gestionar usuarios",
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

def permiso_habilitado(username, permiso, default=True):
    try:
        conn = get_conn()
        dfp = conn.query("SELECT activo FROM usuarios_permisos WHERE username=:u AND permiso=:p", params={"u":username,"p":permiso}, ttl=10)
        if not dfp.empty:
            return bool(int(dfp.iloc[0]["activo"]))
    except Exception:
        pass
    return default

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
    col1,col2 = st.columns([4,1])
    with col1:
        if st.session_state.rut_actual:
            st.success(f"Comensal: {st.session_state.rut_actual}")
        if st.session_state.usuario:
            st.success(f"{st.session_state.usuario['nombre']} - {st.session_state.usuario['rol']}")
    with col2:
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.usuario=None; st.session_state.rut_actual=None; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.session_state.portal_actual="inicio"; st.rerun()



# ===== MODULOS AISLADOS: NO REESCRIBIR LOGICA PROTEGIDA =====
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
    orden_opciones = ["OPCION 1", "OPCION 2", "HIPOCALORICO"]
    opcion_lbl = {"OPCION 1":"Opción 1","OPCION 2":"Opción 2","HIPOCALORICO":"Hipocalórico"}

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
        com=conn.query("SELECT * FROM comensales WHERE rut=:rut", params={"rut": rut}, ttl=60)
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        tab_reserva, tab_reclamos = st.tabs(["📅 Reservar","💬 Reclamos"])

        with tab_reserva:
            es_alemsi = str(institucion or "").strip().casefold() == "alemsi"
            resultado_anterior = st.session_state.pop("resultado_reserva", None)
            if resultado_anterior:
                if resultado_anterior.get("ok"):
                    st.success(resultado_anterior["mensaje"])
                else:
                    st.warning(resultado_anterior["mensaje"])
                if resultado_anterior.get("referencia"):
                    st.info(f"Referencia de consulta: {resultado_anterior['referencia']}")

            if es_alemsi:
                st.info(
                    "Personal ALEMSI: este registro sirve para planificar raciones y consumo de bodega. "
                    "Solo se ofrece la Opción 1 y no se genera cobro, comprobante ni correo."
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
                  div[data-testid="stVerticalBlock"] > div:has(.alemsi-cal-row)
                    + div[data-testid="stHorizontalBlock"] {
                      display:grid !important;
                      grid-template-columns:repeat(7,minmax(0,1fr)) !important;
                      gap:3px !important;
                      width:100% !important;
                  }
                  div[data-testid="stVerticalBlock"] > div:has(.alemsi-cal-row)
                    + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                      width:auto !important;
                      min-width:0 !important;
                      flex:none !important;
                      padding:0 !important;
                  }
                  div[data-testid="stVerticalBlock"] > div:has(.alemsi-cal-row)
                    + div[data-testid="stHorizontalBlock"] button {
                      width:100% !important;
                      min-width:0 !important;
                      min-height:38px !important;
                      padding:2px 0 !important;
                      border-radius:8px !important;
                  }
                  div[data-testid="stVerticalBlock"] > div:has(.alemsi-cal-row)
                    + div[data-testid="stHorizontalBlock"] p,
                  div[data-testid="stVerticalBlock"] > div:has(.alemsi-cal-row)
                    + div[data-testid="stHorizontalBlock"] button p {
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
                        st.markdown(f"<div style='text-align:center;font-weight:700'>{titulo}</div>", unsafe_allow_html=True)

                semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(hoy.year, hoy.month)
                for semana in semanas:
                    st.markdown('<span class="alemsi-cal-row"></span>', unsafe_allow_html=True)
                    columnas = st.columns(7)
                    for columna, dia in zip(columnas, semana):
                        with columna:
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

                # OPTIMIZACION v2.1.3.30: reutilizar df_minutas cacheado y guardar en session para evitar reconsulta
                cache_key = f"{dias[0]}_{dias[-1]}"
                if st.session_state.get("_minutas_cache_key") != cache_key or "_minutas_cache" not in st.session_state:
                    df_minutas = get_minutas_rango(dias[0], dias[-1])
                    if not df_minutas.empty:
                        df_minutas = df_minutas[df_minutas["fecha"].astype(str).isin(dias)].copy()
                    st.session_state["_minutas_cache"] = df_minutas
                    st.session_state["_minutas_cache_key"] = cache_key
                else:
                    df_minutas = st.session_state.get("_minutas_cache", pd.DataFrame())

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
                            servicios_internos = ["Almuerzo", "Cena"]
                            disponibles = 0
                            for servicio in servicios_internos:
                                grupo = filas_fecha[filas_fecha["servicio"].astype(str) == servicio] if not filas_fecha.empty else pd.DataFrame()
                                opcion_1 = grupo[grupo["tipo_opcion"].astype(str).str.casefold() == "opción 1".casefold()] if not grupo.empty else pd.DataFrame()
                                if opcion_1.empty:
                                    continue
                                disponibles += 1
                                plato = str(opcion_1.iloc[0]["plato"])
                                actual = st.session_state.pedidos.get(f_iso, {}).get(servicio, {})
                                estado_actual = actual.get("estado", "") if isinstance(actual, dict) else ""
                                opciones_estado = ["", "Consumiré en casino", "No consumiré", "Llevaré comida propia"]
                                indice = opciones_estado.index(estado_actual) if estado_actual in opciones_estado else 0
                                st.markdown(f"**{servicio}**")
                                st.caption(f"Opción 1: {plato}")
                                estado = st.selectbox(
                                    "Estado", opciones_estado, index=indice,
                                    format_func=lambda x: x or "— Selecciona una respuesta —",
                                    key=f"alemsi_estado_{f_iso}_{servicio}", label_visibility="collapsed",
                                )
                                if estado:
                                    elecciones_dia[servicio] = {"plato": plato, "estado": estado}
                            if disponibles == 0:
                                st.warning("No existe Opción 1 de Almuerzo o Cena para esta fecha.")
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
                        st.session_state.pop("_minutas_cache", None)
                        st.session_state.pop("_minutas_cache_key", None)
                        st.rerun()
                    if anterior:
                        if elecciones_dia:
                            st.session_state.pedidos[f_iso] = elecciones_dia
                        st.session_state.wizard_idx = max(0, idx-1)
                        st.rerun()
                    if siguiente:
                        if es_alemsi:
                            servicios_requeridos = [s for s in ["Almuerzo", "Cena"] if not filas_fecha[(filas_fecha["servicio"].astype(str)==s) & (filas_fecha["tipo_opcion"].astype(str).str.casefold()=="opción 1".casefold())].empty]
                            faltan = [s for s in servicios_requeridos if s not in elecciones_dia]
                            if faltan:
                                st.error("Debes declarar todos los servicios disponibles: " + ", ".join(faltan))
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
                                detalle.append((f_iso, dnom, servicio, seleccion_servicio["plato"], seleccion_servicio["estado"]))
                            else:
                                detalle.append((f_iso, dnom, servicio, seleccion_servicio, get_precio(seleccion_servicio, servicio)))

                    if not detalle:
                        st.error("No hay datos seleccionados.")
                        st.session_state.reserva_revisar = False
                        st.stop()

                    if es_alemsi:
                        df_detalle = pd.DataFrame(detalle, columns=["Fecha", "Día", "Servicio", "Opción 1", "Declaración"])
                        st.dataframe(df_detalle, use_container_width=True, hide_index=True)
                        consumos = int((df_detalle["Declaración"] == "Consumiré en casino").sum())
                        st.metric("Raciones declaradas", consumos)
                        st.caption("Este registro no genera cobro, código, comprobante ni correo.")
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
                            st.metric("Total a pagar", formato_clp(total_real))
                        with st.form("confirmar_reserva_comercial_v21"):
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
                                    for f_iso, dnom, servicio, plato, declaracion in detalle:
                                        estado_bd = {
                                            "Consumiré en casino": "Consumirá",
                                            "No consumiré": "No consumirá",
                                            "Llevaré comida propia": "Comida propia",
                                        }[declaracion]
                                        clave_bloqueo = f"{rut}|{f_iso}|{servicio}"
                                        execute_sql(sesion, "SELECT pg_advisory_xact_lock(hashtext(%s))", (clave_bloqueo,))
                                        existente = execute_sql(
                                            sesion,
                                            "SELECT id FROM solicitudes WHERE rut=%s AND fecha=%s AND servicio=%s ORDER BY id DESC LIMIT 1 FOR UPDATE",
                                            (rut, f_iso, servicio),
                                        ).mappings().first()
                                        ahora_iso = datetime.now().isoformat()
                                        if existente:
                                            if not reserva_modificable(f_iso, servicio):
                                                raise ValueError(f"{servicio} del {date.fromisoformat(f_iso).strftime('%d/%m/%Y')} ya no puede modificarse porque faltan menos de 48 horas.")
                                            execute_sql(
                                                sesion,
                                                "UPDATE solicitudes SET plato=%s,plato_reservado=%s,precio=%s,precio_aplicado=%s,institucion=%s,correo=%s,metodo_pago=%s,estado_pago=%s,estado_consumo=%s,fecha_modificacion=%s,modificado_por=%s,referencia_reserva=%s,tipo_registro=%s WHERE id=%s",
                                                (plato, plato, 0, 0, institucion, correo_cli, "Interno ALEMSI", "No aplica", estado_bd, ahora_iso, rut, referencia_reserva, "CONSUMO_INTERNO", existente["id"]),
                                            )
                                        else:
                                            execute_sql(
                                                sesion,
                                                "INSERT INTO solicitudes "
                                                "(rut,fecha,servicio,plato,plato_reservado,codigo,precio,precio_aplicado,institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion,fecha_modificacion,modificado_por,referencia_reserva,tipo_registro) "
                                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                                (rut, f_iso, servicio, plato, plato, None, 0, 0, institucion, correo_cli, "Interno ALEMSI", "No aplica", estado_bd, ahora_iso, ahora_iso, rut, referencia_reserva, "CONSUMO_INTERNO"),
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
                                            "SELECT id,codigo FROM solicitudes WHERE rut=%s AND fecha=%s AND servicio=%s ORDER BY id DESC LIMIT 1 FOR UPDATE",
                                            (rut, f_iso, servicio),
                                        ).mappings().first()
                                        ahora_iso = datetime.now().isoformat()
                                        if existente:
                                            if not reserva_modificable(f_iso, servicio):
                                                raise ValueError(f"{servicio} del {date.fromisoformat(f_iso).strftime('%d/%m/%Y')} ya no puede modificarse porque faltan menos de 48 horas.")
                                            codigo = existente.get("codigo") or codigo
                                            execute_sql(
                                                sesion,
                                                "UPDATE solicitudes SET plato=%s,plato_reservado=%s,precio=%s,precio_aplicado=%s,institucion=%s,correo=%s,metodo_pago=%s,estado_pago=%s,estado_consumo=%s,fecha_modificacion=%s,modificado_por=%s,referencia_reserva=%s,tipo_registro=%s WHERE id=%s",
                                                (plato, plato, precio_por_linea[(f_iso, servicio, plato)], precio_por_linea[(f_iso, servicio, plato)], institucion, correo_cli, metodo, "Pendiente", "Pendiente", ahora_iso, rut, referencia_reserva, "RESERVA_COMERCIAL", existente["id"]),
                                            )
                                        else:
                                            execute_sql(
                                                sesion,
                                                "INSERT INTO solicitudes "
                                                "(rut,fecha,servicio,plato,plato_reservado,codigo,precio,precio_aplicado,institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion,fecha_modificacion,modificado_por,referencia_reserva,tipo_registro) "
                                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                                (rut, f_iso, servicio, plato, plato, codigo, precio_por_linea[(f_iso, servicio, plato)], precio_por_linea[(f_iso, servicio, plato)], institucion, correo_cli, metodo, "Pendiente", "Pendiente", ahora_iso, ahora_iso, rut, referencia_reserva, "RESERVA_COMERCIAL"),
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
                            pago_token = secrets.token_urlsafe(32)
                            with conn.session as sesion_token:
                                execute_sql(sesion_token, "UPDATE solicitudes SET pago_token=%s WHERE referencia_reserva=%s", (pago_token, referencia_reserva))
                                sesion_token.commit()
                            url_comprobante = _url_carga_comprobante(pago_token)
                            detalle_html = _detalle_html_por_dia(detalle)
                            pdf_reserva = generar_pdf_reserva(nombre,rut,institucion,referencia_reserva,detalle,precio_dia,total_real,metodo,url_comprobante)
                            bloque_link = f"<p style='margin:18px 0'><a href='{url_comprobante}' style='background:#086B37;color:white;padding:12px 18px;text-decoration:none;border-radius:8px;font-weight:bold'>SUBIR COMPROBANTE DE PAGO</a></p>"
                            banco_cfg = get_config_bancaria() if str(metodo).strip().casefold() == "transferencia bancaria".casefold() else {}
                            if banco_cfg:
                                bloque_banco = f"""
                                <div style='background:#f7fbfa;border:1px solid #cfe3df;padding:14px;border-radius:10px;margin:14px 0'>
                                  <h3 style='margin-top:0;color:#0A2F6B'>Datos para transferencia</h3>
                                  <p style='margin:4px 0'><b>Titular / Razón Social:</b> {banco_cfg.get('titular','')}</p>
                                  <p style='margin:4px 0'><b>RUT:</b> {banco_cfg.get('rut','')}</p>
                                  <p style='margin:4px 0'><b>Banco:</b> {banco_cfg.get('banco','')}</p>
                                  <p style='margin:4px 0'><b>Tipo de cuenta:</b> {banco_cfg.get('tipo_cuenta','')}</p>
                                  <p style='margin:4px 0'><b>N° de cuenta:</b> {banco_cfg.get('numero_cuenta','')}</p>
                                  <p style='margin:4px 0'><b>Correo:</b> {banco_cfg.get('correo_comprobantes','')}</p>
                                  <p style='margin:8px 0 0'><b>Monto:</b> {formato_clp(total_real)}</p>
                                  <p style='margin:4px 0'><b>Referencia:</b> {referencia_reserva}</p>
                                  <p style='font-size:12px;color:#666'>Los datos están separados para facilitar copiar y pegar en la banca electrónica.</p>
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
                              <p><b>Método de pago:</b> {metodo} · <b>Estado:</b> Pendiente</p>
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
                        st.session_state.pop("_minutas_cache", None)
                        st.session_state.pop("_minutas_cache_key", None)
                        st.session_state.resultado_reserva = {"ok": ok_resultado, "mensaje": mensaje_resultado, "vouchers": vouchers, "referencia": referencia_reserva}
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
        rut_raw=st.text_input("RUT", placeholder="16.632.880-2")
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
                            correo=st.text_input("Correo*"); institucion=st.selectbox("Institución*", instit_list)
                        if st.form_submit_button("Registrarme", type="primary", use_container_width=True):
                            correo_valido = "@" in correo and "." in correo.rsplit("@", 1)[-1]
                            if nombre and tel and correo_valido and institucion:
                                conn=get_conn()
                                with conn.session as s:
                                    execute_sql(s, "INSERT INTO comensales (rut,nombre,telefono,correo,institucion,fecha_registro) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (rut) DO UPDATE SET nombre=%s, telefono=%s, correo=%s, institucion=%s", (rn,nombre,tel,correo,institucion, datetime.now().isoformat(), nombre, tel, correo, institucion))
                                    s.commit()
                                st.session_state.rut_actual=rn; st.rerun()
                            else:
                                st.error("Completa todos los campos e ingresa un correo válido.")


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


def render_casino():
    usuario = st.session_state.usuario
    roles_casino = ["Cocina", "Finanzas", "Bodega"]
    if usuario and usuario.get("rol") in roles_casino:
        rol = str(usuario["rol"])
        st.markdown(f'<div class="al-card"><h3>{rol}</h3><p>¡Buen día, {usuario.get("nombre") or "equipo"}! Hoy es {datetime.now().strftime("%d/%m/%Y")}. Que tengan una excelente jornada.</p></div>', unsafe_allow_html=True)

        if rol == "Cocina":
            if not permiso_habilitado(usuario.get('username'),'ver_cocina',True):
                st.warning('Tu función Cocina está deshabilitada por el Administrador Total.')
                return
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
                    tarea_id = st.selectbox(
                        "Tarea a gestionar",
                        tarea_ids,
                        format_func=lambda tid: (
                            f"#{tid} · "
                            f"{df_tareas_cocina[df_tareas_cocina['id'].astype(int)==int(tid)].iloc[0]['familia'] or 'Inventario'} · "
                            f"{df_tareas_cocina[df_tareas_cocina['id'].astype(int)==int(tid)].iloc[0]['estado']}"
                        ),
                        key="cocina_tarea_inventario_id",
                    )
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

            if modulo_cocina == "📅 Ver minuta":
                st.markdown("#### 📅 Minuta semanal cuadriculada")
                fecha_minuta = st.date_input("Selecciona una fecha de la semana", value=date.today(), key="fecha_minuta_cocina")
                lunes, domingo = _semana_lunes_domingo(fecha_minuta)
                df_semana = get_minutas_rango(lunes.isoformat(), domingo.isoformat())
                _render_minuta_semanal(df_semana, fecha_minuta)
                st.caption("Cocina visualiza la minuta en modo solo lectura. La gestión de minuta y recetas corresponde a perfiles autorizados.")

            if modulo_cocina == "▶️ Jornada de producción":
                st.markdown("#### Jornada completa de producción")
                st.caption("Visualizar no modifica stock. Iniciar jornada crea una fotografía de lo reservado para todos los servicios del día.")
                fecha_j = st.date_input("Día de producción", value=date.today(), key="fecha_jornada_cocina")
                fecha_iso = fecha_j.isoformat()
                conn = get_conn()
                df_prod = conn.query(
                    """
                    SELECT s.servicio,
                           COALESCE(m.tipo_opcion,'') AS tipo_opcion,
                           COALESCE(s.plato_reservado,s.plato) AS plato,
                           COUNT(*) AS reservadas
                    FROM solicitudes s
                    LEFT JOIN minutas m ON m.fecha=s.fecha AND m.servicio=s.servicio AND UPPER(m.plato)=UPPER(COALESCE(s.plato_reservado,s.plato)) AND m.activo=1
                    WHERE s.fecha=:fecha
                      AND (COALESCE(s.tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR s.estado_consumo='Consumirá')
                    GROUP BY s.servicio, COALESCE(m.tipo_opcion,''), COALESCE(s.plato_reservado,s.plato)
                    ORDER BY CASE s.servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,
                             COALESCE(m.tipo_opcion,''), COALESCE(s.plato_reservado,s.plato)
                    """, params={"fecha":fecha_iso}, ttl=10)

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
                        g["Opción"] = g["tipo_opcion"].replace({"OPCION 1":"1","OPCION 2":"2","HIPOCALORICO":"Hipocalórico","":"—"})
                        st.dataframe(g[["Opción","plato","reservadas"]].rename(columns={"plato":"Plato","reservadas":"Reservadas"}), use_container_width=True, hide_index=True)
                    st.metric("TOTAL JORNADA RESERVADA", total_dia)

                if st.button("👁️ Visualizar jornada completa", use_container_width=True):
                    st.session_state["ver_jornada"] = fecha_iso
                if st.session_state.get("ver_jornada") == fecha_iso:
                    mostrar_bloques(df_prod)

                if estado == "Pendiente":
                    confirmar = st.checkbox(f"Confirmo iniciar la jornada completa del {fecha_j.strftime('%d/%m/%Y')}", key=f"conf_ini_j_{fecha_iso}")
                    if st.button("▶️ INICIAR JORNADA", type="primary", use_container_width=True, disabled=not confirmar):
                        with conn.session as ses:
                            execute_sql(ses, "INSERT INTO jornadas_produccion (fecha,estado,inicio_at,usuario_inicio) VALUES (%s,'En producción',%s,%s) ON CONFLICT (fecha) DO UPDATE SET estado='En producción',inicio_at=EXCLUDED.inicio_at,usuario_inicio=EXCLUDED.usuario_inicio", (fecha_iso,datetime.now().isoformat(),usuario.get('username')))
                            for _,r in df_prod.iterrows():
                                execute_sql(ses, "INSERT INTO jornada_detalle (fecha,servicio,tipo_opcion,plato,reservadas,producidas,entregadas) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fecha,servicio,tipo_opcion,plato) DO UPDATE SET reservadas=EXCLUDED.reservadas", (fecha_iso,str(r['servicio']),str(r['tipo_opcion']),str(r['plato']),int(r['reservadas']),int(r['reservadas']),0))
                            ses.commit()
                        registrar_auditoria(usuario.get('username'),'INICIAR_JORNADA','jornadas_produccion',fecha_iso,'Pendiente','En producción','')
                        st.success("Jornada iniciada. Se congelaron las cantidades reservadas para control. El descuento definitivo de Bodega permanece desactivado en esta prueba.")
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
                        producto_inv=st.selectbox("Producto",inv['id'].tolist(),format_func=lambda x: str(inv[inv['id']==x].iloc[0]['nombre_articulo']),key="inv_prod_cocina")
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
            vista_finanzas = st.radio(
                "Sección Finanzas",
                ["📊 Resumen", "🏢 Por institución", "🧾 Validar comprobantes"],
                horizontal=True,
                key="vista_finanzas_activa",
                label_visibility="collapsed",
            )

            df_reservas = conn.query("""
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
                    MAX(cp.id) AS comprobante_id,
                    MAX(cp.estado) AS estado_comprobante,
                    MAX(cp.fecha_carga) AS fecha_carga_comprobante
                FROM solicitudes s
                LEFT JOIN comensales c ON c.rut=s.rut
                LEFT JOIN comprobantes_pago cp ON cp.referencia_reserva=s.referencia_reserva
                WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
                  AND COALESCE(NULLIF(s.referencia_reserva,''),'') <> ''
                GROUP BY s.referencia_reserva,s.rut
                ORDER BY MAX(c.institucion),MAX(c.nombre),MIN(s.fecha),s.referencia_reserva
            """, ttl=10)

            if df_reservas.empty:
                st.info("No hay reservas comerciales registradas.")
                return

            df_reservas["monto_reserva"] = pd.to_numeric(
                df_reservas["monto_reserva"], errors="coerce"
            ).fillna(0)

            if vista_finanzas == "📊 Resumen":
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
                            lambda s: int(s.fillna("").astype(str).isin(["RECIBIDO","OBSERVADO"]).sum())
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
                        ["RECIBIDO", "OBSERVADO"]
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
                        ["Todos", "RECIBIDO", "OBSERVADO"],
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
                m3.metric(
                    "Observados",
                    int((vista_pend["estado_comprobante"].fillna("").astype(str) == "OBSERVADO").sum()),
                )

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
                ref_val = st.selectbox(
                    "Comprobante a revisar",
                    referencias_val,
                    format_func=lambda r: (
                        f"{vista_pend[vista_pend['referencia_reserva'].astype(str)==str(r)].iloc[0]['institucion']} · "
                        f"{vista_pend[vista_pend['referencia_reserva'].astype(str)==str(r)].iloc[0]['nombre']} · {r}"
                    ),
                    key="fin_validar_referencia",
                )

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
                    nuevo_val = st.radio(
                        "Acción",
                        ["VALIDADO", "OBSERVADO", "RECHAZADO"],
                        format_func=lambda x: {
                            "VALIDADO": "✅ Validar",
                            "OBSERVADO": "⚠️ Observar",
                            "RECHAZADO": "❌ Rechazar",
                        }[x],
                        key=f"fin_accion_{ref_val}",
                    )
                    obs_val = st.text_area(
                        "Observación",
                        value=str(comp_val.get("observacion_validacion") or ""),
                        placeholder="Obligatoria para observar o rechazar.",
                        key=f"fin_obs_bandeja_{ref_val}",
                    )
                    requiere_obs_val = nuevo_val in ["OBSERVADO", "RECHAZADO"]

                    if st.button(
                        "Confirmar revisión",
                        type="primary",
                        use_container_width=True,
                        disabled=(not archivo_disponible or (requiere_obs_val and not obs_val.strip())),
                        key=f"fin_confirmar_bandeja_{ref_val}",
                    ):
                        estado_pago_destino = {
                            "VALIDADO": "Pagado",
                            "OBSERVADO": "Observado",
                            "RECHAZADO": "Pendiente",
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
                        if nuevo_val == "VALIDADO":
                            st.success("✅ Comprobante validado. La reserva quedó pagada y sale de esta bandeja.")
                        elif nuevo_val == "OBSERVADO":
                            st.warning("⚠️ Comprobante observado. Permanecerá visible para seguimiento.")
                        else:
                            st.error("❌ Comprobante rechazado. La reserva vuelve a estado pendiente.")
                        refrescar_vista_persistente()
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
                institucion_sel = st.selectbox(
                    "Institución",
                    instituciones,
                    key="fin_inst_agrupada",
                )
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
                persona_sel = st.selectbox(
                    "Comensal",
                    personas["rut"].astype(str).tolist(),
                    format_func=lambda r: (
                        f"{personas[personas['rut'].astype(str)==str(r)].iloc[0]['nombre']} · {r}"
                    ),
                    key="fin_persona_agrupada",
                )

                df_persona = df_inst[
                    df_inst["rut"].astype(str)==str(persona_sel)
                ].copy()

                refs = df_persona["referencia_reserva"].astype(str).tolist()
                ref_sel = st.selectbox(
                    "Reserva",
                    refs,
                    format_func=lambda r: (
                        f"{r} · "
                        f"{fecha_visible(df_persona[df_persona['referencia_reserva'].astype(str)==str(r)].iloc[0]['fecha_inicio'])}"
                        f" → "
                        f"{fecha_visible(df_persona[df_persona['referencia_reserva'].astype(str)==str(r)].iloc[0]['fecha_fin'])}"
                    ),
                    key="fin_ref_agrupada",
                )

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

                estados_comp = ["RECIBIDO","VALIDADO","OBSERVADO","RECHAZADO"]
                actual_comp = str(comp.get("estado") or "RECIBIDO")
                nuevo_comp = st.selectbox(
                    "Resultado de validación",
                    estados_comp,
                    index=estados_comp.index(actual_comp) if actual_comp in estados_comp else 0,
                    key=f"fin_validar_reserva_{ref_sel}",
                )
                obs_comp = st.text_area(
                    "Observación",
                    value=str(comp.get("observacion_validacion") or ""),
                    key=f"fin_obs_reserva_{ref_sel}",
                )
                requiere_obs = nuevo_comp in ["OBSERVADO","RECHAZADO"]

                if st.button(
                    "Guardar validación de la reserva",
                    type="primary",
                    use_container_width=True,
                    disabled=((requiere_obs and not obs_comp.strip()) or not archivo_disponible),
                    key=f"fin_guardar_reserva_{ref_sel}",
                ):
                    estado_pago_destino = {
                        "RECIBIDO":"Comprobante recibido",
                        "VALIDADO":"Pagado",
                        "OBSERVADO":"Observado",
                        "RECHAZADO":"Pendiente",
                    }[nuevo_comp]

                    with conn.session as ses:
                        execute_sql(
                            ses,
                            "UPDATE comprobantes_pago "
                            "SET estado=%s,validado_por=%s,fecha_validacion=%s,observacion_validacion=%s "
                            "WHERE referencia_reserva=%s",
                            (
                                nuevo_comp,
                                usuario.get("username"),
                                datetime.now().isoformat(),
                                obs_comp.strip() or None,
                                ref_sel,
                            ),
                        )
                        execute_sql(
                            ses,
                            "UPDATE solicitudes SET estado_pago=%s,motivo_estado_pago=%s "
                            "WHERE referencia_reserva=%s",
                            (
                                estado_pago_destino,
                                obs_comp.strip() or None,
                                ref_sel,
                            ),
                        )
                        ses.commit()

                    registrar_auditoria(
                        usuario.get("username"),
                        "VALIDAR_RESERVA_FINANCIERA",
                        "solicitudes",
                        ref_sel,
                        str(reserva["estado_pago"]),
                        estado_pago_destino,
                        obs_comp,
                    )
                    st.success("Reserva y comprobante actualizados en conjunto.")
                    refrescar_vista_persistente()
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
            inst_comp = st.selectbox(
                "Institución",
                instituciones_comp,
                key="fin_comp_inst_agrupada",
            )
            vista_comp = df_comp_res[
                df_comp_res["institucion"].astype(str)==inst_comp
            ].copy()

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

            ref_comp = st.selectbox(
                "Reserva a revisar",
                vista_comp["referencia_reserva"].astype(str).tolist(),
                key="fin_comp_ref_agrupada",
            )
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
                df=conn.query("SELECT username,rol,nombre,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd",params={"username":u,"pwd":hash_pwd(p)},ttl=0)
                if not df.empty and int(df.iloc[0]['activo'])==1 and df.iloc[0]['rol'] in roles_casino:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre'],"debe_cambiar_password":int(df.iloc[0]['debe_cambiar_password'])}; st.session_state.portal_actual="casino"; st.rerun()
                else: st.error("Usuario no válido, deshabilitado o sin permiso para Personal de Casino.")

def render_admin():
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["AdminTotal","AdminCasino","Operaciones","Gerencia"]:
        st.markdown(f'<div class="al-card"><h3>🏢 Administración y Control de Gestión</h3><p>Información consolidada para la gestión operativa y financiera.</p></div>', unsafe_allow_html=True)
        rol_admin = str(st.session_state.usuario.get("rol", ""))
        modulos_admin = ["📊 Reportes","📋 Planilla de Reservas","📈 Dashboard","📦 Inventario y Bodega","🍽️ Minutas","⚖️ Excepciones","🏢 Instituciones","💳 Modalidades de Pago","📧 Correos"]
        if rol_admin == "AdminTotal":
            modulos_admin += ["🏦 Datos transferencia","👥 Usuarios","🧹 Depuración","🛡️ Respaldo"]
        modulo_admin = st.radio("Módulo", modulos_admin, horizontal=True, key="modulo_admin_activo", label_visibility="collapsed")

        # Solo se consulta/renderiza el módulo elegido. Esto evita ejecutar todas las consultas en cada interacción.
        if modulo_admin == "📊 Reportes":
            st.markdown("### 📊 Reportes de Gestión")
            st.caption("Información consolidada para seguimiento financiero, reservas y producción.")
            conn=get_conn()

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
            st.download_button("📥 Descargar Pagos Pendientes CSV", df_pend.to_csv(index=False).encode('utf-8'), "pagos_pendientes.csv", "text/csv")

            st.divider()

            # 2. Platos Solicitados por Día
            st.markdown("#### 2️⃣ Platos solicitados por día")
            df_platos_dia = conn.query("""
                SELECT fecha, plato_reservado, servicio, COUNT(*) as total_solicitado, SUM(precio_aplicado) as monto_total 
                FROM solicitudes
                WHERE COALESCE(tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR estado_consumo='Consumirá'
                GROUP BY fecha, plato_reservado, servicio 
                ORDER BY fecha ASC
            """, ttl=0)
            st.dataframe(_tabla_visible(df_platos_dia,{"fecha":"Fecha","plato_reservado":"Plato","servicio":"Servicio","total_solicitado":"Porciones reservadas","monto_total":"Monto"},["fecha"]),use_container_width=True,hide_index=True)
            if not df_platos_dia.empty:
                resumen_platos = (df_platos_dia.groupby("plato_reservado", as_index=False)["total_solicitado"].sum()
                                  .sort_values("total_solicitado", ascending=False))
                cols_platos = st.columns(4)
                for i, (_, rp) in enumerate(resumen_platos.iterrows()):
                    with cols_platos[i % 4]:
                        st.markdown(f"**{rp['plato_reservado']}**")
                        st.caption(f"{int(rp['total_solicitado'])} porciones")
                st.info(f"📦 Total platos distintos: {len(resumen_platos)} · Total porciones: {int(resumen_platos['total_solicitado'].sum())}")
            st.download_button("📥 Descargar Platos por Día CSV", df_platos_dia.to_csv(index=False).encode('utf-8'), "platos_por_dia.csv", "text/csv")

            st.divider()

            # 3. Control General de Reservas
            st.markdown("#### 3️⃣ Control general de reservas")
            df_control = conn.query("SELECT s.id, s.referencia_reserva, s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.estado_pago, s.estado_consumo, s.precio_aplicado, s.codigo FROM solicitudes s LEFT JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 500", ttl=0)
            st.dataframe(_tabla_visible(df_control,{"referencia_reserva":"Referencia","fecha":"Fecha","rut":"RUT","nombre":"Nombre","institucion":"Institución","plato_reservado":"Plato","metodo_pago":"Modalidad de pago","estado_pago":"Estado de pago","estado_consumo":"Estado de consumo","precio_aplicado":"Monto","codigo":"Código"},["fecha"]),use_container_width=True,hide_index=True)
            st.metric("Total reservas históricas", len(df_control))
            st.download_button("📥 Descargar Control General CSV", df_control.to_csv(index=False).encode('utf-8'), "control_reservas.csv", "text/csv")

            st.divider()
            st.markdown("##### 🔄 Análisis ejecutivo")
            if rol_admin == "Gerencia":
                st.caption("Vista ejecutiva: las acciones operativas de pago y Bodega se gestionan en sus módulos autorizados.")
            else:
                col1,col2=st.columns(2)
                with col1:
                    if not df_pend.empty:
                        id_pago = st.selectbox("Gestionar en Finanzas - ID", df_pend['codigo'].tolist() if 'codigo' in df_pend.columns else [])
                        if st.button("✅ Marcar como Pagado", type="primary"):
                            conn=get_conn()
                            with conn.session as ses_pago:
                                execute_sql(ses_pago, "UPDATE solicitudes SET estado_pago=%s WHERE codigo=%s", ("Pagado", id_pago))
                                ses_pago.commit()
                            st.success(f"Pago {id_pago} marcado Pagado"); st.rerun()
                with col2:
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
                    "Descargar planilla Excel",
                    data=salida_excel.getvalue(),
                    file_name=f"planilla_reservas_{date.today().isoformat()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        if modulo_admin == "📈 Dashboard":
            conn=get_conn(); st.markdown("### Dashboard integral")
            df_dash=conn.query("SELECT s.referencia_reserva,s.fecha,s.servicio,s.rut,c.nombre,c.institucion,s.metodo_pago,s.estado_pago,s.precio_aplicado FROM solicitudes s LEFT JOIN comensales c ON c.rut=s.rut WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'",ttl=10)
            if not df_dash.empty: df_dash['monto_final']=pd.to_numeric(df_dash['precio_aplicado'],errors='coerce').fillna(0)
            _dashboard_financiero(df_dash,"Resumen financiero y operacional")
            df_turnos=conn.query("SELECT fecha,servicio,COUNT(*) AS comensales FROM solicitudes WHERE (COALESCE(tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR estado_consumo='Consumirá') GROUP BY fecha,servicio ORDER BY fecha, CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END",ttl=10)
            if not df_turnos.empty:
                st.markdown("#### Comensales por servicio"); st.bar_chart(df_turnos.groupby('servicio')['comensales'].sum()); st.dataframe(_tabla_visible(df_turnos,{"fecha":"Fecha","servicio":"Servicio","comensales":"Comensales"},["fecha"]),use_container_width=True,hide_index=True)

            st.divider()
            st.markdown("#### Vista agrupada por institución y reserva")
            st.caption(
                "Gerencia puede analizar Institución → Comensal → Reserva → Fecha → Servicio → Estado → Comprobante → Validación."
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
                  AND COALESCE(NULLIF(s.referencia_reserva,''),'') <> ''
                GROUP BY s.referencia_reserva,s.rut
                ORDER BY MAX(c.institucion),MAX(c.nombre),MIN(s.fecha)
            """, ttl=10)

            if not df_ger_res.empty:
                instituciones_ger = sorted(
                    [x for x in df_ger_res["institucion"].dropna().astype(str).unique().tolist() if x]
                )
                inst_ger = st.selectbox(
                    "Institución a analizar",
                    ["Todas"] + instituciones_ger,
                    key="ger_inst_agrupada",
                )
                vista_ger = df_ger_res.copy()
                if inst_ger != "Todas":
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

                if inst_ger != "Todas" and not vista_ger.empty:
                    persona_ger = st.selectbox(
                        "Comensal",
                        vista_ger["rut"].astype(str).drop_duplicates().tolist(),
                        format_func=lambda r: (
                            f"{vista_ger[vista_ger['rut'].astype(str)==str(r)].iloc[0]['nombre']} · {r}"
                        ),
                        key="ger_persona_agrupada",
                    )
                    refs_ger = vista_ger[
                        vista_ger["rut"].astype(str)==str(persona_ger)
                    ]["referencia_reserva"].astype(str).tolist()
                    ref_ger = st.selectbox(
                        "Reserva",
                        refs_ger,
                        key="ger_ref_agrupada",
                    )
                    fila_ger = vista_ger[
                        vista_ger["referencia_reserva"].astype(str)==str(ref_ger)
                    ].iloc[0]

                    g1,g2,g3,g4 = st.columns(4)
                    g1.metric("Fechas", int(fila_ger["fechas"] or 0))
                    g2.metric("Servicios", int(fila_ger["servicios"] or 0))
                    g3.metric("Monto", formato_clp(fila_ger["monto"]))
                    g4.metric("Estado", str(fila_ger["estado_pago"] or "Pendiente"))

                    _render_detalle_reserva_por_fecha(
                        _detalle_reserva_agrupada(conn, ref_ger)
                    )

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
                            rid = st.selectbox(
                                "Tarea enviada a revisión",
                                revisar_ids,
                                key="admin_revision_tarea_inv",
                            )
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
            st.markdown("#### 🍽️ Calendario semanal de minutas")
            st.caption("Vista compacta: una línea corresponde a una semana completa, de lunes a domingo.")
            conn=get_conn(); mes_ref=st.date_input("Mes a visualizar",value=date.today().replace(day=1),key="mes_minuta_admin"); ini=mes_ref.replace(day=1); fin=(ini+timedelta(days=32)).replace(day=1)-timedelta(days=1)
            df_min=conn.query("SELECT id,fecha,dia_semana,servicio,tipo_opcion,plato,activo FROM minutas WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha, CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,id",params={"i":ini.isoformat(),"f":fin.isoformat()},ttl=20)
            if df_min.empty:
                st.info("No hay minutas cargadas para este mes.")
            else:
                inicio_cal = ini - timedelta(days=ini.weekday())
                fin_cal = fin + timedelta(days=(6-fin.weekday()))
                semana = inicio_cal
                while semana <= fin_cal:
                    lunes = semana
                    domingo = semana + timedelta(days=6)
                    df_sem = df_min[
                        (pd.to_datetime(df_min["fecha"], errors="coerce").dt.date >= lunes)
                        & (pd.to_datetime(df_min["fecha"], errors="coerce").dt.date <= domingo)
                    ].copy()
                    _render_minuta_semanal(
                        df_sem,
                        fecha_base=lunes,
                        titulo=True,
                        titulo_personalizado=f"📅 Semana {lunes.strftime('%d/%m')} → {domingo.strftime('%d/%m')}",
                    )
                    semana += timedelta(days=7)
            with st.expander("Agregar o editar minuta por fecha"):
                with st.form("add_minuta_fecha"):
                    fecha_n=st.date_input("Fecha",value=date.today(),key="min_fecha"); serv=st.selectbox("Servicio",["Desayuno","Almuerzo","Once","Cena"],key="min_serv"); opcion=st.selectbox("Opción",["OPCION 1","OPCION 2","HIPOCALORICO"],key="min_op"); plato=st.text_input("Nombre del plato*"); guardar=st.form_submit_button("Guardar minuta",type="primary",use_container_width=True)
                if guardar and plato.strip():
                    dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][fecha_n.weekday()]
                    with conn.session as ses:
                        ex=execute_sql(ses,"SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s ORDER BY id LIMIT 1",(fecha_n.isoformat(),serv,opcion)).first()
                        if ex: execute_sql(ses,"UPDATE minutas SET plato=%s,dia_semana=%s,activo=1 WHERE id=%s",(plato.strip(),dnom,ex[0]))
                        else: execute_sql(ses,"INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo) VALUES (%s,%s,%s,%s,%s,1)",(fecha_n.isoformat(),dnom,serv,opcion,plato.strip()))
                        ses.commit()
                    st.success("Minuta guardada."); st.rerun()
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
                                        if ex: execute_sql(ses,"UPDATE minutas SET plato=%s,dia_semana=%s,activo=1 WHERE id=%s",(str(rr['plato']),dnom,ex[0]))
                                        else: execute_sql(ses,"INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo) VALUES (%s,%s,%s,%s,%s,1)",(fi.isoformat(),dnom,str(rr['servicio']),str(rr['tipo_opcion']),str(rr['plato'])))
                                    ses.commit()
                                st.success("Carga masiva completada."); st.rerun()
                    except Exception as e: st.error(f"No fue posible leer el CSV: {e}")
            with st.expander("Copiar minuta entre meses"):
                c1,c2=st.columns(2)
                with c1: origen=st.date_input("Mes origen",value=ini,key="min_origen")
                with c2: destino=st.date_input("Mes destino",value=(ini+timedelta(days=32)).replace(day=1),key="min_destino")
                if st.button("Copiar mes como base",key="copiar_mes_minuta"):
                    o=origen.replace(day=1); of=(o+timedelta(days=32)).replace(day=1)-timedelta(days=1); d=destino.replace(day=1); src=conn.query("SELECT fecha,servicio,tipo_opcion,plato FROM minutas WHERE activo=1 AND fecha>=:i AND fecha<=:f ORDER BY fecha,id",params={"i":o.isoformat(),"f":of.isoformat()},ttl=0)
                    if src.empty: st.warning("El mes origen no tiene minutas.")
                    else:
                        with conn.session as ses:
                            for _,rr in src.iterrows():
                                fo=pd.to_datetime(rr['fecha']).date(); fd=date(d.year,d.month,min(fo.day,calendar.monthrange(d.year,d.month)[1])); dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][fd.weekday()]; ex=execute_sql(ses,"SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s ORDER BY id LIMIT 1",(fd.isoformat(),str(rr['servicio']),str(rr['tipo_opcion']))).first()
                                if ex: execute_sql(ses,"UPDATE minutas SET plato=%s,dia_semana=%s,activo=1 WHERE id=%s",(str(rr['plato']),dnom,ex[0]))
                                else: execute_sql(ses,"INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo) VALUES (%s,%s,%s,%s,%s,1)",(fd.isoformat(),dnom,str(rr['servicio']),str(rr['tipo_opcion']),str(rr['plato'])))
                            ses.commit()
                        st.success("Mes copiado sin modificar el original."); st.rerun()

        if modulo_admin == "⚖️ Excepciones":
            st.markdown("#### ⚖️ Excepciones - Precio estándar $6400 + casillas especial")
            conn=get_conn()
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
            if st.session_state.usuario.get('rol') in ['AdminTotal','Gerencia']:
                with st.form('institucion_nueva'):
                    c1,c2=st.columns(2)
                    with c1: nom_i=st.text_input('Institución'); valor_i=st.number_input('Valor día',min_value=0,value=6400,step=100)
                    with c2: desc_i=st.text_input('Descripción'); act_i=st.checkbox('Activa',value=True)
                    add_i=st.form_submit_button('Guardar institución',use_container_width=True)
                if add_i and nom_i.strip():
                    with conn.session as ses: execute_sql(ses,"INSERT INTO instituciones (nombre,precio_dia,regla_activa,activa,descripcion) VALUES (%s,%s,0,%s,%s) ON CONFLICT (nombre) DO UPDATE SET precio_dia=EXCLUDED.precio_dia,activa=EXCLUDED.activa,descripcion=EXCLUDED.descripcion",(nom_i.strip(),int(valor_i),1 if act_i else 0,desc_i)); ses.commit()
                    st.success('Institución guardada.'); st.rerun()
                if not dfi.empty:
                    sel_i=st.selectbox('Institución a activar/desactivar',dfi['nombre'].astype(str).tolist(),key='inst_sel_estado'); fila_i=dfi[dfi['nombre'].astype(str)==sel_i].iloc[0]; est_i=st.selectbox('Estado',[1,0],index=0 if int(fila_i['activa']) else 1,format_func=lambda z:'Activa' if z else 'Desactivada',key='inst_estado')
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
                    sm=st.selectbox('Modalidad a administrar',dfm['nombre'].astype(str).tolist(),key='mod_pago_sel'); rm=dfm[dfm['nombre'].astype(str)==sm].iloc[0]; em=st.selectbox('Estado modalidad',[1,0],index=0 if int(rm['activo']) else 1,format_func=lambda z:'Activa' if z else 'Desactivada',key='mod_pago_estado')
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
                id_correo=st.selectbox("Destinatario a activar/desactivar", df_correos["id"].tolist(), format_func=lambda x: f"{df_correos[df_correos['id']==x].iloc[0]['tipo']} · {df_correos[df_correos['id']==x].iloc[0]['correo']}")
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
            st.markdown("#### 🏦 Datos para transferencia bancaria")
            st.caption("Esta información aparece en el correo del comensal solo cuando selecciona Transferencia bancaria.")
            conn = get_conn()
            actual = get_config_bancaria()
            with st.form("config_banco_alemsi"):
                c1,c2 = st.columns(2)
                with c1:
                    titular_b = st.text_input("Nombre / Razón Social*", value=actual.get("titular",""))
                    rut_b = st.text_input("RUT*", value=actual.get("rut",""))
                    banco_b = st.text_input("Banco*", value=actual.get("banco",""))
                with c2:
                    tipo_actual = actual.get("tipo_cuenta","Cuenta Corriente") or "Cuenta Corriente"
                    tipos_cuenta = ["Cuenta Corriente","Cuenta Vista","Cuenta de Ahorro"]
                    tipo_b = st.selectbox("Tipo de cuenta*", tipos_cuenta, index=tipos_cuenta.index(tipo_actual) if tipo_actual in tipos_cuenta else 0)
                    numero_b = st.text_input("N.º de cuenta*", value=actual.get("numero_cuenta",""))
                    correo_b = st.text_input("Correo electrónico*", value=actual.get("correo_comprobantes",""))
                guardar_banco = st.form_submit_button("Guardar datos bancarios", type="primary", use_container_width=True)
            if guardar_banco:
                campos = [titular_b,rut_b,banco_b,tipo_b,numero_b,correo_b]
                if not all(str(x).strip() for x in campos) or "@" not in correo_b:
                    st.error("Completa todos los datos bancarios e ingresa un correo válido.")
                else:
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
                            (
                                titular_b.strip(),rut_b.strip(),banco_b.strip(),tipo_b.strip(),
                                numero_b.strip(),correo_b.strip().lower(),
                                datetime.now().isoformat(),st.session_state.usuario.get("username"),
                            ),
                        )
                        ses.commit()
                    registrar_auditoria(
                        st.session_state.usuario.get("username"),
                        "ACTUALIZAR_DATOS_BANCARIOS",
                        "configuracion_bancaria",
                        "1","","actualizado","Configuración para correos de transferencia",
                    )
                    st.success("Datos bancarios guardados.")
                    refrescar_vista_persistente(limpiar_cache_banco)

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

            with st.expander("➕ Crear usuario nuevo", expanded=dfu.empty):
                with st.form("crear_usuario_total_nuevo", clear_on_submit=True):
                    c1,c2 = st.columns(2)
                    with c1:
                        nu = st.text_input("Usuario nuevo*")
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
                selu = st.selectbox("Selecciona usuario", dfu['username'].astype(str).tolist(), key="adm_u_sel_v2")
                rowu = dfu[dfu['username'].astype(str) == selu].iloc[0]
                permisos_df = cargar_permisos_usuario(selu)
                permisos_activos = set(permisos_df[permisos_df['activo'].astype(int) == 1]['permiso'].astype(str).tolist()) if not permisos_df.empty else set(PERMISOS_DISPONIBLES.keys())
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

        if modulo_admin == "🧹 Depuración":
            st.markdown("#### 🧹 Depuración de reservas y comensales")
            if st.session_state.usuario.get('rol')!='AdminTotal': st.info("Esta herramienta es exclusiva del Administrador Total.")
            else:
                st.warning("Herramienta para limpiar datos de prueba. No modifica usuarios, minutas, recetas, instituciones ni configuración.")
                conn=get_conn(); nr=conn.query("SELECT COUNT(*) AS n FROM solicitudes",ttl=0); nc=conn.query("SELECT COUNT(*) AS n FROM comensales",ttl=0); c1,c2=st.columns(2); c1.metric('Registros de reserva',int(nr.iloc[0]['n']) if not nr.empty else 0); c2.metric('Comensales',int(nc.iloc[0]['n']) if not nc.empty else 0)
                confirmar=st.text_input("Escribe DEPURAR para habilitar",key='depurar_confirm')
                if st.button("Depurar reservas y comensales",type='primary',use_container_width=True,disabled=confirmar.strip().upper()!='DEPURAR'):
                    with conn.session as ses:
                        for tabla in ['comprobantes_pago','ajustes_financieros','jornada_detalle','jornadas_produccion','solicitudes','comensales']: execute_sql(ses,f"DELETE FROM {tabla}")
                        ses.commit()
                    registrar_auditoria(st.session_state.usuario.get('username'),'DEPURAR_DATOS_PRUEBA','reservas_comensales','','','eliminados','Confirmación DEPURAR'); st.success("Datos de prueba depurados."); st.rerun()

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
                df=conn.query("SELECT username,rol,nombre,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username": u, "pwd": hash_pwd(p)}, ttl=0)
                if not df.empty and int(df.iloc[0]['activo'])==1 and df.iloc[0]['rol'] in ["AdminTotal","AdminCasino","Operaciones","Gerencia"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre'],"debe_cambiar_password":int(df.iloc[0]['debe_cambiar_password'])}; st.session_state.portal_actual="administracion"; st.rerun()
                else: st.error("Usuario no válido, deshabilitado o sin acceso administrativo.")


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
        df=conn.query("SELECT username,rol,nombre,correo,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username":u.strip(),"pwd":hash_pwd(p)}, ttl=0)
        if df.empty or int(df.iloc[0]["activo"]) != 1:
            st.error("Usuario o contraseña no válidos, o cuenta deshabilitada.")
        else:
            fila=df.iloc[0]
            st.session_state.usuario={"username":fila["username"],"rol":fila["rol"],"nombre":fila["nombre"],"correo":fila.get("correo", ""),"debe_cambiar_password":int(fila["debe_cambiar_password"])}
            st.session_state.portal_actual="administracion" if str(fila["rol"]) in ["AdminTotal","AdminCasino","Operaciones","Gerencia"] else "casino"
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
    st.session_state.portal_actual = "administracion" if rol_activo in ["AdminTotal", "AdminCasino", "Operaciones", "Gerencia"] else "casino"
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