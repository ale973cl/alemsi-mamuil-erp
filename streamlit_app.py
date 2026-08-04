
import streamlit as st
from common import init_db, get_conn, hash_pwd, normalizar_rut, validar_rut_m11, apply_alemsi_style
import pandas as pd

st.set_page_config(page_title="ALEMSI - Mamuil ERP", page_icon="🍽️", layout="wide")
apply_alemsi_style()
init_db()

st.markdown("""<div class="main-header"><h1>🍽️ Mamuil Malal ERP</h1><p>ALEMSI - Aseo y Servicios Integrales | Sistema modular</p></div>""", unsafe_allow_html=True)

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None

if st.session_state.usuario or st.session_state.rut_actual:
    st.success("Sesión activa - usa el menú lateral izquierdo")
    if st.button("Cerrar sesión", type="secondary"):
        st.session_state.usuario=None; st.session_state.rut_actual=None; st.rerun()
    st.stop()

t1,t2=st.tabs(["🧑 SOY COMENSAL","🔐 PERSONAL CASINO"])

with t1:
    st.markdown('<div class="al-card"><h3>Reserva semanal</h3><p>Escribe tu RUT como quieras: 16.632.880-2 = 16632880-2</p></div>', unsafe_allow_html=True)
    rut_raw=st.text_input("RUT", placeholder="16.632.880-2")
    if rut_raw:
        if not validar_rut_m11(rut_raw):
            st.error("RUT inválido")
        else:
            rn=normalizar_rut(rut_raw)
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rn,)); conn.close()
            if not df.empty:
                st.success(f"Hola {df.iloc[0]['nombre']} - {rn}")
                if st.button("Entrar a Comensal →", type="primary"):
                    st.session_state.rut_actual=rn
                    st.switch_page("page/1_Comensal.py")
            else:
                st.info(f"Primera vez - se guardará como {rn}")
                with st.form("reg"):
                    nombre=st.text_input("Nombre*"); tel=st.text_input("Teléfono*"); correo=st.text_input("Correo*")
                    if st.form_submit_button("Registrarme y continuar", type="primary"):
                        if nombre and tel and correo:
                            conn=get_conn(); cur=conn.cursor()
                            cur.execute("INSERT OR REPLACE INTO comensales VALUES (?,?,?,?,?)",(rn,nombre,tel,correo,"Mamuil"))
                            conn.commit(); conn.close()
                            st.session_state.rut_actual=rn
                            st.switch_page("page/1_Comensal.py")
                        else: st.error("Faltan datos")

with t2:
    st.markdown('<div class="al-card">', unsafe_allow_html=True)
    with st.form("login"):
        u=st.text_input("Usuario"); p=st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            conn=get_conn(); cur=conn.cursor()
            cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p)))
            row=cur.fetchone(); conn.close()
            if row:
                st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}
                if row[1]=="Cocina": st.switch_page("page/2_Cocina.py")
                elif row[1]=="Finanzas": st.switch_page("page/4_Finanzas.py")
                elif row[1]=="Gerencia": st.switch_page("page/5_Gerencia.py")
                else: st.switch_page("page/1_Comensal.py")
            else: st.error("Usuario: admin/admin123 | cocina/cocina123 | finanzas/finanzas123 | gerencia/gerencia123")
    st.markdown('</div>', unsafe_allow_html=True)
