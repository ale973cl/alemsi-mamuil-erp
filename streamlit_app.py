
import streamlit as st
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, PRECIO_DIA_DEFAULT
import pandas as pd
from datetime import date, timedelta, datetime

st.set_page_config(page_title="Mamuil Malal ERP", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

try: apply_alemsi_style()
except: pass

try: init_db()
except:
    import os
    try:
        if os.path.exists("/tmp/casino_erp.db"): os.remove("/tmp/casino_erp.db")
        if os.path.exists("casino_erp.db"): os.remove("casino_erp.db")
    except: pass
    init_db()

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}
if "paso" not in st.session_state: st.session_state.paso=1

st.markdown("""
<div class="main-header">
<h1>🍽️ Mamuil Malal ERP - ALEMSI</h1>
<p>Todo en un mismo artefacto - Comensales + Instituciones + Precios ocultos + Responsive + Regla 1 opción</p>
</div>
""", unsafe_allow_html=True)

# Header sesión
if st.session_state.usuario or st.session_state.rut_actual:
    col1,col2 = st.columns([4,1])
    with col1:
        if st.session_state.rut_actual:
            st.success(f"Comensal: {st.session_state.rut_actual}")
        if st.session_state.usuario:
            st.success(f"{st.session_state.usuario['nombre']} - {st.session_state.usuario['rol']}")
    with col2:
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state.usuario=None; st.session_state.rut_actual=None; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.session_state.paso=1; st.rerun()

# TABS PRINCIPALES - 3 PERFILES
t_comensal, t_casino, t_admin = st.tabs(["🧑 SOY COMENSAL","👨‍🍳 PERSONAL DE CASINO","🏢 ADMINISTRACIÓN"])

