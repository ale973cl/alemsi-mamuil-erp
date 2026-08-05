import hashlib
import re
import random
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from pathlib import Path
import csv
import streamlit as st
from sqlalchemy import text

# Configuración
EMAILS = {
    "cocina": "ale973@gmail.com",
    "finanzas": "finanzas@alemsi.cl",
    "gerencia": "gerencia@alemsi.cl",
    "reclamos": ["ale973@gmail.com", "araucaniashop@gmail.com"],
}
PRECIO_DIA_DEFAULT = 6400

MINUTA = {
    "Lunes": {"Desayuno": ["Desayuno americano", "Té + pan con huevo", "Avena + fruta"], "Almuerzo": ["Carbonada", "Lentejas con arroz", "Pollo asado con puré"], "Once": ["Té + pan con palta", "Té + sándwich ave"], "Cena": ["Crema + sandwich", "Tallarines"]},
    "Martes": {"Desayuno": ["Desayuno americano", "Yogurt + granola"], "Almuerzo": ["Cazuela vacuno", "Porotos con riendas", "Chuleta con arroz"], "Once": ["Té + pan con huevo"], "Cena": ["Charquicán"]},
    "Miércoles": {"Desayuno": ["Desayuno continental"], "Almuerzo": ["Pastel de papas", "Garbanzos con mote", "Pescado frito"], "Once": ["Té + pan con palta"], "Cena": ["Carbonada"]},
    "Jueves": {"Desayuno": ["Desayuno americano"], "Almuerzo": ["Pollo al jugo", "Lentejas con longaniza", "Pollo arvejado", "Puré con carne"], "Once": ["Té + jamón queso"], "Cena": ["Porotos"]},
    "Viernes": {"Desayuno": ["Desayuno completo"], "Almuerzo": ["Cazuela ave", "Fideos boloñesa", "Asado olla"], "Once": ["Té + pan"], "Cena": ["Chupe jurel"]},
    "Sábado": {"Desayuno": ["Desayuno americano"], "Almuerzo": ["Carbonada", "Arroz con pollo"], "Once": ["Té + pan"], "Cena": ["Sopa + sándwich"]},
}

def apply_alemsi_style():
    try:
        st.markdown('''
        <style>
        :root{--alemsi-blue:#0A2F6B; --alemsi-yellow:#FFD400; --alemsi-bg:#F8F9FA; --alemsi-border:#E9ECEF;}
        html, body, [data-testid="stAppViewContainer"]{background:var(--alemsi-bg) !important;}
        .main-header{background:linear-gradient(135deg,var(--alemsi-blue) 0%, #123E7A 100%); padding:28px 32px; border-radius:12px; color:white; margin-bottom:20px;}
        .al-card{background:white; border:1px solid var(--alemsi-border); border-radius:12px; padding:18px 20px; margin:12px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);}
        div[data-testid="stButton"]>button{border-radius:12px !important; font-weight:700 !important; min-height:44px;}
        </style>
        ''', unsafe_allow_html=True)
    except:
        pass

# === CONEXIÓN NATIVA POSTGRESQL ===
def get_conn():
    """Conexión nativa Streamlit PostgreSQL - usa st.secrets.toml [connections.postgresql]"""
    try:
        return st.connection("postgresql", type="sql")
    except Exception as e:
        st.error(f"Error conexión PostgreSQL: {e} - Verifica st.secrets [connections.postgresql]")
        raise



def execute_sql(session, statement: str, params=()):
    """Ejecuta SQL posicional (%s) de forma compatible con SQLAlchemy 2.x."""
    if isinstance(params, dict):
        return session.execute(text(statement), params)
    values = tuple(params or ())
    parts = statement.split("%s")
    if len(parts) - 1 != len(values):
        if values:
            raise ValueError("La cantidad de parámetros no coincide con los marcadores %s")
        return session.execute(text(statement))
    named = []
    bind = {}
    for idx, part in enumerate(parts[:-1]):
        named.append(part)
        named.append(f":p{idx}")
        bind[f"p{idx}"] = values[idx]
    named.append(parts[-1])
    return session.execute(text("".join(named)), bind)


def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()

def formato_clp(v):
    try: return f"${int(v):,}".replace(",", ".")
    except: return str(v)

def limpiar_rut(rut: str) -> str:
    if not rut: return ""
    return re.sub(r'[^0-9Kk]', '', rut).upper()

def normalizar_rut(rut: str) -> str:
    if not rut: return ""
    limpio = limpiar_rut(rut)
    if len(limpio) < 2: return limpio
    cuerpo = limpio[:-1]; dv = limpio[-1]
    rev = cuerpo[::-1]; cf=""
    for i,c in enumerate(rev):
        if i>0 and i%3==0: cf+="."
        cf+=c
    return f"{cf[::-1]}-{dv}"

