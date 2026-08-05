
import sqlite3, hashlib, re, random, smtplib, pandas as pd, os, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "casino_erp.db")
if "/mount/src" in str(Path.cwd()):
    DB_PATH = "/tmp/casino_erp.db"

EMAILS = {"cocina":"ale973@gmail.com","finanzas":"finanzas@alemsi.cl","gerencia":"gerencia@alemsi.cl","reclamos":"gerencia@alemsi.cl","bodega":"bodega@alemsi.cl"}
PRECIO_DIA_DEFAULT = 6400

MINUTA = {
    "Lunes": {"Desayuno":["Desayuno americano","Té + pan con huevo","Avena + fruta"],"Almuerzo":["Carbonada","Lentejas con arroz","Pollo asado con puré"],"Once":["Té + pan con palta","Té + sándwich ave"],"Cena":["Crema + sandwich","Tallarines"]},
    "Martes":{"Desayuno":["Desayuno americano","Yogurt + granola"],"Almuerzo":["Cazuela vacuno","Porotos con riendas","Chuleta con arroz"],"Once":["Té + pan con huevo"],"Cena":["Charquicán"]},
    "Miércoles":{"Desayuno":["Desayuno continental"],"Almuerzo":["Pastel de papas","Garbanzos con mote","Pescado frito"],"Once":["Té + pan con palta"],"Cena":["Carbonada"]},
    "Jueves":{"Desayuno":["Desayuno americano"],"Almuerzo":["Pollo al jugo","Lentejas con longaniza","Pollo arvejado","Puré con carne"],"Once":["Té + jamón queso"],"Cena":["Porotos"]},
    "Viernes":{"Desayuno":["Desayuno completo"],"Almuerzo":["Cazuela ave","Fideos boloñesa","Asado olla"],"Once":["Té + pan"],"Cena":["Chupe jurel"]},
    "Sábado":{"Desayuno":["Desayuno americano"],"Almuerzo":["Carbonada","Arroz con pollo"],"Once":["Té + pan"],"Cena":["Sopa + sándwich"]},
    "Domingo":{"Desayuno":["Desayuno americano"],"Almuerzo":["Asado olla","Pollo asado"],"Once":["Té + pan"],"Cena":["Sopa + sándwich"]},
}

def apply_alemsi_style():
    # V19.3 - SIMPLIFICADO sin adaptación por dispositivo
    try:
        import streamlit as st
        st.markdown('''
        <style>
        :root{--alemsi-blue:#0A2F6B; --alemsi-blue-2:#123E7A; --alemsi-yellow:#FFD400; --alemsi-bg:#F8F9FA; --alemsi-border:#E9ECEF;}
        html, body, [data-testid="stAppViewContainer"]{background:var(--alemsi-bg) !important;}
        h1,h2,h3{color:var(--alemsi-blue);}
        [data-testid="stSidebarNav"]{display:none !important;}
        [data-testid="stSidebar"]{display:none !important;}
        .main-header{background:linear-gradient(135deg,var(--alemsi-blue) 0%, var(--alemsi-blue-2) 100%); padding:28px 32px; border-radius:12px; color:white; margin-bottom:22px;}
        .main-header h1{color:white !important;}
        .al-card{background:white; border:1px solid var(--alemsi-border); border-radius:12px; padding:18px 20px; margin:12px 0;}
        div[data-testid="stButton"]>button{border-radius:12px !important; font-weight:700 !important; min-height:44px;}
        div[data-testid="stButton"]>button[kind="primary"]{background:var(--alemsi-yellow) !important; color:#1A1A1A !important; border:1px solid var(--alemsi-yellow) !important;}
        </style>
        ''', unsafe_allow_html=True)
    except:
        pass

def get_conn(): 
    try: return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    except: return sqlite3.connect("casino_erp.db", check_same_thread=False, timeout=20)

def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()
def formato_clp(v):
    try: return f"${int(v):,}".replace(",",".")
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

def get_instituciones():
    try:
        conn=get_conn(); df=pd.read_sql_query("SELECT nombre FROM instituciones WHERE activa=1 ORDER BY nombre", conn); conn.close()
        return df['nombre'].tolist() if not df.empty else ["Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad","Visitas"]
    except: return ["Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad","Visitas"]

def get_precio_institucion(institucion: str):
    try:
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT precio_dia, precio_especial, regla_activa FROM instituciones WHERE nombre=?", (institucion,))
        row=cur.fetchone(); conn.close()
        if row:
            pdia,pesp,act=row
            if act and pesp is not None: return int(pesp)
            return int(pdia)
        return PRECIO_DIA_DEFAULT
    except: return PRECIO_DIA_DEFAULT

