import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import random
import calendar
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT

st.set_page_config(page_title="Mamuil Malal ERP V20 - PostgreSQL", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

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

st.markdown('''
<div class="main-header">
<h1>🍽️ Mamuil Malal ERP V20 - PostgreSQL + Gmail</h1>
<p>✅ PostgreSQL Supabase + st.connection + Gmail automático + Reportes financieros avanzados</p>
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
            st.session_state.usuario=None; st.session_state.rut_actual=None; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()

t_comensal, t_casino, t_admin = st.tabs(["🧑 SOY COMENSAL","👨‍🍳 PERSONAL DE CASINO","🏢 ADMINISTRACIÓN"])

# ===== COMENSAL - POSTGRESQL + CORREO AUTOMÁTICO =====
with t_comensal:
    if st.session_state.rut_actual:
        rut=st.session_state.rut_actual
        conn=get_conn()
        com=conn.query("SELECT * FROM comensales WHERE rut=%s", params=(rut,), ttl=0)
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        tab_reserva, tab_reclamos = st.tabs(["📅 Reservar","💬 Reclamos"])

        with tab_reserva:
            if not st.session_state.dias_sel:
                st.markdown("#### 📅 Paso 1: Selecciona días - Mes en curso (30/31 días)")
                hoy=date.today()
                ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
                primer_dia_mes = date(hoy.year, hoy.month, 1)
                dias=[primer_dia_mes+timedelta(days=i) for i in range(ultimo_dia)]
                st.caption(f"Mostrando {ultimo_dia} días de {hoy.strftime('%B %Y')} - Precio día {formato_clp(precio_dia)}")
                cols=st.columns(4)
                for i,d in enumerate(dias):
                    lab=f"{['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'][d.weekday()]} {d.strftime('%d/%m')}"
                    with cols[i%4]:
                        sel=d.isoformat() in st.session_state.dias_sel
                        if st.button(lab, key=f"d_{d}", use_container_width=True, type="primary" if sel else "secondary"):
                            if sel: st.session_state.dias_sel.remove(d.isoformat())
                            else: st.session_state.dias_sel.append(d.isoformat())
                            st.rerun()
                if st.session_state.dias_sel:
                    st.info(f"{len(st.session_state.dias_sel)} día(s) - Total {formato_clp(len(st.session_state.dias_sel)*precio_dia)}")
                    if st.button("Siguiente → Menú por día de semana", type="primary", use_container_width=True):
                        st.session_state.dias_sel=sorted(st.session_state.dias_sel)
                        st.session_state.pedidos={d:{} for d in st.session_state.dias_sel}
                        st.session_state.wizard_idx=0; st.rerun()
            else:
                dias=sorted(st.session_state.dias_sel); idx=st.session_state.wizard_idx
                if idx<len(dias):
                    f_iso=dias[idx]; f_obj=date.fromisoformat(f_iso)
                    dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                    st.markdown(f"#### Día {idx+1}/{len(dias)}: {dnom} {f_obj.strftime('%d/%m/%Y')} - Minuta del {dnom}")
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

                    tiene_uno=False
                    for serv, platos in minuta_dia.items():
                        st.markdown(f"**{serv}**")
                        sel_actual = st.session_state.pedidos.get(f_iso,{}).get(serv)
                        cols=st.columns(2)
                        for j, plato in enumerate(platos):
                            with cols[j%2]:
                                is_sel = sel_actual==plato
                                if st.button(f"{plato} - {formato_clp(get_precio(plato,serv))}", key=f"{f_iso}_{serv}_{plato}", use_container_width=True, type="primary" if is_sel else "secondary"):
                                    st.session_state.pedidos[f_iso][serv]=plato
                                    st.rerun()
                        if st.session_state.pedidos.get(f_iso,{}).get(serv): tiene_uno=True
                    st.divider()
                    c1,c2=st.columns(2)
                    with c1:
                        if st.button("← Anterior día", use_container_width=True, disabled=idx==0):
                            st.session_state.wizard_idx-=1; st.rerun()
                    with c2:
                        if st.button("Siguiente día →", type="primary", use_container_width=True, disabled=not tiene_uno):
                            st.session_state.wizard_idx+=1; st.rerun()
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
                                    <b>Minuta:</b> Cada día se asignó según el día de la semana ({", ".join([f"{d} {date.fromisoformat(f).strftime('%d/%m')}" for f in dias])})<br>
                                    <b>Plato reservado:</b> Almacenado nativamente en columna <code>plato_reservado</code><br>
                                    <b>Método pago:</b> Almacenado en columna <code>metodo_pago</code><br>
                                    <b>Estado pago:</b> <code>Pendiente</code> por defecto - Finanzas validará
                                </p>
                                <p style="font-size:12px; color:#666;">Este comprobante se genera automáticamente vía Gmail SMTP (st.secrets [email]). Demo con correo personal antes de corporativo.</p>
                            </div>
                            <div style="text-align:center; padding-top:12px; border-top:1px solid #E9ECEF; font-size:12px; color:#999;">
                                Mamuil Malal ERP - ALEMSI - PostgreSQL + Gmail
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

        with tab_reclamos:
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
with t_casino:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Cocina","Bodega","Finanzas","Admin"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>{rol} - Módulos PostgreSQL</h3></div>', unsafe_allow_html=True)
        tabs_casino = st.tabs(["👨‍🍳 Cocina","📦 Bodega","💰 Finanzas"])
        with tabs_casino[0]:
            st.markdown("#### 👨‍🍳 Cocina - Platos Solicitados por Día (PostgreSQL)")
            conn=get_conn()
            df=conn.query("SELECT fecha, plato_reservado, COUNT(*) as cantidad, servicio FROM solicitudes WHERE fecha >= %s GROUP BY fecha, plato_reservado, servicio ORDER BY fecha", params=(date.today().isoformat(),), ttl=0)
            st.dataframe(df, use_container_width=True)
            st.metric("Total órdenes hoy+", len(df))
        with tabs_casino[1]:
            st.markdown("#### 📦 Bodega PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM bodega_inventario ORDER BY nombre_articulo LIMIT 100", ttl=0)
            st.dataframe(df, use_container_width=True)
        with tabs_casino[2]:
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
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre']}; st.rerun()
                else: st.error("No válido - prueba admin/admin123")

# ===== ADMINISTRACIÓN - REPORTES AVANZADOS POSTGRESQL =====
with t_admin:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Admin","Gerencia"]:
        st.markdown(f'<div class="al-card"><h3>🏢 Administración - Reportes PostgreSQL Avanzados</h3><p>V20 - Tres consultas SQL directas para gestión</p></div>', unsafe_allow_html=True)
        tab_reportes, tab_g, tab_prod, tab_minuta, tab_exc, tab_inst = st.tabs(["📊 REPORTES FINANCIEROS Y COCINA (NUEVO)","📈 Gerencia","📦 Productos","🍽️ Minutas","⚖️ Excepciones","🏢 Instituciones"])

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

        with tab_g:
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
                            s.execute("INSERT INTO minutas (dia_semana,servicio,plato,activo) VALUES (%s,%s,%s,1)", (dia,serv,plato))
                            s.execute("INSERT INTO platos (nombre,servicio,valor,activo) VALUES (%s,%s,%s,1) ON CONFLICT DO NOTHING", (plato,serv,6500))
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
                                s.execute("UPDATE instituciones SET precio_especial=%s, regla_activa=1, descripcion=%s WHERE nombre=%s", (precio_especial_global, motivo_global, nombre))
                            else:
                                s.execute("UPDATE instituciones SET regla_activa=0 WHERE nombre=%s", (nombre,))
                        s.commit()
                    st.success("Reglas actualizadas"); st.rerun()

        with tab_inst:
            st.markdown("#### 🏢 Instituciones PostgreSQL")
            conn=get_conn()
            df=conn.query("SELECT * FROM instituciones ORDER BY nombre", ttl=0)
            st.dataframe(df, use_container_width=True)

    else:
        st.markdown("### 🏢 Administración - Login PostgreSQL")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre FROM usuarios WHERE username=%s AND pwd=%s", params=(u,hash_pwd(p)), ttl=0)
                if not df.empty and df.iloc[0]['rol'] in ["Admin","Gerencia"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre']}; st.rerun()
                else: st.error("Solo admin/gerencia - prueba admin/admin123")

st.divider()
st.caption("V20 PostgreSQL - common.py con %s + solicitudes(plato_reservado, metodo_pago, estado_pago DEFAULT Pendiente) + app.py con minuta por día + comprobante HTML inmediato + Reportes 3 SELECT directos")
