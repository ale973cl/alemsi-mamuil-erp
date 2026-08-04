import streamlit as st, pandas as pd
from datetime import date
from common import get_conn, enviar_email, EMAILS, formato_clp

st.set_page_config(page_title="Finanzas", layout="wide")
st.markdown("## 💰 Finanzas - Validar pagos y reportes")

conn=get_conn()
df=pd.read_sql_query("SELECT s.id,c.rut,c.nombre,s.fecha,s.servicio,s.plato,s.precio,s.estado_pago FROM solicitudes s JOIN comensales c ON s.rut=c.rut ORDER BY s.id DESC",conn)
st.dataframe(df,use_container_width=True)

c1,c2=st.columns(2)
with c1:
    idp=st.number_input("ID a pagar", min_value=0, step=1)
    if st.button("Marcar Pagado"):
        cur=conn.cursor(); cur.execute("UPDATE solicitudes SET estado_pago='Pagado' WHERE id=?",(idp,)); conn.commit(); st.success("Pagado")
with c2:
    st.markdown("### Reportes")
    csv=df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Descargar CSV", csv, "finanzas.csv", "text/csv")
    if st.button("📧 Enviar a finanzas@alemsi.cl"):
        ok,msg=enviar_email(EMAILS['finanzas'], f"Reporte finanzas {date.today()} - Total {formato_clp(df['precio'].sum() if not df.empty else 0)}", df.to_html())
        st.write(ok,msg)
    if st.button("📧 Enviar a gerencia@alemsi.cl"):
        ok,msg=enviar_email(EMAILS['gerencia'], f"Reporte finanzas {date.today()}", df.to_html())
        st.write(ok,msg)

conn.close()
