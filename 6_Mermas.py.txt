import streamlit as st, pandas as pd
from datetime import date
from common import get_conn, enviar_email, EMAILS

st.set_page_config(page_title="Mermas", layout="wide")
st.markdown("## ⚠️ Mermas - Registro humano")

conn=get_conn()
df_inv=pd.read_sql_query("SELECT codigo_insumo, nombre_articulo, stock FROM bodega_inventario",conn)

with st.form("merma_form"):
    st.write("Registrar pérdida")
    insumo_sel=st.selectbox("Artículo", df_inv['nombre_articulo'].tolist())
    row=df_inv[df_inv['nombre_articulo']==insumo_sel].iloc[0]
    cant=st.number_input(f"Cantidad a dar de baja (stock actual {row['stock']})", min_value=0.01, step=0.1)
    motivo=st.selectbox("Motivo", ["Vencido","Quebrado","Mal almacenamiento","Error preparación","Otro"])
    fecha=st.date_input("Fecha merma", value=date.today())
    usuario=st.text_input("Responsable", value="cocina")
    if st.form_submit_button("Registrar merma y descontar stock"):
        cur=conn.cursor()
        cur.execute("INSERT INTO mermas (fecha,codigo_insumo,nombre_articulo,cantidad,motivo,usuario) VALUES (?,?,?,?,?,?)",(fecha.isoformat(),row['codigo_insumo'],insumo_sel,cant,motivo,usuario))
        cur.execute("UPDATE bodega_inventario SET stock=stock-? WHERE codigo_insumo=?",(cant,row['codigo_insumo']))
        conn.commit()
        st.success(f"Merma registrada: {insumo_sel} -{cant}. Descontado de bodega y visible para gerencia.")
        # Notificar
        html=f"<h3>Merma {fecha}</h3><p>{insumo_sel} {cant} - {motivo} - {usuario}</p>"
        enviar_email(EMAILS['gerencia'], f"Merma {insumo_sel} {cant}", html)
        enviar_email(EMAILS['cocina'], f"Merma registrada {insumo_sel}", html)

st.divider()
st.markdown("### Historial mermas")
df_m=pd.read_sql_query("SELECT * FROM mermas ORDER BY fecha DESC",conn)
st.dataframe(df_m, use_container_width=True)

c1,c2=st.columns(2)
with c1:
    csv=df_m.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Descargar CSV mermas", csv, "mermas.csv")
with c2:
    if st.button("📧 Enviar historial mermas a gerencia"):
        ok,msg=enviar_email(EMAILS['gerencia'], f"Mermas {date.today()}", df_m.to_html())
        st.write(ok,msg)

conn.close()
