import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import calendar
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT, execute_sql, get_minutas_rango

st.set_page_config(page_title="Mamuil Malal ERP v2.0 - PostgreSQL", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

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

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}

st.markdown('''
<div class="main-header">
<h1>🍽️ Mamuil Malal ERP v2.0 - PostgreSQL + Gmail</h1>
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
        com=conn.query("SELECT * FROM comensales WHERE rut=:rut", params={"rut": rut}, ttl=0)
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        tab_reserva, tab_reclamos = st.tabs(["📅 Reservar","💬 Reclamos"])

        with tab_reserva:
            # Resultado persistido solo para informar el último proceso.
            resultado_anterior = st.session_state.pop("resultado_reserva", None)
            if resultado_anterior:
                if resultado_anterior.get("correo_ok"):
                    st.success(resultado_anterior["mensaje"])
                else:
                    st.warning(resultado_anterior["mensaje"])
                st.info(f"Códigos: {', '.join(resultado_anterior.get('vouchers', []))}")

            if not st.session_state.dias_sel:
                st.markdown("#### 📅 Paso 1: Selecciona los días")
                hoy = date.today()
                ultimo_dia = calendar.monthrange(hoy.year, hoy.month)[1]
                primer_dia_mes = date(hoy.year, hoy.month, 1)
                dias_disponibles = [
                    primer_dia_mes + timedelta(days=i)
                    for i in range(ultimo_dia)
                    if primer_dia_mes + timedelta(days=i) >= hoy
                ]
                etiquetas_dias = {
                    d.isoformat(): f"{['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'][d.weekday()]} {d.strftime('%d/%m')}"
                    for d in dias_disponibles
                }
                st.caption(
                    "Marca todos los días de una sola vez. La aplicación procesará "
                    "la selección únicamente al pulsar Continuar."
                )
                with st.form("seleccion_dias_v2", clear_on_submit=False):
                    seleccion = st.multiselect(
                        "Días disponibles",
                        options=list(etiquetas_dias),
                        default=[],
                        format_func=lambda valor: etiquetas_dias[valor],
                        placeholder="Selecciona uno o más días",
                    )
                    if seleccion:
                        st.info(
                            f"{len(seleccion)} día(s) · "
                            f"Total convenio {formato_clp(len(seleccion) * precio_dia)}"
                        )
                    continuar = st.form_submit_button(
                        "Continuar → Elegir menús",
                        type="primary",
                        use_container_width=True,
                        disabled=not seleccion,
                    )
                if continuar:
                    st.session_state.dias_sel = sorted(seleccion)
                    st.session_state.pedidos = {dia: {} for dia in seleccion}
                    st.session_state.reserva_revisar = False
                    st.rerun()
            else:
                dias = sorted(st.session_state.dias_sel)
                st.session_state.pedidos = st.session_state.get("pedidos", {}) or {}
                for dia_iso in dias:
                    st.session_state.pedidos.setdefault(dia_iso, {})

                # Una sola lectura remota para todo el rango seleccionado.
                df_minutas = get_minutas_rango(dias[0], dias[-1])
                if not df_minutas.empty:
                    df_minutas = df_minutas[df_minutas["fecha"].astype(str).isin(dias)].copy()

                if not st.session_state.get("reserva_revisar", False):
                    st.markdown("#### 🍽️ Paso 2: Menú por día y servicio")
                    st.caption(
                        "Selecciona todos los menús y guarda una sola vez. "
                        "Puedes omitir un servicio, pero cada día debe tener al menos una selección."
                    )
                    elecciones = {}
                    with st.form("menus_completos_v2", clear_on_submit=False):
                        for f_iso in dias:
                            f_obj = date.fromisoformat(f_iso)
                            dnom = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                            st.markdown(f"##### {dnom} {f_obj.strftime('%d/%m/%Y')}")

                            filas_fecha = (
                                df_minutas[df_minutas["fecha"].astype(str) == f_iso]
                                if not df_minutas.empty else pd.DataFrame()
                            )
                            servicios = []
                            opciones_por_servicio = {}
                            if not filas_fecha.empty:
                                for servicio, grupo in filas_fecha.groupby("servicio", sort=False):
                                    servicios.append(str(servicio))
                                    opciones_por_servicio[str(servicio)] = [
                                        {
                                            "plato": str(row["plato"]),
                                            "tipo": str(row.get("tipo_opcion") or "").strip(),
                                        }
                                        for _, row in grupo.iterrows()
                                    ]
                            else:
                                for servicio, platos in MINUTA.get(dnom, {}).items():
                                    servicios.append(servicio)
                                    opciones_por_servicio[servicio] = [
                                        {"plato": plato, "tipo": ""} for plato in platos
                                    ]

                            if not servicios:
                                st.warning("No existe minuta configurada para esta fecha.")
                                continue

                            columnas = st.columns(2)
                            elecciones[f_iso] = {}
                            for pos_serv, servicio in enumerate(servicios):
                                registros = opciones_por_servicio[servicio]
                                # El token incorpora posición y tipo para tolerar platos repetidos.
                                tokens = [""]
                                etiquetas = {"": "— No reservar este servicio —"}
                                for pos, registro in enumerate(registros):
                                    token = f"{pos}|{registro['tipo']}|{registro['plato']}"
                                    tokens.append(token)
                                    prefijo = f"{registro['tipo']}: " if registro['tipo'] else ""
                                    etiquetas[token] = (
                                        f"{prefijo}{registro['plato']} · "
                                        f"{formato_clp(get_precio(registro['plato'], servicio))}"
                                    )

                                actual = st.session_state.pedidos.get(f_iso, {}).get(servicio, "")
                                indice = 0
                                if actual:
                                    for idx_token, token in enumerate(tokens):
                                        if token and token.split("|", 2)[2] == actual:
                                            indice = idx_token
                                            break
                                with columnas[pos_serv % 2]:
                                    elegido = st.selectbox(
                                        servicio,
                                        options=tokens,
                                        index=indice,
                                        format_func=lambda token, mapa=etiquetas: mapa[token],
                                        key=f"menu_v2_{f_iso}_{servicio}",
                                    )
                                if elegido:
                                    elecciones[f_iso][servicio] = elegido.split("|", 2)[2]
                            st.divider()

                        c1, c2 = st.columns(2)
                        with c1:
                            reiniciar = st.form_submit_button(
                                "← Cambiar días", use_container_width=True
                            )
                        with c2:
                            revisar = st.form_submit_button(
                                "Revisar reserva →", type="primary", use_container_width=True
                            )

                    if reiniciar:
                        st.session_state.dias_sel = []
                        st.session_state.pedidos = {}
                        st.session_state.reserva_revisar = False
                        st.rerun()
                    if revisar:
                        dias_sin_menu = [dia for dia in dias if not elecciones.get(dia)]
                        if dias_sin_menu:
                            st.error(
                                "Selecciona al menos un servicio en: "
                                + ", ".join(date.fromisoformat(d).strftime("%d/%m") for d in dias_sin_menu)
                            )
                        else:
                            st.session_state.pedidos = elecciones
                            st.session_state.reserva_revisar = True
                            st.rerun()
                else:
                    st.markdown("#### ✅ Paso 3: Revisa y confirma")
                    detalle = []
                    for f_iso in dias:
                        f_obj = date.fromisoformat(f_iso)
                        dnom = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][f_obj.weekday()]
                        for servicio, plato in st.session_state.pedidos.get(f_iso, {}).items():
                            detalle.append((f_iso, dnom, servicio, plato, get_precio(plato, servicio)))

                    if not detalle:
                        st.error("No hay menús seleccionados.")
                        st.session_state.reserva_revisar = False
                        st.stop()

                    df_detalle = pd.DataFrame(
                        detalle, columns=["Fecha", "Día", "Servicio", "Plato", "Precio referencia"]
                    )
                    total_real = len(dias) * precio_dia
                    st.dataframe(df_detalle, use_container_width=True, hide_index=True)
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric("Días reservados", len(dias))
                    with c2:
                        st.metric("Total a pagar", formato_clp(total_real))

                    with st.form("confirmar_reserva_v2"):
                        metodo = st.selectbox(
                            "Método de pago*",
                            ["Transferencia", "Débito en local", "Crédito", "Descuento por planilla"],
                        )
                        aceptar = st.checkbox(
                            "Confirmo que las fechas, servicios y platos son correctos."
                        )
                        c1, c2 = st.columns(2)
                        with c1:
                            editar = st.form_submit_button(
                                "← Editar menús", use_container_width=True
                            )
                        with c2:
                            confirmar = st.form_submit_button(
                                "Confirmar, guardar y enviar comprobante",
                                type="primary",
                                use_container_width=True,
                                disabled=not aceptar,
                            )

                    if editar:
                        st.session_state.reserva_revisar = False
                        st.rerun()

                    if confirmar:
                        conn = get_conn()
                        vouchers = []
                        precio_por_linea = {}
                        for f_iso in dias:
                            lineas_dia = [linea for linea in detalle if linea[0] == f_iso]
                            base_linea, resto = divmod(int(precio_dia), len(lineas_dia))
                            for pos, linea in enumerate(lineas_dia):
                                precio_por_linea[(linea[0], linea[2], linea[3])] = (
                                    base_linea + (1 if pos < resto else 0)
                                )

                        # Regla de orden: primero transacción y commit. Solo después inventario y correos.
                        try:
                            with conn.session as sesion:
                                correo_cli = str(com.iloc[0].get("correo") or "").strip()
                                for f_iso, dnom, servicio, plato, precio_ref in detalle:
                                    codigo = gen_codigo(rut, servicio, date.fromisoformat(f_iso))
                                    execute_sql(
                                        sesion,
                                        "INSERT INTO solicitudes "
                                        "(rut,fecha,servicio,plato,plato_reservado,codigo,precio,precio_aplicado,"
                                        "institucion,correo,metodo_pago,estado_pago,estado_consumo,fecha_creacion) "
                                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                        (
                                            rut, f_iso, servicio, plato, plato, codigo,
                                            precio_ref,
                                            precio_por_linea[(f_iso, servicio, plato)],
                                            institucion, correo_cli, metodo,
                                            "Pendiente", "Pendiente", datetime.now().isoformat(),
                                        ),
                                    )
                                    vouchers.append(codigo)
                                sesion.commit()
                        except Exception as error_guardado:
                            st.error(
                                "No fue posible guardar la reserva. No se generó ni envió ningún comprobante. "
                                f"Detalle: {error_guardado}"
                            )
                            st.stop()

                        # Procesos posteriores: una falla aquí no elimina una reserva ya confirmada.
                        for _, _, _, plato, _ in detalle:
                            descontar_bodega(plato)

                        resumen_fechas = ", ".join(
                            f"{['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'][date.fromisoformat(f).weekday()]} "
                            f"{date.fromisoformat(f).strftime('%d/%m')}"
                            for f in dias
                        )
                        html_comprobante = f"""
                        <div style="font-family:Arial,sans-serif;padding:24px;border:2px solid #0A2F6B;border-radius:16px;max-width:760px">
                          <div style="background:#0A2F6B;padding:20px;border-radius:12px;color:white;text-align:center">
                            <h1 style="margin:0;color:white">🍽️ Mamuil Malal</h1>
                            <p>Comprobante de reserva</p>
                          </div>
                          <h2 style="color:#0A2F6B">Hola {nombre}</h2>
                          <p><b>RUT:</b> {rut} · <b>Institución:</b> {institucion}</p>
                          <p><b>Fecha de emisión:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                          <p><b>Días:</b> {len(dias)} · <b>Total:</b> {formato_clp(total_real)}</p>
                          <p><b>Método de pago:</b> {metodo} · <b>Estado:</b> Pendiente</p>
                          <p><b>Fechas:</b> {resumen_fechas}</p>
                          <p><b>Códigos:</b> {', '.join(vouchers)}</p>
                          <h3 style="color:#0A2F6B">Detalle</h3>
                          {df_detalle.to_html(index=False, border=0)}
                        </div>
                        """
                        correo_ok, correo_msg = enviar_email(
                            correo_cli,
                            f"Comprobante de reserva Mamuil Malal · {len(dias)} día(s)",
                            html_comprobante,
                        )
                        cocina_ok, cocina_msg = enviar_email(
                            EMAILS.get("cocina", "ale973@gmail.com"),
                            f"[NUEVA RESERVA] {nombre} · {institucion} · {len(dias)} día(s)",
                            html_comprobante,
                        )

                        if correo_ok:
                            mensaje_resultado = f"Reserva guardada y comprobante enviado a {correo_cli}."
                        else:
                            mensaje_resultado = (
                                "Reserva guardada correctamente, pero no se pudo enviar el comprobante "
                                f"al comensal: {correo_msg}"
                            )
                        if not cocina_ok:
                            mensaje_resultado += f" Aviso a cocina no enviado: {cocina_msg}"

                        st.session_state.dias_sel = []
                        st.session_state.pedidos = {}
                        st.session_state.reserva_revisar = False
                        st.session_state.resultado_reserva = {
                            "correo_ok": correo_ok,
                            "mensaje": mensaje_resultado,
                            "vouchers": vouchers,
                        }
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
                        for destino in EMAILS.get("reclamos", ["ale973@gmail.com", "araucaniashop@gmail.com"]):
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

# ===== PERSONAL DE CASINO =====
with t_casino:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Cocina","Bodega","Finanzas","Admin"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>{rol} - Módulos PostgreSQL</h3></div>', unsafe_allow_html=True)
        tabs_casino = st.tabs(["👨‍🍳 Cocina","📦 Bodega","💰 Finanzas"])
        with tabs_casino[0]:
            st.markdown("#### 👨‍🍳 Cocina - Platos Solicitados por Día (PostgreSQL)")
            conn=get_conn()
            df=conn.query("SELECT fecha, plato_reservado, COUNT(*) as cantidad, servicio FROM solicitudes WHERE fecha >= :fecha GROUP BY fecha, plato_reservado, servicio ORDER BY fecha", params={"fecha": date.today().isoformat()}, ttl=0)
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
            df=conn.query("SELECT * FROM solicitudes WHERE estado_pago=:estado ORDER BY fecha DESC", params={"estado": "Pendiente"}, ttl=0)
            st.dataframe(df, use_container_width=True)
            st.metric("Pendiente", formato_clp(df['precio_aplicado'].sum() if not df.empty else 0))
    else:
        st.markdown("### 👨‍🍳 Personal Casino - Login PostgreSQL")
        with st.form("login_casino"):
            u=st.text_input("Usuario", key="u_casino"); p=st.text_input("Contraseña", type="password", key="p_casino")
            if st.form_submit_button("Ingresar Casino", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username": u, "pwd": hash_pwd(p)}, ttl=0)
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
                            execute_sql(s, "UPDATE solicitudes SET estado_pago=%s WHERE codigo=%s", ("Pagado", id_pago))
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
            df_pend=conn.query("SELECT COUNT(*) as pendientes, SUM(precio_aplicado) as monto_pend FROM solicitudes WHERE estado_pago=:estado", params={"estado": "Pendiente"}, ttl=0)
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

    else:
        st.markdown("### 🏢 Administración - Login PostgreSQL")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn()
                df=conn.query("SELECT username,rol,nombre FROM usuarios WHERE username=:username AND pwd=:pwd", params={"username": u, "pwd": hash_pwd(p)}, ttl=0)
                if not df.empty and df.iloc[0]['rol'] in ["Admin","Gerencia"]:
                    st.session_state.usuario={"username":df.iloc[0]['username'],"rol":df.iloc[0]['rol'],"nombre":df.iloc[0]['nombre']}; st.rerun()
                else: st.error("Solo admin/gerencia - prueba admin/admin123")

st.divider()
st.caption("V20 PostgreSQL - common.py con %s + solicitudes(plato_reservado, metodo_pago, estado_pago DEFAULT Pendiente) + app.py con minuta por día + comprobante HTML inmediato + Reportes 3 SELECT directos")
