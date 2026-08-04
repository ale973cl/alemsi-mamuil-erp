
import sqlite3, hashlib, re, random, smtplib, pandas as pd, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import streamlit as st
from datetime import date, datetime
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "casino_erp.db")
if "/mount/src" in str(Path.cwd()):
    DB_PATH = "/tmp/casino_erp.db"

EMAILS = {"cocina":"ale973@gmail.com","finanzas":"finanzas@alemsi.cl","gerencia":"gerencia@alemsi.cl","reclamos":"gerencia@alemsi.cl"}
PRECIO_DIA_DEFAULT = 6400

MINUTA = {
    "Lunes": {"Desayuno":["Desayuno americano","Té + pan con huevo","Avena + fruta"],"Almuerzo":["Carbonada","Lentejas con arroz","Pollo asado con puré"],"Once":["Té + pan con palta","Té + sándwich ave"],"Cena":["Crema + sandwich","Tallarines"]},
    "Martes":{"Desayuno":["Desayuno americano","Yogurt + granola"],"Almuerzo":["Cazuela vacuno","Porotos con riendas","Chuleta con arroz"],"Once":["Té + pan con huevo"],"Cena":["Charquicán"]},
    "Miércoles":{"Desayuno":["Desayuno continental"],"Almuerzo":["Pastel de papas","Garbanzos con mote","Pescado frito"],"Once":["Té + pan con palta"],"Cena":["Carbonada"]},
    "Jueves":{"Desayuno":["Desayuno americano"],"Almuerzo":["Pollo al jugo","Lentejas con longaniza","Pollo arvejado","Puré con carne"],"Once":["Té + jamón queso"],"Cena":["Porotos"]},
    "Viernes":{"Desayuno":["Desayuno completo"],"Almuerzo":["Cazuela ave","Fideos boloñesa","Asado olla"],"Once":["Té + pan"],"Cena":["Chupe jurel"]},
    "Sábado":{"Desayuno":["Desayuno americano"],"Almuerzo":["Carbonada","Arroz con pollo"],"Once":["Té + pan"],"Cena":["Sopa + sándwich"]},
}

