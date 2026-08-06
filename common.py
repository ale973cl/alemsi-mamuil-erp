import hashlib
import re
import random
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
import streamlit as st

# Configuración
EMAILS = {"cocina": "ale973@gmail.com", "finanzas": "finanzas@alemsi.cl", "gerencia": "gerencia@alemsi.cl"}
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

def exec_sql(session, sql, params=None):
    """Ejecuta SQL nativo con placeholders %s usando SQLAlchemy 2.x."""
    connection = session.connection()
    return connection.exec_driver_sql(sql, params or ())

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

def get_instituciones():
    try:
        conn = get_conn()
        df = conn.query("SELECT nombre FROM instituciones WHERE activa=1 ORDER BY nombre", ttl=0)
        if not df.empty:
            return df['nombre'].tolist()
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad"]
    except:
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad"]

def get_precio_institucion(institucion: str):
    try:
        conn=get_conn()
        df = conn.query("SELECT precio_dia, precio_especial, regla_activa FROM instituciones WHERE nombre=%s", params=(institucion,), ttl=0)
        if not df.empty:
            pdia,pesp,act=df.iloc[0]
            if act and pesp is not None: return int(pesp)
            return int(pdia)
        return PRECIO_DIA_DEFAULT
    except: return PRECIO_DIA_DEFAULT

def get_precio_persona_institucion(rut: str, institucion: str):
    try:
        conn=get_conn()
        df = conn.query("SELECT precio_especial, descripcion FROM excepciones_personas WHERE rut=%s AND activa=1", params=(normalizar_rut_db(rut),), ttl=0)
        if not df.empty:
            return int(df.iloc[0]['precio_especial']), f"Excepción: {df.iloc[0]['descripcion']}"
    except: pass
    precio = get_precio_institucion(institucion)
    return precio, f"Institución {institucion}"

def get_precio(plato, servicio):
    try:
        conn=get_conn()
        df = conn.query("SELECT valor FROM platos WHERE nombre=%s", params=(plato,), ttl=0)
        if not df.empty:
            return int(df.iloc[0]['valor'])
        return 3500
    except: return 3500

def descontar_bodega(plato):
    try:
        conn=get_conn()
        with conn.session as s:
            df_rec = conn.query("SELECT insumo,cantidad FROM recetas WHERE plato=%s", params=(plato,), ttl=0)
            for _, row in df_rec.iterrows():
                insumo, cant = row['insumo'], float(row['cantidad'])
                df_stock = conn.query("SELECT id, stock FROM bodega_inventario WHERE nombre_articulo ILIKE %s ORDER BY caduca ASC", params=(f"%{insumo}%",), ttl=0)
                for _, srow in df_stock.iterrows():
                    if cant<=0: break
                    id_, stock = srow['id'], float(srow['stock'])
                    if stock<=0: continue
                    desc = min(stock, cant)
                    exec_sql(s, "UPDATE bodega_inventario SET stock=stock-%s WHERE id=%s", (desc, id_))
                    cant-=desc
            s.commit()
    except Exception as e:
        pass

def enviar_email(destino, asunto, html):
    """Mantiene operación nativa con SMTP Gmail - lee st.secrets [email]"""
    try:
        cfg=st.secrets.get("email",{})
        if not cfg:
            return False, "Secrets [email] no configurado - Configura smtp_server, smtp_port, email_user, email_pass en formato TOML"
        server=smtplib.SMTP(cfg["smtp_server"],cfg["smtp_port"])
        server.starttls()
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
            exec_sql(s, """
                CREATE TABLE IF NOT EXISTS usuarios (
                    username TEXT PRIMARY KEY,
                    pwd TEXT,
                    rol TEXT,
                    nombre TEXT
                )
            """)
            # Comensales
            exec_sql(s, """
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
            exec_sql(s, """
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
            exec_sql(s, """
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
            exec_sql(s, """
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
            exec_sql(s, """
                CREATE TABLE IF NOT EXISTS minutas (
                    id SERIAL PRIMARY KEY,
                    dia_semana TEXT,
                    servicio TEXT,
                    plato TEXT,
                    activo INTEGER DEFAULT 1
                )
            """)
            # Solicitudes - ESTRUCTURA NATIVA POSTGRESQL CON COLUMNAS SOLICITADAS
            exec_sql(s, """
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
            exec_sql(s, """
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
            exec_sql(s, """
                CREATE TABLE IF NOT EXISTS recetas (
                    id SERIAL PRIMARY KEY,
                    plato TEXT,
                    insumo TEXT,
                    cantidad REAL,
                    unidad TEXT DEFAULT 'kilo',
                    instrucciones TEXT
                )
            """)
            exec_sql(s, """
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
            exec_sql(s, """
                CREATE TABLE IF NOT EXISTS bodega_cargas_log (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    archivo TEXT,
                    cantidad INTEGER,
                    responsable TEXT
                )
            """)
            exec_sql(s, """
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
            exec_sql(s, """
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
            # Usuarios por defecto con %s
            usuarios_default = [
                ("admin","admin123","Admin","Admin"),
                ("cocina","cocina123","Cocina","Cocina"),
                ("bodega","bodega123","Bodega","Bodega"),
                ("finanzas","finanzas123","Finanzas","Finanzas"),
                ("gerencia","gerencia123","Gerencia","Gerencia")
            ]
            for u,p,r,n in usuarios_default:
                exec_sql(s, "INSERT INTO usuarios (username,pwd,rol,nombre) VALUES (%s,%s,%s,%s) ON CONFLICT (username) DO NOTHING", (u, hash_pwd(p), r, n))

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
                exec_sql(s, "INSERT INTO instituciones (nombre,precio_dia,precio_especial,regla_activa,activa,descripcion) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (nombre) DO NOTHING", (nombre, pdia, pesp, ract, act, desc))

            s.commit()
    except Exception as e:
        st.error(f"Error al inicializar la base de datos: {e}")
        raise
