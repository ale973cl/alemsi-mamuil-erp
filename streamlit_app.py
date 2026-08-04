import streamlit as st
from common import (
    init_db, get_conn, hash_pwd, normalizar_rut, validar_rut_m11, apply_alemsi_style,
    MINUTA, PRECIO_DIA_FIJO, formato_clp, gen_codigo, descontar_bodega, enviar_email, EMAILS,
    SERVICIOS, DIAS_SEMANA, get_precio,
    listar_platos, agregar_plato, actualizar_plato, eliminar_plato, sincronizar_platos_faltantes,
    get_minuta_dia, listar_minuta_dia, asignar_plato_minuta, quitar_plato_minuta,
    listar_dias_cerrados, dia_cerrado, cerrar_dia, reabrir_dia,
    reporte_por_plato, produccion_dia,
)
import pandas as pd
from datetime import date, timedelta, datetime

st.set_page_config(page_title="Mamuil Malal ERP", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")
apply_alemsi_style()
init_db()
st.markdown("<style>[data-testid='stSidebarNav']{display:none !important;} [data-testid='stSidebar']{display:none !important;} [data-testid='collapsedControl']{display:none !important;}</style>", unsafe_allow_html=True)

if "menu" not in st.session_state: st.session_state.menu = "Login"
if "usuario" not in st.session_state: st.session_state.usuario = None
if "rut_actual" not in st.session_state: st.session_state.rut_actual = None
if "dias_sel" not in st.session_state: st.session_state.dias_sel = []
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx = 0
if "pedidos" not in st.session_state: st.session_state.pedidos = {}
if "paso" not in st.session_state: st.session_state.paso = 1
if "show_menu" not in st.session_state: st.session_state.show_menu = False

col_logo, col_btn = st.columns([8, 1])
with col_logo:
    st.markdown('<div style="background: linear-gradient(135deg,#0A2F6B 0%, #123E7A 100%); padding:14px 22px; border-radius:12px; color:white; font-family:Sora"><h3 style="margin:0; color:white">🍽️ Mamuil Malal ERP | ALEMSI</h3><small style="color:#C9D6EA">Aseo y Servicios Integrales - @alemsichile | $6.400 día completo</small></div>', unsafe_allow_html=True)
with col_btn:
    if st.button("☰", key="hamburger", use_container_width=True):
        st.session_state.show_menu = not st.session_state.show_menu

if st.session_state.show_menu:
    st.markdown("#### Navegación")
    opciones = ["Login"]
    if st.session_state.rut_actual:
        opciones.extend(["Comensal - Reservar", "Reclamos / Sugerencias"])
    if st.session_state.usuario:
        rol = st.session_state.usuario["rol"]
        if rol in ["Cocina", "Admin"]: opciones.extend(["Cocina", "Reportes"])
        if rol in ["Bodega", "Admin"]: opciones.append("Bodega")
        if rol in ["Finanzas", "Admin"]: opciones.extend(["Finanzas", "Reportes"])
        if rol in ["Gerencia", "Admin"]: opciones.extend(["Gerencia", "Reclamos Admin", "Reportes", "Platos y Minuta"])
        opciones.append("Cerrar sesión")
    opciones = list(dict.fromkeys(opciones))
    for op in opciones:
        if st.button(op, key=f"nav_{op}", use_container_width=True):
            if op == "Cerrar sesión":
                st.session_state.usuario = None; st.session_state.rut_actual = None; st.session_state.menu = "Login"; st.session_state.paso = 1; st.session_state.dias_sel = []; st.session_state.show_menu = False; st.rerun()
            else:
                st.session_state.menu = op; st.session_state.show_menu = False; st.rerun()
    st.divider()

# ========= LOGIN =========
if st.session_state.menu == "Login":
    if st.session_state.rut_actual:
        st.session_state.menu = "Comensal - Reservar"
        st.rerun()
    st.markdown('<div class="main-header"><h1>Hola, bienvenido a selección de menú</h1><p>Solo ingresa tu RUT para reservar</p></div>', unsafe_allow_html=True)
    t1, t2 = st.tabs(["🧑 SOY COMENSAL", "🔐 PERSONAL CASINO"])
    with t1:
        rut_raw = st.text_input("RUT", placeholder="16.632.880-2", key="rut_input")
        if rut_raw:
            if not validar_rut_m11(rut_raw):
                st.error("RUT no válido")
            else:
                rn = normalizar_rut(rut_raw)
                conn = get_conn(); df = pd.read_sql_query("SELECT * FROM comensales WHERE rut=?", conn, params=(rn,)); conn.close()
                if not df.empty:
                    st.success(f"Hola {df.iloc[0]['nombre']} 👋 - {len(df)} reservas previas guardadas")
                    if st.button("Continuar → Reservar menú", type="primary", use_container_width=True):
                        st.session_state.rut_actual = rn
                        st.session_state.paso = 1
                        st.session_state.dias_sel = []
                        st.session_state.menu = "Comensal - Reservar"
                        st.rerun()
                else:
                    st.info("Primera vez, regístrate - tus datos se guardarán")
                    with st.form("reg"):
                        nombre = st.text_input("Nombre completo*")
                        tel = st.text_input("Teléfono*")
                        correo = st.text_input("Correo*")
                        if st.form_submit_button("Registrarme y reservar 🍽️", type="primary", use_container_width=True):
                            if nombre and tel and correo:
                                conn = get_conn(); cur = conn.cursor()
                                cur.execute("INSERT OR REPLACE INTO comensales VALUES (?,?,?,?,?,?)", (rn, nombre, tel, correo, "Mamuil", datetime.now().isoformat()))
                                conn.commit(); conn.close()
                                st.success("Datos guardados ✅")
                                st.session_state.rut_actual = rn
                                st.session_state.paso = 1
                                st.session_state.dias_sel = []
                                st.session_state.menu = "Comensal - Reservar"
                                st.rerun()
                            else: st.error("Completa todos")
    with t2:
        with st.form("login_staff"):
            u = st.text_input("Usuario"); p = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar", type="primary"):
                conn = get_conn(); cur = conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?", (u, hash_pwd(p))); row = cur.fetchone(); conn.close()
                if row:
                    st.session_state.usuario = {"username": row[0], "rol": row[1], "nombre": row[2]}
                    if row[1] == "Cocina": st.session_state.menu = "Cocina"
                    elif row[1] == "Bodega": st.session_state.menu = "Bodega"
                    elif row[1] == "Finanzas": st.session_state.menu = "Finanzas"
                    elif row[1] == "Gerencia": st.session_state.menu = "Gerencia"
                    else: st.session_state.menu = "Comensal - Reservar"
                    st.rerun()
                else: st.error("Credenciales inválidas")

# ========= COMENSAL - RESERVA CON SELECCION MULTIPLE =========
elif st.session_state.menu == "Comensal - Reservar":
    if not st.session_state.rut_actual:
        st.session_state.menu = "Login"; st.rerun()
    conn = get_conn(); com = pd.read_sql_query("SELECT * FROM comensales WHERE rut=?", conn, params=(st.session_state.rut_actual,)); conn.close()
    nombre = com.iloc[0]['nombre'] if not com.empty else "Comensal"

    if st.session_state.paso == 1:
        st.markdown(f'<div class="main-header"><h1>Hola {nombre} 👋 bienvenido a selección de menú</h1><p>Calendario selección múltiple - Toca varios días - $6.400 por día</p></div>', unsafe_allow_html=True)

        conn = get_conn(); hist = pd.read_sql_query("SELECT fecha,plato,codigo,estado_pago FROM solicitudes WHERE rut=? ORDER BY fecha DESC LIMIT 5", conn, params=(st.session_state.rut_actual,)); conn.close()
        if not hist.empty:
            with st.expander(f"📚 Tus últimas {len(hist)} reservas guardadas"):
                st.dataframe(hist, use_container_width=True)

        col1, col2 = st.columns([1.7, 1])
        hoy = date.today()
        dias_cerrados = listar_dias_cerrados()

        with col1:
            st.markdown("### 📅 Paso 1: Selección múltiple de días (45 días)")
            st.caption("Toca los días que quieras. Los días con 🔒 ya fueron cerrados por Cocina y no se pueden reservar.")
            dias_futuros = [hoy + timedelta(days=i) for i in range(45)]
            headers = st.columns(7)
            for i, h in enumerate(["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]): headers[i].markdown(f"**{h}**")
            for week_start in range(0, 45, 7):
                cols = st.columns(7)
                for j in range(7):
                    if week_start + j >= len(dias_futuros): continue
                    d = dias_futuros[week_start + j]
                    iso = d.isoformat()
                    es_sel = iso in st.session_state.dias_sel
                    es_cerrado = iso in dias_cerrados
                    label = f"{'🔒' if es_cerrado else ''}{d.day:02d}/{d.month:02d}"
                    with cols[j]:
                        if es_cerrado:
                            st.button(label, key=f"cal_{iso}", use_container_width=True, disabled=True)
                        else:
                            if st.button(label, key=f"cal_{iso}", use_container_width=True, type="primary" if es_sel else "secondary", help="Toca para seleccionar/deseleccionar"):
                                if es_sel: st.session_state.dias_sel.remove(iso)
                                else: st.session_state.dias_sel.append(iso)
                                st.session_state.dias_sel = sorted(set(st.session_state.dias_sel))
                                st.rerun()
            st.divider()
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Lun-Vie esta semana", use_container_width=True):
                    lunes = hoy - timedelta(days=hoy.weekday())
                    for i in range(5):
                        iso = (lunes + timedelta(days=i)).isoformat()
                        if date.fromisoformat(iso) >= hoy and iso not in st.session_state.dias_sel and iso not in dias_cerrados:
                            st.session_state.dias_sel.append(iso)
                    st.session_state.dias_sel = sorted(set(st.session_state.dias_sel)); st.rerun()
            with c2:
                if st.button("Próx. 5 hábiles", use_container_width=True):
                    added = 0; d = hoy
                    while added < 5:
                        iso_d = d.isoformat()
                        if d.weekday() < 5 and iso_d not in st.session_state.dias_sel and iso_d not in dias_cerrados:
                            st.session_state.dias_sel.append(iso_d); added += 1
                        d += timedelta(days=1)
                    st.session_state.dias_sel = sorted(set(st.session_state.dias_sel)); st.rerun()
            with c3:
                if st.button("Limpiar todo", use_container_width=True):
                    st.session_state.dias_sel = []; st.rerun()

        with col2:
            st.markdown(f'<div class="al-card"><h3>✅ Seleccionados: {len(st.session_state.dias_sel)} días</h3>', unsafe_allow_html=True)
            if st.session_state.dias_sel:
                for iso in sorted(st.session_state.dias_sel):
                    dobj = date.fromisoformat(iso)
                    dnom = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dobj.weekday()]
                    cc1, cc2 = st.columns([4, 1])
                    cc1.write(f"**{dnom} {dobj.strftime('%d/%m/%Y')}**")
                    if cc2.button("❌", key=f"del_{iso}"):
                        st.session_state.dias_sel.remove(iso); st.rerun()
                st.divider()
                st.metric("Total a pagar", formato_clp(len(st.session_state.dias_sel) * PRECIO_DIA_FIJO), f"{len(st.session_state.dias_sel)} días x $6.400")
            st.markdown("</div>", unsafe_allow_html=True)
            if st.session_state.dias_sel:
                if st.button("Siguiente → Elegir menú por día", type="primary", use_container_width=True):
                    st.session_state.pedidos = {d: {} for d in st.session_state.dias_sel}
                    st.session_state.wizard_idx = 0
                    st.session_state.paso = 2
                    st.rerun()
            else:
                st.info("👆 Toca varias fechas arriba.")

    elif st.session_state.paso == 2:
        dias = sorted(st.session_state.dias_sel)
        idx = st.session_state.wizard_idx
        if idx >= len(dias):
            st.markdown('<div class="main-header"><h1>Resumen de tu reserva</h1><p>Verifica y finaliza - se guardará y comunicará a cocina/bodega/finanzas</p></div>', unsafe_allow_html=True)
            df_resumen = []
            for f_iso in dias:
                dobj = date.fromisoformat(f_iso)
                dnom = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dobj.weekday()]
                platos_txt = " | ".join([f"{k}:{v}" for k, v in st.session_state.pedidos.get(f_iso, {}).items()]) or "Día completo"
                df_resumen.append((f_iso, f"{dnom} {dobj.strftime('%d/%m')}", platos_txt, PRECIO_DIA_FIJO))
            df = pd.DataFrame(df_resumen, columns=["Fecha ISO", "Día", "Menú elegido", "Precio"])
            st.dataframe(df[["Día", "Menú elegido", "Precio"]], use_container_width=True)
            st.markdown(f'<div class="al-card"><h2>Total: {formato_clp(len(dias) * PRECIO_DIA_FIJO)}</h2><p>{len(dias)} días x $6.400 - Comunicación automática a cocina, bodega y finanzas</p></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("← Volver a editar menú", use_container_width=True):
                    st.session_state.wizard_idx = 0; st.rerun()
            with c2:
                if st.button("✅ FINALIZAR RESERVA - Guardar y notificar", type="primary", use_container_width=True):
                    dias_cerrados_check = listar_dias_cerrados()
                    dias_validos = [d for d in dias if d not in dias_cerrados_check]
                    if len(dias_validos) < len(dias):
                        st.warning(f"⚠️ {len(dias) - len(dias_validos)} día(s) fueron cerrados por Cocina justo ahora y no se reservarán.")
                    if not dias_validos:
                        st.error("Todos los días seleccionados ya fueron cerrados. Vuelve al calendario y elige otras fechas.")
                    else:
                        conn = get_conn(); cur = conn.cursor(); vouchers = []
                        for f_iso in dias_validos:
                            dobj = date.fromisoformat(f_iso)
                            pedidos_dia = st.session_state.pedidos.get(f_iso, {})
                            plato_txt = " | ".join([f"{k}:{v}" for k, v in pedidos_dia.items()]) or "Día completo"
                            cod = gen_codigo(st.session_state.rut_actual, "DIA", dobj)
                            cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)", (st.session_state.rut_actual, f_iso, "DIA_COMPLETO", plato_txt, cod, PRECIO_DIA_FIJO, "Pendiente", datetime.now().isoformat()))
                            if pedidos_dia:
                                for serv, plato in pedidos_dia.items():
                                    cur.execute("INSERT INTO solicitudes_detalle (rut,nombre,fecha,servicio,plato,valor_ref,codigo,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)", (st.session_state.rut_actual, nombre, f_iso, serv, plato, get_precio(plato, serv), cod, datetime.now().isoformat()))
                                    descontar_bodega(plato)
                            else:
                                cur.execute("INSERT INTO solicitudes_detalle (rut,nombre,fecha,servicio,plato,valor_ref,codigo,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)", (st.session_state.rut_actual, nombre, f_iso, "DIA_COMPLETO", "Día completo (sin menú específico)", PRECIO_DIA_FIJO, cod, datetime.now().isoformat()))
                            vouchers.append(cod)
                        conn.commit(); conn.close()
                        html_resumen = df[df["Fecha ISO"].isin(dias_validos)][["Día", "Menú elegido", "Precio"]].to_html()
                        ok1, msg1 = enviar_email(EMAILS["cocina"], f"🍽️ Nueva reserva {nombre} - {len(dias_validos)} días", f"<h3>Reserva {nombre}</h3>{html_resumen}<p>Códigos: {', '.join(vouchers)}</p>")
                        ok2, msg2 = enviar_email(EMAILS["finanzas"], f"💰 Reserva {formato_clp(len(dias_validos) * PRECIO_DIA_FIJO)} - {nombre}", f"<h3>Pago pendiente</h3>{html_resumen}")
                        st.success(f"✅ Reserva guardada - {formato_clp(len(dias_validos) * PRECIO_DIA_FIJO)} - Códigos: {', '.join(vouchers)}")
                        st.info(f"Comunicación: Bodega descontada ✅ | Cocina: {'Enviado' if ok1 else msg1} | Finanzas: {'Enviado' if ok2 else msg2}")
                        st.balloons()
                        st.session_state.dias_sel = []; st.session_state.pedidos = {}; st.session_state.wizard_idx = 0; st.session_state.paso = 1
        else:
            f_act = dias[idx]; d_obj = date.fromisoformat(f_act)
            dnom = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][d_obj.weekday()]
            st.markdown(f'<div class="main-header"><h1>{dnom} {d_obj.strftime("%d/%m/%Y")} - Día {idx + 1} de {len(dias)}</h1><p>Elige tu menú para este día</p></div>', unsafe_allow_html=True)
            if f_act not in st.session_state.pedidos: st.session_state.pedidos[f_act] = {}
            minuta_dia = get_minuta_dia(dnom)
            if not minuta_dia:
                st.warning("Todavía no hay platos cargados para este día. Se reservará como día completo sin menú específico.")
            for serv in SERVICIOS:
                ops = minuta_dia.get(serv, [])
                if not ops: continue
                st.markdown(f'<div class="al-card"><h3>{serv}</h3>', unsafe_allow_html=True)
                cols = st.columns(2)
                for i, plato in enumerate(ops):
                    sel = st.session_state.pedidos[f_act].get(serv) == plato
                    with cols[i % 2]:
                        if st.button(f"{'✅ ' if sel else ''}{plato}", key=f"{f_act}_{serv}_{plato}", type="primary" if sel else "secondary", use_container_width=True):
                            if sel: del st.session_state.pedidos[f_act][serv]
                            else: st.session_state.pedidos[f_act][serv] = plato
                            st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            st.divider()
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                if st.button("← Calendario", use_container_width=True):
                    st.session_state.paso = 1; st.rerun()
            with c2:
                if st.button("← Anterior", disabled=idx == 0, use_container_width=True):
                    st.session_state.wizard_idx -= 1; st.rerun()
            with c3:
                if idx < len(dias) - 1:
                    if st.button("Siguiente día →", type="primary", use_container_width=True):
                        st.session_state.wizard_idx += 1; st.rerun()
                else:
                    if st.button("Ver resumen →", type="primary", use_container_width=True):
                        st.session_state.wizard_idx += 1; st.rerun()

