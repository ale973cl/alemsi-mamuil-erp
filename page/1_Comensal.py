
import streamlit as st, pandas as pd
from datetime import date, timedelta
from common import get_conn, get_precio, gen_codigo, descontar_bodega, formato_clp, enviar_email, EMAILS, MINUTA, apply_alemsi_style
st.set_page_config(page_title="Comensal", layout="wide")
apply_alemsi_style()
if "rut_actual" not in st.session_state or not st.session_state.rut_actual:
    st.warning("Debes loguearte en la página principal"); st.stop()
rut=st.session_state.rut_actual
conn=get_conn(); com=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
if com.empty: st.error("RUT no encontrado"); st.stop()
nombre=com.iloc[0]['nombre']
st.markdown(f'<div class="main-header"><h1>Hola {nombre} 👋</h1><p>Reserva semanal - ALEMSI</p></div>', unsafe_allow_html=True)
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}
if not st.session_state.dias_sel:
    st.markdown("### 📅 Paso 1: ¿Qué días?")
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
    if st.session_state.dias_sel and st.button("Siguiente → Menú", type="primary"):
        st.session_state.dias_sel=sorted(st.session_state.dias_sel)
        st.session_state.pedidos={d:{} for d in st.session_state.dias_sel}
        st.session_state.wizard_idx=0; st.rerun()
    st.stop()
dias=sorted(st.session_state.dias_sel); idx=st.session_state.wizard_idx
if idx>=len(dias):
    total=0; detalle=[]
    for f_iso in dias:
        dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(f_iso).weekday()]
        for serv,plato in st.session_state.pedidos.get(f_iso,{}).items():
            pr=get_precio(plato,serv); total+=pr; detalle.append((f_iso,dnom,serv,plato,pr))
    df=pd.DataFrame(detalle, columns=["Fecha","Día","Servicio","Plato","Precio"])
    st.markdown('<div class="al-card"><h3>Resumen</h3></div>', unsafe_allow_html=True)
    st.dataframe(df, use_container_width=True)
    st.metric("Total", formato_clp(total))
    if st.button("✅ FINALIZAR RESERVA", type="primary", use_container_width=True):
        conn=get_conn(); cur=conn.cursor(); vouchers=[]
        for f_iso,dnom,serv,plato,pr in detalle:
            cod=gen_codigo(rut,serv,date.fromisoformat(f_iso))
            cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago) VALUES (?,?,?,?,?,?,?)",(rut,f_iso,serv,plato,cod,pr,"Pendiente"))
            vouchers.append(cod)
            descontar_bodega(plato)
        conn.commit(); conn.close()
        html=f"<h3>Ticket {nombre}</h3>{df.to_html()}<p>Total {formato_clp(total)}</p><p>Códigos: {', '.join(vouchers)}</p>"
        conn=get_conn(); dfc=pd.read_sql_query("SELECT correo FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
        correo_cli=dfc.iloc[0]['correo'] if not dfc.empty else None
        if correo_cli: enviar_email(correo_cli,"Ticket Mamuil",html)
        enviar_email(EMAILS['cocina'],f"Orden cocina {nombre}",html)
        enviar_email(EMAILS['finanzas'],f"Reserva {formato_clp(total)} {nombre}",html)
        st.success(f"Reserva OK - Códigos: {', '.join(vouchers)}"); st.balloons()
    if st.button("Cancelar todo", type="secondary"):
        st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.rerun()
    st.stop()
f_act=dias[idx]; d_obj=date.fromisoformat(f_act)
dnom=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][d_obj.weekday()]
st.markdown(f'<div class="main-header"><h1>{dnom} {d_obj.strftime("%d/%m")} ({idx+1}/{len(dias)})</h1><p>Elige 1 plato por servicio</p></div>', unsafe_allow_html=True)
if f_act not in st.session_state.pedidos: st.session_state.pedidos[f_act]={}
for serv in ["Desayuno","Almuerzo","Once","Cena"]:
    ops=MINUTA.get(dnom,{}).get(serv,[])
    if not ops: continue
    st.markdown(f"#### {serv}")
    cols=st.columns(2)
    for i,plato in enumerate(ops):
        sel=st.session_state.pedidos[f_act].get(serv)==plato
        with cols[i%2]:
            if st.button(f"{plato} - {formato_clp(get_precio(plato,serv))}", key=f"{f_act}_{serv}_{plato}", type="primary" if sel else "secondary", use_container_width=True):
                if sel: del st.session_state.pedidos[f_act][serv]
                else: st.session_state.pedidos[f_act][serv]=plato
                st.rerun()
c1,c2=st.columns(2)
with c1:
    if st.button("← Anterior", disabled=idx==0): st.session_state.wizard_idx-=1; st.rerun()
with c2:
    if idx < len(dias)-1:
        if st.button("Siguiente →", type="primary"): st.session_state.wizard_idx+=1; st.rerun()
    else:
        if st.button("Ver resumen", type="primary"): st.session_state.wizard_idx+=1; st.rerun()
