
import streamlit as st
from common import init_db, get_conn, hash_pwd, normalizar_rut, normalizar_rut_db, limpiar_rut, validar_rut_m11, apply_alemsi_style, MINUTA, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, get_instituciones, get_precio_institucion, get_precio_persona_institucion, PRECIO_DIA_DEFAULT
import pandas as pd
from datetime import date, timedelta, datetime
import random

st.set_page_config(page_title="Mamuil Malal ERP V19", page_icon="🍽️", layout="wide", initial_sidebar_state="collapsed")

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

st.markdown('''
<div class="main-header">
<h1>🍽️ Mamuil Malal ERP V19 - ALEMSI</h1>
<p>✅ V18 base intacta + Adaptaciones: Cocina 7+7 días + Recetas + Reporte 24h + Bodega masiva CSV + Inventarios aleatorios + Finanzas glosa + Admin minutas + Excepciones</p>
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

# ===== COMENSAL - MANTIENE TODO V18 =====
with t_comensal:
    if st.session_state.rut_actual:
        rut=st.session_state.rut_actual
        conn=get_conn(); com=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
        if com.empty: st.session_state.rut_actual=None; st.rerun()
        nombre=com.iloc[0]['nombre']
        institucion=com.iloc[0]['institucion'] if 'institucion' in com.columns and com.iloc[0]['institucion'] else "Visitas"
        precio_dia, glosa_precio = get_precio_persona_institucion(rut, institucion)

        st.markdown(f'<div class="al-card"><h3>Hola {nombre} 👋 - {institucion}</h3><p>RUT: {rut} | {glosa_precio}: {formato_clp(precio_dia)}</p></div>', unsafe_allow_html=True)

        tab_reserva, tab_reclamos = st.tabs(["📅 Reservar","💬 Reclamos"])

        with tab_reserva:
            if not st.session_state.dias_sel:
                st.markdown("#### 📅 Paso 1: Selecciona días")
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
                    st.info(f"{len(st.session_state.dias_sel)} día(s) - Total {formato_clp(len(st.session_state.dias_sel)*precio_dia)}")
                    if st.button("Siguiente → Menú", type="primary", use_container_width=True):
                        st.session_state.dias_sel=sorted(st.session_state.dias_sel)
                        st.session_state.pedidos={d:{} for d in st.session_state.dias_sel}
                        st.session_state.wizard_idx=0; st.rerun()
            else:
                dias=sorted(st.session_state.dias_sel); idx=st.session_state.wizard_idx
                if idx>=len(dias):
                    dias_sin = [f for f in dias if not st.session_state.pedidos.get(f)]
                    if dias_sin:
                        st.error(f"❌ Faltan {len(dias_sin)} día(s)"); st.stop()
                    total=0; detalle=[]
                    for f_iso in dias:
                        dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(f_iso).weekday()]
                        for serv,plato in st.session_state.pedidos.get(f_iso,{}).items():
                            pr=get_precio(plato,serv); total+=pr; detalle.append((f_iso,dnom,serv,plato,pr))
                    df=pd.DataFrame(detalle, columns=["Fecha","Día","Servicio","Plato","Precio"])
                    total_real = len(dias)*precio_dia
                    st.dataframe(df, use_container_width=True)
                    st.metric("Total", formato_clp(total_real))
                    metodo=st.selectbox("Método pago", ["Transferencia","Débito en local","Crédito"])
                    if st.button("✅ FINALIZAR", type="primary", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor(); vouchers=[]
                        conn2=get_conn(); dfc=pd.read_sql_query("SELECT correo FROM comensales WHERE rut=?",conn2,params=(rut,)); conn2.close()
                        correo_cli=dfc.iloc[0]['correo'] if not dfc.empty else ""
                        for f_iso,dnom,serv,plato,pr in detalle:
                            cod=gen_codigo(rut,serv,date.fromisoformat(f_iso))
                            cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago,fecha_creacion,institucion,precio_aplicado,metodo_pago,correo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(rut,f_iso,serv,plato,cod,pr,"Pendiente", datetime.now().isoformat(), institucion, precio_dia, metodo, correo_cli))
                            vouchers.append(cod)
                            descontar_bodega(plato)
                        conn.commit(); conn.close()
                        st.success(f"Reserva OK - {formato_clp(total_real)} - {', '.join(vouchers[:3])}"); st.balloons()
                        st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0
                else:
                    f_act=dias[idx]; d_obj=date.fromisoformat(f_act)
                    dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][d_obj.weekday()]
                    st.markdown(f"### {dnom} {d_obj.strftime('%d/%m')} ({idx+1}/{len(dias)})")
                    if f_act not in st.session_state.pedidos: st.session_state.pedidos[f_act]={}
                    pedidos_actuales = st.session_state.pedidos.get(f_act, {})
                    tiene_uno = len(pedidos_actuales) > 0
                    if tiene_uno: st.success(f"✅ {', '.join([f'{k}: {v}' for k,v in pedidos_actuales.items()])}")
                    else: st.warning(f"⚠️ Al menos 1 opción para avanzar")
                    for serv in ["Desayuno","Almuerzo","Once","Cena"]:
                        ops=MINUTA.get(dnom,{}).get(serv,[])
                        if not ops: continue
                        st.write(f"**{serv}**")
                        cols=st.columns(2)
                        for i,plato in enumerate(ops):
                            sel=st.session_state.pedidos[f_act].get(serv)==plato
                            with cols[i%2]:
                                if st.button(f"{plato} {formato_clp(get_precio(plato,serv))}", key=f"{f_act}_{serv}_{plato}", type="primary" if sel else "secondary", use_container_width=True):
                                    if sel: del st.session_state.pedidos[f_act][serv]
                                    else: st.session_state.pedidos[f_act][serv]=plato
                                    st.rerun()
                    c1,c2=st.columns(2)
                    with c1:
                        if st.button("← Anterior", disabled=idx==0, use_container_width=True):
                            st.session_state.wizard_idx-=1; st.rerun()
                    with c2:
                        if idx < len(dias)-1:
                            if st.button("Siguiente →", type="primary", use_container_width=True, disabled=not tiene_uno):
                                st.session_state.wizard_idx+=1; st.rerun()
                        else:
                            if st.button("Ver resumen", type="primary", use_container_width=True, disabled=not tiene_uno):
                                st.session_state.wizard_idx+=1; st.rerun()
        with tab_reclamos:
            with st.form("reclamo"):
                tipo=st.selectbox("Tipo", ["Reclamo","Sugerencia","Felicitación"])
                categoria=st.selectbox("Categoría", ["Comida","Atención","Higiene","Infraestructura","Otro"])
                mensaje=st.text_area("Mensaje*")
                if st.form_submit_button("Enviar", type="primary", use_container_width=True):
                    if mensaje:
                        conn=get_conn(); cur=conn.cursor()
                        cur.execute("INSERT INTO reclamos_sugerencias (rut,nombre,tipo,categoria,mensaje,fecha,estado) VALUES (?,?,?,?,?,?,?)",(rut,nombre,tipo,categoria,mensaje, datetime.now().isoformat(),"Pendiente"))
                        conn.commit(); conn.close()
                        st.success("Enviado")
    else:
        st.markdown("### Reserva - RUT chileno")
        rut_raw=st.text_input("RUT", placeholder="16.632.880-2")
        if rut_raw:
            if not validar_rut_m11(rut_raw):
                st.error("RUT inválido")
            else:
                rn=normalizar_rut_db(rut_raw); rv=normalizar_rut(rut_raw)
                conn=get_conn(); df=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rn,)); conn.close()
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
                                conn=get_conn(); cur=conn.cursor()
                                cur.execute("INSERT OR REPLACE INTO comensales (rut,nombre,telefono,correo,institucion,fecha_registro) VALUES (?,?,?,?,?,?)",(rn,nombre,tel,correo,institucion, datetime.now().isoformat()))
                                conn.commit(); conn.close()
                                st.session_state.rut_actual=rn; st.rerun()

# ===== PERSONAL DE CASINO - ADAPTACIONES NUEVAS =====
with t_casino:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Cocina","Bodega","Finanzas","Admin"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>{rol} - Módulos mejorados V19</h3></div>', unsafe_allow_html=True)
        tabs_casino = st.tabs(["👨‍🍳 Cocina","📦 Bodega","💰 Finanzas"])

        # COCINA - ADAPTACIONES
        with tabs_casino[0]:
            st.markdown("#### 👨‍🍳 Cocina - Últimos 7 días + Próximos 7 días + Recetas + Reporte 24h")
            tc1,tc2,tc3,tc4 = st.tabs(["📅 Órdenes 7+7 días","📖 Recetas","📋 Reporte 24h anticipación","📊 Por turno"])

            with tc1:
                rango=st.selectbox("Ver", ["Próximos 7 días","Últimos 7 días","Todos últimos 14 días"])
                hoy=date.today()
                if rango=="Próximos 7 días":
                    f_ini=hoy; f_fin=hoy+timedelta(days=7)
                elif rango=="Últimos 7 días":
                    f_ini=hoy-timedelta(days=7); f_fin=hoy
                else:
                    f_ini=hoy-timedelta(days=7); f_fin=hoy+timedelta(days=7)
                conn=get_conn()
                df=pd.read_sql_query("SELECT s.id, s.fecha, c.nombre, c.institucion, s.servicio, s.plato, s.codigo, s.estado_consumo FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.fecha BETWEEN ? AND ? ORDER BY s.fecha, s.servicio", conn, params=(f_ini.isoformat(), f_fin.isoformat()))
                conn.close()
                st.dataframe(df, use_container_width=True)
                st.metric("Total órdenes en rango", len(df))
                if not df.empty:
                    id_sel=st.selectbox("ID cambiar estado", df['id'].tolist())
                    nuevo=st.selectbox("Nuevo estado", ["Pendiente","En Proceso","Completado","Entregado"])
                    if st.button("Actualizar cocina", type="primary"):
                        conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE solicitudes SET estado_consumo=? WHERE id=?",(nuevo,id_sel)); conn.commit(); conn.close(); st.success("OK"); st.rerun()

            with tc2:
                st.markdown("##### 📖 Recetas - Cómo se preparan")
                conn=get_conn(); df_platos=pd.read_sql_query("SELECT DISTINCT nombre FROM platos WHERE activo=1",conn); conn.close()
                plato_sel=st.selectbox("Selecciona plato para ver receta", df_platos['nombre'].tolist() if not df_platos.empty else [])
                if plato_sel:
                    conn=get_conn()
                    df_rec=pd.read_sql_query("SELECT insumo,cantidad,unidad,instrucciones FROM recetas WHERE plato=?",conn,params=(plato_sel,))
                    conn.close()
                    st.dataframe(df_rec, use_container_width=True)
                    if not df_rec.empty:
                        st.info(f"**{plato_sel}** - Ingredientes y preparación")
                        for _,r in df_rec.iterrows():
                            st.write(f"- {r['cantidad']} {r['unidad']} {r['insumo']}: {r['instrucciones']}")
                    else:
                        st.warning("Sin receta cargada - Admin debe cargarla")

            with tc3:
                st.markdown("##### 📋 Reporte 24h anticipación - Turno día subsiguiente")
                st.caption("Reporte con 24h de anticipación de lo que deben preparar al día siguiente del subsiguiente. Ej: Hoy lunes → reporte para miércoles")
                fecha_reporte=st.date_input("Fecha a preparar (por defecto pasado mañana)", value=date.today()+timedelta(days=2))
                conn=get_conn()
                df_rep=pd.read_sql_query("SELECT s.servicio, s.plato, COUNT(*) as cantidad_platos, COUNT(DISTINCT s.rut) as comensales, c.institucion FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.fecha=? GROUP BY s.servicio, s.plato, c.institucion ORDER BY s.servicio, cantidad_platos DESC", conn, params=(fecha_reporte.isoformat(),))
                conn.close()
                if df_rep.empty:
                    st.info(f"Sin reservas para {fecha_reporte} - {fecha_reporte.strftime('%A')}")
                else:
                    st.success(f"Reporte {fecha_reporte} - Total comensales únicos: {df_rep['comensales'].sum()} - Total platos: {df_rep['cantidad_platos'].sum()}")
                    st.dataframe(df_rep, use_container_width=True)
                    # Resumen por turno
                    df_turno=df_rep.groupby('servicio').agg({'cantidad_platos':'sum','comensales':'sum'}).reset_index()
                    st.markdown("###### Cantidad por turno")
                    st.dataframe(df_turno, use_container_width=True)
                    # Detalle por plato
                    df_plato=df_rep.groupby('plato').agg({'cantidad_platos':'sum'}).reset_index().sort_values('cantidad_platos', ascending=False)
                    st.markdown("###### Cantidad por tipo de plato (ej: Carbonada x 15, Puré x 8)")
                    st.dataframe(df_plato, use_container_width=True)
                    csv=df_rep.to_csv(index=False).encode('utf-8')
                    st.download_button("Descargar reporte 24h CSV", csv, f"reporte_cocina_{fecha_reporte}.csv", "text/csv")

            with tc4:
                st.markdown("##### 📊 Cantidad por turno y diferenciados")
                fecha_turno=st.date_input("Fecha turno", value=date.today(), key="turno")
                conn=get_conn()
                df_t=pd.read_sql_query("SELECT servicio, plato, COUNT(*) as qty, institucion FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE fecha=? GROUP BY servicio, plato, institucion", conn, params=(fecha_turno.isoformat(),))
                conn.close()
                st.dataframe(df_t, use_container_width=True)
                if not df_t.empty:
                    st.bar_chart(df_t.groupby('plato')['qty'].sum())

        # BODEGA - ADAPTACIONES
        with tabs_casino[1]:
            st.markdown("#### 📦 Bodega - Inventario + Carga masiva CSV + Inventarios aleatorios")
            tb1,tb2,tb3,tb4 = st.tabs(["📦 Inventario","➕ Agregar","📤 Carga masiva CSV/XLS","🎲 Inventarios aleatorios"])

            with tb1:
                conn=get_conn(); df=pd.read_sql_query("SELECT * FROM bodega_inventario ORDER BY seccion, stock ASC", conn); conn.close()
                st.dataframe(df, use_container_width=True)
                if not df.empty:
                    st.metric("Bajo crítico", len(df[df['stock']<df['critico']]))
                    df_bajo=df[df['stock']<df['critico']]
                    if not df_bajo.empty:
                        st.warning("Bajo stock crítico")
                        st.dataframe(df_bajo, use_container_width=True)

            with tb2:
                with st.form("add_prod"):
                    c1,c2=st.columns(2)
                    with c1:
                        codigo=st.text_input("Código*"); nombre=st.text_input("Nombre artículo*"); unidad=st.selectbox("Unidad", ["kilo","unidad","litro","paquete"])
                    with c2:
                        stock=st.number_input("Stock", value=0.0); precio=st.number_input("Precio", value=0); critico=st.number_input("Crítico", value=5.0); seccion=st.selectbox("Sección", ["General","Abarrotes","Carnes","Verduras","Lácteos","Bebidas","Limpieza"])
                        caduca=st.date_input("Caduca", value=date.today()+timedelta(days=180))
                    if st.form_submit_button("Agregar producto", type="primary", use_container_width=True):
                        if codigo and nombre:
                            conn=get_conn(); cur=conn.cursor()
                            cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion) VALUES (?,?,?,?,?,?,?,?)",(codigo,nombre,unidad,stock,precio,critico,caduca.isoformat(),seccion))
                            conn.commit(); conn.close()
                            st.success("Agregado")

            with tb3:
                st.markdown("##### 📤 Carga masiva - CSV o XLSX - Con registro de errores y responsable")
                st.caption("Formato CSV: codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion")
                archivo=st.file_uploader("Sube CSV o XLSX", type=["csv","xlsx","xls"])
                responsable=st.text_input("Responsable carga*", value=st.session_state.usuario['nombre'] if st.session_state.usuario else "")
                if archivo and responsable:
                    try:
                        if archivo.name.endswith('.csv'):
                            df_up=pd.read_csv(archivo)
                        else:
                            df_up=pd.read_excel(archivo)
                        st.write("Preview:", df_up.head())
                        st.info(f"Filas: {len(df_up)} - Columnas esperadas: codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion")
                        if st.button("Procesar carga masiva", type="primary", use_container_width=True):
                            ok=0; err=0; errores=[]
                            conn=get_conn(); cur=conn.cursor()
                            for idx,row in df_up.iterrows():
                                try:
                                    codigo=row.get('codigo_insumo') or row.get('codigo') or f"AUTO-{idx}"
                                    nombre=row.get('nombre_articulo') or row.get('nombre')
                                    if not nombre: raise ValueError("Sin nombre")
                                    unidad=row.get('unidad','kilo')
                                    stock=float(row.get('stock',0))
                                    precio=int(row.get('precio',0))
                                    critico=float(row.get('critico',5))
                                    caduca=row.get('caduca', (date.today()+timedelta(days=90)).isoformat())
                                    seccion=row.get('seccion','General')
                                    # Verifica si existe, suma stock
                                    cur.execute("SELECT id,stock FROM bodega_inventario WHERE codigo_insumo=? OR nombre_articulo=?", (codigo,nombre))
                                    r=cur.fetchone()
                                    if r:
                                        cur.execute("UPDATE bodega_inventario SET stock=stock+?, precio=?, caduca=?, seccion=? WHERE id=?",(stock,precio,str(caduca),seccion,r[0]))
                                    else:
                                        cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion) VALUES (?,?,?,?,?,?,?,?)",(codigo,nombre,unidad,stock,precio,critico,str(caduca),seccion))
                                    ok+=1
                                except Exception as e:
                                    err+=1
                                    errores.append(f"Fila {idx}: {str(e)}")
                            conn.commit()
                            # Log
                            cur.execute("INSERT INTO bodega_cargas_log (fecha,usuario,archivo_nombre,filas_ok,filas_error,errores,responsable,tipo_carga) VALUES (?,?,?,?,?,?,?,?)",(datetime.now().isoformat(), st.session_state.usuario['username'], archivo.name, ok, err, "\n".join(errores)[:2000], responsable, "masiva"))
                            conn.commit(); conn.close()
                            st.success(f"Carga OK: {ok} OK, {err} errores")
                            if errores:
                                st.error("\n".join(errores[:10]))
                    except Exception as e:
                        st.error(f"Error leyendo archivo: {e}")

                st.divider()
                st.markdown("###### Historial cargas - Registro quién, cuándo, responsable, errores")
                conn=get_conn(); df_log=pd.read_sql_query("SELECT fecha,usuario,archivo_nombre,filas_ok,filas_error,responsable FROM bodega_cargas_log ORDER BY fecha DESC LIMIT 20",conn); conn.close()
                st.dataframe(df_log, use_container_width=True)

            with tb4:
                st.markdown("##### 🎲 Inventarios aleatorios - Alertas OD")
                st.caption("Genera inventario aleatorio por sección para que encargados recuerden hacer inventario")
                seccion_inv=st.selectbox("Sección para inventario aleatorio", ["General","Abarrotes","Carnes","Verduras","Lácteos","Bebidas","Limpieza","Todas"])
                responsable_inv=st.text_input("Responsable OD", value=st.session_state.usuario['nombre'] if st.session_state.usuario else "")
                if st.button("🎲 Generar inventario aleatorio", type="primary", use_container_width=True):
                    conn=get_conn()
                    if seccion_inv=="Todas":
                        df_art=pd.read_sql_query("SELECT id,nombre_articulo,seccion FROM bodega_inventario ORDER BY RANDOM() LIMIT 10",conn)
                    else:
                        df_art=pd.read_sql_query("SELECT id,nombre_articulo,seccion FROM bodega_inventario WHERE seccion=? ORDER BY RANDOM() LIMIT 10",conn,params=(seccion_inv,))
                    conn.close()
                    if df_art.empty:
                        st.warning("Sin artículos en esa sección")
                    else:
                        articulos_json=df_art.to_json()
                        fecha_prog=(date.today()+timedelta(days=random.randint(1,7))).isoformat()
                        conn=get_conn(); cur=conn.cursor()
                        cur.execute("INSERT INTO inventarios_aleatorios (fecha_generada,fecha_programada,seccion,articulos,responsable,estado) VALUES (?,?,?,?,?,?)",(datetime.now().isoformat(), fecha_prog, seccion_inv, articulos_json, responsable_inv, "Pendiente"))
                        conn.commit(); conn.close()
                        st.success(f"Inventario aleatorio generado para {seccion_inv} - Programado {fecha_prog} - Responsable {responsable_inv}")
                        st.dataframe(df_art, use_container_width=True)
                        # Alerta
                        st.markdown(f'<div class="alert-card">🔔 Alerta OD: {responsable_inv} debe hacer inventario {seccion_inv} el {fecha_prog} - Artículos: {", ".join(df_art["nombre_articulo"].tolist())}</div>', unsafe_allow_html=True)

                st.divider()
                st.markdown("###### Inventarios pendientes - Alertas")
                conn=get_conn(); df_inv=pd.read_sql_query("SELECT * FROM inventarios_aleatorios WHERE estado='Pendiente' ORDER BY fecha_programada",conn); conn.close()
                if df_inv.empty:
                    st.info("Sin inventarios pendientes")
                else:
                    st.dataframe(df_inv, use_container_width=True)
                    for _,r in df_inv.iterrows():
                        dias_atraso=(date.fromisoformat(r['fecha_programada'])-date.today()).days
                        if dias_atraso<=1:
                            st.warning(f"🔔 Recuerda inventario {r['seccion']} - Responsable {r['responsable']} - Programado {r['fecha_programada']} - URGENTE")
                # Marcar realizado
                if not df_inv.empty:
                    id_real=st.selectbox("Marcar inventario realizado", df_inv['id'].tolist())
                    resultado=st.text_area("Resultado conteo")
                    if st.button("Marcar como realizado", type="primary"):
                        conn=get_conn(); cur=conn.cursor()
                        cur.execute("UPDATE inventarios_aleatorios SET estado='Realizado', fecha_realizado=?, resultado=? WHERE id=?",(datetime.now().isoformat(), resultado, id_real))
                        conn.commit(); conn.close()
                        st.success("Marcado realizado"); st.rerun()

        # FINANZAS - ADAPTACIONES
        with tabs_casino[2]:
            st.markdown("#### 💰 Finanzas - Reservas por institución + Montos + RUT + Glosa")
            tf1,tf2,tf3 = st.tabs(["📊 Por institución","👤 Detalle por persona","📑 Glosa semanal/mensual"])

            with tf1:
                conn=get_conn()
                df=pd.read_sql_query("SELECT c.institucion, COUNT(DISTINCT s.rut) as personas, COUNT(*) as reservas, SUM(s.precio_aplicado) as monto, SUM(CASE WHEN s.estado_pago='Pendiente' THEN s.precio_aplicado ELSE 0 END) as pendiente FROM solicitudes s JOIN comensales c ON s.rut=c.rut GROUP BY c.institucion",conn)
                conn.close()
                st.dataframe(df, use_container_width=True)
                if not df.empty:
                    st.metric("Total pendiente todas instituciones", formato_clp(df['pendiente'].sum()))
                    st.bar_chart(df.set_index('institucion')['monto'])

            with tf2:
                st.markdown("##### Pedro Pérez consumió 3 días - Detalle por persona con RUT, correo, método")
                filtro_inst=st.selectbox("Filtrar institución", ["Todas"]+get_instituciones())
                conn=get_conn()
                if filtro_inst=="Todas":
                    df_det=pd.read_sql_query("SELECT s.fecha, s.rut, c.nombre, c.correo, c.institucion, s.plato, s.precio_aplicado, s.estado_pago, s.metodo_pago, s.codigo FROM solicitudes s JOIN comensales c ON s.rut=c.rut ORDER BY s.fecha DESC LIMIT 200",conn)
                else:
                    df_det=pd.read_sql_query("SELECT s.fecha, s.rut, c.nombre, c.correo, c.institucion, s.plato, s.precio_aplicado, s.estado_pago, s.metodo_pago, s.codigo FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE c.institucion=? ORDER BY s.fecha DESC LIMIT 200",conn,params=(filtro_inst,))
                conn.close()
                st.dataframe(df_det, use_container_width=True)
                if not df_det.empty:
                    # Resumen por persona
                    df_pers=df_det.groupby(['rut','nombre','correo','institucion']).agg({'fecha':'count','precio_aplicado':'sum'}).reset_index().rename(columns={'fecha':'dias_consumidos','precio_aplicado':'total_pagado'})
                    st.markdown("###### Resumen por persona: cuántos días consumió y cuánto")
                    st.dataframe(df_pers, use_container_width=True)
                    st.download_button("Descargar detalle CSV", df_det.to_csv(index=False).encode('utf-8'), "finanzas_detalle.csv", "text/csv")

            with tf3:
                st.markdown("##### 📑 Glosa semanal y mensual - Elige reporte")
                tipo_glosa=st.selectbox("Tipo reporte", ["Semanal","Mensual","Personalizado"])
                if tipo_glosa=="Semanal":
                    inicio=st.date_input("Inicio semana", value=date.today()-timedelta(days=date.today().weekday()))
                    fin=inicio+timedelta(days=6)
                elif tipo_glosa=="Mensual":
                    inicio=st.date_input("Mes", value=date.today().replace(day=1))
                    fin=(inicio+timedelta(days=32)).replace(day=1)-timedelta(days=1)
                else:
                    c1,c2=st.columns(2)
                    with c1: inicio=st.date_input("Desde")
                    with c2: fin=st.date_input("Hasta")
                st.info(f"Glosa {tipo_glosa}: {inicio} al {fin}")
                conn=get_conn()
                df_glosa=pd.read_sql_query("SELECT c.institucion, COUNT(*) as reservas, COUNT(DISTINCT s.rut) as personas, SUM(s.precio_aplicado) as monto_total, SUM(CASE WHEN s.metodo_pago='Transferencia' THEN s.precio_aplicado ELSE 0 END) as transferencia, SUM(CASE WHEN s.metodo_pago='Débito en local' THEN s.precio_aplicado ELSE 0 END) as debito_local FROM solicitudes s JOIN comensales c ON s.rut=c.rut WHERE s.fecha BETWEEN ? AND ? GROUP BY c.institucion",conn,params=(inicio.isoformat(), fin.isoformat()))
                conn.close()
                st.dataframe(df_glosa, use_container_width=True)
                if not df_glosa.empty:
                    st.metric("Total glosa", formato_clp(df_glosa['monto_total'].sum()))
                    # Valorizado bodega
                    conn=get_conn(); df_bod=pd.read_sql_query("SELECT SUM(stock*precio) as valorizado FROM bodega_inventario",conn); conn.close()
                    st.metric("Bodega valorizada", formato_clp(df_bod.iloc[0]['valorizado'] if not df_bod.empty and df_bod.iloc[0]['valorizado'] else 0))
                    st.download_button(f"Descargar glosa {tipo_glosa} CSV", df_glosa.to_csv(index=False).encode('utf-8'), f"glosa_{tipo_glosa}_{inicio}_{fin}.csv", "text/csv")
                # Reportes adicionales
                st.markdown("###### Reportes adicionales")
                if st.button("Generar reporte comensales + bodega valorizado"):
                    conn=get_conn()
                    df_c=pd.read_sql_query("SELECT institucion, COUNT(*) as comensales FROM comensales GROUP BY institucion",conn)
                    df_b=pd.read_sql_query("SELECT seccion, SUM(stock*precio) as valorizado, COUNT(*) as items FROM bodega_inventario GROUP BY seccion",conn)
                    conn.close()
                    st.write("Comensales por institución"); st.dataframe(df_c, use_container_width=True)
                    st.write("Bodega valorizado por sección"); st.dataframe(df_b, use_container_width=True)

    else:
        st.markdown("### 👨‍🍳 Personal Casino - Login")
        st.caption("cocina/cocina123 | bodega/bodega123 | finanzas/finanzas123")
        with st.form("login_casino"):
            u=st.text_input("Usuario", key="u_casino")
            p=st.text_input("Contraseña", type="password", key="p_casino")
            if st.form_submit_button("Ingresar Casino", type="primary", use_container_width=True):
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p))); row=cur.fetchone(); conn.close()
                if row and row[1] in ["Cocina","Bodega","Finanzas","Admin"]:
                    st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}; st.rerun()
                else: st.error("No válido")

# ===== ADMINISTRACIÓN - ADAPTACIONES =====
with t_admin:
    if st.session_state.usuario and st.session_state.usuario["rol"] in ["Admin","Gerencia"]:
        rol=st.session_state.usuario["rol"]
        st.markdown(f'<div class="al-card"><h3>🏢 {rol} - V19 Completo</h3><p>Admin productos + Minutas + Valores + Excepciones + Instituciones + Reportes</p></div>', unsafe_allow_html=True)
        tab_g, tab_prod, tab_minuta, tab_exc, tab_inst, tab_recl = st.tabs(["📊 Gerencia","📦 Productos","🍽️ Minutas","⚖️ Excepciones","🏢 Instituciones","💬 Reclamos"])

        with tab_g:
            st.markdown("##### Gerencia - Todo tipo de reportes disponibles")
            conn=get_conn()
            df_sol=pd.read_sql_query("SELECT institucion, COUNT(*) as total, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY institucion",conn)
            df_com=pd.read_sql_query("SELECT institucion, COUNT(*) as comensales FROM comensales GROUP BY institucion",conn)
            df_pend=pd.read_sql_query("SELECT COUNT(*) as pendientes, SUM(precio_aplicado) as monto_pend FROM solicitudes WHERE estado_pago='Pendiente'",conn)
            df_bod_val=pd.read_sql_query("SELECT SUM(stock*precio) as valorizado FROM bodega_inventario",conn)
            df_metodo=pd.read_sql_query("SELECT metodo_pago, COUNT(*) as qty, SUM(precio_aplicado) as monto FROM solicitudes GROUP BY metodo_pago",conn)
            conn.close()
            c1,c2,c3,c4=st.columns(4)
            with c1: st.metric("Reservas", df_sol['total'].sum() if not df_sol.empty else 0)
            with c2: st.metric("Monto", formato_clp(df_sol['monto'].sum() if not df_sol.empty else 0))
            with c3: st.metric("Pendiente", formato_clp(df_pend.iloc[0]['monto_pend'] if not df_pend.empty and df_pend.iloc[0]['monto_pend'] else 0))
            with c4: st.metric("Bodega valorizado", formato_clp(df_bod_val.iloc[0]['valorizado'] if not df_bod_val.empty and df_bod_val.iloc[0]['valorizado'] else 0))
            st.dataframe(df_sol, use_container_width=True)
            st.dataframe(df_com, use_container_width=True)
            st.dataframe(df_metodo, use_container_width=True)
            st.info("Todos los reportes de funciones disponibles: reservas por institución, comensales, bodega valorizado, método pago (Transferencia/Débito local), glosa semanal/mensual, etc.")

        with tab_prod:
            st.markdown("#### 📦 Admin productos - Activar/desactivar")
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM platos ORDER BY servicio, nombre",conn); conn.close()
            st.dataframe(df, use_container_width=True)
            if not df.empty:
                id_prod=st.selectbox("ID producto", df['id'].tolist(), key="prod_id")
                col1,col2=st.columns(2)
                with col1:
                    if st.button("Desactivar producto", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE platos SET activo=0 WHERE id=?",(id_prod,)); conn.commit(); conn.close(); st.rerun()
                with col2:
                    if st.button("Activar producto", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE platos SET activo=1 WHERE id=?",(id_prod,)); conn.commit(); conn.close(); st.rerun()
            st.divider()
            st.markdown("##### Agregar nuevo producto")
            with st.form("add_plato"):
                nombre=st.text_input("Nombre plato*"); servicio=st.selectbox("Servicio", ["Desayuno","Almuerzo","Once","Cena"]); valor=st.number_input("Valor", value=6500, step=100); desc=st.text_input("Descripción")
                if st.form_submit_button("Agregar plato", type="primary", use_container_width=True):
                    if nombre:
                        conn=get_conn(); cur=conn.cursor(); cur.execute("INSERT INTO platos (nombre,servicio,valor,activo,descripcion) VALUES (?,?,?,?,?)",(nombre,servicio,valor,1,desc)); conn.commit(); conn.close(); st.success("Agregado"); st.rerun()

        with tab_minuta:
            st.markdown("#### 🍽️ Cargar minutas - Responsable admin")
            st.caption("Admin carga minutas por día y servicio, verifica y modifica valores")
            conn=get_conn(); df_min=pd.read_sql_query("SELECT * FROM minutas WHERE activo=1 ORDER BY dia_semana, servicio",conn); conn.close()
            st.dataframe(df_min, use_container_width=True)
            t1,t2=st.tabs(["➕ Agregar a minuta","✏️ Modificar valores"])
            with t1:
                with st.form("add_minuta"):
                    dia=st.selectbox("Día semana", ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"])
                    serv=st.selectbox("Servicio", ["Desayuno","Almuerzo","Once","Cena"], key="min_serv")
                    plato=st.text_input("Nombre plato*")
                    if st.form_submit_button("Agregar a minuta", type="primary", use_container_width=True):
                        if plato:
                            conn=get_conn(); cur=conn.cursor()
                            cur.execute("INSERT INTO minutas (dia_semana,servicio,plato,activo) VALUES (?,?,?,1)",(dia,serv,plato))
                            # También agrega a platos si no existe
                            cur.execute("SELECT id FROM platos WHERE nombre=?", (plato,))
                            if not cur.fetchone():
                                cur.execute("INSERT INTO platos (nombre,servicio,valor,activo) VALUES (?,?,?,1)",(plato,serv,6500))
                            conn.commit(); conn.close()
                            st.success(f"Minuta {dia} {serv} {plato} agregada"); st.rerun()
            with t2:
                conn=get_conn(); df_pl=pd.read_sql_query("SELECT id,nombre,servicio,valor FROM platos WHERE activo=1",conn); conn.close()
                if not df_pl.empty:
                    id_val=st.selectbox("Plato a modificar valor", df_pl['id'].tolist(), format_func=lambda x: f"{df_pl[df_pl['id']==x].iloc[0]['nombre']} - {formato_clp(df_pl[df_pl['id']==x].iloc[0]['valor'])}")
                    nuevo_valor=st.number_input("Nuevo valor", value=int(df_pl[df_pl['id']==id_val].iloc[0]['valor']), step=100)
                    if st.button("Actualizar valor", type="primary"):
                        conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE platos SET valor=? WHERE id=?",(nuevo_valor,id_val)); conn.commit(); conn.close(); st.success("Valor actualizado"); st.rerun()

        with tab_exc:
            st.markdown("#### ⚖️ Excepciones - Nueva regla: Todos estándar $6.400 + Selección por casilla con precio especial")
            st.caption("NUEVA REGLA: Por defecto todos pagan $6.400 estándar. Solo admin marca con ☑️ qué instituciones tienen precio especial (ej Alemsi 0 gratis, Chofer 3400) según su criterio. Solo aplica a seleccionadas.")
            conn=get_conn(); df_exc=pd.read_sql_query("SELECT * FROM excepciones_personas ORDER BY activa DESC, institucion",conn); df_inst_exc=pd.read_sql_query("SELECT nombre,precio_dia,precio_especial,regla_activa,descripcion FROM instituciones",conn); conn.close()
            st.markdown("##### Instituciones con regla especial")
            st.dataframe(df_inst_exc, use_container_width=True)
            st.markdown("##### Personas con excepción")
            st.dataframe(df_exc, use_container_width=True)
            te1,te2=st.tabs(["➕ Excepción persona","🏢 Regla institución"])
            with te1:
                with st.form("exc_pers"):
                    rut_exc=st.text_input("RUT persona* (ej 12345678-9)"); nombre_exc=st.text_input("Nombre*"); inst_exc=st.selectbox("Institución", get_instituciones(), key="exc_inst")
                    precio_exc=st.number_input("Precio especial* (0 = gratis)", value=0, step=100); desc_exc=st.text_input("Motivo", value="Excepción personal - no se cobra")
                    if st.form_submit_button("Guardar excepción persona", type="primary", use_container_width=True):
                        if rut_exc and nombre_exc:
                            if not validar_rut_m11(rut_exc):
                                st.error("RUT inválido")
                            else:
                                rn_db=normalizar_rut_db(rut_exc)
                                conn=get_conn(); cur=conn.cursor()
                                cur.execute("INSERT INTO excepciones_personas (rut,nombre,institucion,precio_especial,descripcion,activa,fecha_creacion) VALUES (?,?,?,?,?,?,?)",(rn_db,nombre_exc,inst_exc,precio_exc,desc_exc,1, datetime.now().isoformat()))
                                conn.commit(); conn.close()
                                st.success(f"Excepción {nombre_exc} {rn_db} {formato_clp(precio_exc)} creada")
                                st.rerun()
                if not df_exc.empty:
                    id_exc=st.selectbox("ID excepción para desactivar", df_exc['id'].tolist())
                    if st.button("Desactivar excepción", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE excepciones_personas SET activa=0 WHERE id=?",(id_exc,)); conn.commit(); conn.close(); st.rerun()
            with te2:
                st.markdown("###### ✅ NUEVA REGLA: Todos precio estándar $6.400 - Selecciona por casilla quién tiene precio especial")
                st.caption("Por defecto todos pagan estándar. Solo las instituciones que marques con ☑️ tendrán precio especial según tu criterio.")
                conn=get_conn(); df_inst_all=pd.read_sql_query("SELECT nombre, precio_dia, precio_especial, regla_activa, descripcion FROM instituciones ORDER BY nombre", conn); conn.close()
                st.markdown("**Selecciona instituciones con precio especial (casilla):**")
                # Crear formulario con checkboxes
                with st.form("form_reglas_casilla"):
                    cols = st.columns(2)
                    seleccionadas = {}
                    for idx, row in df_inst_all.iterrows():
                        col = cols[idx % 2]
                        with col:
                            activa_actual = bool(row['regla_activa'])
                            check = st.checkbox(f"{row['nombre']} - Actual: {formato_clp(row['precio_especial']) if row['precio_especial'] else 'Estándar'} {'✅' if activa_actual else ''}", value=activa_actual, key=f"chk_{row['nombre']}")
                            seleccionadas[row['nombre']] = check
                    st.divider()
                    st.markdown("**Define precio especial para las seleccionadas:**")
                    c1,c2=st.columns(2)
                    with c1:
                        precio_especial_global=st.number_input("Precio especial a aplicar (ej 3400 Chofer, 0 Alemsi gratis)", value=3400, step=100, help="Se aplicará a todas las que marcaste")
                    with c2:
                        motivo_global=st.text_input("Motivo / Criterio", value="Precio especial según criterio admin")
                    if st.form_submit_button("💾 Guardar precios especiales para seleccionadas", type="primary", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor()
                        actualizadas=0
                        for nombre, marcado in seleccionadas.items():
                            if marcado:
                                cur.execute("UPDATE instituciones SET precio_especial=?, regla_activa=1, descripcion=? WHERE nombre=?", (precio_especial_global, motivo_global, nombre))
                                actualizadas+=1
                            else:
                                cur.execute("UPDATE instituciones SET regla_activa=0, descripcion=? WHERE nombre=?", (f"Precio estándar {formato_clp(PRECIO_DIA_DEFAULT)} - sin regla", nombre))
                        conn.commit(); conn.close()
                        st.success(f"✅ Actualizadas {actualizadas} instituciones con precio especial {formato_clp(precio_especial_global)} - Resto vuelve a estándar {formato_clp(PRECIO_DIA_DEFAULT)}")
                        st.rerun()

                st.divider()
                st.markdown("**O asignación individual por institución:**")
                inst_rule=st.selectbox("Institución individual", df_inst_all['nombre'].tolist(), key="exc_rule_ind")
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT precio_dia,precio_especial,regla_activa,descripcion FROM instituciones WHERE nombre=?",(inst_rule,)); r=cur.fetchone(); conn.close()
                precio_actual=r[0] if r else 6400; precio_esp=r[1] if r and r[1] else None; activa=bool(r[2]) if r else False
                if activa and precio_esp:
                    st.success(f"ACTIVA: {inst_rule} paga {formato_clp(precio_esp)} (estándar {formato_clp(precio_actual)}) - Motivo: {r[3]}")
                else:
                    st.info(f"ESTÁNDAR: {inst_rule} paga {formato_clp(PRECIO_DIA_DEFAULT)} (sin regla especial)")
                with st.form("rule_inst_ind"):
                    nuevo_esp=st.number_input("Precio especial individual (0 = gratis)", value=int(precio_esp) if precio_esp else 3400, step=100)
                    activar=st.checkbox("Activar precio especial para esta institución", value=activa)
                    desc_rule=st.text_input("Motivo criterio", value=r[3] if r and r[3] else "")
                    if st.form_submit_button("Guardar individual", type="primary", use_container_width=True):
                        conn=get_conn(); cur=conn.cursor()
                        if activar:
                            cur.execute("UPDATE instituciones SET precio_especial=?, regla_activa=1, descripcion=? WHERE nombre=?",(nuevo_esp, desc_rule, inst_rule))
                        else:
                            cur.execute("UPDATE instituciones SET regla_activa=0, descripcion=? WHERE nombre=?", (f"Estándar - {desc_rule}", inst_rule))
                        conn.commit(); conn.close()
                        st.success(f"{'ACTIVADA' if activar else 'DESACTIVADA - vuelve a estándar'}: {inst_rule} -> {formato_clp(nuevo_esp) if activar else formato_clp(PRECIO_DIA_DEFAULT)}")
                        st.rerun()

        with tab_inst:
            st.markdown("#### 🏢 Admin Instituciones")
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM instituciones ORDER BY nombre", conn); conn.close()
            st.dataframe(df, use_container_width=True)
            with st.form("add_inst"):
                nombre=st.text_input("Nombre*"); precio=st.number_input("Precio día público", value=6400, step=100); desc=st.text_input("Descripción")
                if st.form_submit_button("Guardar institución", type="primary", use_container_width=True):
                    if nombre:
                        conn=get_conn(); cur=conn.cursor(); cur.execute("INSERT OR REPLACE INTO instituciones (nombre,precio_dia,activa,descripcion) VALUES (?,?,1,?)",(nombre,precio,desc)); conn.commit(); conn.close(); st.success("Guardada"); st.rerun()

        with tab_recl:
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM reclamos_sugerencias ORDER BY fecha DESC",conn); conn.close()
            st.dataframe(df, use_container_width=True)

    else:
        st.markdown("### 🏢 Administración - Login")
        with st.form("login_admin"):
            u=st.text_input("Usuario", key="u_admin"); p=st.text_input("Contraseña", type="password", key="p_admin")
            if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p))); row=cur.fetchone(); conn.close()
                if row and row[1] in ["Admin","Gerencia"]:
                    st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}; st.rerun()
                else: st.error("Solo admin/gerencia")

st.divider()
st.caption("V19 - Todo V18 intacto + Cocina 7+7 días + Recetas + Reporte 24h + Bodega CSV con log + Inventarios aleatorios OD + Finanzas glosa semanal/mensual + Admin minutas + Excepciones personales")