def get_precio_persona_institucion(rut: str, institucion: str):
    try:
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT precio_especial, descripcion FROM excepciones_personas WHERE rut=? AND activa=1", (normalizar_rut_db(rut),))
        row=cur.fetchone()
        if row:
            conn.close()
            return int(row[0]), f"Excepción: {row[1]}"
        conn.close()
    except: pass
    precio = get_precio_institucion(institucion)
    return precio, f"Institución {institucion}"

def gen_codigo(rut, serv, fecha_obj): return f"{limpiar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha_obj.strftime('%d%m')}-{random.randint(100,999)}"

def get_precio(plato, servicio):
    try:
        conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT valor FROM platos WHERE nombre=?",(plato,)); row=cur.fetchone(); conn.close()
        if row: return row[0]
        return 3500
    except: return 3500

def enviar_email(destino, asunto, html):
    try:
        import streamlit as st
        cfg=st.secrets.get("email",{})
        if not cfg: return False,"No secrets"
        server=smtplib.SMTP(cfg["smtp_server"],cfg["smtp_port"])
        server.starttls(); server.login(cfg["email_user"],cfg["email_pass"])
        msg=MIMEMultipart(); msg["From"]=cfg["email_user"]; msg["To"]=destino; msg["Subject"]=asunto
        msg.attach(MIMEText(html,"html"))
        server.send_message(msg); server.quit()
        return True,"OK"
    except Exception as e: return False,str(e)

def descontar_bodega(plato):
    try:
        conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT insumo,cantidad FROM recetas WHERE plato=?",(plato,)); recetas=cur.fetchall(); conn.close()
        for insumo,cant in recetas:
            conn2=get_conn(); cur2=conn2.cursor(); cur2.execute("SELECT id,stock FROM bodega_inventario WHERE nombre_articulo LIKE ? ORDER BY caduca ASC",(f"%{insumo}%",)); stocks=cur2.fetchall(); conn2.close()
            for id_,stock in stocks:
                if cant<=0: break
                if stock<=0: continue
                desc=min(float(stock), float(cant))
                conn3=get_conn(); cur3=conn3.cursor(); cur3.execute("UPDATE bodega_inventario SET stock=stock-? WHERE id=?",(desc,id_)); conn3.commit(); conn3.close()
                cant-=desc
    except: pass