def normalizar_rut_db(rut: str) -> str:
    limpio = limpiar_rut(rut)
    if len(limpio) < 2: return limpio
    return f"{limpio[:-1]}-{limpio[-1]}"

def validar_rut_m11(rut: str) -> bool:
    try:
        limpio = limpiar_rut(rut)
        if len(limpio) < 2: return False
        cuerpo = limpio[:-1]; dv = limpio[-1]
        if not cuerpo.isdigit() or len(cuerpo)<1 or len(cuerpo)>8: return False
        suma, mult = 0,2
        for d in reversed(cuerpo):
            suma+=int(d)*mult
            mult=2 if mult==7 else mult+1
        resto=11-(suma%11)
        dv_calc={11:"0",10:"K"}.get(resto,str(resto))
        return dv_calc==dv
    except: return False

def gen_codigo(rut, serv, fecha_obj): 
    return f"{limpiar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha_obj.strftime('%d%m')}-{random.randint(100,999)}"

@st.cache_data(ttl=300, show_spinner=False)
def get_instituciones():
    try:
        conn = get_conn()
        df = conn.query("SELECT nombre FROM instituciones WHERE activa=1 ORDER BY nombre", ttl=300)
        if not df.empty:
            return df['nombre'].tolist()
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad"]
    except:
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad"]

@st.cache_data(ttl=120, show_spinner=False)
def get_precio_institucion(institucion: str):
    try:
        conn=get_conn()
        df = conn.query("SELECT precio_dia, precio_especial, regla_activa FROM instituciones WHERE nombre=:institucion", params={"institucion": institucion}, ttl=120)
        if not df.empty:
            pdia,pesp,act=df.iloc[0]
            if act and pesp is not None: return int(pesp)
            return int(pdia)
        return PRECIO_DIA_DEFAULT
    except: return PRECIO_DIA_DEFAULT

@st.cache_data(ttl=60, show_spinner=False)
def get_precio_persona_institucion(rut: str, institucion: str):
    try:
        conn=get_conn()
        df = conn.query("SELECT precio_especial, descripcion FROM excepciones_personas WHERE rut=:rut AND activa=1", params={"rut": normalizar_rut_db(rut)}, ttl=60)
        if not df.empty:
            return int(df.iloc[0]['precio_especial']), f"Excepción: {df.iloc[0]['descripcion']}"
    except: pass
    precio = get_precio_institucion(institucion)
    return precio, f"Institución {institucion}"


@st.cache_data(ttl=120, show_spinner=False)
def get_precios_platos():
    """Carga los precios activos en una sola consulta para evitar una consulta por botón."""
    try:
        conn = get_conn()
        df = conn.query("SELECT nombre, valor FROM platos WHERE activo=1", ttl=120)
        if df.empty:
            return {}
        return {str(row["nombre"]): int(row["valor"]) for _, row in df.iterrows()}
    except Exception:
        return {}

def get_precio(plato, servicio):
    precios = get_precios_platos()
    return int(precios.get(plato, 3500))

@st.cache_data(ttl=300, show_spinner=False)
def get_minutas_rango(fecha_inicio: str, fecha_fin: str):
    """Carga en una sola consulta la minuta de un rango para el formulario de reservas."""
    try:
        conn = get_conn()
        return conn.query(
            """
            SELECT fecha, dia_semana, servicio, tipo_opcion, plato
            FROM minutas
            WHERE activo=1 AND fecha BETWEEN :inicio AND :fin
            ORDER BY fecha,
                     CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,
                     CASE tipo_opcion WHEN 'Opción 1' THEN 1 WHEN 'Opción 2' THEN 2 WHEN 'Hipocalórico' THEN 3 ELSE 4 END,
                     id
            """,
            params={"inicio": fecha_inicio, "fin": fecha_fin},
            ttl=300,
        )
    except Exception:
        return pd.DataFrame(columns=["fecha", "dia_semana", "servicio", "tipo_opcion", "plato"])


