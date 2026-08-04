import streamlit as st, pandas as pd
from datetime import date, timedelta
from common import get_conn, enviar_email, EMAILS, formato_clp

st.set_page_config(page_title="Cocina", layout="wide")
st.markdown("## 👨‍🍳 Cocina - Producción y Check-in")

t1,t2=st.tabs(["✅ Check-in voucher","📋 Producción semanal"])

with t1:
    cod=st.text_input("Código voucher")
    if st.button("Validar código"):
        conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT id,estado_consumo,estado_pago,rut,plato FROM solicitudes WHERE codigo=?",(cod.strip(),)); row=cur.fetchone()
        if not row: st.error("Código no existe")
        elif row[1]=="Consumido": st.warning("Ya consumido")
        elif row[2]!="Pagado" and row[2]!="Pendiente": st.error(f"Estado pago: {row[2]}")
        else:
            # Validar servicio activo
            cur.execute("UPDATE solicitudes SET estado_consumo='Consumido' WHERE id=?",(row[0],)); conn.commit(); st.success(f"✅ ACCESO OK - {row[4]} - {row[3]}"); st.balloons()
        conn.close()

with t2:
    d1=st.date_input("Desde", value=date.today()); d2=st.date_input("Hasta", value=date.today()+timedelta(days=6))
    conn=get_conn(); df=pd.read_sql_query("SELECT fecha,servicio,plato,COUNT(*) as cant, SUM(precio) as total FROM solicitudes WHERE fecha BETWEEN ? AND ? GROUP BY fecha,servicio,plato ORDER BY fecha,servicio",conn,params=(d1.isoformat(),d2.isoformat()))
    st.dataframe(df,use_container_width=True)
    c1,c2=st.columns(2)
    with c1:
        csv=df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Descargar producción CSV", csv, "produccion.csv")
    with c2:
        if st.button("📧 Enviar a ale973@gmail.com"):
            ok,msg=enviar_email(EMAILS['cocina'], f"Producción {d1} al {d2}", df.to_html())
            st.write(ok,msg)
    conn.close()
