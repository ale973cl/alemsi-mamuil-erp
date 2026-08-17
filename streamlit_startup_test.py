import streamlit as st
from sqlalchemy import text
from datetime import datetime

st.set_page_config(
    page_title="ALEMSI · Prueba de arranque",
    page_icon="🧪",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background: linear-gradient(145deg,#f8fbfa,#eef8f5);
}
.alemsi-box {
    border: 1px solid #dcebe6;
    background: white;
    border-radius: 16px;
    padding: 22px;
    margin: 12px 0;
}
.ok { color:#087443; font-weight:700; }
.warn { color:#b26a00; font-weight:700; }
.bad { color:#b42318; font-weight:700; }
</style>
""", unsafe_allow_html=True)

st.title("🧪 ALEMSI · Prueba de arranque")
st.caption("Diagnóstico temporal · no modifica datos ni ejecuta migraciones")

st.info(
    "Este archivo NO llama a init_db(), NO crea tablas, NO ejecuta ALTER/UPDATE "
    "y NO modifica información de producción."
)

def get_conn_probe():
    return st.connection("postgresql", type="sql")

st.markdown("### 1. Arranque de Streamlit")
st.markdown('<div class="alemsi-box"><span class="ok">✅ Streamlit inició correctamente.</span></div>',
            unsafe_allow_html=True)

st.markdown("### 2. Conexión PostgreSQL / Supabase")

try:
    conn = get_conn_probe()
    st.markdown('<div class="alemsi-box"><span class="ok">✅ Objeto de conexión creado.</span></div>',
                unsafe_allow_html=True)

    df_ping = conn.query(
        "SELECT current_database() AS base, current_timestamp AS fecha_hora",
        ttl=0,
    )

    if not df_ping.empty:
        st.success("✅ PostgreSQL respondió correctamente.")
        st.dataframe(df_ping, use_container_width=True, hide_index=True)
    else:
        st.warning("La consulta respondió, pero no devolvió filas.")

except Exception as exc:
    st.error("❌ No fue posible conectar con PostgreSQL.")
    st.code(str(exc))
    st.stop()

st.markdown("### 3. Tablas esenciales ALEMSI")

tablas = [
    "comensales",
    "solicitudes",
    "instituciones",
    "minutas",
    "platos",
    "usuarios",
    "comprobantes_pago",
]

resultados = []

for tabla in tablas:
    try:
        df = conn.query(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name=:tabla
            ) AS existe
            """,
            params={"tabla": tabla},
            ttl=0,
        )
        existe = bool(df.iloc[0]["existe"]) if not df.empty else False

        cantidad = None
        if existe:
            # El nombre proviene exclusivamente de la lista interna anterior.
            df_count = conn.query(f'SELECT COUNT(*) AS cantidad FROM "{tabla}"', ttl=0)
            cantidad = int(df_count.iloc[0]["cantidad"]) if not df_count.empty else 0

        resultados.append({
            "Tabla": tabla,
            "Existe": "✅ Sí" if existe else "❌ No",
            "Registros": cantidad if cantidad is not None else "—",
        })

    except Exception as exc:
        resultados.append({
            "Tabla": tabla,
            "Existe": "⚠️ Error",
            "Registros": str(exc)[:100],
        })

st.dataframe(resultados, use_container_width=True, hide_index=True)

st.markdown("### 4. Lectura de datos sin información personal")

try:
    df_reservas = conn.query(
        """
        SELECT
            COUNT(*) AS reservas_totales,
            COUNT(*) FILTER (
                WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA'
            ) AS reservas_activas
        FROM solicitudes
        """,
        ttl=0,
    )

    if not df_reservas.empty:
        c1, c2 = st.columns(2)
        c1.metric("Reservas totales", int(df_reservas.iloc[0]["reservas_totales"] or 0))
        c2.metric("Reservas activas", int(df_reservas.iloc[0]["reservas_activas"] or 0))

    st.success("✅ Lectura de datos operativa.")

except Exception as exc:
    st.warning("La conexión funciona, pero falló la consulta de reservas.")
    st.code(str(exc))

st.divider()
st.caption(f"Prueba ejecutada: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
st.caption("ALEMSI · Mamuil Malal · Diagnóstico temporal")
