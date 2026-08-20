import hashlib
import re
import socket
import random
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import date, datetime, time, timedelta
from pathlib import Path
import csv
import streamlit as st
from sqlalchemy import text

# Configuración
EMAILS = {
    "cocina": "ale973@gmail.com",
    "finanzas": "finanzas@alemsi.cl",
    "gerencia": "gerencia@alemsi.cl",
    "admin_casino": "ale973@gmail.com",
    "reclamos": ["ale973@gmail.com", "araucaniashop@gmail.com"],
}
PRECIO_DIA_DEFAULT = 6400
SCHEMA_VERSION = "2026-08-20-circuitos-funcionales-v2"

MINUTA = {
    "Lunes": {"Desayuno": ["Desayuno americano", "Té + pan con huevo", "Avena + fruta"], "Almuerzo": ["Carbonada", "Lentejas con arroz", "Pollo asado con puré"], "Once": ["Té + pan con palta", "Té + sándwich ave"], "Cena": ["Crema + sandwich", "Tallarines"]},
    "Martes": {"Desayuno": ["Desayuno americano", "Yogurt + granola"], "Almuerzo": ["Cazuela vacuno", "Porotos con riendas", "Chuleta con arroz"], "Once": ["Té + pan con huevo"], "Cena": ["Charquicán"]},
    "Miércoles": {"Desayuno": ["Desayuno continental"], "Almuerzo": ["Pastel de papas", "Garbanzos con mote", "Pescado frito"], "Once": ["Té + pan con palta"], "Cena": ["Carbonada"]},
    "Jueves": {"Desayuno": ["Desayuno americano"], "Almuerzo": ["Pollo al jugo", "Lentejas con longaniza", "Pollo arvejado", "Puré con carne"], "Once": ["Té + jamón queso"], "Cena": ["Porotos"]},
    "Viernes": {"Desayuno": ["Desayuno completo"], "Almuerzo": ["Cazuela ave", "Fideos boloñesa", "Asado olla"], "Once": ["Té + pan"], "Cena": ["Chupe jurel"]},
    "Sábado": {"Desayuno": ["Desayuno americano"], "Almuerzo": ["Carbonada", "Arroz con pollo"], "Once": ["Té + pan"], "Cena": ["Sopa + sándwich"]},
}

def apply_alemsi_style():
    """Identidad visual ALEMSI. No contiene lógica de reservas ni acceso a datos."""
    try:
        st.markdown('''
        <style>
        :root{
            --alemsi-ink:#123f48;
            --alemsi-teal:#168c8e;
            --alemsi-teal-dark:#0c4b54;
            --alemsi-teal-soft:#eaf6f3;
            --alemsi-yellow:#ffd443;
            --alemsi-bg:#f8fbfa;
            --alemsi-border:#dcebe6;
        }
        html, body, [data-testid="stAppViewContainer"]{background:linear-gradient(140deg,#f9fcfb,#eef8f5) !important;color:var(--alemsi-ink);}
        [data-testid="stHeader"]{background:rgba(255,255,255,.88);}
        .main-header{position:relative;overflow:hidden;background:linear-gradient(135deg,#0b5860 0%,#0d7273 58%,#15938f 100%);padding:0;border-radius:22px;color:#fff;margin:4px 0 22px;box-shadow:0 20px 50px rgba(18,63,72,.18);}
        .main-header:after{content:"";position:absolute;width:260px;height:260px;border-radius:50%;right:-80px;top:-120px;background:rgba(255,212,67,.14);}
        .alemsi-topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 26px;border-bottom:1px solid rgba(255,255,255,.16);position:relative;z-index:1;}
        .alemsi-brand{display:flex;align-items:center;gap:13px;}
        .alemsi-mark{width:46px;height:46px;display:grid;grid-template-columns:1fr 1fr;gap:4px;transform:rotate(45deg);}
        .alemsi-mark span{display:block;border-radius:6px;background:#fff;opacity:.98;}
        .alemsi-mark span:nth-child(1){background:#63d0ca}.alemsi-mark span:nth-child(2){background:#74bdec}.alemsi-mark span:nth-child(4){background:#b9d7e7}
        .alemsi-brandcopy strong{display:block;font-size:20px;letter-spacing:.08em;line-height:1}.alemsi-brandcopy small{display:block;margin-top:5px;font-size:9px;letter-spacing:.12em;color:#cce7e5;text-transform:uppercase;}
        .alemsi-secure{font-size:12px;color:#d9efed;background:rgba(255,255,255,.10);padding:8px 12px;border-radius:999px;white-space:nowrap;}
        .alemsi-hero{padding:31px 30px 34px;position:relative;z-index:1;}
        .alemsi-place{display:inline-flex;align-items:center;gap:8px;font-size:10px;letter-spacing:.16em;font-weight:800;color:#b8dedb;text-transform:uppercase;}
        .alemsi-place:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--alemsi-yellow);}
        .alemsi-hero h1{font-size:clamp(29px,4vw,46px);line-height:1.02;letter-spacing:-.035em;margin:12px 0 9px;color:#fff;}
        .alemsi-hero h1 em{font-style:normal;color:var(--alemsi-yellow);}
        .alemsi-hero p{max-width:760px;margin:0;color:#d8ebea;font-size:14px;line-height:1.55;}
        .al-card{background:#fff;border:1px solid var(--alemsi-border);border-radius:18px;padding:18px 20px;margin:12px 0;box-shadow:0 7px 24px rgba(25,81,78,.07);}
        div[data-testid="stButton"]>button{border-radius:12px !important;font-weight:700 !important;min-height:44px;border-color:#cfe3df;}
        div[data-testid="stButton"]>button[kind="primary"]{background:var(--alemsi-teal) !important;border-color:var(--alemsi-teal) !important;}
        div[data-testid="stTabs"] button[role="tab"]{font-weight:700;color:var(--alemsi-ink);}
        [data-testid="stMetric"]{background:#fff;border:1px solid var(--alemsi-border);padding:14px;border-radius:14px;}
        @media(max-width:700px){.alemsi-topbar{padding:15px 18px}.alemsi-secure{display:none}.alemsi-hero{padding:25px 20px 28px}.alemsi-brandcopy small{letter-spacing:.08em}.main-header{border-radius:16px;}}
        </style>
        ''', unsafe_allow_html=True)
    except Exception:
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