# ========= COMENSAL - TODO DENTRO MISMO ARTEFACTO =========
with t_comensal:
    if st.session_state.rut_actual:
        rut=st.session_state.rut_actual
        conn=get_conn(); com=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia = get_precio_institucion(institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | Precio día: {formato_clp(precio_dia)} (regla oculta aplicada)</p></div>', unsafe_allow_html=True)

        # SUB-TABS COMENSAL
        tab_reserva, tab_reclamos = st.tabs(["📅 Reservar","💬 Reclamos / Sugerencias"])

        with tab_reserva:
            if not st.session_state.dias_sel:
                st.markdown("#### 📅 Paso 1: Selecciona días (Responsive)")
                st.caption("Calendario 7 días - En celular se apila automáticamente a 2 columnas")
                hoy=date.today(); lunes=hoy - timedelta(days=hoy.weekday())
                dias=[lunes+timedelta(days=i) for i in range(7)]
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
                    st.info(f"{len(st.session_state.dias_sel)} día(s) - Total estimado {formato_clp(len(st.session_state.dias_sel)*precio_dia)}")
                    if st.button("Siguiente → Menú por día", type="primary", use_container_width=True):
                        st.session_state.dias_sel=sorted(st.session_state.dias_sel)
                        st.session_state.pedidos={d:{} for d in st.session_state.dias_sel}
                        st.session_state.wizard_idx=0; st.rerun()
            else:
                dias=sorted(st.session_state.dias_sel); idx=st.session_state.wizard_idx
                if idx>=len(dias):
                    # VALIDACIÓN FINAL
                    dias_sin = [f for f in dias if not st.session_state.pedidos.get(f)]
                    if dias_sin:
                        st.error(f"❌ Faltan {len(dias_sin)} día(s) sin comida")
                        for f_iso in dias_sin:
                            dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(f_iso).weekday()]
                            st.warning(f"• {dnom} {date.fromisoformat(f_iso).strftime('%d/%m')} - Sin selección")
                        if st.button("← Volver a completar", type="primary", use_container_width=True):
                            st.session_state.wizard_idx=0; st.rerun()
                        st.stop()
                    total=0; detalle=[]
                    for f_iso in dias:
                        dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(f_iso).weekday()]
                        for serv,plato in st.session_state.pedidos.get(f_iso,{}).items():
                            pr=get_precio(plato,serv); total+=pr; detalle.append((f_iso,dnom,serv,plato,pr))
                    df=pd.DataFrame(detalle, columns=["Fecha","Día","Servicio","Plato","Precio"])
                    # Total real con precio institución
                    total_real = len(dias)*precio_dia
                    st.markdown(f"### ✅ Resumen - {institucion} - {formato_clp(precio_dia)}/día")
                    st.dataframe(df, use_container_width=True)
                    st.metric("Total a pagar (con regla institución)", formato_clp(total_real), f"{len(dias)} días x {formato_clp(precio_dia)}")
                    if st.button("✅ FINALIZAR RESERVA - Ticket + Cocina + Finanzas", type="primary", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor(); vouchers=[]
                        for f_iso,dnom,serv,plato,pr in detalle:
                            cod=gen_codigo(rut,serv,date.fromisoformat(f_iso))
                            cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago,fecha_creacion,institucion,precio_aplicado) VALUES (?,?,?,?,?,?,?,?,?,?)",(rut,f_iso,serv,plato,cod,pr,"Pendiente", datetime.now().isoformat(), institucion, precio_dia))
                            vouchers.append(cod)
                            descontar_bodega(plato)
                        # También insertar días sin detalle pero con precio día
                        for f_iso in dias:
                            if f_iso not in [d[0] for d in detalle]:
                                # Día con al menos 1 opción ya validado, pero si no tiene servicio específico, crear registro día completo
                                cod=gen_codigo(rut,"DIA",date.fromisoformat(f_iso))
                                plato_txt=" | ".join([f"{k}:{v}" for k,v in st.session_state.pedidos.get(f_iso,{}).items()])
                                cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago,fecha_creacion,institucion,precio_aplicado) VALUES (?,?,?,?,?,?,?,?,?,?)",(rut,f_iso,"DIA_COMPLETO",plato_txt,precio_dia,"Pendiente", datetime.now().isoformat(), institucion, precio_dia))
                        conn.commit(); conn.close()
                        html=f"<h3>Ticket {nombre} {rut} - {institucion} - {formato_clp(total_real)}</h3>{df.to_html()}<p>Códigos: {', '.join(vouchers)}</p>"
                        conn=get_conn(); dfc=pd.read_sql_query("SELECT correo FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
                        correo_cli=dfc.iloc[0]['correo'] if not dfc.empty else None
                        if correo_cli: enviar_email(correo_cli,"Ticket Mamuil",html)
                        enviar_email(EMAILS['cocina'],f"Orden cocina {nombre} - {institucion}",html)
                        enviar_email(EMAILS['finanzas'],f"Reserva {formato_clp(total_real)} {nombre} - {institucion} (precio oculto {formato_clp(precio_dia)})",html)
                        st.success(f"Reserva OK - {institucion} - {formato_clp(total_real)} - Códigos: {', '.join(vouchers[:3])}...")
                        st.balloons()
                        st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0
                else:
                    f_act=dias[idx]; d_obj=date.fromisoformat(f_act)
                    dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][d_obj.weekday()]
                    st.markdown(f"### {dnom} {d_obj.strftime('%d/%m')} ({idx+1}/{len(dias)}) | {formato_clp(precio_dia)}")
                    if f_act not in st.session_state.pedidos: st.session_state.pedidos[f_act]={}
                    pedidos_actuales = st.session_state.pedidos.get(f_act, {})
                    tiene_uno = len(pedidos_actuales) > 0
                    st.progress((idx)/len(dias))
                    if tiene_uno: st.success(f"✅ {', '.join([f'{k}: {v}' for k,v in pedidos_actuales.items()])}")
                    else: st.warning(f"⚠️ Debes seleccionar al menos 1 opción para el {dnom} para avanzar")
                    for serv in ["Desayuno","Almuerzo","Once","Cena"]:
                        ops=MINUTA.get(dnom,{}).get(serv,[])
                        if not ops: continue
                        st.markdown(f'<div class="al-card"><h4>{serv}</h4>', unsafe_allow_html=True)
                        cols=st.columns(2)
                        for i,plato in enumerate(ops):
                            sel=st.session_state.pedidos[f_act].get(serv)==plato
                            with cols[i%2]:
                                if st.button(f"{plato} {formato_clp(get_precio(plato,serv))}", key=f"{f_act}_{serv}_{plato}", type="primary" if sel else "secondary", use_container_width=True):
                                    if sel: del st.session_state.pedidos[f_act][serv]
                                    else: st.session_state.pedidos[f_act][serv]=plato
                                    st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)
                    c1,c2=st.columns(2)
                    with c1:
                        if st.button("← Anterior", disabled=idx==0, use_container_width=True):
                            st.session_state.wizard_idx-=1; st.rerun()
                    with c2:
                        if idx < len(dias)-1:
                            if st.button("Siguiente →", type="primary", use_container_width=True, disabled=not tiene_uno):
                                st.session_state.wizard_idx+=1; st.rerun()
                            if not tiene_uno: st.caption("🔒 Elige 1 comida")
                        else:
                            if st.button("Ver resumen", type="primary", use_container_width=True, disabled=not tiene_uno):
                                st.session_state.wizard_idx+=1; st.rerun()
                            if not tiene_uno: st.caption("🔒 Elige 1 comida")

        with tab_reclamos:
            st.markdown(f"### 💬 Reclamos - {nombre} - {institucion}")
            with st.form("reclamo_comensal"):
                tipo=st.selectbox("Tipo", ["Reclamo","Sugerencia","Felicitación","Consulta"])
                categoria=st.selectbox("Categoría", ["Comida / Sabor","Atención / Servicio","Higiene / Limpieza","Infraestructura","Tiempo de espera","Otro"])
                mensaje=st.text_area("Mensaje*")
                if st.form_submit_button("Enviar reclamo", type="primary", use_container_width=True):
                    if mensaje:
                        conn=get_conn(); cur=conn.cursor()
                        cur.execute("INSERT INTO reclamos_sugerencias (rut,nombre,tipo,categoria,mensaje,fecha,estado) VALUES (?,?,?,?,?,?,?)",(rut,nombre,tipo,categoria,mensaje, datetime.now().isoformat(),"Pendiente"))
                        conn.commit(); conn.close()
                        enviar_email(EMAILS["reclamos"], f"{tipo} - {nombre} - {institucion}", f"<p>{mensaje}</p><p>Institución: {institucion}</p>")
                        st.success("Enviado ✅")
            conn=get_conn(); df=pd.read_sql_query("SELECT fecha,tipo,categoria,mensaje,estado FROM reclamos_sugerencias WHERE rut=? ORDER BY fecha DESC",conn,params=(rut,)); conn.close()
            st.dataframe(df, use_container_width=True)

    else:
        st.markdown("### Reserva - Solo RUT chileno - Todos los formatos")
        st.caption("Formatos válidos: 12.345.678-9, 12345678-9, 12.345.678-K, 12345678-K, 7.123.456-8 | Con puntos y guión obligatorio")
        rut_raw=st.text_input("RUT", placeholder="16.632.880-2", key="rut_comensal")
        if rut_raw:
            if not validar_rut_m11(rut_raw):
                st.error(f"❌ RUT inválido - {rut_raw} - Formatos válidos: 12.345.678-9, 12345678-9, con K")
            else:
                rn=normalizar_rut_db(rut_raw)
                rv=normalizar_rut(rut_raw)
                conn=get_conn(); df=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rn,)); conn.close()
                if not df.empty:
                    inst_prev = df.iloc[0]['institucion'] if 'institucion' in df.columns else "Visitas"
                    st.success(f"Hola {df.iloc[0]['nombre']} - {rv} - {inst_prev}")
                    if st.button("Entrar a reservar →", type="primary", use_container_width=True):
                        st.session_state.rut_actual=rn; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
                else:
                    st.info(f"Primera vez - {rv} se guardará")
                    instit_list = get_instituciones()
                    with st.form("reg_comensal"):
                        c1,c2=st.columns(2)
                        with c1:
                            nombre=st.text_input("Nombre completo*")
                            tel=st.text_input("Teléfono*")
                        with c2:
                            correo=st.text_input("Correo* para ticket")
                            institucion=st.selectbox("Seleccione su institución*", instit_list)
                        if st.form_submit_button("Registrarme y continuar", type="primary", use_container_width=True):
                            if nombre and tel and correo and institucion:
                                conn=get_conn(); cur=conn.cursor()
                                cur.execute("INSERT OR REPLACE INTO comensales (rut,nombre,telefono,correo,institucion,fecha_registro) VALUES (?,?,?,?,?,?)",(rn,nombre,tel,correo,institucion, datetime.now().isoformat()))
                                conn.commit(); conn.close()
                                st.session_state.rut_actual=rn; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
                            else: st.error("Falta datos")