def init_db():
    import os
    # Borra DB corrupta si falla
    try:
        conn=get_conn(); cur=conn.cursor()
    except:
        try:
            if os.path.exists(DB_PATH): os.remove(DB_PATH)
            if os.path.exists("/tmp/casino_erp.db"): os.remove("/tmp/casino_erp.db")
            if os.path.exists("casino_erp.db"): os.remove("casino_erp.db")
        except: pass
        conn=get_conn(); cur=conn.cursor()

    # Tablas base
    cur.execute("CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, pwd TEXT, rol TEXT, nombre TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS instituciones (nombre TEXT PRIMARY KEY, precio_dia INTEGER DEFAULT 6400, precio_especial INTEGER, regla_activa INTEGER DEFAULT 0, activa INTEGER DEFAULT 1, descripcion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS excepciones_personas (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, nombre TEXT, institucion TEXT, precio_especial INTEGER, descripcion TEXT, activa INTEGER DEFAULT 1, fecha_creacion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS comensales (rut TEXT PRIMARY KEY, nombre TEXT, telefono TEXT, correo TEXT, institucion TEXT, fecha_registro TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS solicitudes (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, fecha TEXT, servicio TEXT, plato TEXT, codigo TEXT, estado_pago TEXT DEFAULT 'Pendiente', estado_consumo TEXT DEFAULT 'Pendiente', precio INTEGER, fecha_creacion TEXT, institucion TEXT, precio_aplicado INTEGER, metodo_pago TEXT DEFAULT 'Pendiente', correo TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS precios (servicio TEXT PRIMARY KEY, precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS platos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, servicio TEXT, valor INTEGER, activo INTEGER DEFAULT 1, descripcion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS minutas (id INTEGER PRIMARY KEY AUTOINCREMENT, dia_semana TEXT, servicio TEXT, plato TEXT, activo INTEGER DEFAULT 1)")
    cur.execute("CREATE TABLE IF NOT EXISTS bodega_inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo_insumo TEXT, nombre_articulo TEXT, unidad TEXT, stock REAL, precio INTEGER, critico REAL, caduca TEXT, foto_path TEXT, seccion TEXT DEFAULT 'General')")
    cur.execute("CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY AUTOINCREMENT, plato TEXT, insumo TEXT, cantidad REAL, unidad TEXT, instrucciones TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, codigo_insumo TEXT, nombre_articulo TEXT, cantidad REAL, motivo TEXT, usuario TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS reclamos_sugerencias (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, nombre TEXT, tipo TEXT, categoria TEXT, mensaje TEXT, fecha TEXT, estado TEXT DEFAULT 'Pendiente', respuesta TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS bodega_cargas_log (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, usuario TEXT, archivo_nombre TEXT, filas_ok INTEGER, filas_error INTEGER, errores TEXT, responsable TEXT, tipo_carga TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventarios_aleatorios (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha_generada TEXT, fecha_programada TEXT, seccion TEXT, articulos TEXT, responsable TEXT, estado TEXT DEFAULT 'Pendiente', fecha_realizado TEXT, resultado TEXT)")

    # Migraciones para DB vieja
    def add_col(tabla, col, typ):
        try:
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {typ}")
        except: pass
    add_col("solicitudes","institucion","TEXT")
    add_col("solicitudes","precio_aplicado","INTEGER")
    add_col("solicitudes","metodo_pago","TEXT")
    add_col("solicitudes","correo","TEXT")
    add_col("solicitudes","fecha_creacion","TEXT")
    add_col("comensales","fecha_registro","TEXT")
    add_col("bodega_inventario","seccion","TEXT DEFAULT 'General'")
    add_col("platos","activo","INTEGER DEFAULT 1")
    add_col("platos","descripcion","TEXT")
    add_col("instituciones","precio_dia","INTEGER DEFAULT 6400")
    add_col("instituciones","precio_especial","INTEGER")
    add_col("instituciones","regla_activa","INTEGER DEFAULT 0")
    add_col("instituciones","activa","INTEGER DEFAULT 1")
    add_col("instituciones","descripcion","TEXT")

    for u,p,r,n in [("admin","admin123","Admin","Admin Total"),("cocina","cocina123","Cocina","Encargado Cocina"),("bodega","bodega123","Bodega","Encargado Bodega"),("finanzas","finanzas123","Finanzas","Encargado Finanzas"),("gerencia","gerencia123","Gerencia","Gerencia")]:
        cur.execute("INSERT OR IGNORE INTO usuarios (username,pwd,rol,nombre) VALUES (?,?,?,?)",(u,hash_pwd(p),r,n))

    # V19.3 - Todos precio estándar 6400, admin asigna por casilla
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
    for inst in instituciones_default:
        cur.execute("INSERT OR IGNORE INTO instituciones (nombre,precio_dia,precio_especial,regla_activa,activa,descripcion) VALUES (?,?,?,?,?,?)", inst)

    cur.execute("SELECT COUNT(*) FROM precios")
    if cur.fetchone()[0]==0:
        for s,pr in [("Desayuno",3500),("Almuerzo",6500),("Once",3500),("Cena",5500),("DIA_COMPLETO",6400)]: cur.execute("INSERT OR IGNORE INTO precios VALUES (?,?)",(s,pr))

    cur.execute("SELECT COUNT(*) FROM bodega_inventario")
    if cur.fetchone()[0]==0:
        base=[('ABA-ARROZ-78','Arroz','kilo',50,1567,10,'2027-01-30','General'),('ABA-LENTEJ-73','Lentejas','kilo',20,3278,5,'2026-09-29','Abarrotes'),('CAR-CARNEM-43','Carne Molida','kilo',15,10929,5,'2026-12-15','Carnes'),('CAR-PECHUG-33','Pechuga Pollo','kilo',15,8291,5,'2026-10-06','Carnes'),('OVO-HUEVOS-18','Huevos','unidad',100,276,5,'2026-12-22','Lácteos')]
        for r in base: cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca,seccion) VALUES (?,?,?,?,?,?,?,?)",r)

    cur.execute("SELECT COUNT(*) FROM platos")
    if cur.fetchone()[0]==0:
        for n,s,v in [('Carbonada','Almuerzo',6500),('Lentejas con arroz','Almuerzo',6500),('Pollo asado con puré','Almuerzo',6500),('Cazuela vacuno','Almuerzo',6500),('Desayuno americano','Desayuno',3500)]: cur.execute("INSERT INTO platos (nombre,servicio,valor,activo) VALUES (?,?,?,1)",(n,s,v))

    cur.execute("SELECT COUNT(*) FROM recetas")
    if cur.fetchone()[0]==0:
        cur.execute("INSERT INTO recetas (plato,insumo,cantidad,unidad,instrucciones) VALUES ('Carbonada','Arroz',0.15,'kilo','Cocinar arroz'),('Carbonada','Carne Molida',0.2,'kilo','Freir')")

    cur.execute("SELECT COUNT(*) FROM minutas")
    if cur.fetchone()[0]==0:
        for dia, servs in MINUTA.items():
            for serv, platos in servs.items():
                for plato in platos:
                    cur.execute("INSERT INTO minutas (dia_semana,servicio,plato,activo) VALUES (?,?,?,1)",(dia,serv,plato))

    conn.commit(); conn.close()