def descontar_bodega(plato):
    """Descuenta insumos por FEFO dentro de una única transacción."""
    try:
        conn = get_conn()
        with conn.session as session:
            recetas = execute_sql(
                session,
                "SELECT insumo, cantidad FROM recetas WHERE plato=%s",
                (plato,),
            ).mappings().all()
            for receta in recetas:
                pendiente = float(receta["cantidad"] or 0)
                if pendiente <= 0:
                    continue
                lotes = execute_sql(
                    session,
                    """
                    SELECT id, stock
                    FROM bodega_inventario
                    WHERE nombre_articulo ILIKE %s AND stock > 0
                    ORDER BY caduca ASC NULLS LAST, id ASC
                    FOR UPDATE
                    """,
                    (f"%{receta['insumo']}%",),
                ).mappings().all()
                for lote in lotes:
                    if pendiente <= 0:
                        break
                    descuento = min(float(lote["stock"] or 0), pendiente)
                    execute_sql(
                        session,
                        "UPDATE bodega_inventario SET stock=GREATEST(stock-%s, 0) WHERE id=%s",
                        (descuento, lote["id"]),
                    )
                    pendiente -= descuento
            session.commit()
    except Exception:
        # El descuento de inventario no debe anular una reserva ya confirmada.
        return False
    return True

def enviar_email(destino, asunto, html):
    """Mantiene operación nativa con SMTP Gmail - lee st.secrets [email]"""
    try:
        cfg=st.secrets.get("email",{})
        if not cfg:
            return False, "Secrets [email] no configurado - Configura smtp_server, smtp_port, email_user, email_pass en formato TOML"
        server=smtplib.SMTP(cfg["smtp_server"], int(cfg["smtp_port"]), timeout=20)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(cfg["email_user"],cfg["email_pass"])
        msg=MIMEMultipart()
        msg["From"]=cfg["email_user"]
        msg["To"]=destino
        msg["Subject"]=asunto
        msg.attach(MIMEText(html,"html"))
        server.send_message(msg)
        server.quit()
        return True,"OK"
    except Exception as e:
        return False,str(e)