# ========= PERSONAL DE CASINO =========
with t_casino:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Cocina","Bodega","Finanzas","Admin"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>👨‍🍳 {rol} - Módulos operativos</h3><p>Responsive - Botones se ajustan a celular/tablet/PC</p></div>', unsafe_allow_html=True)
        tabs_casino = st.tabs(["Cocina","Bodega","Finanzas"])
        with tabs_casino[0]:
            st.markdown("#### 👨‍🍳 Cocina - Órdenes del día")
            conn=get_conn(); df=pd.read_sql_query("SELECT s.id, s.fecha, c.nombre, c.institucion, s.plato, s.codigo, s.estado_consumo FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.fecha >= date('now','-7 days') ORDER BY s.fecha DESC", conn); conn.close()
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                id_sel=st.selectbox("ID a cambiar", df['id'].tolist())
                nuevo=st.selectbox("Nuevo estado consumo", ["Pendiente","En Proceso","Completado","Entregado"])
                if st.button("Actualizar estado cocina", type="primary"):
                    conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE solicitudes SET estado_consumo=? WHERE id=?",(nuevo,id_sel)); conn.commit(); conn.close(); st.success("Actualizado"); st.rerun()
        with tabs_casino[1]:
            st.markdown("#### 📦 Bodega - Inventario")
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM bodega_inventario ORDER BY stock ASC", conn); conn.close()
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                st.metric("Bajo stock crítico", len(df[df['stock']<df['critico']]))
        with tabs_casino[2]:
            st.markdown("#### 💰 Finanzas - Pagos por institución")
            conn=get_conn(); df=pd.read_sql_query("SELECT s.fecha, c.nombre, c.institucion, s.precio_aplicado, s.estado_pago, s.codigo FROM solicitudes s JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 100", conn); conn.close()
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                st.metric("Pendiente total", formato_clp(df[df['estado_pago']=='Pendiente']['precio_aplicado'].sum()))
                df_inst = df.groupby('institucion')['precio_aplicado'].sum().reset_index()
                st.markdown("##### Total por institución (precio oculto aplicado)")
                st.dataframe(df_inst, use_container_width=True)
                cod_sel=st.selectbox("Código para marcar pagado", df['codigo'].tolist())
                if st.button("Marcar como Pagado", type="primary"):
                    conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE solicitudes SET estado_pago='Pagado' WHERE codigo=?",(cod_sel,)); conn.commit(); conn.close(); st.success("Pagado"); st.rerun()
    else:
        st.markdown("### 👨‍🍳 Personal de Casino - Login")
        st.caption("Usuarios: cocina/cocina123 | bodega/bodega123 | finanzas/finanzas123")
        with st.form("login_casino"):
            u=st.text_input("Usuario", key="u_casino")
            p=st.text_input("Contraseña", type="password", key="p_casino")
            if st.form_submit_button("Ingresar a Casino", type="primary", use_container_width=True):
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p))); row=cur.fetchone(); conn.close()
                if row and row[1] in ["Cocina","Bodega","Finanzas","Admin"]:
                    st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}; st.rerun()
                else: st.error("Usuario no válido para casino")

