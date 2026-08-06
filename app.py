import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import random
import calendar
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT, get_config_seguridad, set_config_seguridad, enmascarar_correo, iniciar_validacion_comensal, validar_codigo_comensal

st.set_page_config(page_title="Mamuil Malal - Reserva de Alimentación", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

try: apply_alemsi_style()
except: pass

try: init_db()
except Exception as e:
    st.error(f"Error inicializando DB PostgreSQL: {e} - Verifica secrets [connections.postgresql]")
    st.stop()

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}
if "main_view" not in st.session_state: st.session_state.main_view="🧑 SOY COMENSAL"
if "comensal_view" not in st.session_state: st.session_state.comensal_view="📅 Reservar"
if "casino_view" not in st.session_state: st.session_state.casino_view="👨‍🍳 Cocina"
if "admin_view" not in st.session_state: st.session_state.admin_view="📊 Reportes"

st.markdown('''
<div class="main-header">
<h1>ALEMSI · Mamuil Malal</h1>
<p>Portal de reserva de alimentación</p>
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
            st.session_state.usuario=None; st.session_state.rut_actual=None; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0
            st.session_state.main_view="🧑 SOY COMENSAL"
            st.rerun()

main_view = st.radio(
    "Módulo",
    ["🧑 SOY COMENSAL", "👨‍🍳 PERSONAL DE CASINO", "🏢 ADMINISTRACIÓN"],
    key="main_view",
    horizontal=True,
    label_visibility="collapsed",
)

# ===== COMENSAL - POSTGRESQL + CORREO AUTOMÁTICO =====
if main_view == "🧑 SOY COMENSAL":
    if st.session_state.rut_actual:
        rut=st.session_state.rut_actual
        conn=get_conn()
        com=conn.query("SELECT * FROM comensales WHERE rut=%s", params=(rut,), ttl=0)
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        comensal_view = st.radio(
            "Sección comensal",
            ["📅 Reservar", "💬 Reclamos"],
            key="comensal_view",
            horizontal=True,
            label_visibility="collapsed",
        )

        if comensal_view == "📅 Reservar":
            if not st.session_state.dias_sel:
                hoy = date.today()
                ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
                primer_dia_mes = date(hoy.year, hoy.month, 1)
                dias = [primer_dia_mes + timedelta(days=i) for i in range(ultimo_dia)]
                nombres_meses = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

                st.markdown("### Selecciona los días de tu reserva")
                st.caption("Puedes elegir un día, días consecutivos o días intercalados del mes en curso.")
                st.markdown(f"#### {nombres_meses[hoy.month]} {hoy.year}")

                # Calendario real: siete columnas alineadas de lunes a domingo.
                encabezados = st.columns(7)
                for col, nombre_dia in zip(encabezados, ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]):
                    col.markdown(f"<div style='text-align:center;font-weight:700;color:#62788C'>{nombre_dia}</div>", unsafe_allow_html=True)

                celdas = [None] * primer_dia_mes.weekday() + dias
                while len(celdas) % 7:
                    celdas.append(None)

                for semana in range(0, len(celdas), 7):
                    columnas = st.columns(7)
                    for columna, dia_cal in zip(columnas, celdas[semana:semana+7]):
                        with columna:
                            if dia_cal is None:
                                st.markdown("&nbsp;", unsafe_allow_html=True)
                                continue
                            fecha_iso = dia_cal.isoformat()
                            seleccionado = fecha_iso in st.session_state.dias_sel
                            pasado = dia_cal < hoy
                            if st.button(
                                str(dia_cal.day),
                                key=f"d_{fecha_iso}",
                                use_container_width=True,
                                type="primary" if seleccionado else "secondary",
                                disabled=pasado,
                            ):
                                if seleccionado:
                                    st.session_state.dias_sel.remove(fecha_iso)
                                else:
                                    st.session_state.dias_sel.append(fecha_iso)
                                st.rerun()
                            if pasado:
                                st.caption("Pasado")

                st.caption(f"Valor por día: {formato_clp(precio_dia)}")
                if st.session_state.dias_sel:
                    st.info(f"{len(st.session_state.dias_sel)} día(s) seleccionado(s) · Total estimado {formato_clp(len(st.session_state.dias_sel) * precio_dia)}")

                if st.button("Continuar a selección de menú →", type="primary", use_container_width=True):
                    if not st.session_state.dias_sel:
                        st.warning("Selecciona al menos un día para continuar.")
                    else:
                        st.session_state.dias_sel = sorted(st.session_state.dias_sel)
                        st.session_state.pedidos = {d: {} for d in st.session_state.dias_sel}
                        st.session_state.wizard_idx = 0
                        st.rerun()
            else:
                dias=sorted(st.session_state.dias_sel); idx=st.session_state.wizard_idx
                if idx<len(dias):
                    f_iso=dias[idx]; f_obj=date.fromisoformat(f_iso)
                    dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                    st.markdown(f"### {dnom} {f_obj.strftime('%d/%m/%Y')}")
                    st.caption(f"Día {idx + 1} de {len(dias)} · Selecciona uno o más servicios")
                    # Captura minuta elegida según día de la semana
                    minuta_dia = MINUTA.get(dnom, {})
                    # Intentar cargar de DB minutas activas
                    try:
                        conn=get_conn()
                        df_min_db = conn.query("SELECT servicio, plato FROM minutas WHERE dia_semana=%s AND activo=1", params=(dnom,), ttl=0)
                        if not df_min_db.empty:
                            for _, r in df_min_db.iterrows():
                                serv=r['servicio']; plato=r['plato']
                                if serv not in minuta_dia: minuta_dia[serv]=[]
                                if plato not in minuta_dia[serv]: minuta_dia[serv].append(plato)
                    except: pass

                    # Selección compacta día por día, sin botones por plato.
                    # Las opciones quedan en session_state y el usuario puede avanzar o volver.
                    servicios_orden = ["Desayuno", "Almuerzo", "Once", "Cena"]
                    pedidos_dia = st.session_state.pedidos.setdefault(f_iso, {})
                    opciones_guardadas = {}

                    with st.form(f"menu_dia_{f_iso}"):
                        iconos_servicio = {"Desayuno": "🍳", "Almuerzo": "🍽️", "Once": "☕", "Cena": "🌙"}
                        for serv in servicios_orden:
                            platos = list(dict.fromkeys(minuta_dia.get(serv, [])))
                            st.markdown(
                                f"<div class='service-title'>{iconos_servicio[serv]} {serv}</div>",
                                unsafe_allow_html=True,
                            )
                            if not platos:
                                st.markdown(
                                    "<div class='service-empty'>Sin minuta disponible para este servicio.</div>",
                                    unsafe_allow_html=True,
                                )
                                continue

                            opciones = ["— No reservar este servicio —"] + platos
                            actual = pedidos_dia.get(serv)
                            indice = opciones.index(actual) if actual in opciones else 0
                            opciones_guardadas[serv] = st.selectbox(
                                f"Selecciona tu {serv.lower()}",
                                opciones,
                                index=indice,
                                key=f"sel_{f_iso}_{serv}",
                                label_visibility="collapsed",
                            )

                        st.caption("Puedes volver al día anterior y cambiar tus selecciones antes de confirmar.")
                        c1, c2 = st.columns(2)
                        with c1:
                            volver = st.form_submit_button(
                                "← Día anterior",
                                use_container_width=True,
                                disabled=idx == 0,
                            )
                        with c2:
                            etiqueta = "Revisar reserva →" if idx == len(dias) - 1 else "Guardar y continuar →"
                            avanzar = st.form_submit_button(
                                etiqueta,
                                type="primary",
                                use_container_width=True,
                            )

                    if volver or avanzar:
                        seleccion_dia = {
                            serv: plato
                            for serv, plato in opciones_guardadas.items()
                            if plato != "— No reservar este servicio —"
                        }
                        st.session_state.pedidos[f_iso] = seleccion_dia

                        if volver:
                            st.session_state.wizard_idx = max(0, idx - 1)
                            st.rerun()

                        if avanzar:
                            if not seleccion_dia:
                                st.warning("Selecciona al menos un servicio para este día antes de continuar.")
                            else:
                                st.session_state.wizard_idx += 1
                                st.rerun()
                else:
                    # Resumen y formulario con metodo_pago
                    dias_sin = [f for f in dias if not st.session_state.pedidos.get(f)]
                    if dias_sin:
                        st.error(f"❌ Faltan {len(dias_sin)} día(s) con selección"); 
                        if st.button("Volver a seleccionar"): st.session_state.dias_sel=[]; st.rerun()
                        st.stop()
                    total=0; detalle=[]
                    for f_iso in dias:
                        dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(f_iso).weekday()]
                        for serv,plato in st.session_state.pedidos.get(f_iso,{}).items():
                            pr=get_precio(plato,serv); total+=pr; detalle.append((f_iso,dnom,serv,plato,pr))
                    df=pd.DataFrame(detalle, columns=["Fecha","Día","Servicio","Plato","Precio"])
                    total_real = len(dias)*precio_dia
                    st.dataframe(df, use_container_width=True)
                    st.metric("Total a pagar", formato_clp(total_real))
                    
                    # Formulario captura minuta + método pago
                    st.markdown("#### 💳 Método de pago y confirmación")
                    metodo=st.selectbox("Método de pago*", ["Transferencia","Débito en local","Crédito", "Descuento por planilla"])
                    if st.button("✅ CONFIRMAR Y ENVIAR COMPROBANTE POR CORREO", type="primary", use_container_width=True):
                        conn=get_conn()
                        with conn.session as s:
                            vouchers=[]
                            dfc=conn.query("SELECT correo FROM comensales WHERE rut=%s", params=(rut,), ttl=0)
                            correo_cli=dfc.iloc[0]['correo'] if not dfc.empty else ""
                            for f_iso,dnom,serv,plato,pr in detalle:
                                cod=gen_codigo(rut,serv,date.fromisoformat(f_iso))
                                # INSERT PostgreSQL con %s - columnas nativas plato_reservado, metodo_pago, estado_pago DEFAULT 'Pendiente'
                                s.execute(
                                    "INSERT INTO solicitudes (rut,fecha,servicio,plato,plato_reservado,codigo,precio,precio_aplicado,institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (rut,f_iso,serv,plato,plato, cod, pr, precio_dia, institucion, correo_cli, metodo, "Pendiente", "Pendiente", datetime.now().isoformat())
                                )
                                vouchers.append(cod)
                            s.commit()
                        # Descontar bodega
                        for _,_,_,plato,_ in detalle:
                            descontar_bodega(plato)

                        # Despacho comprobante HTML inmediato al correo del comensal
                        html_comprobante = f'''
                        <div style="font-family:Arial, sans-serif; padding:24px; border:2px solid #0A2F6B; border-radius:16px; max-width:700px;">
                            <div style="background:linear-gradient(135deg,#0A2F6B 0%, #123E7A 100%); padding:20px; border-radius:12px; color:white; text-align:center;">
                                <h1 style="margin:0;">🍽️ Mamuil Malal</h1>
                                <p style="margin:4px 0 0 0;">Comprobante de Reserva - ERP V20</p>
                            </div>
                            <div style="padding:16px 0;">
                                <h2 style="color:#0A2F6B;">Hola {nombre} 👋</h2>
                                <p><b>RUT:</b> {rut} | <b>Institución:</b> {institucion}</p>
                                <p><b>Fecha reserva:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                                <p><b>Días reservados:</b> {len(dias)} | <b>Total:</b> <span style="color:#0A2F6B; font-size:18px; font-weight:bold;">{formato_clp(total_real)}</span></p>
                                <p><b>Método pago:</b> {metodo} | <b>Estado pago:</b> Pendiente</p>
                                <p><b>Códigos voucher:</b> {", ".join(vouchers)}</p>
                                <hr style="border:1px solid #E9ECEF;">
                                <h3 style="color:#0A2F6B;">Detalle minutas elegidas según día de semana:</h3>
                                {df.to_html(index=False, border=0, classes='table')}
                                <hr>
                                <p style="background:#F8F9FA; padding:12px; border-radius:8px; font-size:13px;">
                                    <b>Minuta:</b> Cada día se asignó según el día de la semana ({", ".join([date.fromisoformat(f).strftime('%d/%m') for f in dias])})<br>
                                    <b>Plato reservado:</b> Almacenado nativamente en columna <code>plato_reservado</code><br>
                                    <b>Método pago:</b> Almacenado en columna <code>metodo_pago</code><br>
                                    <b>Estado pago:</b> <code>Pendiente</code> por defecto - Finanzas validará
                                </p>
                                <p style="font-size:12px; color:#666;">Conserva este correo como comprobante de tu reserva.</p>
                            </div>
                            <div style="text-align:center; padding-top:12px; border-top:1px solid #E9ECEF; font-size:12px; color:#999;">
                                Mamuil Malal · Sistema de Reserva de Alimentación
                            </div>
                        </div>
                        '''
                        ok1, msg1 = enviar_email(correo_cli, f"✅ Comprobante Reserva {len(dias)} días - {formato_clp(total_real)} - Mamuil Malal", html_comprobante)
                        ok2, msg2 = enviar_email(EMAILS.get('cocina','ale973@gmail.com'), f"[NUEVA RESERVA] {nombre} - {institucion} - {len(dias)} días", html_comprobante)
                        
                        if ok1:
                            st.success(f"✅ Reserva confirmada - Comprobante enviado a {correo_cli}")
                            st.balloons()
                        else:
                            st.warning(f"Reserva guardada pero correo no enviado: {msg1} - Verifica Secrets [email]")
                        st.info(f"Códigos: {', '.join(vouchers)}")
                        # Limpiar sesión
                        st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0
                        if st.button("Hacer nueva reserva"): st.rerun()

        if comensal_view == "💬 Reclamos":
            with st.form("reclamo"):
                tipo=st.selectbox("Tipo", ["Reclamo","Sugerencia","Felicitación"])
                categoria=st.selectbox("Categoría", ["Comida","Atención","Higiene","Infraestructura","Otro"])
                mensaje=st.text_area("Mensaje*")
                if st.form_submit_button("Enviar", type="primary", use_container_width=True):
                    if mensaje:
                        conn=get_conn()
                        with conn.session as s:
                            s.execute("INSERT INTO reclamos_sugerencias (rut,nombre,tipo,categoria,mensaje,fecha,estado) VALUES (%s,%s,%s,%s,%s,%s,%s)", (rut,nombre,tipo,categoria,mensaje, datetime.now().isoformat(),"Pendiente"))
                            s.commit()
                        st.success("Enviado")
    else:
        st.markdown("### Reserva - RUT chileno - PostgreSQL")
        rut_raw=st.text_input("RUT", placeholder="16.632.880-2")
        if rut_raw:
            if not validar_rut_m11(rut_raw):
                st.error("RUT inválido")
            else:
                rn=normalizar_rut_db(rut_raw); rv=normalizar_rut(rut_raw)
                conn=get_conn()
                df=conn.query("SELECT * FROM comensales WHERE rut=%s", params=(rn,), ttl=0)
                if not df.empty:
                    st.success(f"Hola {df.iloc[0]['nombre']} - {rv}")
                    modo_validacion = get_config_seguridad("validacion_comensal", "SOLO_RUT")
                    if modo_validacion == "RUT_MAS_CODIGO":
                        correo_registrado = str(df.iloc[0].get('correo') or "")
                        st.caption(f"Por seguridad enviaremos un código a {enmascarar_correo(correo_registrado)}")
                        c_env, c_val = st.columns([1, 2])
                        with c_env:
                            if st.button("Enviar código", use_container_width=True):
                                if correo_registrado:
                                    ok, mensaje = iniciar_validacion_comensal(rn, correo_registrado)
                                    if ok:
                                        st.success("Código enviado. Revisa tu correo.")
                                    else:
                                        st.error(f"No fue posible enviar el código: {mensaje}")
                                else:
                                    st.error("Este comensal no tiene un correo registrado.")
                        with c_val:
                            with st.form("validar_codigo_comensal"):
                                codigo = st.text_input("Código de 6 dígitos", max_chars=6)
                                validar = st.form_submit_button("Validar e ingresar", type="primary", use_container_width=True)
                            if validar:
                                ok, mensaje = validar_codigo_comensal(rn, codigo)
                                if ok:
                                    st.session_state.rut_actual = rn
                                    st.rerun()
                                else:
                                    st.error(mensaje)
                    else:
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
                            if nombre and tel and correo and institucion:
                                conn=get_conn()
                                with conn.session as s:
                                    s.execute("INSERT INTO comensales (rut,nombre,telefono,correo,institucion,fecha_registro) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (rut) DO UPDATE SET nombre=%s, telefono=%s, correo=%s, institucion=%s", (rn,nombre,tel,correo,institucion, datetime.now().isoformat(), nombre, tel, correo, institucion))
                                    s.commit()
                                st.session_state.rut_actual=rn; st.rerun()

# ===== PERSONAL DE CASINO =====
if main_view == "👨‍🍳 PERSONAL DE CASINO":
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Cocina","Bodega","Finanzas","Admin"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>{rol} - Módulos PostgreSQL</h3></div>', unsafe_allow_html=True)
        casino_view = st.radio(
            "Sección personal",
            ["👨‍🍳 Cocina", "📦 Bodega", "💰 Finanzas"],
            key="casino_view",
            horizontal=True,
            label_visibility="collapsed",
        )
        if casino_view == "👨‍🍳 Cocina":
            st.markdown("#### 👨‍🍳 Cocina - Platos Solicitados por Día (PostgreSQL)")
            conn=get_conn()
            df=conn.query("SELECT fecha, plato_reservado, COUNT(*) as cantidad, servicio FROM solicitudes WHERE fecha >= %s GROUP BY fecha, plato_reservado, servicio ORDER BY fecha", params=(date.today().isoformat(),), ttl=0)
            st.dataframe(df, use_container_width=True)
            st.metric("Total órdenes hoy+", len(df))
        if casino_view == "📦 Bodega":
            st.markdown("#### 📦 Bodega PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM bodega_inventario ORDER BY nombre_articulo LIMIT 100", ttl=0)
            st.dataframe(df, use_container_width=True)
        if casino_view == "💰 Finanzas":
            st.markdown("#### 💰 Finanzas - Pagos Pendientes")
            conn=get_conn()
            df=conn.query("SELECT * FROM solicitudes WHERE estado_pago=%s ORDER BY fecha DESC", params=("Pendiente",), ttl=0)
            st.dataframe(df, use_container_width=True)
            st.metric("Pendiente", formato_clp(df['precio_aplicado'].sum() if not df.empty else 0))
    else:
        st.markdown("### 👨‍🍳 Personal Casino - Login PostgreSQL")
        with st.form("login_casino"):
            u=st.text_input("Usuario", key="u_casino"); p=st.text_input("Contraseña", type="password", key="p_casino")
            if st.form_submit_button("Ingresar Casino", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre FROM usuarios WHERE username=%s AND pwd=%s", params=(u, hash_pwd(p)), ttl=0)
                if not df.empty and df.iloc[0]['rol'] in ["Cocina","Bodega","Finanzas","Admin"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre']}
                    st.session_state.main_view="👨‍🍳 PERSONAL DE CASINO"
                    st.rerun()
                else: st.error("No válido - prueba admin/admin123")

# ===== ADMINISTRACIÓN - REPORTES AVANZADOS POSTGRESQL =====
if main_view == "🏢 ADMINISTRACIÓN":
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Admin","Gerencia"]:
        st.markdown(f'<div class="al-card"><h3>🏢 Administración - Reportes PostgreSQL Avanzados</h3><p>V20 - Tres consultas SQL directas para gestión</p></div>', unsafe_allow_html=True)
        admin_view = st.radio(
            "Sección administración",
            ["📊 Reportes", "📈 Gerencia", "📦 Productos", "🍽️ Minutas", "⚖️ Excepciones", "🏢 Instituciones", "🔐 Seguridad"],
            key="admin_view",
            horizontal=True,
            label_visibility="collapsed",
        )

        # === REPORTES ===
        if admin_view == "📊 Reportes":
            st.markdown("### 📊 Reportes financieros y de cocina")
            st.caption("Resumen operativo, financiero y de producción.")
            conn=get_conn()

            # 1. Pagos Pendientes
            st.markdown("#### 1️⃣ Pagos Pendientes (Filtrado por estado 'Pendiente')")
            st.code("SELECT s.fecha, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.precio_aplicado, s.codigo, s.estado_pago FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.estado_pago='Pendiente' ORDER BY s.fecha DESC", language="sql")
            df_pend = conn.query("""
                SELECT s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.precio_aplicado, s.codigo, s.estado_pago 
                FROM solicitudes s 
                JOIN comensales c ON s.rut=c.rut 
                WHERE s.estado_pago=%s 
                ORDER BY s.fecha DESC
            """, params=("Pendiente",), ttl=0)
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
            df_control = conn.query("SELECT s.id, s.fecha, s.rut, c.nombre, c.institucion, s.plato_reservado, s.metodo_pago, s.estado_pago, s.estado_consumo, s.precio_aplicado, s.codigo FROM solicitudes s LEFT JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 500", ttl=0)
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
                            s.execute("UPDATE solicitudes SET estado_pago=%s WHERE codigo=%s", ("Pagado", id_pago))
                            s.commit()
                        st.success(f"Pago {id_pago} marcado Pagado"); st.rerun()
            with col2:
                st.markdown("**Valorización bodega**")
                df_bod = conn.query("SELECT SUM(stock*precio) as valorizado FROM bodega_inventario", ttl=0)
                st.metric("Bodega valorizada", formato_clp(df_bod.iloc[0]['valorizado'] if not df_bod.empty and df_bod.iloc[0]['valorizado'] else 0))

        if admin_view == "📈 Gerencia":
            st.markdown("##### Gerencia - Reportes consolidados PostgreSQL")
            conn=get_conn()
            df_sol=conn.query("SELECT institucion, COUNT(*) as total, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY institucion", ttl=0)
            df_com=conn.query("SELECT institucion, COUNT(*) as comensales FROM comensales GROUP BY institucion", ttl=0)
            df_pend=conn.query("SELECT COUNT(*) as pendientes, SUM(precio_aplicado) as monto_pend FROM solicitudes WHERE estado_pago=%s", params=("Pendiente",), ttl=0)
            df_metodo=conn.query("SELECT metodo_pago, COUNT(*) as qty, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY metodo_pago", ttl=0)
            c1,c2,c3=st.columns(3)
            with c1: st.metric("Reservas", int(df_sol['total'].sum()) if not df_sol.empty else 0)
            with c2: st.metric("Monto", formato_clp(df_sol['monto'].sum() if not df_sol.empty else 0))
            with c3: st.metric("Pendiente", formato_clp(df_pend.iloc[0]['monto_pend'] if not df_pend.empty and df_pend.iloc[0]['monto_pend'] else 0))
            st.dataframe(df_sol, use_container_width=True)
            st.dataframe(df_metodo, use_container_width=True)

        if admin_view == "📦 Productos":
            st.markdown("#### 📦 Admin productos PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM platos ORDER BY servicio, nombre", ttl=0)
            st.dataframe(df, use_container_width=True)

        if admin_view == "🍽️ Minutas":
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
                            s.execute("INSERT INTO minutas (dia_semana,servicio,plato,activo) VALUES (%s,%s,%s,1)", (dia,serv,plato))
                            s.execute("INSERT INTO platos (nombre,servicio,valor,activo) VALUES (%s,%s,%s,1) ON CONFLICT DO NOTHING", (plato,serv,6500))
                            s.commit()
                        st.success(f"Minuta {dia} {serv} {plato} agregada"); st.rerun()

        if admin_view == "⚖️ Excepciones":
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
                                s.execute("UPDATE instituciones SET precio_especial=%s, regla_activa=1, descripcion=%s WHERE nombre=%s", (precio_especial_global, motivo_global, nombre))
                            else:
                                s.execute("UPDATE instituciones SET regla_activa=0 WHERE nombre=%s", (nombre,))
                        s.commit()
                    st.success("Reglas actualizadas"); st.rerun()

        if admin_view == "🏢 Instituciones":
            st.markdown("#### 🏢 Instituciones PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM instituciones ORDER BY nombre", ttl=0)
            st.dataframe(df, use_container_width=True)

        if admin_view == "🔐 Seguridad":
            st.markdown("#### Acceso de comensales")
            st.caption("La opción predeterminada es Solo RUT. Activar código por correo no modifica reservas, precios ni comprobantes.")
            modo_actual = get_config_seguridad("validacion_comensal", "SOLO_RUT")
            duracion_actual = int(get_config_seguridad("codigo_duracion_minutos", "10") or 10)
            intentos_actual = int(get_config_seguridad("codigo_max_intentos", "5") or 5)
            with st.form("config_seguridad_comensal"):
                modo = st.radio(
                    "Método de acceso",
                    ["SOLO_RUT", "RUT_MAS_CODIGO"],
                    index=0 if modo_actual == "SOLO_RUT" else 1,
                    format_func=lambda x: "Solo RUT" if x == "SOLO_RUT" else "RUT + código enviado al correo",
                )
                c1, c2 = st.columns(2)
                with c1:
                    duracion = st.number_input("Duración del código (minutos)", min_value=5, max_value=30, value=duracion_actual)
                with c2:
                    intentos = st.number_input("Máximo de intentos", min_value=3, max_value=10, value=intentos_actual)
                guardar_seg = st.form_submit_button("Guardar configuración", type="primary", use_container_width=True)
            if guardar_seg:
                usuario_actual = st.session_state.usuario.get("username", "Admin")
                set_config_seguridad("validacion_comensal", modo, "SOLO_RUT o RUT_MAS_CODIGO", usuario_actual)
                set_config_seguridad("codigo_duracion_minutos", str(int(duracion)), "Vigencia del código temporal", usuario_actual)
                set_config_seguridad("codigo_max_intentos", str(int(intentos)), "Máximo de intentos por código", usuario_actual)
                st.success("Configuración de acceso actualizada.")

    else:
        st.markdown("### 🏢 Administración - Login PostgreSQL")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre FROM usuarios WHERE username=%s AND pwd=%s", params=(u,hash_pwd(p)), ttl=0)
                if not df.empty and df.iloc[0]['rol'] in ["Admin","Gerencia"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre']}
                    st.session_state.main_view="🏢 ADMINISTRACIÓN"
                    st.rerun()
                else: st.error("Solo admin/gerencia - prueba admin/admin123")

st.divider()
st.caption("© 2026 ALEMSI · Sistema de Alimentación Mamuil Malal")
