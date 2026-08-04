import streamlit as st
from common import init_db, get_conn, hash_pwd, normalizar_rut, validar_rut_m11
import pandas as pd

st.set_page_config(page_title="Mamuil - Bienvenido", page_icon="🍽️", layout="wide")
init_db()

st.markdown("""
<style>
.main-header{background: linear-gradient(135deg,#0f3d2e 0%,#1e8a5d 100%); padding:28px; border-radius:18px; color:white; margin-bottom:20px}
.al-card{background:white; padding:20px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.08); border-left:4px solid #FFD400}
</style>
<div class="main-header"><h1>🍽️ Hola, bienvenido a selección de menú</h1><p>ALEMSI - Casino Mamuil Malal • Reserva tu alimentación</p></div>
""", unsafe_allow_html=True)

if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None

if st.session_state.usuario or st.session_state.rut_actual:
    st.success("Sesión activa - usa el menú lateral izquierdo 👈 para ir a tu app")
    if st.button("Cerrar sesión"):
        st.session_state.usuario=None; st.session_state.rut_actual=None; st.rerun()
    st.stop()

t1,t2=st.tabs(["🧑 SOY COMENSAL","🔐 PERSONAL CASINO"])

with t1:
    st.markdown('<div class="al-card"><h3>👋 Bienvenido</h3><p>Solo ingresa tu RUT para reservar tu menú semanal</p></div>', unsafe_allow_html=True)
    rut_raw=st.text_input("Ingresa tu RUT para reservar", placeholder="Ej: 12.345.678-9")
    if rut_raw:
        if not validar_rut_m11(rut_raw):
            st.error("RUT no válido, revisa e intenta nuevamente")
        else:
            rn=normalizar_rut(rut_raw)
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rn,)); conn.close()
            if not df.empty:
                st.success(f"Hola {df.iloc[0]['nombre']} 👋")
                if st.button("Continuar a selección de menú →", type="primary", use_container_width=True):
                    st.session_state.rut_actual=rn
                    st.info("👈 Ahora selecciona **Comensal** en el menú lateral izquierdo para continuar")
            else:
                st.info("¡Primera vez por aquí! Registrémonos rápido")
                with st.form("reg"):
                    nombre=st.text_input("Tu nombre completo*")
                    tel=st.text_input("Teléfono*")
                    correo=st.text_input("Correo* (te llegará tu ticket)")
                    if st.form_submit_button("Registrarme y elegir mi menú 🍽️", type="primary", use_container_width=True):
                        if nombre and tel and correo:
                            conn=get_conn(); cur=conn.cursor()
                            cur.execute("INSERT OR REPLACE INTO comensales VALUES (?,?,?,?,?)",(rn,nombre,tel,correo,"Mamuil"))
                            conn.commit(); conn.close()
                            st.session_state.rut_actual=rn
                            st.success("Registrado ✅")
                            st.info("👈 Ahora selecciona **Comensal** en el menú lateral izquierdo para continuar")
                        else: st.error("Completa todos los datos por favor")

with t2:
    st.markdown('<div class="al-card"><h3>Acceso personal casino</h3></div>', unsafe_allow_html=True)
    with st.form("login"):
        u=st.text_input("Usuario"); p=st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
            conn=get_conn(); cur=conn.cursor()
            cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p)))
            row=cur.fetchone(); conn.close()
            if row:
                st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}
                st.success(f"Bienvenido {row[2]} - Rol {row[1]}")
                st.info("👈 Selecciona tu módulo en el menú lateral izquierdo")
            else: st.error("Usuario: cocina/cocina123 | bodega/bodega123 | finanzas/finanzas123 | gerencia/gerencia123")