# ========= RECLAMOS / SUGERENCIAS / FELICITACIONES =========
elif st.session_state.menu == "Reclamos / Sugerencias":
    if not st.session_state.rut_actual:
        st.session_state.menu = "Login"; st.rerun()
    conn = get_conn(); com = pd.read_sql_query("SELECT * FROM comensales WHERE rut=?", conn, params=(st.session_state.rut_actual,)); conn.close()
    nombre = com.iloc[0]['nombre'] if not com.empty else "Comensal"
    st.markdown(f'<div class="main-header"><h1>💬 Reclamos, Sugerencias y Felicitaciones</h1><p>Hola {nombre} - Tu opinión nos ayuda a mejorar</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["✍️ Enviar nuevo", "📚 Mis mensajes guardados"])
    with tab1:
        with st.form("reclamo_form"):
            tipo = st.selectbox("Tipo", ["Reclamo", "Sugerencia", "Felicitación", "Consulta"])
            categoria = st.selectbox("Categoría", ["Comida / Sabor", "Atención / Servicio", "Higiene / Limpieza", "Infraestructura", "Tiempo de espera", "Otro"])
            mensaje = st.text_area("Cuéntanos tu experiencia*", height=150, placeholder="Ej: El lunes el pollo estaba muy seco, sugeriría...")
            if st.form_submit_button("Enviar", type="primary", use_container_width=True):
                if mensaje:
                    conn = get_conn(); cur = conn.cursor()
                    cur.execute("INSERT INTO reclamos_sugerencias (rut,nombre,tipo,categoria,mensaje,fecha,estado) VALUES (?,?,?,?,?,?,?)", (st.session_state.rut_actual, nombre, tipo, categoria, mensaje, datetime.now().isoformat(), "Pendiente"))
                    conn.commit(); conn.close()
                    html = f"<h3>{tipo} de {nombre} - {st.session_state.rut_actual}</h3><p><b>Categoría:</b> {categoria}</p><p>{mensaje}</p>"
                    enviar_email(EMAILS["reclamos"], f"{tipo} - {categoria} - {nombre}", html)
                    st.success("✅ Guardado y notificado a Gerencia. ¡Gracias por tu feedback!")
                else: st.error("Escribe tu mensaje")
    with tab2:
        conn = get_conn(); df = pd.read_sql_query("SELECT fecha,tipo,categoria,mensaje,estado,respuesta FROM reclamos_sugerencias WHERE rut=? ORDER BY fecha DESC", conn, params=(st.session_state.rut_actual,)); conn.close()
        if df.empty:
            st.info("Aún no has enviado mensajes")
        else:
            st.dataframe(df, use_container_width=True)

# ========= COCINA (producción diaria + cierre del proceso de comensales) =========
elif st.session_state.menu == "Cocina":
    st.markdown('<div class="main-header"><h1>👨‍🍳 Cocina - Producción diaria</h1><p>Conteo de comensales por plato y cierre del proceso</p></div>', unsafe_allow_html=True)
    fecha_sel = st.date_input("Fecha de producción", value=date.today())
    f_iso = fecha_sel.isoformat()
    cerrado = dia_cerrado(f_iso)
    if cerrado:
        st.warning("🔒 Este día ya fue cerrado. Los comensales ya no pueden reservar para esta fecha.")
    df = produccion_dia(f_iso)
    if df.empty:
        st.info("Aún no hay reservas para esta fecha.")
    else:
        st.dataframe(df, use_container_width=True)
        st.metric("Total comensales", int(df['comensales'].sum()))
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("⬇️ Descargar reporte CSV", csv, f"produccion_{f_iso}.csv", "text/csv", use_container_width=True)
        if not cerrado:
            st.divider()
            if st.button("🔒 Cerrar proceso de comensales de este día", type="primary", use_container_width=True):
                total = cerrar_dia(f_iso, st.session_state.usuario["username"])
                html = df.to_html()
                ok1, msg1 = enviar_email(EMAILS["cocina"], f"🔒 Cierre {f_iso} - {total} comensales", f"<h3>Cierre de producción {f_iso}</h3>{html}")
                ok2, msg2 = enviar_email(EMAILS["finanzas"], f"🔒 Cierre {f_iso} - consolidado", f"<h3>Consolidado {f_iso}</h3>{html}")
                st.success(f"✅ Día {f_iso} cerrado - {total} comensales.")
                st.info(f"Correo cocina: {'Enviado' if ok1 else msg1} | Correo finanzas: {'Enviado' if ok2 else msg2}")
                st.rerun()
    if cerrado and st.session_state.usuario["rol"] == "Admin":
        st.divider()
        if st.button("🔓 Reabrir día (solo Admin)"):
            reabrir_dia(f_iso); st.success("Día reabierto"); st.rerun()

# ========= REPORTES POR PLATO =========
elif st.session_state.menu == "Reportes":
    st.markdown('<div class="main-header"><h1>📊 Reportes por plato</h1><p>Consumo consolidado por plato en un rango de fechas</p></div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    f_ini = c1.date_input("Desde", value=date.today() - timedelta(days=7))
    f_fin = c2.date_input("Hasta", value=date.today())
    if f_ini > f_fin:
        st.error("La fecha 'Desde' no puede ser posterior a 'Hasta'")
    else:
        df = reporte_por_plato(f_ini.isoformat(), f_fin.isoformat())
        if df.empty:
            st.info("No hay reservas registradas en ese rango.")
        else:
            st.markdown("#### Detalle por día")
            st.dataframe(df, use_container_width=True)
            resumen = df.groupby("plato").agg(pedidos=("pedidos", "sum")).reset_index().sort_values("pedidos", ascending=False)
            st.markdown("#### Ranking de platos más pedidos")
            st.dataframe(resumen, use_container_width=True)
            st.metric("Total de pedidos en el rango", int(df['pedidos'].sum()))
            st.caption("El 'valor referencial' es el precio cargado en el módulo de Platos; no reemplaza la facturación real, que se calcula por día completo ($6.400).")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Descargar CSV", csv, f"reporte_platos_{f_ini}_{f_fin}.csv", "text/csv", use_container_width=True)

# ========= PLATOS Y MINUTA (carga de platos) =========
elif st.session_state.menu == "Platos y Minuta":
    st.markdown('<div class="main-header"><h1>🍽️ Carga de platos y minuta</h1><p>Administra los platos y qué día/servicio aparecen para los comensales</p></div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["➕ Platos", "📅 Asignar a minuta"])
    with tab1:
        st.markdown("#### Agregar nuevo plato")
        with st.form("nuevo_plato", clear_on_submit=True):
            nombre_p = st.text_input("Nombre del plato*")
            servicio_p = st.selectbox("Servicio", SERVICIOS)
            valor_p = st.number_input("Valor CLP (referencial)", min_value=0, value=6500, step=100)
            if st.form_submit_button("Guardar plato", type="primary", use_container_width=True):
                if nombre_p:
                    agregar_plato(nombre_p, servicio_p, valor_p)
                    st.success(f"Plato '{nombre_p}' guardado ✅"); st.rerun()
                else:
                    st.error("Escribe el nombre del plato")
        st.divider()
        if st.button("🔄 Sincronizar platos que están en la minuta pero no en esta lista"):
            n = sincronizar_platos_faltantes()
            st.success(f"{n} plato(s) agregado(s) con valor referencial {formato_clp(PRECIO_DIA_FIJO)}. Edítalos abajo si es necesario.")
            st.rerun()
        st.markdown("#### 📋 Platos cargados")
        df_platos = listar_platos()
        if df_platos.empty:
            st.info("Aún no hay platos cargados")
        else:
            st.dataframe(df_platos, use_container_width=True)
            st.markdown("#### ✏️ Editar / eliminar plato")
            id_sel = st.selectbox("Selecciona un plato por ID", df_platos['id'].tolist())
            fila = df_platos[df_platos['id'] == id_sel].iloc[0]
            with st.form("editar_plato"):
                nombre_e = st.text_input("Nombre", value=fila['nombre'])
                servicio_e = st.selectbox("Servicio", SERVICIOS, index=SERVICIOS.index(fila['servicio']) if fila['servicio'] in SERVICIOS else 0)
                valor_e = st.number_input("Valor CLP", min_value=0, value=int(fila['valor'] or 0), step=100)
                ce1, ce2 = st.columns(2)
                with ce1:
                    if st.form_submit_button("💾 Guardar cambios", type="primary", use_container_width=True):
                        actualizar_plato(id_sel, nombre_e, servicio_e, valor_e)
                        st.success("Actualizado ✅"); st.rerun()
                with ce2:
                    if st.form_submit_button("🗑️ Eliminar plato", use_container_width=True):
                        eliminar_plato(id_sel)
                        st.success("Eliminado ✅"); st.rerun()
    with tab2:
        st.caption("Define qué platos aparecen en el menú de cada día para los comensales")
        df_platos = listar_platos()
        if df_platos.empty:
            st.info("Primero carga platos en la pestaña anterior")
        else:
            dia_m = st.selectbox("Día", DIAS_SEMANA)
            servicio_m = st.selectbox("Servicio ", SERVICIOS, key="serv_minuta")
            opciones_m = df_platos[df_platos['servicio'] == servicio_m]['nombre'].tolist()
            if opciones_m:
                plato_sel = st.selectbox("Plato a asignar", opciones_m)
                if st.button("➕ Agregar a la minuta", type="primary"):
                    asignar_plato_minuta(dia_m, servicio_m, plato_sel)
                    st.success(f"{plato_sel} agregado a {dia_m} - {servicio_m}"); st.rerun()
            else:
                st.warning(f"No hay platos cargados para {servicio_m}")
            st.markdown(f"### Minuta actual de {dia_m}")
            df_m = listar_minuta_dia(dia_m)
            if df_m.empty:
                st.info("Sin platos asignados a este día todavía")
            else:
                st.dataframe(df_m[["servicio", "plato"]], use_container_width=True)
                id_quitar = st.selectbox("Quitar de la minuta (ID)", df_m['id'].tolist())
                if st.button("🗑️ Quitar de la minuta"):
                    quitar_plato_minuta(id_quitar); st.success("Quitado"); st.rerun()

# ========= GERENCIA =========
elif st.session_state.menu == "Gerencia":
    st.markdown('<div class="main-header"><h1>Gerencia - Resumen</h1></div>', unsafe_allow_html=True)
    conn = get_conn()
    df_sol = pd.read_sql_query("SELECT COUNT(*) as total, SUM(precio) as monto FROM solicitudes", conn)
    df_rec = pd.read_sql_query("SELECT * FROM reclamos_sugerencias ORDER BY fecha DESC", conn)
    conn.close()
    st.metric("Total reservas guardadas", df_sol.iloc[0]['total'] if not df_sol.empty else 0)
    st.metric("Monto total", formato_clp(df_sol.iloc[0]['monto'] or 0))
    st.markdown("### Reclamos / Sugerencias guardados")
    st.dataframe(df_rec, use_container_width=True)

elif st.session_state.menu == "Reclamos Admin":
    conn = get_conn(); df = pd.read_sql_query("SELECT * FROM reclamos_sugerencias ORDER BY fecha DESC", conn); conn.close()
    st.markdown('<div class="main-header"><h1>Reclamos Admin</h1></div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        id_sel = st.selectbox("Responder reclamo ID", df['id'].tolist())
        resp = st.text_area("Respuesta")
        if st.button("Guardar respuesta"):
            conn = get_conn(); cur = conn.cursor(); cur.execute("UPDATE reclamos_sugerencias SET respuesta=?, estado='Respondido' WHERE id=?", (resp, id_sel)); conn.commit(); conn.close(); st.success("Respuesta guardada"); st.rerun()

else:
    st.info(f"Módulo {st.session_state.menu} - Comunicación entre apps activa: cada reserva descuenta bodega, notifica cocina y finanzas, y guarda todo en BD")