def init_db():
    """Inicialización PostgreSQL con %s y tabla solicitudes nativa con plato_reservado, metodo_pago, estado_pago DEFAULT 'Pendiente'"""
    conn = get_conn()
    try:
        with conn.session as s:
            # Usuarios
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS usuarios (
                    username TEXT PRIMARY KEY,
                    pwd TEXT,
                    rol TEXT,
                    nombre TEXT
                )
            """)
            # Comensales
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS comensales (
                    rut TEXT PRIMARY KEY,
                    nombre TEXT,
                    telefono TEXT,
                    correo TEXT,
                    institucion TEXT,
                    fecha_registro TEXT
                )
            """)
            # Instituciones - precio estándar $6400
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS instituciones (
                    nombre TEXT PRIMARY KEY,
                    precio_dia INTEGER DEFAULT 6400,
                    precio_especial INTEGER,
                    regla_activa INTEGER DEFAULT 0,
                    activa INTEGER DEFAULT 1,
                    descripcion TEXT
                )
            """)
            # Excepciones personas
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS excepciones_personas (
                    id SERIAL PRIMARY KEY,
                    rut TEXT,
                    nombre TEXT,
                    institucion TEXT,
                    precio_especial INTEGER,
                    descripcion TEXT,
                    activa INTEGER DEFAULT 1,
                    fecha_creacion TEXT
                )
            """)
            # Platos
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS platos (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT,
                    servicio TEXT,
                    valor INTEGER,
                    activo INTEGER DEFAULT 1,
                    descripcion TEXT
                )
            """)
            # Minutas
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS minutas (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    dia_semana TEXT,
                    servicio TEXT,
                    tipo_opcion TEXT,
                    plato TEXT,
                    activo INTEGER DEFAULT 1
                )
            """)
            # Solicitudes - ESTRUCTURA NATIVA POSTGRESQL CON COLUMNAS SOLICITADAS
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS solicitudes (
                    id SERIAL PRIMARY KEY,
                    rut TEXT,
                    fecha TEXT,
                    servicio TEXT,
                    plato TEXT,
                    plato_reservado TEXT,
                    codigo TEXT,
                    precio INTEGER,
                    precio_aplicado INTEGER,
                    institucion TEXT,
                    correo TEXT,
                    metodo_pago TEXT,
                    estado_pago TEXT DEFAULT 'Pendiente',
                    estado_consumo TEXT DEFAULT 'Pendiente',
                    fecha_creacion TEXT
                )
            """)
            # Bodega
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS bodega_inventario (
                    id SERIAL PRIMARY KEY,
                    codigo_insumo TEXT,
                    nombre_articulo TEXT,
                    unidad TEXT,
                    stock REAL,
                    precio INTEGER,
                    critico REAL,
                    caduca TEXT,
                    seccion TEXT DEFAULT 'General',
                    foto_path TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS recetas (
                    id SERIAL PRIMARY KEY,
                    plato TEXT,
                    insumo TEXT,
                    cantidad REAL,
                    unidad TEXT DEFAULT 'kilo',
                    instrucciones TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS mermas (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    codigo_insumo TEXT,
                    nombre_articulo TEXT,
                    cantidad REAL,
                    motivo TEXT,
                    usuario TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS bodega_cargas_log (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    archivo TEXT,
                    cantidad INTEGER,
                    responsable TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS inventarios_aleatorios (
                    id SERIAL PRIMARY KEY,
                    fecha_generada TEXT,
                    fecha_programada TEXT,
                    seccion TEXT,
                    articulos TEXT,
                    responsable TEXT,
                    estado TEXT DEFAULT 'Pendiente',
                    fecha_realizado TEXT,
                    resultado TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS reclamos_sugerencias (
                    id SERIAL PRIMARY KEY,
                    rut TEXT,
                    nombre TEXT,
                    tipo TEXT,
                    categoria TEXT,
                    mensaje TEXT,
                    fecha TEXT,
                    estado TEXT DEFAULT 'Pendiente'
                )
            """)
            # Migraciones idempotentes para instalaciones existentes
            for column_sql in [
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS plato_reservado TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS metodo_pago TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS estado_pago TEXT DEFAULT 'Pendiente'",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS estado_consumo TEXT DEFAULT 'Pendiente'",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS precio_aplicado INTEGER",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS institucion TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS correo TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS fecha_creacion TEXT",
                "ALTER TABLE minutas ADD COLUMN IF NOT EXISTS fecha TEXT",
                "ALTER TABLE minutas ADD COLUMN IF NOT EXISTS tipo_opcion TEXT",
            ]:
                execute_sql(s, column_sql)

            # Usuarios por defecto con %s
            usuarios_default = [
                ("admin","admin123","Admin","Admin"),
                ("cocina","cocina123","Cocina","Cocina"),
                ("bodega","bodega123","Bodega","Bodega"),
                ("finanzas","finanzas123","Finanzas","Finanzas"),
                ("gerencia","gerencia123","Gerencia","Gerencia")
            ]
            for u,p,r,n in usuarios_default:
                execute_sql(s, "INSERT INTO usuarios (username,pwd,rol,nombre) VALUES (%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING", (u, hash_pwd(p), r, n))

            # Instituciones con precio estándar $6400 - usando %s
            instituciones_default = [
                ("Carabineros", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("PDI", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("SAG", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("Aduana", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("Chofer de Aduana", 6400, None, 0, 1, "Precio estándar - admin puede asignar 3400"),
                ("Alemsi", 6400, None, 0, 1, "Precio estándar - admin puede asignar 0 gratis"),
                ("Coordinadores", 6400, None, 0, 1, "Precio estándar"),
                ("Vialidad", 6400, None, 0, 1, "Precio estándar"),
                ("Visitas", 6400, None, 0, 1, "Precio estándar público"),
            ]
            for nombre, pdia, pesp, ract, act, desc in instituciones_default:
                execute_sql(s, "INSERT INTO instituciones (nombre,precio_dia,precio_especial,regla_activa,activa,descripcion) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (nombre) DO NOTHING", (nombre, pdia, pesp, ract, act, desc))

            # Carga idempotente de la minuta real de agosto 2026 proveniente del PDF ALEMSI.
            minuta_csv = Path(__file__).with_name("minuta_agosto_2026.csv")
            if minuta_csv.exists():
                dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                with minuta_csv.open(encoding="utf-8-sig", newline="") as archivo:
                    for fila in csv.DictReader(archivo):
                        fecha_menu = fila["fecha"].strip()
                        dia_semana = dias_semana[date.fromisoformat(fecha_menu).weekday()]
                        existe = execute_sql(
                            s,
                            "SELECT 1 FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s LIMIT 1",
                            (fecha_menu, fila["servicio"].strip(), fila["tipo_opcion"].strip()),
                        ).first()
                        if not existe:
                            execute_sql(
                                s,
                                "INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo) VALUES (%s,%s,%s,%s,%s,1)",
                                (fecha_menu, dia_semana, fila["servicio"].strip(), fila["tipo_opcion"].strip(), fila["plato"].strip()),
                            )

            # Índices para acelerar accesos frecuentes en Streamlit/Supabase.
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_minutas_fecha_activo ON minutas (fecha, activo)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_rut ON solicitudes (rut)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_fecha ON solicitudes (fecha)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_estado_pago ON solicitudes (estado_pago)",
            ]:
                execute_sql(s, index_sql)

            s.commit()
    except Exception as e:
        # Fallback para conexiones que no usan session context
        try:
            conn.query("SELECT 1", ttl=0)
            # Si query funciona, las tablas se crearán via query individuales
            st.warning(f"init_db con session falló, usando fallback: {e}")
        except Exception as e2:
            st.error(f"Error init_db PostgreSQL: {e} / {e2}")
            raise