# ========= ADMINISTRACIÓN =========
with t_admin:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Admin","Gerencia"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>🏢 {rol} - Administración completa</h3><p>Gerencia + Admin Instituciones + Reclamos + Precios ocultos</p></div>', unsafe_allow_html=True)
        tab_g, tab_inst, tab_recl = st.tabs(["📊 Gerencia","🏢 Instituciones","💬 Reclamos Admin"])

        with tab_g:
            conn=get_conn()
            df_sol=pd.read_sql_query("SELECT institucion, COUNT(*) as total, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY institucion",conn)
            df_com=pd.read_sql_query("SELECT institucion, COUNT(*) as comensales FROM comensales GROUP BY institucion",conn)
            df_pend=pd.read_sql_query("SELECT COUNT(*) as pendientes, SUM(precio_aplicado) as monto_pend FROM solicitudes WHERE estado_pago='Pendiente'",conn)
            conn.close()
            c1,c2,c3=st.columns(3)
            with c1: st.metric("Reservas totales", df_sol['total'].sum() if not df_sol.empty else 0)
            with c2: st.metric("Monto total", formato_clp(df_sol['monto'].sum() if not df_sol.empty else 0))
            with c3: st.metric("Pendiente por cobrar", formato_clp(df_pend.iloc[0]['monto_pend'] if not df_pend.empty and df_pend.iloc[0]['monto_pend'] else 0))
            st.markdown("##### Ventas por institución (con regla oculta)")
            st.dataframe(df_sol, use_container_width=True)
            st.markdown("##### Comensales por institución")
            st.dataframe(df_com, use_container_width=True)

        with tab_inst:
            st.markdown("#### 🏢 Admin Instituciones - Reglas ocultas solo admin")
            st.caption("Solo admin ve precio especial. Comensal solo ve total final.")
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM instituciones ORDER BY nombre", conn); conn.close()
            st.dataframe(df, use_container_width=True)
            t1,t2,t3=st.tabs(["➕ Agregar/Editar","🔄 Activar/Desactivar","💰 Regla Oculta"])
            with t1:
                with st.form("add_inst"):
                    nombre=st.text_input("Nombre institución*")
                    precio=st.number_input("Precio día público", value=6400, step=100)
                    desc=st.text_input("Descripción interna")
                    if st.form_submit_button("Guardar institución", type="primary", use_container_width=True):
                        if nombre:
                            conn=get_conn(); cur=conn.cursor(); cur.execute("INSERT OR REPLACE INTO instituciones (nombre,precio_dia,activa,descripcion) VALUES (?,?,1,?)",(nombre,precio,desc)); conn.commit(); conn.close(); st.success("Guardada"); st.rerun()
            with t2:
                if not df.empty:
                    inst_sel=st.selectbox("Institución", df['nombre'].tolist(), key="act_inst")
                    c1,c2=st.columns(2)
                    with c1:
                        if st.button("Desactivar (ocultar)", use_container_width=True):
                            conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE instituciones SET activa=0 WHERE nombre=?",(inst_sel,)); conn.commit(); conn.close(); st.rerun()
                    with c2:
                        if st.button("Activar", use_container_width=True):
                            conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE instituciones SET activa=1 WHERE nombre=?",(inst_sel,)); conn.commit(); conn.close(); st.rerun()
            with t3:
                st.markdown("##### 🔒 Regla de valor diferente oculta")
                st.caption("Ej: Carabineros público $6.400 pero paga $3.200 - Solo admin activa, comensal solo ve total")
                if not df.empty:
                    inst_rule=st.selectbox("Institución para regla", df['nombre'].tolist(), key="rule_inst")
                    conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT precio_dia, precio_especial, regla_activa, descripcion FROM instituciones WHERE nombre=?",(inst_rule,)); r=cur.fetchone(); conn.close()
                    precio_actual = r[0] if r else 6400
                    precio_esp = r[1] if r and r[1] else 3200
                    activa = bool(r[2]) if r else False
                    st.info(f"Público: {formato_clp(precio_actual)} | Especial oculto: {formato_clp(precio_esp) if precio_esp else 'No definido'} | Activa: {activa}")
                    with st.form("rule_form"):
                        nuevo_esp=st.number_input("Precio especial oculto (lo que realmente paga)", value=int(precio_esp or 3200), step=100)
                        activar=st.checkbox("Activar regla oculta", value=activa)
                        desc_rule=st.text_input("Motivo interno", value=r[3] if r and r[3] else "")
                        if st.form_submit_button("Guardar regla oculta", type="primary", use_container_width=True):
                            conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE instituciones SET precio_especial=?, regla_activa=?, descripcion=? WHERE nombre=?",(nuevo_esp, 1 if activar else 0, desc_rule, inst_rule)); conn.commit(); conn.close(); st.success(f"Regla {inst_rule}: {'ACTIVA '+formato_clp(nuevo_esp) if activar else 'Desactivada'}"); st.rerun()

        with tab_recl:
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM reclamos_sugerencias ORDER BY fecha DESC",conn); conn.close()
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                id_r=st.selectbox("ID reclamo", df['id'].tolist())
                respuesta=st.text_area("Respuesta")
                estado=st.selectbox("Estado", ["Pendiente","En Revisión","Resuelto","Respondido"])
                if st.button("Responder reclamo", type="primary"):
                    conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE reclamos_sugerencias SET respuesta=?, estado=? WHERE id=?",(respuesta,estado,id_r)); conn.commit(); conn.close(); st.success("Actualizado"); st.rerun()
    else:
        st.markdown("### 🏢 Administración - Login")
        st.caption("Usuarios: admin/admin123 | gerencia/gerencia123")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin")
            p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar a Administración", type="primary", use_container_width=True):
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p))); row=cur.fetchone(); conn.close()
                if row and row[1] in ["Admin","Gerencia"]:
                    st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}; st.rerun()
                else: st.error("Solo admin/gerencia")

st.divider()
st.caption("📱 Responsive: Celular=botones grandes 52px y columnas apiladas | Tablet=2 columnas | PC=4 columnas | Todo en un mismo artefacto, sin repos separados | Regla 1 opción mínima por día | Precios ocultos por institución")