@st.cache_data(ttl=300, show_spinner=False)
def get_correos(tipo: str):
    """Obtiene destinatarios activos desde PostgreSQL; usa EMAILS como respaldo."""
    tipo = str(tipo or "").strip().lower()
    try:
        conn = get_conn()
        df = conn.query(
            "SELECT correo FROM configuracion_correos WHERE tipo=:tipo AND activo=1 ORDER BY id",
            params={"tipo": tipo},
            ttl=300,
        )
        if not df.empty:
            return [str(x).strip() for x in df["correo"].tolist() if str(x).strip()]
    except Exception:
        pass
    fallback = EMAILS.get(tipo, [])
    if isinstance(fallback, str):
        return [fallback]
    return list(fallback)

def limpiar_cache_correos():
    get_correos.clear()

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

def normalizar_correo(correo: str) -> str:
    return str(correo or "").strip().lower()

def validar_correo_estructura(correo: str) -> bool:
    correo = normalizar_correo(correo)
    return bool(re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", correo))

def dominio_correo_resuelve(correo: str) -> bool:
    """Valida que el dominio exista/resuelva. No restringe proveedor ni institución.
    Se usa DNS del sistema; una caída temporal de DNS se informa como validación fallida.
    """
    correo = normalizar_correo(correo)
    if not validar_correo_estructura(correo):
        return False
    dominio = correo.rsplit("@", 1)[-1]
    try:
        socket.getaddrinfo(dominio, 25, proto=socket.IPPROTO_TCP)
        return True
    except OSError:
        return False

def normalizar_telefono_chile(telefono: str) -> str:
    digitos = re.sub(r"\D", "", str(telefono or ""))
    if digitos.startswith("56"):
        digitos = digitos[2:]
    if digitos.startswith("0"):
        digitos = digitos[1:]
    if len(digitos) == 9 and digitos.startswith("9"):
        return f"+56 9 {digitos[1:5]} {digitos[5:9]}"
    return ""

def telefono_movil_chile_valido(telefono: str) -> bool:
    return bool(normalizar_telefono_chile(telefono))

def gen_codigo(rut, serv, fecha_obj): 
    return f"{limpiar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha_obj.strftime('%d%m')}-{random.randint(100,999)}"


HORAS_SERVICIO = {
    "Desayuno": time(8, 0),
    "Almuerzo": time(13, 0),
    "Once": time(17, 0),
    "Cena": time(20, 0),
}

def gen_referencia_reserva(rut: str) -> str:
    """Genera una referencia corta para consultar una operación completa."""
    sello = datetime.now().strftime("%Y%m%d%H%M")
    rut_corto = limpiar_rut(rut)[-4:] or "0000"
    aleatorio = random.randint(1000, 9999)
    return f"MM-{sello}-{rut_corto}-{aleatorio}"

def fecha_hora_servicio(fecha_iso: str, servicio: str) -> datetime:
    hora = HORAS_SERVICIO.get(servicio, time(12, 0))
    return datetime.combine(date.fromisoformat(fecha_iso), hora)

def reserva_modificable(fecha_iso: str, servicio: str, ahora: datetime | None = None, anticipacion_horas: int = 48) -> bool:
    ahora = ahora or datetime.now()
    return ahora <= fecha_hora_servicio(fecha_iso, servicio) - timedelta(hours=max(int(anticipacion_horas), 0))

def max_dias_consecutivos(fechas) -> int:
    """Mayor racha de fechas ISO, aunque la selección tenga intervalos."""
    dias=sorted({date.fromisoformat(str(f)) for f in fechas})
    mayor=racha=0
    anterior=None
    for dia in dias:
        racha=racha+1 if anterior and dia==anterior+timedelta(days=1) else 1
        mayor=max(mayor,racha)
        anterior=dia
    return mayor

@st.cache_data(ttl=300, show_spinner=False)
def get_instituciones():
    try:
        conn = get_conn()
        df = conn.query("SELECT nombre FROM instituciones WHERE activa=1 ORDER BY nombre", ttl=300)
        if not df.empty:
            return df['nombre'].tolist()
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","ALEMSI Paso Fronterizo","ALEMSI Administrativos","Coordinadores","Vialidad"]
    except:
        return ["Visitas","Carabineros","PDI","SAG","Aduana","Chofer de Aduana","ALEMSI Paso Fronterizo","ALEMSI Administrativos","Coordinadores","Vialidad"]

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
            WHERE activo=1 AND COALESCE(estado,'PUBLICABLE')='PUBLICABLE' AND fecha BETWEEN :inicio AND :fin
            ORDER BY fecha,
                     CASE servicio WHEN 'Desayuno' THEN 1 WHEN 'Almuerzo' THEN 2 WHEN 'Once' THEN 3 WHEN 'Cena' THEN 4 ELSE 5 END,
                     CASE UPPER(REPLACE(tipo_opcion,'Ó','O')) WHEN 'OPCION 1' THEN 1 WHEN 'OPCION 2' THEN 2 WHEN 'OPCION 3' THEN 3 WHEN 'HIPOCALORICO' THEN 4 ELSE 5 END,
                     id
            """,
            params={"inicio": fecha_inicio, "fin": fecha_fin},
            ttl=300,
        )
    except Exception:
        return pd.DataFrame(columns=["fecha", "dia_semana", "servicio", "tipo_opcion", "plato"])


def descontar_bodega(plato):
    """Compatibilidad histórica: el descuento directo por plato está deshabilitado.

    Regla de oro v36: una reserva nunca mueve stock. El único descuento automático
    autorizado se ejecuta dentro de "Iniciar jornada" de Producción, donde existe
    fecha, servicio, cantidad consolidada, minuta vigente, receta aprobada y bloqueo
    transaccional contra doble ejecución.
    """
    return False

def enviar_email(destino, asunto, html, adjuntos=None):
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
        for adj in (adjuntos or []):
            nombre_archivo, contenido, mime_subtype = adj
            part = MIMEApplication(contenido, _subtype=mime_subtype or "pdf")
            part.add_header("Content-Disposition", "attachment", filename=nombre_archivo)
            msg.attach(part)
        server.send_message(msg)
        server.quit()
        return True,"OK"
    except Exception as e:
        return False,str(e)


def es_personal_alemsi(rol):
    """Devuelve True para perfiles internos ALEMSI. Helper centralizado v30."""
    return str(rol or "").strip() in {"Cocina", "Finanzas", "Bodega", "Gerencia", "AdminCasino", "AdminTotal", "Operaciones"}

def init_db():
    """Aplica el esquema una sola vez por versión.

    Si falta la tabla o la marca de migración se conserva el inicializador
    idempotente completo como recuperación para instalaciones incompletas.
    """
    conn = get_conn()
    try:
        aplicada = conn.query(
            "SELECT 1 FROM migraciones_app WHERE clave=:clave LIMIT 1",
            params={"clave": SCHEMA_VERSION}, ttl=0,
        )
        if not aplicada.empty:
            return False
    except Exception:
        pass
    try:
        with conn.session as s:
            # Usuarios
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS usuarios (
                    username TEXT PRIMARY KEY,
                    pwd TEXT,
                    rol TEXT,
                    nombre TEXT,
                    activo INTEGER DEFAULT 1,
                    fecha_creacion TEXT
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
                    activo INTEGER DEFAULT 1,
                    estado TEXT DEFAULT 'PUBLICABLE'
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
                    fecha_creacion TEXT,
                    fecha_modificacion TEXT,
                    modificado_por TEXT,
                    referencia_reserva TEXT,
                    tipo_registro TEXT DEFAULT 'RESERVA_COMERCIAL',
                    estado_reserva TEXT DEFAULT 'ACTIVA'
                )
            """)
            # Bodega
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS bodega_inventario (
                    id SERIAL PRIMARY KEY,
                    codigo_insumo TEXT,
                    familia TEXT,
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
            # Tareas de inventario ordenadas por Administración Casino a Cocina.
            # La tarea NO modifica stock: Cocina registra el conteo y Administración/Bodega lo revisa.
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS tareas_inventario_cocina (
                    id SERIAL PRIMARY KEY,
                    fecha_creacion TEXT,
                    creado_por TEXT,
                    asignado_a TEXT DEFAULT 'Cocina',
                    fecha_programada TEXT,
                    familia TEXT,
                    seccion TEXT,
                    detalle TEXT,
                    prioridad TEXT DEFAULT 'Normal',
                    estado TEXT DEFAULT 'Pendiente',
                    iniciado_por TEXT,
                    fecha_inicio TEXT,
                    resultado TEXT,
                    completado_por TEXT,
                    fecha_completado TEXT,
                    revisado_por TEXT,
                    fecha_revision TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS recetas (
                    id SERIAL PRIMARY KEY,
                    plato TEXT,
                    insumo TEXT,
                    cantidad REAL,
                    unidad TEXT DEFAULT 'kilo',
                    instrucciones TEXT,
                    estado TEXT DEFAULT 'BORRADOR',
                    version INTEGER DEFAULT 1,
                    merma_pct REAL DEFAULT 0,
                    margen_produccion_pct REAL DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS servicios_produccion (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT NOT NULL,
                    servicio TEXT NOT NULL,
                    estado TEXT DEFAULT 'Pendiente',
                    inicio_at TEXT,
                    fin_at TEXT,
                    usuario_inicio TEXT,
                    usuario_fin TEXT,
                    detalle_planificado TEXT,
                    detalle_cierre TEXT,
                    novedades TEXT,
                    UNIQUE(fecha, servicio)
                )
            """)

            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS jornadas_produccion (
                    fecha TEXT PRIMARY KEY,
                    estado TEXT DEFAULT 'Pendiente',
                    inicio_at TEXT,
                    fin_at TEXT,
                    usuario_inicio TEXT,
                    usuario_fin TEXT,
                    novedades TEXT,
                    reporte_enviado_at TEXT,
                    reporte_estado TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS jornada_detalle (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT NOT NULL,
                    servicio TEXT NOT NULL,
                    tipo_opcion TEXT,
                    plato TEXT NOT NULL,
                    reservadas INTEGER DEFAULT 0,
                    producidas INTEGER DEFAULT 0,
                    entregadas INTEGER DEFAULT 0,
                    motivo_diferencia TEXT,
                    observaciones TEXT,
                    UNIQUE(fecha, servicio, tipo_opcion, plato)
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS excepciones_reserva (
                    id SERIAL PRIMARY KEY,
                    rut TEXT NOT NULL,
                    fecha_desde TEXT NOT NULL,
                    fecha_hasta TEXT NOT NULL,
                    motivo TEXT NOT NULL,
                    autorizado_por TEXT NOT NULL,
                    autorizado_at TEXT NOT NULL,
                    activa INTEGER DEFAULT 1
                )
            """)
            execute_sql(s, """
                CREATE INDEX IF NOT EXISTS idx_excepciones_reserva_rut_fechas
                ON excepciones_reserva(rut, fecha_desde, fecha_hasta, activa)
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS usuarios_permisos (
                    username TEXT NOT NULL,
                    permiso TEXT NOT NULL,
                    activo INTEGER DEFAULT 1,
                    PRIMARY KEY(username, permiso)
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS auditoria_acciones (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    usuario TEXT,
                    accion TEXT,
                    entidad TEXT,
                    referencia TEXT,
                    valor_anterior TEXT,
                    valor_nuevo TEXT,
                    motivo TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS registro_login (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT,
                    usuario TEXT,
                    rol TEXT,
                    evento TEXT,
                    resultado TEXT,
                    ip TEXT,
                    zona_horaria TEXT,
                    locale TEXT,
                    user_agent TEXT,
                    detalle TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS minuta_revision_coordinacion (
                    id SERIAL PRIMARY KEY,
                    fecha TEXT NOT NULL,
                    servicio TEXT NOT NULL,
                    tipo_opcion TEXT NOT NULL,
                    plato_actual TEXT,
                    accion TEXT NOT NULL,
                    observacion TEXT,
                    plato_propuesto TEXT,
                    usuario TEXT,
                    fecha_accion TEXT,
                    estado TEXT DEFAULT 'Pendiente'
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS receta_revision_coordinacion (
                    id SERIAL PRIMARY KEY,
                    plato TEXT NOT NULL,
                    version_receta INTEGER,
                    accion TEXT NOT NULL,
                    observacion TEXT,
                    usuario TEXT,
                    fecha_accion TEXT,
                    estado TEXT DEFAULT 'Pendiente'
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS migraciones_app (
                    clave TEXT PRIMARY KEY,
                    aplicado_at TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS ajustes_financieros (
                    referencia_reserva TEXT PRIMARY KEY,
                    monto_ajustado INTEGER,
                    motivo TEXT,
                    usuario TEXT,
                    fecha TEXT
                )
            """)

            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS configuracion_correos (
                    id SERIAL PRIMARY KEY,
                    tipo TEXT NOT NULL,
                    correo TEXT NOT NULL,
                    descripcion TEXT,
                    activo INTEGER DEFAULT 1,
                    fecha_creacion TEXT,
                    UNIQUE(tipo, correo)
                )
            """)
            execute_sql(s, """
                CREATE INDEX IF NOT EXISTS idx_configuracion_correos_tipo_activo
                ON configuracion_correos(tipo, activo)
            """)

            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS modalidades_pago (
                    id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 1, descripcion TEXT
                )
            """)
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS inventarios_fisicos (
                    id SERIAL PRIMARY KEY, fecha TEXT, codigo_insumo TEXT, nombre_articulo TEXT, stock_teorico REAL, stock_real REAL, diferencia REAL, responsable TEXT, observacion TEXT, creado_at TEXT
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
            # Estructuras de minuta: se migran aquí, nunca durante la navegación.
            execute_sql(s, """CREATE TABLE IF NOT EXISTS minuta_documentos (
                id SERIAL PRIMARY KEY, nombre_archivo TEXT NOT NULL,
                mime_type TEXT DEFAULT 'application/pdf', contenido BYTEA,
                sha256 TEXT, fecha_desde TEXT, fecha_hasta TEXT,
                cargado_por TEXT, cargado_at TEXT, estado TEXT DEFAULT 'FUENTE',
                observacion TEXT
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS minuta_observaciones_gerencia (
                id SERIAL PRIMARY KEY, fecha_desde TEXT NOT NULL,
                fecha_hasta TEXT NOT NULL, observacion TEXT NOT NULL,
                usuario TEXT, fecha_accion TEXT, estado TEXT DEFAULT 'ABIERTA'
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS minuta_flujo_coordinacion (
                id SERIAL PRIMARY KEY, fecha_desde TEXT NOT NULL,
                fecha_hasta TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                estado TEXT NOT NULL DEFAULT 'EN_REVISION', observacion TEXT,
                enviado_por TEXT, enviado_at TEXT, coordinador TEXT,
                coordinacion_at TEXT, activo INTEGER DEFAULT 1
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS notificaciones_internas (
                id SERIAL PRIMARY KEY, evento TEXT NOT NULL, rol_destino TEXT NOT NULL,
                usuario_destino TEXT, titulo TEXT NOT NULL, mensaje TEXT,
                entidad TEXT, entidad_id TEXT, creado_por TEXT, creado_at TEXT,
                leido_at TEXT, estado TEXT DEFAULT 'PENDIENTE'
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS correo_outbox (
                id SERIAL PRIMARY KEY, evento TEXT NOT NULL, destino TEXT NOT NULL,
                asunto TEXT NOT NULL, cuerpo_html TEXT, entidad TEXT, entidad_id TEXT,
                estado TEXT DEFAULT 'PENDIENTE', intentos INTEGER DEFAULT 0,
                creado_at TEXT, ultimo_intento_at TEXT, enviado_at TEXT, error TEXT
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS opiniones_experiencia (
                id SERIAL PRIMARY KEY, tipo TEXT NOT NULL, fecha TEXT NOT NULL,
                identificacion TEXT, servicio TEXT, comentario TEXT NOT NULL,
                evidencia_nombre TEXT, evidencia BYTEA, responsable TEXT,
                estado TEXT NOT NULL, resolucion TEXT, creado_por TEXT,
                creado_at TEXT, cerrado_por TEXT, cerrado_at TEXT
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS configuracion_operativa (
                clave TEXT PRIMARY KEY, valor INTEGER NOT NULL, descripcion TEXT,
                actualizado_por TEXT, actualizado_at TEXT
            )""")
            execute_sql(s, """CREATE TABLE IF NOT EXISTS solicitudes_excepcion_cancelacion (
                id SERIAL PRIMARY KEY, referencia_reserva TEXT NOT NULL, rut TEXT NOT NULL,
                fecha TEXT NOT NULL, servicio TEXT NOT NULL, motivo TEXT NOT NULL,
                estado TEXT DEFAULT 'PENDIENTE', solicitado_at TEXT, resuelto_por TEXT,
                resuelto_at TEXT, resolucion TEXT, impacto_economico INTEGER DEFAULT 0
            )""")
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
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS tipo_registro TEXT DEFAULT 'RESERVA_COMERCIAL'",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS tipo_opcion TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS fecha_modificacion TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS modificado_por TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS referencia_reserva TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS estado_reserva TEXT DEFAULT 'ACTIVA'",
                "ALTER TABLE minuta_revision_coordinacion ADD COLUMN IF NOT EXISTS flujo_id INTEGER",
                "ALTER TABLE minutas ADD COLUMN IF NOT EXISTS fecha TEXT",
                "ALTER TABLE minutas ADD COLUMN IF NOT EXISTS tipo_opcion TEXT",
                "ALTER TABLE minutas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'PUBLICABLE'",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS activo INTEGER DEFAULT 1",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS fecha_creacion TEXT",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS debe_cambiar_password INTEGER DEFAULT 1",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS correo TEXT",
                "ALTER TABLE recetas ADD COLUMN IF NOT EXISTS estado TEXT DEFAULT 'BORRADOR'",
                "ALTER TABLE recetas ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
                "ALTER TABLE recetas ADD COLUMN IF NOT EXISTS merma_pct REAL DEFAULT 0",
                "ALTER TABLE recetas ADD COLUMN IF NOT EXISTS margen_produccion_pct REAL DEFAULT 0",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS comprobante_url TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS pago_token TEXT",
                "ALTER TABLE solicitudes ADD COLUMN IF NOT EXISTS motivo_estado_pago TEXT",
                "ALTER TABLE bodega_inventario ADD COLUMN IF NOT EXISTS familia TEXT",
                "ALTER TABLE platos ADD COLUMN IF NOT EXISTS tipo_plato TEXT",
                "ALTER TABLE platos ADD COLUMN IF NOT EXISTS proteina_principal TEXT",
                "ALTER TABLE platos ADD COLUMN IF NOT EXISTS temporada TEXT",
            ]:
                execute_sql(s, column_sql)
            execute_sql(s, """CREATE UNIQUE INDEX IF NOT EXISTS ux_revision_coord_item
                ON minuta_revision_coordinacion(flujo_id,fecha,servicio,tipo_opcion)
                WHERE flujo_id IS NOT NULL""")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_notificaciones_rol_estado ON notificaciones_internas(rol_destino,estado,creado_at)")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_outbox_estado ON correo_outbox(estado,creado_at)")
            for clave,valor,descripcion in [
                ('reserva_anticipacion_horas',48,'Anticipación mínima para reservar'),
                ('cancelacion_anticipacion_horas',48,'Anticipación mínima para cancelar'),
                ('reserva_max_dias_consecutivos',7,'Máximo de días consecutivos'),
            ]:
                execute_sql(s,"INSERT INTO configuracion_operativa (clave,valor,descripcion) VALUES (%s,%s,%s) ON CONFLICT (clave) DO NOTHING",(clave,valor,descripcion))

            # v40: conserva históricos y neutraliza duplicados heredados antes de crear la invariante.
            execute_sql(s, """
                WITH ranked AS (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY rut,fecha,servicio ORDER BY id DESC
                    ) AS rn
                    FROM solicitudes
                    WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA'
                )
                UPDATE solicitudes AS sol
                SET estado_reserva='INACTIVA_DUPLICADA_V40'
                FROM ranked r
                WHERE sol.id=r.id AND r.rn>1
            """)
            execute_sql(s, """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_solicitudes_rut_fecha_servicio_activa
                ON solicitudes (rut, fecha, servicio)
                WHERE COALESCE(estado_reserva,'ACTIVA')='ACTIVA'
            """)

            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS comprobantes_pago (
                    id SERIAL PRIMARY KEY,
                    referencia_reserva TEXT,
                    pago_token TEXT,
                    nombre_archivo TEXT,
                    mime_type TEXT,
                    contenido BYTEA,
                    fecha_carga TEXT,
                    estado TEXT DEFAULT 'RECIBIDO'
                )
            """)
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_comprobantes_pago_token ON comprobantes_pago(pago_token)")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS rut TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS validado_por TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS fecha_validacion TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS observacion_validacion TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS drive_file_id TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS drive_url TEXT")
            execute_sql(s, "ALTER TABLE comprobantes_pago ADD COLUMN IF NOT EXISTS storage_provider TEXT DEFAULT 'POSTGRESQL'")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_comprobantes_referencia ON comprobantes_pago(referencia_reserva)")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_comprobantes_estado ON comprobantes_pago(estado)")
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS encuestas_satisfaccion (
                    id SERIAL PRIMARY KEY,
                    tipo TEXT NOT NULL,
                    pago_token TEXT,
                    referencia_reserva TEXT,
                    rut TEXT,
                    institucion TEXT,
                    puntaje_general INTEGER,
                    puntaje_comida INTEGER,
                    puntaje_atencion INTEGER,
                    puntaje_limpieza INTEGER,
                    puntaje_variedad INTEGER,
                    puntaje_facilidad INTEGER,
                    puntaje_claridad INTEGER,
                    comentario TEXT,
                    fecha_respuesta TEXT
                )
            """)
            execute_sql(s, "CREATE UNIQUE INDEX IF NOT EXISTS ux_encuesta_token_tipo ON encuestas_satisfaccion(pago_token,tipo)")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_encuesta_ref ON encuestas_satisfaccion(referencia_reserva)")
            execute_sql(s, """
                CREATE TABLE IF NOT EXISTS configuracion_bancaria (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    titular TEXT,
                    rut TEXT,
                    banco TEXT,
                    tipo_cuenta TEXT,
                    numero_cuenta TEXT,
                    correo_comprobantes TEXT,
                    activo INTEGER DEFAULT 1,
                    actualizado_at TEXT,
                    actualizado_por TEXT
                )
            """)

            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_solicitudes_referencia ON solicitudes(referencia_reserva)")
            execute_sql(s, "CREATE INDEX IF NOT EXISTS idx_solicitudes_rut_fecha_servicio ON solicitudes(rut, fecha, servicio)")

            # AUTH-02: los usuarios se administran exclusivamente desde la interfaz.
            # No crear, reactivar ni sobrescribir contraseñas desde init_db().
            # El primer Administrador Total se crea mediante el bootstrap seguro de la interfaz,
            # protegido por st.secrets["security"]["bootstrap_key"].

            # Modalidades oficiales administrables sin borrar historial.
            for nombre_pago,descripcion_pago in [("Transferencia bancaria","Transferencia con comprobante"),("Débito en la instalación","Pago presencial mediante débito")]:
                execute_sql(s,"INSERT INTO modalidades_pago (nombre,activo,descripcion) VALUES (%s,1,%s) ON CONFLICT (nombre) DO NOTHING",(nombre_pago,descripcion_pago))

            # Instituciones con precio estándar $6400 - usando %s
            instituciones_default = [
                ("Carabineros", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("PDI", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("SAG", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("Aduana", 6400, None, 0, 1, "Precio estándar - sin regla"),
                ("Chofer de Aduana", 6400, None, 0, 1, "Precio estándar - admin puede asignar 3400"),
                ("ALEMSI Paso Fronterizo", 0, None, 0, 1, "Personal ALEMSI Paso Fronterizo - consumo interno sin cobro"),
                ("ALEMSI Administrativos", 0, None, 0, 1, "Personal ALEMSI Administrativo - almuerzo interno sin cobro"),
                ("Coordinadores", 6400, None, 0, 1, "Precio estándar"),
                ("Vialidad", 6400, None, 0, 1, "Precio estándar"),
                ("Visitas", 6400, None, 0, 1, "Precio estándar público"),
            ]
            for nombre, pdia, pesp, ract, act, desc in instituciones_default:
                execute_sql(s, "INSERT INTO instituciones (nombre,precio_dia,precio_especial,regla_activa,activa,descripcion) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (nombre) DO NOTHING", (nombre, pdia, pesp, ract, act, desc))

            # MIG-35: normaliza la institución histórica "Alemsi" sin perder comensales.
            # Se mantiene como compatibilidad únicamente si existía en versiones anteriores.
            execute_sql(s, "UPDATE comensales SET institucion='ALEMSI Paso Fronterizo' WHERE LOWER(TRIM(COALESCE(institucion,'')))='alemsi'")
            execute_sql(s, "UPDATE solicitudes SET institucion='ALEMSI Paso Fronterizo' WHERE LOWER(TRIM(COALESCE(institucion,'')))='alemsi'")
            execute_sql(s, "UPDATE instituciones SET activa=0, descripcion='Migrado a ALEMSI Paso Fronterizo' WHERE LOWER(TRIM(nombre))='alemsi'")

            # MIG-36: normaliza las variantes históricas de Opción 1 / Opción 2 / Hipocalórico.
            # Esto corrige precarga de fechas antiguas, visualización semanal y conteos sin perder minutas.
            execute_sql(s, """
                UPDATE minutas SET tipo_opcion = CASE
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 1','OPCION 1','OPCIÓN1','OPCION1') THEN 'OPCION 1'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 2','OPCION 2','OPCIÓN2','OPCION2') THEN 'OPCION 2'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 3','OPCION 3','OPCIÓN3','OPCION3') THEN 'OPCION 3'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('HIPOCALÓRICO','HIPOCALORICO') THEN 'HIPOCALORICO'
                    ELSE UPPER(TRIM(tipo_opcion)) END
                WHERE TRIM(COALESCE(tipo_opcion,''))<>''
            """)
            execute_sql(s, """
                UPDATE solicitudes SET tipo_opcion = CASE
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 1','OPCION 1','OPCIÓN1','OPCION1') THEN 'OPCION 1'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 2','OPCION 2','OPCIÓN2','OPCION2') THEN 'OPCION 2'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('OPCIÓN 3','OPCION 3','OPCIÓN3','OPCION3') THEN 'OPCION 3'
                    WHEN UPPER(TRIM(tipo_opcion)) IN ('HIPOCALÓRICO','HIPOCALORICO') THEN 'HIPOCALORICO'
                    ELSE UPPER(TRIM(tipo_opcion)) END
                WHERE TRIM(COALESCE(tipo_opcion,''))<>''
            """)

            # Regla comercial vigente: base estándar $6.400/día para instituciones cobrables.
            # Las excepciones se conservan en precio_especial + regla_activa.
            execute_sql(s, "UPDATE instituciones SET precio_dia=6400 WHERE (precio_dia IS NULL OR precio_dia<>6400) AND nombre NOT IN ('ALEMSI Paso Fronterizo','ALEMSI Administrativos')")

            # Carga idempotente de la minuta real de agosto 2026 proveniente del PDF ALEMSI.
            minuta_csv = Path(__file__).with_name("minuta_agosto_2026.csv")
            if minuta_csv.exists():
                dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                with minuta_csv.open(encoding="utf-8-sig", newline="") as archivo:
                    for fila in csv.DictReader(archivo):
                        fecha_menu = fila["fecha"].strip()
                        dia_semana = dias_semana[date.fromisoformat(fecha_menu).weekday()]
                        servicio_menu = fila["servicio"].strip()
                        tipo_menu_raw = fila["tipo_opcion"].strip()
                        tipo_menu_norm = tipo_menu_raw.upper().replace("Ó","O")
                        mapa_tipo = {"OPCION 1":"OPCION 1","OPCION1":"OPCION 1","OPCION 2":"OPCION 2","OPCION2":"OPCION 2","OPCION 3":"OPCION 3","OPCION3":"OPCION 3","HIPOCALORICO":"HIPOCALORICO"}
                        tipo_menu = mapa_tipo.get(tipo_menu_norm, tipo_menu_norm)
                        plato_menu = fila["plato"].strip()
                        existente = execute_sql(
                            s,
                            "SELECT id FROM minutas WHERE fecha=%s AND servicio=%s AND tipo_opcion=%s ORDER BY id LIMIT 1",
                            (fecha_menu, servicio_menu, tipo_menu),
                        ).first()
                        if existente:
                            execute_sql(
                                s,
                                "UPDATE minutas SET dia_semana=%s, plato=%s, activo=1 WHERE id=%s",
                                (dia_semana, plato_menu, existente[0]),
                            )
                        else:
                            execute_sql(
                                s,
                                "INSERT INTO minutas (fecha,dia_semana,servicio,tipo_opcion,plato,activo) VALUES (%s,%s,%s,%s,%s,1)",
                                (fecha_menu, dia_semana, servicio_menu, tipo_menu, plato_menu),
                            )

            # Recetas tipo de prueba: BORRADOR. No descuentan inventario hasta aprobación.
            recetas_tipo = [
                ("CAZUELA DE AVE","Pollo",0.25,"kg",8.0,5.0),
                ("CAZUELA DE AVE","Papa",0.20,"kg",12.0,5.0),
                ("CAZUELA DE AVE","Zapallo",0.12,"kg",10.0,5.0),
                ("LENTEJAS GUISADAS","Lentejas",0.09,"kg",2.0,5.0),
                ("LENTEJAS GUISADAS","Cebolla",0.03,"kg",12.0,5.0),
                ("LENTEJAS GUISADAS","Zanahoria",0.03,"kg",15.0,5.0),
                ("CARBONADA DE VACUNO","Vacuno",0.16,"kg",8.0,5.0),
                ("CARBONADA DE VACUNO","Papa",0.15,"kg",12.0,5.0),
                ("CARBONADA DE VACUNO","Zapallo",0.08,"kg",10.0,5.0),
                ("PASTEL DE PAPA","Carne molida",0.15,"kg",7.0,5.0),
                ("PASTEL DE PAPA","Papa",0.28,"kg",15.0,5.0),
                ("PASTEL DE PAPA","Cebolla",0.04,"kg",12.0,5.0),
                ("POLLO ARVEJADO CON ARROZ ZANAHORIA","Pollo",0.20,"kg",8.0,5.0),
                ("POLLO ARVEJADO CON ARROZ ZANAHORIA","Arroz",0.08,"kg",1.0,5.0),
                ("POLLO ARVEJADO CON ARROZ ZANAHORIA","Arvejas",0.05,"kg",3.0,5.0),
            ]
            for plato_r, insumo_r, cant_r, unidad_r, merma_r, margen_r in recetas_tipo:
                existe_r = execute_sql(s, "SELECT id FROM recetas WHERE UPPER(plato)=UPPER(%s) AND UPPER(insumo)=UPPER(%s) LIMIT 1", (plato_r, insumo_r)).first()
                if not existe_r:
                    execute_sql(s, "INSERT INTO recetas (plato,insumo,cantidad,unidad,instrucciones,estado,version,merma_pct,margen_produccion_pct) VALUES (%s,%s,%s,%s,%s,'BORRADOR',1,%s,%s)", (plato_r, insumo_r, cant_r, unidad_r, "Receta tipo para pruebas; validar con Cocina antes de aprobar.", merma_r, margen_r))

            # Índices para acelerar accesos frecuentes en Streamlit/Supabase.
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_minutas_fecha_activo ON minutas (fecha, activo)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_rut ON solicitudes (rut)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_fecha ON solicitudes (fecha)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_estado_pago ON solicitudes (estado_pago)",
                "CREATE INDEX IF NOT EXISTS idx_solicitudes_rut_fecha_servicio_id ON solicitudes (rut, fecha, servicio, id DESC)",
                "CREATE INDEX IF NOT EXISTS idx_platos_nombre_servicio ON platos (LOWER(TRIM(nombre)), servicio)",
                "CREATE INDEX IF NOT EXISTS idx_servicios_produccion_fecha_servicio ON servicios_produccion (fecha, servicio)",
            ]:
                execute_sql(s, index_sql)

            execute_sql(
                s,
                "INSERT INTO migraciones_app (clave,aplicado_at) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET aplicado_at=EXCLUDED.aplicado_at",
                (SCHEMA_VERSION, datetime.now().isoformat()),
            )

            s.commit()
            return True
    except Exception as e:
        # Fallback para conexiones que no usan session context
        try:
            conn.query("SELECT 1", ttl=0)
            # Si query funciona, las tablas se crearán via query individuales
            st.warning(f"init_db con session falló, usando fallback: {e}")
        except Exception as e2:
            st.error(f"Error init_db PostgreSQL: {e} / {e2}")
            raise
