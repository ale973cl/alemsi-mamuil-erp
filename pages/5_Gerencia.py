import streamlit as st, pandas as pd
from common import get_conn, formato_clp

st.set_page_config(page_title="Gerencia", layout="wide")
st.markdown("## 📊 Gerencia - Dashboard cruzado")

conn=get_conn()
tot=pd.read_sql_query("SELECT COUNT(*) c, SUM(precio) total FROM solicitudes",conn)
bodega=pd.read_sql_query("SELECT nombre_articulo,stock,critico FROM bodega_inventario",conn)
mermas=pd.read_sql_query("SELECT nombre_articulo, SUM(cantidad) cant FROM mermas GROUP BY nombre_articulo",conn)

c1,c2,c3=st.columns(3)
c1.metric("Solicitudes totales", int(tot.iloc[0]['c'] or 0))
c2.metric("Ventas totales", formato_clp(tot.iloc[0]['total'] or 0))
c3.metric("Insumos críticos", len(bodega[bodega['stock']<=bodega['critico']]))

st.markdown("### Stock crítico (validación automática)")
st.dataframe(bodega[bodega['stock']<=bodega['critico']], use_container_width=True)

st.markdown("### Mermas por insumo")
st.dataframe(mermas, use_container_width=True)

conn.close()
