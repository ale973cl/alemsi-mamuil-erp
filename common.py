import sqlite3, hashlib, re, random, smtplib, pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import streamlit as st
from datetime import date
import os
from pathlib import Path

# En Streamlit Cloud el FS es efímero, usamos /tmp si no se puede escribir en repo
DB_PATH = os.environ.get("DB_PATH", "casino_erp.db")
# Si estamos en Streamlit Cloud y el archivo no existe, usar /tmp para que sea escribible
if "/mount/src" in str(Path.cwd()) and not os.path.exists(DB_PATH):
    DB_PATH = "/tmp/casino_erp.db"

EMAILS = {"cocina":"ale973@gmail.com","finanzas":"finanzas@alemsi.cl","gerencia":"gerencia@alemsi.cl"}

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
    :root{
      --alemsi-blue:#0A2F6B; --alemsi-blue-2:#123E7A; --alemsi-blue-light:#E8EEF8;
      --alemsi-green:#00A650; --alemsi-mint:#00C896;
      --alemsi-yellow:#FFD400; --alemsi-yellow-hover:#FFC300;
      --alemsi-bg:#F8F9FA; --alemsi-card:#FFFFFF; --alemsi-border:#E9ECEF; --radius:12px;
    }
    html, body, [data-testid="stAppViewContainer"]{background:var(--alemsi-bg) !important;}
    html, body, [class*="css"]{font-family:'Inter',sans-serif;}
    h1,h2,h3{font-family:'Sora',sans-serif; color:var(--alemsi-blue);}
    .main-header{background:linear-gradient(135deg,var(--alemsi-blue) 0%, var(--alemsi-blue-2) 100%); padding:28px 32px; border-radius:12px; color:white; margin-bottom:22px; box-shadow:0 12px 32px rgba(10,47,107,0.20);}
    .main-header h1{color:white !important;} .main-header p{color:#C9D6EA !important;}
    .main-header::after{content:"ALEMSI • Aseo y Servicios Integrales - @alemsichile"; display:block; font-size:11px; letter-spacing:0.12em; color:#7FB069; margin-top:8px; font-weight:600;}
    .al-card, .card-plato, [data-testid="stMetric"], .ticket{background:var(--alemsi-card); border:1px solid var(--alemsi-border); border-radius:12px; padding:18px 20px; margin:12px 0; box-shadow:0 2px 12px rgba(10,47,107,0.04); transition:all .22s ease;}
    .al-card:hover, .card-plato:hover{transform:translateY(-2px); box-shadow:0 10px 28px rgba(10,47,107,0.09); border-color:var(--alemsi-blue-light);}
    .card-selected{border-color:var(--alemsi-yellow) !important; background:#FFFEF0 !important; box-shadow:0 0 0 2px rgba(255,212,0,0.25) !important;}
    div[data-testid="stButton"]>button{border-radius:12px !important; font-weight:700 !important; transition:all .2s ease !important;}
    div[data-testid="stButton"]>button[kind="primary"]{background:var(--alemsi-yellow) !important; color:#1A1A1A !important; border:1px solid var(--alemsi-yellow) !important; box-shadow:0 6px 16px rgba(255,212,0,0.35);}
    div[data-testid="stButton"]>button[kind="primary"]:hover{background:var(--alemsi-yellow-hover) !important; transform:translateY(-1px);}
    div[data-testid="stButton"]>button[kind="secondary"]{background:white !important; color:var(--alemsi-blue) !important; border:1.5px solid var(--alemsi-border) !important;}
    div[data-testid="stButton"]>button[kind="secondary"]:hover{border-color:var(--alemsi-green) !important; color:var(--alemsi-green) !important; background:#F0FDF4 !important;}
    .badge{padding:6px 12px; border-radius:20px; font-size:12px; font-weight:700; display:inline-block;}
    .badge-pendiente{background:#FFF8E1; color:#8D6E00; border:1px solid #FFECB3;}
    .badge-proceso{background:#E8F0FE; color:var(--alemsi-blue); border:1px solid #C9D6EA;}
    .badge-completado{background:#E6FFF5; color:#006644; border:1px solid #00A650;}
    .badge-no-pagado{background:#FFEBEE; color:#B71C1C; border:1px solid #FFCDD2;}
    [data-testid="stDataFrame"],[data-testid="stTable"]{background:white; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(10,47,107,0.04); border:1px solid var(--alemsi-border);}
    [data-testid="stSidebar"]{background:white !important; border-right:1px solid var(--alemsi-border);}
    [data-testid="stMetric"]{border-left:4px solid var(--alemsi-yellow); background:white;}
    </style>
    """, unsafe_allow_html=True)

def badge_estado(estado: str):
    e=estado.lower()
    if "pendiente" in e or "por validar" in e: return f'<span class="badge badge-pendiente">● {estado}</span>'
    elif "proceso" in e or "prepar" in e: return f'<span class="badge badge-proceso">◐ {estado}</span>'
    elif "completado" in e or "consumido" in e or "pagado" in e: return f'<span class="badge badge-completado">✔ {estado}</span>'
    else: return f'<span class="badge badge-no-pagado">● {estado}</span>'

def get_conn(): 
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)

def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()

def formato_clp(v):
    try: return f"${int(v):,}".replace(",",".")
    except: return str(v)

def normalizar_rut(rut: str) -> str:
    if not rut: return ""
    limpio = re.sub(r'[^0-9Kk]', '', rut).upper()
    if len(limpio) < 2: return limpio
    return f"{limpio[:-1]}-{limpio[-1]}"

def validar_rut_m11(rut: str) -> bool:
    try:
        rn = normalizar_rut(rut)
        cuerpo,dv = rn.split("-")
        suma, mult = 0,2
        for d in reversed(cuerpo):
            suma+=int(d)*mult
            mult=2 if mult==7 else mult+1
        resto=11-(suma%11)
        dv_calc={11:"0",10:"K"}.get(resto,str(resto))
        return dv_calc==dv
    except: return False

def gen_codigo(rut, serv, fecha_obj):
    return f"{normalizar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha_obj.strftime('%d%m')}-{random.randint(100,999)}"

def enviar_email(destino, asunto, html):
    try:
        cfg=st.secrets.get("email",{})
        if not cfg: return False,"Secrets [email] no configurado"
        server=smtplib.SMTP(cfg["smtp_server"],cfg["smtp_port"])
        server.starttls(); server.login(cfg["email_user"],cfg["email_pass"])
        msg=MIMEMultipart()
        msg["From"]=cfg["email_user"]; msg["To"]=destino; msg["Subject"]=asunto
        msg.attach(MIMEText(html,"html"))
        server.send_message(msg); server.quit()
        return True,"OK"
    except Exception as e: return False,str(e)

def get_precio(plato, servicio):
    try:
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT valor FROM platos WHERE nombre=?",(plato,)); row=cur.fetchone(); conn.close()
        if row: return row[0]
        conn=get_conn(); df=pd.read_sql_query("SELECT precio FROM precios WHERE servicio=?",conn,params=(servicio,)); conn.close()
        return int(df.iloc[0][0]) if not df.empty else 3500
    except:
        return 3500

def descontar_bodega(plato):
    """FIX: evita OperationalError usando conexiones separadas y try/except"""
    try:
        conn=get_conn(); cur=conn.cursor()
        cur.execute("SELECT insumo,cantidad FROM recetas WHERE plato=?",(plato,))
        recetas = cur.fetchall()
        conn.close()
        if not recetas:
            return
        for insumo,cant in recetas:
            if cant<=0: continue
            conn2=get_conn(); cur2=conn2.cursor()
            cur2.execute("SELECT id,stock FROM bodega_inventario WHERE nombre_articulo LIKE ? ORDER BY caduca ASC",(f"%{insumo}%",))
            stocks = cur2.fetchall()
            conn2.close()
            for id_,stock in stocks:
                if cant<=0: break
                if stock<=0: continue
                desc=min(float(stock), float(cant))
                conn3=get_conn(); cur3=conn3.cursor()
                cur3.execute("UPDATE bodega_inventario SET stock=stock-? WHERE id=?",(desc,id_))
                conn3.commit(); conn3.close()
                cant-=desc
    except Exception as e:
        # No detener la reserva si falla bodega
        print(f"descontar_bodega error: {e}")
        pass

def init_db():
    conn=get_conn(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, pwd TEXT, rol TEXT, nombre TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS comensales (rut TEXT PRIMARY KEY, nombre TEXT, telefono TEXT, correo TEXT, institucion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS solicitudes (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, fecha TEXT, servicio TEXT, plato TEXT, codigo TEXT, estado_pago TEXT DEFAULT 'Pendiente', estado_consumo TEXT DEFAULT 'Pendiente', precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS precios (servicio TEXT PRIMARY KEY, precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS platos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, servicio TEXT, valor INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS bodega_inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo_insumo TEXT, nombre_articulo TEXT, unidad TEXT, stock REAL, precio INTEGER, critico REAL, caduca TEXT, foto_path TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS recetas (plato TEXT, insumo TEXT, cantidad REAL)")
    cur.execute("CREATE TABLE IF NOT EXISTS mermas (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, codigo_insumo TEXT, nombre_articulo TEXT, cantidad REAL, motivo TEXT, usuario TEXT)")
    for u,p,r,n in [("admin","admin123","Admin","Admin"),("cocina","cocina123","Cocina","Cocina"),("finanzas","finanzas123","Finanzas","Finanzas"),("gerencia","gerencia123","Gerencia","Gerencia")]:
        cur.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?)",(u,hash_pwd(p),r,n))
    cur.execute("SELECT COUNT(*) FROM precios")
    if cur.fetchone()[0]==0:
        for s,pr in [("Desayuno",3500),("Almuerzo",6500),("Once",3500),("Cena",5500)]: cur.execute("INSERT INTO precios VALUES (?,?)",(s,pr))
    cur.execute("SELECT COUNT(*) FROM bodega_inventario")
    if cur.fetchone()[0]==0:
        base=[('ABA-ARROZ-78','Arroz','kilo',50,1567,10,'2027-01-30'),('ABA-LENTEJ-73','Lentejas','kilo',20,3278,5,'2026-09-29'),('CAR-CARNEM-43','Carne Molida','kilo',15,10929,5,'2026-12-15'),('CAR-PECHUG-33','Pechuga Pollo','kilo',15,8291,5,'2026-10-06'),('OVO-HUEVOS-18','Huevos','unidad',100,276,5,'2026-12-22'),('CON-PAPASP-32','Papas','kilo',20,3559,5,'2026-12-20')]
        for r in base: cur.execute("INSERT INTO bodega_inventario (codigo_insumo,nombre_articulo,unidad,stock,precio,critico,caduca) VALUES (?,?,?,?,?,?,?)",r)
    cur.execute("SELECT COUNT(*) FROM platos")
    if cur.fetchone()[0]==0:
        for n,s,v in [('Carbonada','Almuerzo',6500),('Lentejas con arroz','Almuerzo',6500),('Pollo asado con puré','Almuerzo',6500),('Cazuela vacuno','Almuerzo',6500),('Desayuno americano','Desayuno',3500),('Té + pan con huevo','Desayuno',3000)]: cur.execute("INSERT INTO platos (nombre,servicio,valor) VALUES (?,?,?)",(n,s,v))
    cur.execute("SELECT COUNT(*) FROM recetas")
    if cur.fetchone()[0]==0:
        cur.execute("INSERT INTO recetas VALUES ('Carbonada','Arroz',0.15),('Carbonada','Carne Molida',0.2),('Lentejas con arroz','Lentejas',0.2)")
    conn.commit(); conn.close()
