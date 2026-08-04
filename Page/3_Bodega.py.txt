import streamlit as st
import pandas as pd
from datetime import date, timedelta
from common import get_conn

st.set_page_config(page_title="Bodega", layout="wide")
st.markdown("## 📦 Bodega - Lógica humana con buscador + imagen + carga masiva")

conn=get_conn()
# Buscador humano
q=st.text_input("🔍 Buscar insumo (ej: pollo, arroz, huevo)", placeholder="Escribe para filtrar...")
df=pd.read_sql_query("SELECT * FROM bodega_inventario",conn)

# Mapeo emoji humano por insumo
emoji_map={"arroz":"🍚","pollo":"🍗","carne":"🥩","huevo":"🥚","papa":"🥔","lenteja":"🫘","leche":"🥛","pan":"🍞"}
def get_emoji(nombre):
    for k,v in emoji_map.items():
        if k in nombre.lower(): return v
    return "📦"

if q:
    df=df[df['nombre_articulo'].str.contains(q, case=False, na=False)]

# Mostrar como botones con imagen (cards)
cols=st.columns(4)
for i, (_,row) in enumerate(df.iterrows()):
    with cols[i%4]:
        emoji=get_emoji(row['nombre_articulo'])
        stock=row['stock']
        color="🟢" if stock>row['critico'] else "🔴"
        st.markdown(f"### {emoji} {row['nombre_articulo']}\n{color} Stock: {stock} {row['unidad']}")
        if stock<=row['critico']: st.error(f"Bajo crítico {row['critico']}")
        else: st.caption(f"Crítico: {row['critico']} | ${row['precio']}")

st.divider()
st.markdown("### 📥📤 Carga masiva y descarga")

c1,c2,c3=st.columns(3)
with c1:
    st.markdown("**Descargar inventario actual**")
    csv=df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Descargar CSV", csv, "inventario_actual.csv", "text/csv")
    # PDF simple via HTML
    html_pdf=df.to_html()
    st.download_button("📄 Descargar como HTML (para PDF)", html_pdf, "inventario.html", "text/html")

with c2:
    st.markdown("**Subir CSV para sumar stock** (lógica: stock existente + nuevo)")
    st.caption("Formato CSV: codigo_insumo,cantidad  o nombre_articulo,cantidad")
    up=st.file_uploader("Sube CSV", type=["csv"])
    if up:
        try:
            up_df=pd.read_csv(up)
            st.dataframe(up_df.head())
            if st.button("✅ Sumar al stock existente"):
                conn=get_conn(); cur=conn.cursor()
                sumados=0
                for _,r in up_df.iterrows():
                    codigo=r.get('codigo_insumo') or r.get('codigo')
                    nombre=r.get('nombre_articulo') or r.get('nombre')
                    cant=float(r.get('cantidad',0))
                    if codigo:
                        cur.execute("UPDATE bodega_inventario SET stock=stock+? WHERE codigo_insumo=?",(cant,codigo))
                        if cur.rowcount==0 and nombre:
                            cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca) VALUES (?,?,?,?,?,?,?)",(codigo,nombre,'kilo',cant,0,5,'2027-01-01'))
                        sumados+=1
                    elif nombre:
                        cur.execute("UPDATE bodega_inventario SET stock=stock+? WHERE nombre_articulo LIKE ?", (cant,f"%{nombre}%"))
                        sumados+=1
                conn.commit(); conn.close()
                st.success(f"Stock sumado en {sumados} filas. Valida abajo.")
                st.rerun()
        except Exception as e: st.error(f"Error CSV: {e}")

with c3:
    st.markdown("**Enviar reporte por correo**")
    email_dest=st.text_input("Email destino", value="ale973@gmail.com")
    if st.button("📧 Enviar inventario por email"):
        from common import enviar_email
        html=f"<h3>Inventario Mamuil {date.today()}</h3>{df.to_html()}"
        ok,msg=enviar_email(email_dest,f"Inventario {date.today()} - Mamuil",html)
        if ok: st.success(f"Enviado a {email_dest}")
        else: st.error(msg)

conn.close()
st.divider()
st.caption("Validación cruzada: cada reserva descuenta aquí. Si stock < crítico, no se podrá reservar ese plato (lo validamos en comensal).")
