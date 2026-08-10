import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import calendar
import json
import secrets
from io import BytesIO
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
    try:
        base = str(st.secrets.get("app", {}).get("public_url", "")).strip().rstrip("/")
    except Exception:
        base = ""
    return f"{base}/?pago_token={token}" if base else ""

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
    st.error(f"Error inicializando DB PostgreSQL: {e} - Verifica secrets [connections.postgresql]")
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
    st.markdown(f"### 📎 Subir comprobante · {ref}")
    st.info("Puedes cargar el comprobante ahora o después de consumir. La carga no marca el pago como validado; Finanzas debe revisarlo.")
    archivo=st.file_uploader("Comprobante (PDF, JPG o PNG · máximo 10 MB)", type=["pdf","jpg","jpeg","png"])
    if archivo is not None and archivo.size > 10*1024*1024:
        st.error("El archivo supera el máximo de 10 MB.")
    elif archivo is not None and st.button("Enviar comprobante", type="primary", use_container_width=True):
        contenido=archivo.getvalue()
        with conn.session as ses:
            execute_sql(ses,"INSERT INTO comprobantes_pago (referencia_reserva,pago_token,nombre_archivo,mime_type,contenido,fecha_carga,estado) VALUES (%s,%s,%s,%s,%s,%s,%s)",(ref,token_q,archivo.name,archivo.type,contenido,datetime.now().isoformat(),"RECIBIDO"))
            execute_sql(ses,"UPDATE solicitudes SET comprobante_url=%s,estado_pago=%s,motivo_estado_pago=%s WHERE pago_token=%s",(f"DB:{ref}","Comprobante recibido","Pendiente de validación por Finanzas",token_q))
            ses.commit()
        for destino in get_correos("finanzas"):
            enviar_email(destino,f"[COMPROBANTE RECIBIDO] {ref}",f"<p>Se recibió un comprobante para la reserva <b>{ref}</b>. Debe ser revisado y validado por Finanzas.</p>")
        st.success("Comprobante recibido correctamente. Finanzas realizará la validación.")
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
                st.markdown("#### 📅 Paso 1: Selecciona las fechas")
                hoy = date.today()
                primer_dia = date(hoy.year, hoy.month, 1)
                ultimo_numero = calendar.monthrange(hoy.year, hoy.month)[1]
                ultimo_dia = date(hoy.year, hoy.month, ultimo_numero)

                # Una lectura cacheada permite mostrar como disponibles solo fechas con minuta real.
                df_disponibilidad = get_minutas_rango(primer_dia.isoformat(), ultimo_dia.isoformat())
                fechas_con_minuta = set(df_disponibilidad["fecha"].astype(str).tolist()) if not df_disponibilidad.empty else set()

                st.markdown(f"### {primer_dia.strftime('%B %Y').capitalize()}")
                st.caption(
                    "Puedes elegir un día, fechas consecutivas o fechas intercaladas. "
                    "Los días pasados y los días sin minuta no están disponibles."
                )

                if "fechas_calendario" not in st.session_state:
                    st.session_state.fechas_calendario = []

                seleccion_actual = set(st.session_state.fechas_calendario)
                encabezados = st.columns(7)
                for col, titulo in zip(encabezados, ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]):
                    with col:
                        st.markdown(f"<div style='text-align:center;font-weight:700'>{titulo}</div>", unsafe_allow_html=True)

                semanas = calendar.Calendar(firstweekday=0).monthdatescalendar(hoy.year, hoy.month)
                for semana in semanas:
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
                                if st.button(
                                    etiqueta,
                                    key=f"cal_dia_{fecha_iso}",
                                    use_container_width=True,
                                    type="primary" if seleccionado else "secondary",
                                ):
                                    if seleccionado:
                                        seleccion_actual.remove(fecha_iso)
                                    else:
                                        seleccion_actual.add(fecha_iso)
                                    st.session_state.fechas_calendario = sorted(seleccion_actual)
                                    st.rerun()
                            else:
                                motivo = "Pasado" if dia < hoy else "Sin minuta"
                                st.markdown(
                                    f"<div style='text-align:center;color:#999;padding:7px 0'>"
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
                            for servicio in orden_servicios:
                                registros = opciones_por_servicio.get(servicio, [])
                                icono = iconos_servicio.get(servicio, "🍴")
                                with st.expander(f"{icono} {servicio}", expanded=False):
                                    if not registros:
                                        st.info(f"{servicio}: sin opciones disponibles en la minuta de esta fecha.")
                                        continue
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
                            bloque_link = f"<p style='margin:18px 0'><a href='{url_comprobante}' style='background:#086B37;color:white;padding:12px 18px;text-decoration:none;border-radius:8px;font-weight:bold'>SUBIR COMPROBANTE DE PAGO</a></p>" if url_comprobante else "<p><b>Enlace de carga:</b> configura [app].public_url en Secrets para habilitarlo.</p>"
                            html_comprobante = f"""
                            <div style="font-family:Arial,sans-serif;padding:24px;border:2px solid #0A2F6B;border-radius:16px;max-width:760px">
                              <div style="background:#0A2F6B;padding:20px;border-radius:12px;color:white;text-align:center"><h1 style="margin:0;color:white">🍽️ Mamuil Malal</h1><p>Comprobante de reserva</p></div>
                              <h2 style="color:#0A2F6B">Hola {nombre}</h2>
                              <p style="font-size:18px"><b>Referencia:</b> {referencia_reserva}</p>
                              <p><b>RUT:</b> {rut} · <b>Institución:</b> {institucion}</p>
                              <p><b>Fecha de emisión:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                              <p><b>Días:</b> {len(dias)} · <b>Valor total de la reserva:</b> {formato_clp(total_real)}</p>
                              <p><b>Método de pago:</b> {metodo} · <b>Estado:</b> Pendiente</p>
                              <p><b>Fechas:</b> {resumen_fechas}</p>
                              <h3 style="color:#0A2F6B">Detalle de reserva</h3>{detalle_html}
                              <div style="background:#F1F6F3;padding:14px;border-radius:10px;margin-top:14px"><b>Sube tu comprobante aquí</b>{bloque_link}<span style="font-size:13px">El pago no es obligatorio antes del consumo. Puedes utilizar este mismo enlace cuando corresponda.</span></div>
                            </div>"""
                            adjuntos=[(f"Reserva_{referencia_reserva}.pdf",pdf_reserva,"pdf")]
                            correo_ok, correo_msg = enviar_email(correo_cli, f"Reserva {referencia_reserva} · Mamuil Malal", html_comprobante, adjuntos=adjuntos)
                            resultados_cocina = [enviar_email(destino, f"[NUEVA RESERVA] {nombre} · {institucion} · {len(dias)} día(s)", html_comprobante, adjuntos=adjuntos) for destino in get_correos("cocina")]
                            cocina_ok = any(ok for ok, _ in resultados_cocina) if resultados_cocina else False
                            mensaje_resultado = f"¡Felicitaciones! Tu reserva fue realizada con éxito. Te esperamos. Comprobante enviado a {correo_cli}." if correo_ok else f"Tu reserva fue realizada con éxito, referencia {referencia_reserva}, pero el comprobante no pudo enviarse: {correo_msg}"
                            if not cocina_ok:
                                mensaje_resultado += " No fue posible notificar a Cocina."
                            ok_resultado = correo_ok

                        st.session_state.dias_sel = []
                        st.session_state.pedidos = {}
                        st.session_state.reserva_revisar = False
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
        st.markdown("### Reserva - RUT chileno - PostgreSQL")
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


def render_casino():
    usuario = st.session_state.usuario
    roles_casino = ["Cocina", "Finanzas"]
    if usuario and usuario.get("rol") in roles_casino:
        rol = str(usuario["rol"])
        st.markdown(f'<div class="al-card"><h3>{rol}</h3><p>Sesión operativa activa. Este portal se mantiene durante los rerun.</p></div>', unsafe_allow_html=True)

        if rol == "Cocina":
            if not permiso_habilitado(usuario.get('username'),'ver_cocina',True):
                st.warning('Tu función Cocina está deshabilitada por el Administrador Total.')
                return
            tab_minuta, tab_jornada, tab_recetas, tab_bodega = st.tabs([
                "📅 Ver minuta", "▶️ Jornada de producción", "📖 Recetas", "📦 Bodega operativa"
            ])

            with tab_minuta:
                st.markdown("#### Minuta por día")
                fecha_minuta = st.date_input("Selecciona cualquier fecha", value=date.today(), key="fecha_minuta_cocina")
                dfm = get_minutas_rango(fecha_minuta.isoformat(), fecha_minuta.isoformat())
                if dfm.empty:
                    st.warning("No existe minuta cargada para esta fecha.")
                else:
                    for servicio in ["Desayuno", "Almuerzo", "Once", "Cena"]:
                        gm = dfm[dfm["servicio"].astype(str) == servicio]
                        if gm.empty:
                            continue
                        st.markdown(f"### {servicio}")
                        vista = gm[[c for c in ["tipo_opcion", "plato"] if c in gm.columns]].copy()
                        if "tipo_opcion" in vista.columns:
                            vista["tipo_opcion"] = vista["tipo_opcion"].replace({"OPCION 1":"Opción 1","OPCION 2":"Opción 2","HIPOCALORICO":"Hipocalórico"})
                        st.dataframe(vista.rename(columns={"tipo_opcion":"Opción", "plato":"Plato"}), use_container_width=True, hide_index=True)
                st.divider()
                primer_dia_mes = date(fecha_minuta.year, fecha_minuta.month, 1)
                ultimo_dia_mes = date(fecha_minuta.year, fecha_minuta.month, calendar.monthrange(fecha_minuta.year, fecha_minuta.month)[1])
                df_mes = get_minutas_rango(primer_dia_mes.isoformat(), ultimo_dia_mes.isoformat())
                with st.expander("Ver minuta completa del mes"):
                    if df_mes.empty:
                        st.info("No hay minuta mensual cargada.")
                    else:
                        st.dataframe(df_mes[[c for c in ["fecha","servicio","tipo_opcion","plato"] if c in df_mes.columns]], use_container_width=True, hide_index=True)

            with tab_jornada:
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
                            c1,c2=st.columns(2)
                            with c1:
                                prod=st.number_input("Producidas", min_value=0, value=int(r['producidas'] or r['reservadas']), step=1, key=f"jp_{r['id']}")
                            with c2:
                                ent=st.number_input("Entregadas", min_value=0, value=int(r['entregadas'] or r['reservadas']), step=1, key=f"je_{r['id']}")
                            motivo=""
                            if int(prod)!=int(r['reservadas']) or int(ent)!=int(r['reservadas']):
                                motivo=st.text_input("Motivo obligatorio de la diferencia", key=f"jm_{r['id']}")
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

            with tab_recetas:
                st.markdown("#### Recetas y estimaciones")
                conn=get_conn()
                dfr=conn.query("SELECT plato,insumo,cantidad,unidad,merma_pct,margen_produccion_pct,estado,version,instrucciones FROM recetas ORDER BY plato,insumo",ttl=30)
                st.dataframe(dfr,use_container_width=True,hide_index=True)
                st.caption("Las recetas precargadas están en BORRADOR. No descuentan Bodega hasta ser revisadas y aprobadas.")

            with tab_bodega:
                st.markdown("#### Bodega operativa · acceso controlado de Cocina")
                conn=get_conn()
                dfb=conn.query("SELECT codigo_insumo,nombre_articulo,unidad,stock,critico,caduca,seccion FROM bodega_inventario ORDER BY nombre_articulo LIMIT 300",ttl=30)
                st.dataframe(dfb,use_container_width=True,hide_index=True)
                st.caption("Consulta de stock activa. El descuento automático definitivo se habilitará solo tras validar recetas y producción.")

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
            st.markdown("#### 💰 Finanzas")
            conn=get_conn()
            df=conn.query("""
                SELECT COALESCE(NULLIF(s.referencia_reserva,''), s.rut || '-' || s.fecha) AS referencia_reserva,
                       s.rut, MAX(c.nombre) AS nombre, MAX(c.correo) AS correo, MAX(c.institucion) AS institucion,
                       MIN(s.fecha) AS fecha_inicio, MAX(s.fecha) AS fecha_fin, COUNT(DISTINCT s.fecha) AS dias,
                       MAX(s.precio_aplicado) AS valor_dia,
                       COUNT(DISTINCT s.fecha)*MAX(s.precio_aplicado) AS monto_calculado,
                       MAX(s.metodo_pago) AS metodo_pago, MAX(s.estado_pago) AS estado_pago,
                       MAX(a.monto_ajustado) AS monto_ajustado, MAX(a.motivo) AS motivo_ajuste
                FROM solicitudes s
                LEFT JOIN comensales c ON c.rut=s.rut
                LEFT JOIN ajustes_financieros a ON a.referencia_reserva=s.referencia_reserva
                WHERE COALESCE(s.tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'
                GROUP BY COALESCE(NULLIF(s.referencia_reserva,''), s.rut || '-' || s.fecha), s.rut
                ORDER BY MAX(s.fecha) DESC
            """,ttl=10)
            if df.empty:
                st.info("No hay reservas comerciales registradas.")
            else:
                df['monto_final']=df['monto_ajustado'].fillna(df['monto_calculado'])
                st.dataframe(df[["referencia_reserva","nombre","rut","correo","institucion","fecha_inicio","fecha_fin","dias","metodo_pago","estado_pago","monto_final"]],use_container_width=True,hide_index=True)
                pendientes=df[df['estado_pago'].astype(str)!='Pagado']
                c1,c2=st.columns(2)
                with c1: st.metric("Pendiente / no validado",formato_clp(pendientes['monto_final'].sum() if not pendientes.empty else 0))
                with c2: st.metric("Pagado",formato_clp(df[df['estado_pago'].astype(str)=='Pagado']['monto_final'].sum() if not df.empty else 0))

                ref=st.selectbox("Gestionar reserva",df['referencia_reserva'].astype(str).tolist(),key="fin_ref")
                fila=df[df['referencia_reserva'].astype(str)==str(ref)].iloc[0]
                st.markdown(f"**{fila['nombre']} · {fila['rut']} · {fila['institucion']}**")
                df_comp=conn.query("SELECT id,nombre_archivo,mime_type,fecha_carga,estado,contenido FROM comprobantes_pago WHERE referencia_reserva=:r ORDER BY fecha_carga DESC",params={"r":ref},ttl=0)
                if not df_comp.empty:
                    st.success(f"Comprobante recibido · {df_comp.iloc[0]['fecha_carga']}")
                    comp=df_comp.iloc[0]
                    st.download_button("📎 Descargar comprobante para revisión",bytes(comp['contenido']),file_name=str(comp['nombre_archivo']),mime=str(comp['mime_type'] or 'application/octet-stream'),use_container_width=True)
                else:
                    st.caption("Aún no se ha cargado comprobante para esta reserva.")
                metodo_actual=str(fila['metodo_pago'] or 'Transferencia bancaria')
                metodos=["Transferencia bancaria","Débito en la instalación"]
                metodo=st.selectbox("Método de pago",metodos,index=metodos.index(metodo_actual) if metodo_actual in metodos else 0)
                estados=["Pendiente","Comprobante recibido","Observado","Pagado"]
                estado_actual=str(fila['estado_pago'] or 'Pendiente')
                estado_nuevo=st.selectbox("Estado de pago",estados,index=estados.index(estado_actual) if estado_actual in estados else 0)
                monto_actual=int(fila['monto_final'] or 0)
                monto_nuevo=st.number_input("Monto final",min_value=0,value=monto_actual,step=100)
                motivo=st.text_area("Motivo / observación (obligatorio si cambia monto o queda Observado)")
                requiere_motivo=(int(monto_nuevo)!=monto_actual or estado_nuevo=='Observado')
                if st.button("Guardar gestión financiera",type="primary",use_container_width=True,disabled=(requiere_motivo and not motivo.strip())):
                    with conn.session as ses:
                        execute_sql(ses,"UPDATE solicitudes SET metodo_pago=%s,estado_pago=%s,motivo_estado_pago=%s WHERE referencia_reserva=%s",(metodo,estado_nuevo,motivo if estado_nuevo=='Observado' else None,ref))
                        if int(monto_nuevo)!=int(fila['monto_calculado'] or 0):
                            execute_sql(ses,"INSERT INTO ajustes_financieros (referencia_reserva,monto_ajustado,motivo,usuario,fecha) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (referencia_reserva) DO UPDATE SET monto_ajustado=EXCLUDED.monto_ajustado,motivo=EXCLUDED.motivo,usuario=EXCLUDED.usuario,fecha=EXCLUDED.fecha",(ref,int(monto_nuevo),motivo,usuario.get('username'),datetime.now().isoformat()))
                        ses.commit()
                    registrar_auditoria(usuario.get('username'),'GESTION_FINANCIERA','solicitudes',ref,f"{estado_actual}/{monto_actual}",f"{estado_nuevo}/{monto_nuevo}",motivo)
                    st.success("Gestión financiera guardada con trazabilidad.")
                    st.rerun()

                st.divider(); st.markdown("##### Reporte semanal")
                hoy=date.today(); inicio=hoy-timedelta(days=6)
                dfs=df[(pd.to_datetime(df['fecha_fin']).dt.date>=inicio)&(pd.to_datetime(df['fecha_fin']).dt.date<=hoy)].copy()
                st.dataframe(dfs[["referencia_reserva","nombre","institucion","fecha_fin","metodo_pago","estado_pago","monto_final"]],use_container_width=True,hide_index=True)
                st.download_button("📥 Descargar reporte semanal CSV",dfs.to_csv(index=False).encode('utf-8'),f"finanzas_{inicio}_{hoy}.csv","text/csv")
                st.caption("La carga por enlace seguro ya queda habilitada. El recordatorio automático de las 17:00 se mantiene como capa de automatización externa y no depende de que Streamlit permanezca abierto.")
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
        st.markdown(f'<div class="al-card"><h3>🏢 Administración - Reportes PostgreSQL Avanzados</h3><p>V20 - Tres consultas SQL directas para gestión</p></div>', unsafe_allow_html=True)
        tab_reportes, tab_planilla, tab_g, tab_prod, tab_minuta, tab_exc, tab_inst, tab_correos, tab_usuarios = st.tabs(["📊 Reportes","📋 Planilla reservas","📈 Gerencia","📦 Productos","🍽️ Minutas","⚖️ Excepciones","🏢 Instituciones","📧 Correos","👥 Usuarios"])

        # === NUEVA PESTAÑA REPORTES AVANZADOS - 3 CONSULTAS SQL DIRECTAS ===
        with tab_reportes:
            st.markdown("### 📊 Reportes Financieros y de Cocina - PostgreSQL Directo")
            st.caption("Tres consultas SQL directas (SELECT) expuestas en tablas dinámicas Streamlit - Control gestión restaurante")
            conn=get_conn()

            # 1. Pagos Pendientes
            st.markdown("#### 1️⃣ Pagos Pendientes (Filtrado por estado 'Pendiente')")
            st.code("SELECT s.fecha, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.precio_aplicado, s.codigo, s.estado_pago FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.estado_pago='Pendiente' ORDER BY s.fecha DESC", language="sql")
            df_pend = conn.query("""
                SELECT s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.precio_aplicado, s.codigo, s.estado_pago 
                FROM solicitudes s 
                JOIN comensales c ON s.rut=c.rut 
                WHERE s.estado_pago=:estado_pago 
                ORDER BY s.fecha DESC
            """, params={"estado_pago": "Pendiente"}, ttl=0)
            st.dataframe(df_pend, use_container_width=True)
            c1,c2=st.columns(2)
            with c1: st.metric("Total registros pendientes", len(df_pend))
            with c2: st.metric("Monto total pendiente", formato_clp(df_pend['precio_aplicado'].sum() if not df_pend.empty else 0))
            st.download_button("📥 Descargar Pagos Pendientes CSV", df_pend.to_csv(index=False).encode('utf-8'), "pagos_pendientes.csv", "text/csv")

            st.divider()

            # 2. Platos Solicitados por Día
            st.markdown("#### 2️⃣ Platos Solicitados por Día (Conteo acumulado por fecha para compras cocina)")
            st.code("SELECT fecha, plato_reservado, servicio, COUNT(*) as total_solicitado, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY fecha, plato_reservado, servicio ORDER BY fecha", language="sql")
            df_platos_dia = conn.query("""
                SELECT fecha, plato_reservado, servicio, COUNT(*) as total_solicitado, SUM(precio_aplicado) as monto_total 
                FROM solicitudes
                WHERE COALESCE(tipo_registro,'RESERVA_COMERCIAL') <> 'CONSUMO_INTERNO' OR estado_consumo='Consumirá'
                GROUP BY fecha, plato_reservado, servicio 
                ORDER BY fecha ASC
            """, ttl=0)
            st.dataframe(df_platos_dia, use_container_width=True)
            if not df_platos_dia.empty:
                st.bar_chart(df_platos_dia.set_index('plato_reservado')['total_solicitado'])
                st.info(f"📦 Cocina debe comprar para {len(df_platos_dia)} combinaciones de platos - Total porciones: {df_platos_dia['total_solicitado'].sum()}")
            st.download_button("📥 Descargar Platos por Día CSV", df_platos_dia.to_csv(index=False).encode('utf-8'), "platos_por_dia.csv", "text/csv")

            st.divider()

            # 3. Control General de Reservas
            st.markdown("#### 3️⃣ Control General de Reservas (Historial global)")
            st.code("SELECT * FROM solicitudes ORDER BY fecha DESC LIMIT 500", language="sql")
            df_control = conn.query("SELECT s.id, s.referencia_reserva, s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.estado_pago, s.estado_consumo, s.precio_aplicado, s.codigo FROM solicitudes s LEFT JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 500", ttl=0)
            st.dataframe(df_control, use_container_width=True)
            st.metric("Total reservas históricas", len(df_control))
            st.download_button("📥 Descargar Control General CSV", df_control.to_csv(index=False).encode('utf-8'), "control_reservas.csv", "text/csv")

            st.divider()
            st.markdown("##### 🔄 Acciones sobre reportes")
            col1,col2=st.columns(2)
            with col1:
                if not df_pend.empty:
                    id_pago = st.selectbox("Marcar pago como Pagado - ID", df_pend['codigo'].tolist() if 'codigo' in df_pend.columns else [])
                    if st.button("✅ Marcar como Pagado", type="primary"):
                        conn=get_conn()
                        with conn.session as s:
                            execute_sql(s, "UPDATE solicitudes SET estado_pago=%s WHERE codigo=%s", ("Pagado", id_pago))
                            s.commit()
                        st.success(f"Pago {id_pago} marcado Pagado"); st.rerun()
            with col2:
                st.markdown("**Valorización bodega**")
                df_bod = conn.query("SELECT SUM(stock*precio) as valorizado FROM bodega_inventario", ttl=0)
                st.metric("Bodega valorizada", formato_clp(df_bod.iloc[0]['valorizado'] if not df_bod.empty and df_bod.iloc[0]['valorizado'] else 0))

        with tab_planilla:
            st.markdown("### Planilla de reservas")
            st.caption("Cada fila corresponde a un servicio reservado. La referencia agrupa toda la operación del comensal.")
            conn = get_conn()
            referencia_buscar = st.text_input("Consultar por referencia", placeholder="Ej.: MM-20260806-...")
            sql_planilla = """
                SELECT s.referencia_reserva AS referencia, s.fecha, s.servicio, s.rut,
                       c.nombre, c.institucion, c.correo, s.plato_reservado AS plato,
                       s.precio_aplicado, s.metodo_pago, s.estado_pago, s.estado_consumo,
                       s.codigo, s.fecha_creacion, s.fecha_modificacion, s.tipo_registro
                FROM solicitudes s
                LEFT JOIN comensales c ON c.rut=s.rut
            """
            params_planilla = {}
            if referencia_buscar.strip():
                sql_planilla += " WHERE UPPER(COALESCE(s.referencia_reserva,'')) = UPPER(:referencia)"
                params_planilla["referencia"] = referencia_buscar.strip()
            sql_planilla += " ORDER BY s.fecha DESC, s.referencia_reserva, s.servicio"
            df_planilla = conn.query(sql_planilla, params=params_planilla or None, ttl=0)
            st.dataframe(df_planilla, use_container_width=True, hide_index=True)
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
            elif referencia_buscar.strip():
                st.warning("No se encontró una reserva con esa referencia.")

        with tab_g:
            st.markdown("##### Gerencia - Reportes consolidados PostgreSQL")
            conn=get_conn()
            df_sol=conn.query("SELECT institucion, COUNT(*) as total, SUM(precio_aplicado) as monto FROM solicitudes WHERE COALESCE(tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL' GROUP BY institucion", ttl=0)
            df_com=conn.query("SELECT institucion, COUNT(*) as comensales FROM comensales GROUP BY institucion", ttl=0)
            df_pend=conn.query("SELECT COUNT(*) as pendientes, SUM(precio_aplicado) as monto_pend FROM solicitudes WHERE estado_pago=:estado AND COALESCE(tipo_registro,'RESERVA_COMERCIAL')='RESERVA_COMERCIAL'", params={"estado": "Pendiente"}, ttl=0)
            df_metodo=conn.query("SELECT metodo_pago, COUNT(*) as qty, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY metodo_pago", ttl=0)
            c1,c2,c3=st.columns(3)
            with c1: st.metric("Reservas", int(df_sol['total'].sum()) if not df_sol.empty else 0)
            with c2: st.metric("Monto", formato_clp(df_sol['monto'].sum() if not df_sol.empty else 0))
            with c3: st.metric("Pendiente", formato_clp(df_pend.iloc[0]['monto_pend'] if not df_pend.empty and df_pend.iloc[0]['monto_pend'] else 0))
            st.dataframe(df_sol, use_container_width=True)
            st.dataframe(df_metodo, use_container_width=True)

        with tab_prod:
            st.markdown("#### 📦 Admin productos PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM platos ORDER BY servicio, nombre", ttl=0)
            st.dataframe(df, use_container_width=True)

        with tab_minuta:
            st.markdown("#### 🍽️ Minutas - Carga por día semana")
            conn=get_conn()
            df_min=conn.query("SELECT * FROM minutas WHERE activo=1 ORDER BY dia_semana, servicio", ttl=0)
            st.dataframe(df_min, use_container_width=True)
            with st.form("add_minuta"):
                dia=st.selectbox("Día semana", ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"])
                serv=st.selectbox("Servicio", ["Desayuno","Almuerzo","Once","Cena"], key="min_serv")
                plato=st.text_input("Nombre plato*")
                if st.form_submit_button("Agregar a minuta", type="primary", use_container_width=True):
                    if plato:
                        conn=get_conn()
                        with conn.session as s:
                            execute_sql(s, "INSERT INTO minutas (dia_semana,servicio,plato,activo) VALUES (%s,%s,%s,1)", (dia,serv,plato))
                            execute_sql(s, "INSERT INTO platos (nombre,servicio,valor,activo) VALUES (%s,%s,%s,1) ON CONFLICT DO NOTHING", (plato,serv,6500))
                            s.commit()
                        st.success(f"Minuta {dia} {serv} {plato} agregada"); st.rerun()

        with tab_exc:
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

        with tab_inst:
            st.markdown("#### 🏢 Instituciones PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM instituciones ORDER BY nombre", ttl=0)
            st.dataframe(df, use_container_width=True)

        with tab_correos:
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
                        limpiar_cache_correos()
                        st.success("Destinatario guardado.")
                        st.rerun()

            if not df_correos.empty:
                st.divider()
                id_correo=st.selectbox("Destinatario a activar/desactivar", df_correos["id"].tolist(), format_func=lambda x: f"{df_correos[df_correos['id']==x].iloc[0]['tipo']} · {df_correos[df_correos['id']==x].iloc[0]['correo']}")
                estado_actual=int(df_correos[df_correos['id']==id_correo].iloc[0]['activo'] or 0)
                nuevo_estado=st.selectbox("Estado", [1,0], index=0 if estado_actual else 1, format_func=lambda x: "Activo" if x else "Inactivo")
                if st.button("Actualizar estado del destinatario", use_container_width=True):
                    with conn.session as ses:
                        execute_sql(ses, "UPDATE configuracion_correos SET activo=%s WHERE id=%s", (nuevo_estado,id_correo))
                        ses.commit()
                    limpiar_cache_correos()
                    st.success("Estado actualizado.")
                    st.rerun()

        with tab_usuarios:
            rol_gestor = st.session_state.usuario.get("rol")
            conn=get_conn()
            dfu=conn.query("SELECT username,nombre,rol,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password,fecha_creacion FROM usuarios ORDER BY username",ttl=0)
            if rol_gestor in ["AdminTotal","Gerencia"]:
                st.markdown("#### 🔑 Restablecer contraseña")
                if not dfu.empty:
                    usuario_reset=st.selectbox("Usuario",dfu['username'].astype(str).tolist(),key="reset_usuario")
                    with st.form("reset_password_form"):
                        temp=st.text_input("Nueva contraseña temporal",type="password")
                        motivo_reset=st.text_input("Motivo del restablecimiento*")
                        do_reset=st.form_submit_button("Restablecer contraseña",use_container_width=True)
                    if do_reset:
                        if len(temp)<8 or not motivo_reset.strip():
                            st.error("La contraseña temporal debe tener al menos 8 caracteres y debes indicar un motivo.")
                        else:
                            with conn.session as ses:
                                execute_sql(ses,"UPDATE usuarios SET pwd=%s,debe_cambiar_password=1 WHERE username=%s",(hash_pwd(temp),usuario_reset)); ses.commit()
                            registrar_auditoria(st.session_state.usuario.get('username'),'RESET_PASSWORD','usuarios',usuario_reset,'','hash temporal',motivo_reset)
                            st.success("Contraseña restablecida. El usuario deberá cambiarla en el próximo ingreso.")
            if rol_gestor != "AdminTotal":
                st.info("Gerencia puede restablecer contraseñas. Solo el Administrador Total puede crear usuarios, cambiar roles o activar/desactivar funciones.")
            else:
                st.markdown("#### 👥 Gestión de usuarios y permisos")
                st.dataframe(dfu,use_container_width=True,hide_index=True)
                with st.form("crear_usuario_total"):
                    c1,c2=st.columns(2)
                    with c1:
                        nu=st.text_input("Usuario nuevo*"); nn=st.text_input("Nombre*")
                    with c2:
                        nr=st.selectbox("Rol*",["Cocina","Finanzas","Gerencia","AdminCasino","Operaciones","AdminTotal"])
                        np=st.text_input("Contraseña inicial*",type="password")
                    if st.form_submit_button("Crear / actualizar usuario",type="primary",use_container_width=True):
                        if nu.strip() and nn.strip() and np:
                            with conn.session as ses:
                                execute_sql(ses,"INSERT INTO usuarios (username,pwd,rol,nombre,activo,fecha_creacion,debe_cambiar_password) VALUES (%s,%s,%s,%s,1,%s,1) ON CONFLICT (username) DO UPDATE SET pwd=EXCLUDED.pwd,rol=EXCLUDED.rol,nombre=EXCLUDED.nombre,activo=1,debe_cambiar_password=1",(nu.strip(),hash_pwd(np),nr,nn.strip(),datetime.now().isoformat()))
                                ses.commit()
                            registrar_auditoria(st.session_state.usuario.get('username'),'CREAR_ACTUALIZAR_USUARIO','usuarios',nu,'',nr,'')
                            st.success("Usuario guardado."); st.rerun()
                        else: st.error("Completa usuario, nombre y contraseña.")
                if not dfu.empty:
                    selu=st.selectbox("Usuario a administrar",dfu['username'].astype(str).tolist(),key="adm_u_sel")
                    rowu=dfu[dfu['username'].astype(str)==selu].iloc[0]
                    activo_n=st.selectbox("Estado de cuenta",[1,0],index=0 if int(rowu['activo']) else 1,format_func=lambda x:"Activo" if x else "Deshabilitado")
                    rol_n=st.selectbox("Rol",["Cocina","Finanzas","Gerencia","AdminCasino","Operaciones","AdminTotal"],index=["Cocina","Finanzas","Gerencia","AdminCasino","Operaciones","AdminTotal"].index(str(rowu['rol'])) if str(rowu['rol']) in ["Cocina","Finanzas","Gerencia","AdminCasino","Operaciones","AdminTotal"] else 0)
                    if st.button("Guardar estado / rol",use_container_width=True):
                        with conn.session as ses:
                            execute_sql(ses,"UPDATE usuarios SET activo=%s,rol=%s WHERE username=%s",(activo_n,rol_n,selu)); ses.commit()
                        registrar_auditoria(st.session_state.usuario.get('username'),'MODIFICAR_USUARIO','usuarios',selu,f"{rowu['rol']}/{rowu['activo']}",f"{rol_n}/{activo_n}",'')
                        st.success("Usuario actualizado."); st.rerun()
                    st.markdown("##### Permisos específicos")
                    permisos=["ver_cocina","ver_bodega","cargar_inventario","ver_finanzas","modificar_montos","validar_pagos","ver_gerencia","editar_minuta","gestionar_usuarios"]
                    for perm in permisos:
                        actual=permiso_habilitado(selu,perm,default=True)
                        val=st.checkbox(perm.replace('_',' ').title(),value=actual,key=f"perm_{selu}_{perm}")
                        if val!=actual:
                            with conn.session as ses:
                                execute_sql(ses,"INSERT INTO usuarios_permisos (username,permiso,activo) VALUES (%s,%s,%s) ON CONFLICT (username,permiso) DO UPDATE SET activo=EXCLUDED.activo",(selu,perm,1 if val else 0)); ses.commit()
                            registrar_auditoria(st.session_state.usuario.get('username'),'CAMBIAR_PERMISO','usuarios_permisos',f"{selu}:{perm}",actual,val,'')
                            st.rerun()

    else:
        st.markdown("### 🏢 Administración - Login PostgreSQL")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre,COALESCE(activo,1) AS activo,COALESCE(debe_cambiar_password,0) AS debe_cambiar_password FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username": u, "pwd": hash_pwd(p)}, ttl=0)
                if not df.empty and int(df.iloc[0]['activo'])==1 and df.iloc[0]['rol'] in ["AdminTotal","AdminCasino","Operaciones","Gerencia"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre'],"debe_cambiar_password":int(df.iloc[0]['debe_cambiar_password'])}; st.session_state.portal_actual="administracion"; st.rerun()
                else: st.error("Usuario no válido, deshabilitado o sin acceso administrativo.")


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
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🧑 Soy Comensal", type="primary", use_container_width=True):
            st.session_state.portal_actual = "comensal"
            st.rerun()
    with c2:
        if st.button("👨‍🍳 Personal de Casino", use_container_width=True):
            st.session_state.portal_actual = "casino"
            st.rerun()
    with c3:
        if st.button("🏢 Administración", use_container_width=True):
            st.session_state.portal_actual = "administracion"
            st.rerun()
    st.caption("Los módulos internos solo se muestran después de elegir el acceso correspondiente y autenticar el perfil cuando aplica.")
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