def apply_alemsi_style():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Sora:wght@600;700&display=swap');
    :root{--alemsi-blue:#0A2F6B; --alemsi-blue-2:#123E7A; --alemsi-yellow:#FFD400; --alemsi-bg:#F8F9FA; --alemsi-border:#E9ECEF;}
    html, body, [data-testid="stAppViewContainer"]{background:var(--alemsi-bg) !important;}
    html, body, [class*="css"]{font-family:'Inter',sans-serif;}
    h1,h2,h3{font-family:'Sora',sans-serif; color:var(--alemsi-blue);}
    [data-testid="stSidebarNav"]{display:none !important;} [data-testid="stSidebar"]{display:none !important;} [data-testid="collapsedControl"]{display:none !important;}
    .main-header{background:linear-gradient(135deg,var(--alemsi-blue) 0%, var(--alemsi-blue-2) 100%); padding:28px 32px; border-radius:12px; color:white; margin-bottom:22px; box-shadow:0 12px 32px rgba(10,47,107,0.20);}
    .main-header h1{color:white !important; font-size:28px !important;} .main-header p{color:#C9D6EA !important;}
    .al-card{background:white; border:1px solid var(--alemsi-border); border-radius:12px; padding:18px 20px; margin:12px 0; box-shadow:0 2px 12px rgba(10,47,107,0.04);}
    div[data-testid="stButton"]>button{border-radius:12px !important; font-weight:700 !important; min-height:48px; transition:all .2s ease;}
    div[data-testid="stButton"]>button[kind="primary"]{background:var(--alemsi-yellow) !important; color:#1A1A1A !important; border:1px solid var(--alemsi-yellow) !important;}
    /* RESPONSIVE */
    @media (max-width: 1024px){
        .main-header{padding:20px 24px;} .main-header h1{font-size:22px !important;}
        [data-testid="column"]{flex:1 1 50% !important; min-width:50% !important;}
    }
    @media (max-width: 768px){
        html, body{font-size:15px;} .main-header{padding:16px 18px; border-radius:10px; margin-bottom:14px;}
        .main-header h1{font-size:20px !important; line-height:1.2;} .main-header p{font-size:13px;}
        .al-card{padding:14px 14px; margin:8px 0;}
        div[data-testid="stButton"]>button{width:100% !important; min-height:52px; font-size:16px !important; padding:12px 16px;}
        [data-testid="column"]{width:100% !important; flex:1 1 100% !important; min-width:100% !important;}
        [data-testid="stHorizontalBlock"]{flex-direction:column; gap:8px;}
        input, select, textarea{font-size:16px !important; min-height:48px;}
    }
    @media (max-width: 480px){
        .main-header h1{font-size:18px !important;} div[data-testid="stButton"]>button{font-size:15px !important; min-height:50px;}
    }
    </style>
    """, unsafe_allow_html=True)

def get_conn(): 
    try: return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    except: return sqlite3.connect("casino_erp.db", check_same_thread=False, timeout=15)

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
    cuerpo = limpio[:-1]
    dv = limpio[-1]
    # Formato visual con puntos
    rev = cuerpo[::-1]
    cuerpo_form=""
    for i,c in enumerate(rev):
        if i>0 and i%3==0: cuerpo_form+="."
        cuerpo_form+=c
    cuerpo_form=cuerpo_form[::-1]
    return f"{cuerpo_form}-{dv}"

def normalizar_rut_db(rut: str) -> str:
    limpio = limpiar_rut(rut)
    if len(limpio) < 2: return limpio
    return f"{limpio[:-1]}-{limpio[-1]}"

def validar_rut_m11(rut: str) -> bool:
    try:
        limpio = limpiar_rut(rut)
        if len(limpio) < 2: return False
        cuerpo = limpio[:-1]
        dv = limpio[-1]
        if not cuerpo.isdigit(): return False
        if len(cuerpo) < 1 or len(cuerpo) > 8: return False
        suma, mult = 0,2
        for d in reversed(cuerpo):
            suma+=int(d)*mult
            mult=2 if mult==7 else mult+1
        resto=11-(suma%11)
        dv_calc={11:"0",10:"K"}.get(resto,str(resto))
        return dv_calc==dv
    except: return False

def get_precio_institucion(institucion: str):
    try:
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT precio_dia, precio_especial, regla_activa FROM instituciones WHERE nombre=?", (institucion,))
        row=cur.fetchone(); conn.close()
        if row:
            precio_dia, precio_especial, regla_activa = row
            if regla_activa and precio_especial is not None:
                return int(precio_especial)
            return int(precio_dia)
        return PRECIO_DIA_DEFAULT
    except: return PRECIO_DIA_DEFAULT

def get_instituciones():
    try:
        conn=get_conn(); df=pd.read_sql_query("SELECT nombre FROM instituciones WHERE activa=1 ORDER BY nombre", conn); conn.close()
        return df['nombre'].tolist() if not df.empty else ["Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad","Visitas"]
    except: return ["Carabineros","PDI","SAG","Aduana","Chofer de Aduana","Alemsi","Coordinadores","Vialidad","Visitas"]

def gen_codigo(rut, serv, fecha_obj): return f"{limpiar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha_obj.strftime('%d%m')}-{random.randint(100,999)}"

def get_precio(plato, servicio):
    try:
        conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT valor FROM platos WHERE nombre=?",(plato,)); row=cur.fetchone(); conn.close()
        if row: return row[0]
        return 3500
    except: return 3500

def enviar_email(destino, asunto, html):
    try:
        cfg=st.secrets.get("email",{})
        if not cfg: return False,"No configurado"
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
    try: conn=get_conn(); cur=conn.cursor()
    except:
        try:
            if os.path.exists(DB_PATH): os.remove(DB_PATH)
            if os.path.exists("/tmp/casino_erp.db"): os.remove("/tmp/casino_erp.db")
        except: pass
        conn=get_conn(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, pwd TEXT, rol TEXT, nombre TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS instituciones (nombre TEXT PRIMARY KEY, precio_dia INTEGER DEFAULT 6400, precio_especial INTEGER, regla_activa INTEGER DEFAULT 0, activa INTEGER DEFAULT 1, descripcion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS comensales (rut TEXT PRIMARY KEY, nombre TEXT, telefono TEXT, correo TEXT, institucion TEXT, fecha_registro TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS solicitudes (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, fecha TEXT, servicio TEXT, plato TEXT, codigo TEXT, estado_pago TEXT DEFAULT 'Pendiente', estado_consumo TEXT DEFAULT 'Pendiente', precio INTEGER, fecha_creacion TEXT, institucion TEXT, precio_aplicado INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS precios (servicio TEXT PRIMARY KEY, precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS platos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, servicio TEXT, valor INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS bodega_inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo_insumo TEXT, nombre_articulo TEXT, unidad TEXT, stock REAL, precio INTEGER, critico REAL, caduca TEXT, foto_path TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS recetas (plato TEXT, insumo TEXT, cantidad REAL)")
    cur.execute("CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, codigo_insumo TEXT, nombre_articulo TEXT, cantidad REAL, motivo TEXT, usuario TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS reclamos_sugerencias (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, nombre TEXT, tipo TEXT, categoria TEXT, mensaje TEXT, fecha TEXT, estado TEXT DEFAULT 'Pendiente', respuesta TEXT)")
    for u,p,r,n in [("admin","admin123","Admin","Admin"),("cocina","cocina123","Cocina","Cocina"),("bodega","bodega123","Bodega","Bodega"),("finanzas","finanzas123","Finanzas","Finanzas"),("gerencia","gerencia123","Gerencia","Gerencia")]:
        cur.execute("INSERT OR IGNORE INTO usuarios (username,pwd,rol,nombre) VALUES (?,?,?,?)",(u,hash_pwd(p),r,n))
    instituciones_default = [
        ("Carabineros", 6400, 3200, 0, 1, "Convenio 50% oculto"),
        ("PDI", 6400, 3200, 0, 1, "Convenio 50% oculto"),
        ("SAG", 6400, 4500, 0, 1, "Precio SAG"),
        ("Aduana", 6400, 4000, 0, 1, "Precio Aduana"),
        ("Chofer de Aduana", 6400, 3000, 0, 1, "Precio Chofer"),
        ("Alemsi", 6400, 2000, 0, 1, "Precio interno oculto"),
        ("Coordinadores", 6400, 3500, 0, 1, "Coordinadores"),
        ("Vialidad", 6400, 4500, 0, 1, "Vialidad"),
        ("Visitas", 6400, None, 0, 1, "Precio público"),
    ]
    for inst in instituciones_default:
        cur.execute("INSERT OR IGNORE INTO instituciones (nombre,precio_dia,precio_especial,regla_activa,activa,descripcion) VALUES (?,?,?,?,?,?)", inst)
    cur.execute("SELECT COUNT(*) FROM precios")
    if cur.fetchone()[0]==0:
        for s,pr in [("Desayuno",3500),("Almuerzo",6500),("Once",3500),("Cena",5500),("DIA_COMPLETO",6400)]: cur.execute("INSERT OR IGNORE INTO precios VALUES (?,?)",(s,pr))
    cur.execute("SELECT COUNT(*) FROM bodega_inventario")
    if cur.fetchone()[0]==0:
        base=[('ABA-ARROZ-78','Arroz','kilo',50,1567,10,'2027-01-30'),('ABA-LENTEJ-73','Lentejas','kilo',20,3278,5,'2026-09-29'),('CAR-CARNEM-43','Carne Molida','kilo',15,10929,5,'2026-12-15'),('CAR-PECHUG-33','Pechuga Pollo','kilo',15,8291,5,'2026-10-06'),('OVO-HUEVOS-18','Huevos','unidad',100,276,5,'2026-12-22')]
        for r in base: cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca) VALUES (?,?,?,?,?,?,?)",r)
    cur.execute("SELECT COUNT(*) FROM platos")
    if cur.fetchone()[0]==0:
        for n,s,v in [('Carbonada','Almuerzo',6500),('Lentejas con arroz','Almuerzo',6500),('Pollo asado con puré','Almuerzo',6500),('Cazuela vacuno','Almuerzo',6500),('Desayuno americano','Desayuno',3500),('Té + pan con huevo','Desayuno',3000)]: cur.execute("INSERT INTO platos (nombre,servicio,valor) VALUES (?,?,?)",(n,s,v))
    cur.execute("SELECT COUNT(*) FROM recetas")
    if cur.fetchone()[0]==0:
        cur.execute("INSERT INTO recetas VALUES ('Carbonada','Arroz',0.15),('Carbonada','Carne Molida',0.2),('Lentejas con arroz','Lentejas',0.2)")
    conn.commit(); conn.close()
