"""
ERP Mamuil Malal - V7 MEJORADA - FINAL
- RUT normalizado: 16.632.880-2 = 16632880-2 = 16 632 880-2 (misma persona)
- Comensal: 1) Elige días en calendario chips 2) Wizard día x día con menú estático
- No queda preseleccionado al pasar de día
- Finaliza -> Ticket + Orden cocina + Descuento bodega automático + Reporte finanzas
- Interfaz amigable tipo app delivery, no Access
"""
import streamlit as st
import sqlite3, pandas as pd, hashlib, random, re, os
from datetime import datetime, date, timedelta
from pathlib import Path

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def enviar_email(destinatario, asunto, html_body):
    """Usa secrets de Streamlit: [email] smtp_server, smtp_port, email_user, email_pass"""
    try:
        cfg = st.secrets.get("email", {})
        if not cfg:
            return False, "No hay secrets [email] configurados"
        server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"])
        server.starttls()
        server.login(cfg["email_user"], cfg["email_pass"])
        msg = MIMEMultipart()
        msg["From"] = cfg["email_user"]
        msg["To"] = destinatario
        msg["Subject"] = asunto
        msg.attach(MIMEText(html_body, "html"))
        server.send_message(msg)
        server.quit()
        return True, "OK"
    except Exception as e:
        return False, str(e)

def plantilla_ticket(nombre, rut, dias, detalle_html, total, codigos):
    return f"""
    <div style="font-family:'Inter',Arial; background:#FFFFFF; border:1px solid #E9ECEF; border-radius:12px; padding:24px; box-shadow:0 4px 16px rgba(11,47,92,0.06)">
    <div style="background:linear-gradient(135deg,#0B2F5C,#123E7A); padding:16px 20px; border-radius:10px; margin:-24px -24px 20px -24px;">
      <h2 style="color:white; margin:0; font-family:'Sora'">🍽️ Ticket Reserva Mamuil Malal</h2>
      <p style="color:#C9D6EA; margin:4px 0 0 0; font-size:13px;">ALEMSI - Aseo y Servicios Integrales</p>
    </div>
    <p><b>Comensal:</b> {nombre} - {rut}<br>
    <b>Días:</b> {', '.join(dias)}<br>
    <b>Total:</b> <span style="background:#E6FFF5; color:#006644; padding:4px 10px; border-radius:20px; font-weight:700;">{total}</span></p>
    {detalle_html}
    <p><b>Códigos acceso:</b> <code style="background:#F8F9FA; padding:6px 10px; border-radius:8px; border:1px dashed #0B2F5C;">{', '.join(codigos)}</code></p>
    <hr style="border:1px solid #E9ECEF; margin:16px 0;">
    <p style="background:#F8F9FA; padding:12px; border-radius:8px; font-size:13px;"><b>Datos pago transferencia:</b><br>
    Comercial Mamuil Malal Ltda - RUT 76.123.456-7<br>
    Banco Estado - Cta Cte 12345678<br>
    finanzas@alemsi.cl</p>
    <small style="color:#64748B;">Presenta este código en casino - Estado: <span class="badge badge-pendiente">Pendiente</span></small>
    </div>
    """


DB_PATH = "casino_erp.db"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
for f in ["logo","platos","inventario"]:
    (UPLOAD_DIR/f).mkdir(exist_ok=True)

st.set_page_config(page_title="Mamuil V7 Mejorada", page_icon="🍽️", layout="wide")

# ========= ESTILO ALEMSI - INSTAGRAM REAL @alemsichile =========
# Colores extraidos de IG: degradé azul profesional dominante, logo verde en apex, titular amarillo-blanco, botón amarillo ¡APLICA AHORA!, check amarillo
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
.chip-day{display:inline-block; padding:14px 18px; border-radius:12px; border:1.5px solid var(--alemsi-border); margin:6px; background:white; font-weight:600; width:140px; text-align:center; color:var(--alemsi-blue); transition:.22s;}
.chip-day:hover{border-color:var(--alemsi-blue); background:var(--alemsi-blue-light); transform:translateY(-2px);}
.chip-selected{background:var(--alemsi-blue) !important; color:white !important; border-color:var(--alemsi-blue) !important; box-shadow:0 8px 20px rgba(10,47,107,0.25) !important;}
div[data-testid="stButton"]>button{border-radius:12px !important; font-weight:700 !important; transition:all .2s ease !important;}
div[data-testid="stButton"]>button[kind="primary"]{background:var(--alemsi-yellow) !important; color:#1A1A1A !important; border:1px solid var(--alemsi-yellow) !important; box-shadow:0 6px 16px rgba(255,212,0,0.35);}
div[data-testid="stButton"]>button[kind="primary"]:hover{background:var(--alemsi-yellow-hover) !important; transform:translateY(-1px); box-shadow:0 8px 22px rgba(255,212,0,0.45);}
div[data-testid="stButton"]>button[kind="secondary"]{background:white !important; color:var(--alemsi-blue) !important; border:1.5px solid var(--alemsi-border) !important;}
div[data-testid="stButton"]>button[kind="secondary"]:hover{border-color:var(--alemsi-green) !important; color:var(--alemsi-green) !important; background:#F0FDF4 !important;}
.badge{padding:6px 12px; border-radius:20px; font-size:12px; font-weight:700; display:inline-block;}
.badge-pendiente{background:#FFF8E1; color:#8D6E00; border:1px solid #FFECB3;}
.badge-proceso{background:#E8F0FE; color:var(--alemsi-blue); border:1px solid #C9D6EA;}
.badge-completado{background:#E6FFF5; color:#006644; border:1px solid #00A650; position:relative; padding-left:26px;}
.badge-completado::before{content:"✔"; position:absolute; left:10px; color:var(--alemsi-yellow); background:var(--alemsi-blue); width:14px; height:14px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:9px; top:50%; transform:translateY(-50%);}
.badge-no-pagado{background:#FFEBEE; color:#B71C1C; border:1px solid #FFCDD2;}
.al-check{color:var(--alemsi-yellow); background:var(--alemsi-blue); border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; justify-content:center; margin-right:8px; font-size:12px;}
[data-testid="stDataFrame"],[data-testid="stTable"]{background:white; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(10,47,107,0.04); border:1px solid var(--alemsi-border);}
[data-testid="stSidebar"]{background:white !important; border-right:1px solid var(--alemsi-border);}
[data-testid="stMetric"]{border-left:4px solid var(--alemsi-yellow); background:white;}
</style>
""", unsafe_allow_html=True)

# Helper visual para badges
# Helper visual para badges
def badge_estado(estado: str) -> str:
    e=estado.lower()
    if "pendiente" in e or "por validar" in e:
        return f'<span class="badge badge-pendiente">● {estado}</span>'
    elif "proceso" in e or "prepar" in e:
        return f'<span class="badge badge-proceso">◐ {estado}</span>'
    elif "completado" in e or "consumido" in e or "pagado" in e:
        return f'<span class="badge badge-completado">✔ {estado}</span>'
    else:
        return f'<span class="badge badge-pendiente">{estado}</span>'


# ========= HELPERS =========
def get_conn(): return sqlite3.connect(DB_PATH, check_same_thread=False)
def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()
def formato_clp(v): 
    try: return f"${int(v):,}".replace(",",".")
    except: return str(v)

def normalizar_rut(rut: str) -> str:
    if not rut: return ""
    limpio = re.sub(r'[^0-9Kk]', '', rut).upper()
    if len(limpio) < 2: return limpio
    cuerpo, dv = limpio[:-1], limpio[-1]
    return f"{cuerpo}-{dv}"

def gen_codigo(rut, serv, fecha):
    return f"{normalizar_rut(rut)[:4]}-{serv[:3].upper()}-{fecha.strftime('%d%m')}-{random.randint(100,999)}"

MINUTA = {
    "Lunes": {"Desayuno":["Desayuno americano","Té + pan con huevo","Avena + fruta"],"Almuerzo":["Carbonada","Lentejas con arroz","Pollo asado con puré"],"Once":["Té + pan con palta","Té + sándwich ave"],"Cena":["Crema + sandwich","Tallarines"]},
    "Martes":{"Desayuno":["Desayuno americano","Yogurt + granola"],"Almuerzo":["Cazuela vacuno","Porotos con riendas","Chuleta con arroz"],"Once":["Té + pan con huevo"],"Cena":["Charquicán"]},
    "Miércoles":{"Desayuno":["Desayuno continental"],"Almuerzo":["Pastel de papas","Garbanzos con mote","Pescado frito"],"Once":["Té + pan con palta"],"Cena":["Carbonada"]},
    "Jueves":{"Desayuno":["Desayuno americano"],"Almuerzo":["Pollo al jugo","Lentejas con longaniza","Pollo arvejado","Puré con carne"],"Once":["Té + jamón queso"],"Cena":["Porotos"]},
    "Viernes":{"Desayuno":["Desayuno completo"],"Almuerzo":["Cazuela ave","Fideos boloñesa","Asado olla"],"Once":["Té + pan"],"Cena":["Chupe jurel"]},
    "Sábado":{"Desayuno":["Desayuno americano"],"Almuerzo":["Carbonada","Arroz con pollo"],"Once":["Té + pan"],"Cena":["Sopa + sándwich"]},
}

INVENTARIO_REAL = [
    ('ABA-ARROZ-78','Arroz','kilo',50,1567,10,'2027-01-30'),('ABA-LENTEJ-73','Lentejas','kilo',20,3278,5,'2026-09-29'),
    ('CAR-CARNEM-43','Carne Molida','kilo',15,10929,5,'2026-12-15'),('CAR-PECHUG-33','Pechuga Pollo','kilo',15,8291,5,'2026-10-06'),
    ('OVO-HUEVOS-18','Huevos','unidad',100,276,5,'2026-12-22'),('CON-PAPASP-32','Papas','kilo',20,3559,5,'2026-12-20'),
]
PLATOS_REAL = [
    ('Carbonada','Almuerzo',6500),('Lentejas con arroz','Almuerzo',6500),('Pollo asado con puré','Almuerzo',6500),
    ('Cazuela vacuno','Almuerzo',6500),('Chuleta con arroz','Almuerzo',6500),('Pastel de papas','Almuerzo',6500),
    ('Garbanzos con mote','Almuerzo',6500),('Pescado frito','Almuerzo',7000),('Pollo arvejado','Almuerzo',6500),
    ('Puré con carne','Almuerzo',6500),('Desayuno americano','Desayuno',3500),('Té + pan con huevo','Desayuno',3000),
    ('Avena + fruta','Desayuno',2800),('Crema + sandwich','Cena',5500),('Charquicán','Cena',5500),
]

def init_db():
    conn=get_conn(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, pwd TEXT, rol TEXT, nombre TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS comensales (rut TEXT PRIMARY KEY, nombre TEXT, telefono TEXT, correo TEXT, institucion TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS solicitudes (id INTEGER PRIMARY KEY AUTOINCREMENT, rut TEXT, fecha TEXT, servicio TEXT, plato TEXT, codigo TEXT, estado_pago TEXT DEFAULT 'Pendiente', estado_consumo TEXT DEFAULT 'Pendiente', precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS precios (servicio TEXT PRIMARY KEY, precio INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS precios_platos (plato TEXT PRIMARY KEY, precio INTEGER, servicio TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS bodega_inventario (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo_insumo TEXT, nombre_articulo TEXT, unidad TEXT, stock REAL, precio INTEGER, critico REAL, caduca TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS platos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, servicio TEXT, valor INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS recetas (id INTEGER PRIMARY KEY AUTOINCREMENT, plato TEXT, insumo TEXT, cantidad REAL)")
    for u,p,r,n in [("admin","admin123","Admin","Admin"),("cocina","cocina123","Cocina","Cocina"),("finanzas","finanzas123","Finanzas","Finanzas"),("gerencia","gerencia123","Gerencia","Gerencia")]:
        cur.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?)",(u,hash_pwd(p),r,n))
    cur.execute("SELECT COUNT(*) FROM precios")
    if cur.fetchone()[0]==0:
        for s,pr in [("Desayuno",3500),("Almuerzo",6500),("Once",3500),("Cena",5500)]: cur.execute("INSERT INTO precios VALUES (?,?)",(s,pr))
    cur.execute("SELECT COUNT(*) FROM bodega_inventario")
    if cur.fetchone()[0]==0:
        for r in INVENTARIO_REAL: cur.execute("INSERT INTO bodega_inventario VALUES (NULL,?,?,?,?,?,?,?)",r)
    cur.execute("SELECT COUNT(*) FROM platos")
    if cur.fetchone()[0]==0:
        for n,s,v in PLATOS_REAL: cur.execute("INSERT INTO platos (nombre,servicio,valor) VALUES (?,?,?)",(n,s,v))
    # recetas ejemplo para descuento
    cur.execute("SELECT COUNT(*) FROM recetas")
    if cur.fetchone()[0]==0:
        cur.execute("INSERT INTO recetas (plato,insumo,cantidad) VALUES ('Carbonada','Arroz',0.15),('Carbonada','Carne Molida',0.2),('Lentejas con arroz','Lentejas',0.2),('Lentejas con arroz','Arroz',0.1),('Pollo asado con puré','Pechuga Pollo',0.25)")
    conn.commit(); conn.close()
init_db()

def get_precio(plato, servicio):
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT precio FROM precios_platos WHERE plato=?",(plato,))
    row=cur.fetchone()
    if row: 
        conn.close(); return row[0]
    cur.execute("SELECT valor FROM platos WHERE nombre=?",(plato,))
    row=cur.fetchone(); conn.close()
    if row: return row[0]
    conn=get_conn(); df=pd.read_sql_query("SELECT precio FROM precios WHERE servicio=?",conn,params=(servicio,)); conn.close()
    return int(df.iloc[0][0]) if not df.empty else 3500

def descontar_bodega(plato):
    conn=get_conn(); cur=conn.cursor()
    cur.execute("SELECT insumo,cantidad FROM recetas WHERE plato=?",(plato,))
    for insumo,cant in cur.fetchall():
        cur.execute("SELECT id,stock FROM bodega_inventario WHERE nombre_articulo LIKE ? ORDER BY caduca ASC",(f"%{insumo}%",))
        for id_,stock in cur.fetchall():
            if cant<=0: break
            desc=min(stock,cant)
            cur.execute("UPDATE bodega_inventario SET stock=stock-? WHERE id=?",(desc,id_))
            cant-=desc
    conn.commit(); conn.close()

# ========= SESION =========
if "usuario" not in st.session_state: st.session_state.usuario=None
if "rut_actual" not in st.session_state: st.session_state.rut_actual=None
if "dias_sel" not in st.session_state: st.session_state.dias_sel=[]
if "wizard_idx" not in st.session_state: st.session_state.wizard_idx=0
if "pedidos" not in st.session_state: st.session_state.pedidos={}  # {fecha_iso: {servicio: plato}}

# ========= LOGIN =========
if not st.session_state.usuario and not st.session_state.rut_actual:
    st.markdown('<div class="main-header"><h1>🍽️ Mamuil Malal V7</h1><p>Reserva amigable por días · RUT inteligente · Ticket automático</p></div>', unsafe_allow_html=True)
    t1,t2=st.tabs(["🧑 SOY COMENSAL","🔐 PERSONAL"])
    with t1:
        st.markdown("### 1️⃣ Ingresa tu RUT")
        st.caption("Puedes escribir 16.632.880-2, 16632880-2 o 16 632 880 2 — es la misma persona, lo normalizamos automático")
        rut_raw=st.text_input("RUT", placeholder="Ej: 16.632.880-2")
        if rut_raw:
            rut_norm=normalizar_rut(rut_raw)
            conn=get_conn(); df=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rut_norm,)); conn.close()
            if not df.empty:
                st.success(f"¡Hola {df.iloc[0]['nombre']}! RUT reconocido como {rut_norm}")
                if st.button("Continuar → Elegir días", type="primary", use_container_width=True):
                    st.session_state.rut_actual=rut_norm; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
            else:
                st.info("Primera vez, completa tus datos (se guardará como "+rut_norm+")")
                with st.form("reg"):
                    c1,c2=st.columns(2)
                    with c1: nombre=st.text_input("Nombre completo*"); tel=st.text_input("Teléfono*")
                    with c2: correo=st.text_input("Correo"); inst=st.selectbox("Institución",["Mamuil","SAG","Aduanas","PDI","Carabineros","Otro"])
                    if st.form_submit_button("Registrarme y continuar", type="primary"):
                        if nombre and tel:
                            conn=get_conn(); cur=conn.cursor()
                            cur.execute("INSERT OR REPLACE INTO comensales VALUES (?,?,?,?,?)",(rut_norm,nombre,tel,correo,inst))
                            conn.commit(); conn.close()
                            st.session_state.rut_actual=rut_norm; st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
                        else: st.error("Nombre y teléfono obligatorios")
    with t2:
        with st.form("login"):
            u=st.text_input("Usuario"); p=st.text_input("Contraseña", type="password")
            if st.form_submit_button("Ingresar"):
                conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT username,rol,nombre FROM usuarios WHERE username=? AND pwd=?",(u,hash_pwd(p))); row=cur.fetchone(); conn.close()
                if row: st.session_state.usuario={"username":row[0],"rol":row[1],"nombre":row[2]}; st.rerun()
                else: st.error("admin/admin123, cocina/cocina123, finanzas/finanzas123, gerencia/gerencia123")
    st.stop()

# ========= PERSONAL =========
if st.session_state.usuario:
    user=st.session_state.usuario; rol=user['rol']
    st.sidebar.success(f"{user['nombre']} - {rol}")
    if st.sidebar.button("Cerrar sesión"): st.session_state.usuario=None; st.rerun()
    menu=[]
    if rol in ["Admin","Gerencia"]: menu+=["💲 Precios","📦 Bodega","📊 Dashboard"]
    if rol in ["Cocina","Admin"]: menu+=["✅ Check-in","👨‍🍳 Producción Semanal"]
    if rol in ["Finanzas","Admin"]: menu+=["💰 Validar Pagos"]
    sel=st.sidebar.radio("Menú", menu)
    if sel=="✅ Check-in":
        st.markdown('<div class="main-header"><h1>Check-in</h1></div>', unsafe_allow_html=True)
        cod=st.text_input("Código voucher"); 
        if st.button("Validar"):
            conn=get_conn(); cur=conn.cursor(); cur.execute("SELECT id,estado_consumo,estado_pago FROM solicitudes WHERE codigo=?",(cod.strip(),)); row=cur.fetchone()
            if not row: st.error("Código no existe")
            elif row[1]=="Consumido": st.warning("Ya consumido")
            elif row[2]!="Pagado": st.error("No pagado")
            else: cur.execute("UPDATE solicitudes SET estado_consumo='Consumido' WHERE id=?",(row[0],)); conn.commit(); st.success("✅ ACCESO OK"); st.balloons()
            conn.close()
    elif sel=="👨‍🍳 Producción Semanal":
        st.markdown('<div class="main-header"><h1>Producción Semanal - Cocina</h1></div>', unsafe_allow_html=True)
        d1=st.date_input("Desde", value=date.today()); d2=st.date_input("Hasta", value=date.today()+timedelta(days=6))
        conn=get_conn(); df=pd.read_sql_query("SELECT fecha,servicio,plato,COUNT(*) as cant FROM solicitudes WHERE fecha BETWEEN ? AND ? GROUP BY fecha,servicio,plato ORDER BY fecha,servicio",conn,params=(d1.isoformat(),d2.isoformat())); conn.close()
        st.dataframe(df,use_container_width=True)
        st.info("Esta tabla es la orden de servicio semanal. Al confirmar reservas se descuenta automático de bodega.")
    elif sel=="💲 Precios":
        st.markdown('<div class="main-header"><h1>Editar Precios</h1></div>', unsafe_allow_html=True)
        conn=get_conn(); df=pd.read_sql_query("SELECT servicio,precio FROM precios",conn); conn.close()
        for _,r in df.iterrows():
            c1,c2=st.columns([3,2]); c1.write(f"{r['servicio']}"); pr=c2.number_input(f"Precio {r['servicio']}", value=int(r['precio']), key=f"pr_{r['servicio']}")
            if st.button(f"Guardar {r['servicio']}", key=f"btn_{r['servicio']}"):
                conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE precios SET precio=? WHERE servicio=?",(pr,r['servicio'])); conn.commit(); conn.close(); st.success("Guardado"); st.rerun()
    elif sel=="📦 Bodega":
        conn=get_conn(); df=pd.read_sql_query("SELECT nombre_articulo,stock,critico FROM bodega_inventario",conn); conn.close(); st.dataframe(df,use_container_width=True)
    elif sel=="💰 Validar Pagos":
        conn=get_conn(); df=pd.read_sql_query("SELECT s.id,c.rut,c.nombre,s.fecha,s.servicio,s.plato,s.precio,s.estado_pago FROM solicitudes s JOIN comensales c ON s.rut=c.rut ORDER BY s.id DESC",conn); conn.close()
        st.dataframe(df,use_container_width=True)
        idp=st.number_input("ID a pagar", min_value=0, step=1)
        if st.button("Marcar Pagado"):
            conn=get_conn(); cur=conn.cursor(); cur.execute("UPDATE solicitudes SET estado_pago='Pagado' WHERE id=?",(idp,)); conn.commit(); conn.close(); st.success("Pagado"); st.rerun()
    elif sel=="📊 Dashboard":
        conn=get_conn(); tot=pd.read_sql_query("SELECT COUNT(*) c FROM solicitudes",conn).iloc[0]['c']; conn.close(); st.metric("Solicitudes",tot)
    st.stop()

# ========= COMENSAL WIZARD =========
# 1 - SELECCIONAR DIAS
rut=st.session_state.rut_actual
conn=get_conn(); com=pd.read_sql_query("SELECT * FROM comensales WHERE rut=?",conn,params=(rut,)); conn.close()
nombre=com.iloc[0]['nombre'] if not com.empty else rut

st.markdown(f'<div class="main-header"><h1>Hola {nombre} 👋</h1><p>Reserva tu semana en 3 pasos</p></div>', unsafe_allow_html=True)

if not st.session_state.dias_sel:
    st.markdown("## 📅 Paso 1: ¿Qué días vas a usar el casino?")
    st.caption("Pincha los días (puedes elegir varios). Lunes a Sábado próximos.")
    hoy=date.today()
    lunes=hoy - timedelta(days=hoy.weekday())
    if hoy.weekday()==6: lunes+=timedelta(days=7)
    dias=[lunes+timedelta(days=i) for i in range(12)]  # 12 días
    cols=st.columns(3)
    for i,d in enumerate(dias):
        label=f"{['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'][d.weekday()]} {d.strftime('%d/%m')}"
        with cols[i%3]:
            if st.button(label, key=f"dia_{d.isoformat()}", use_container_width=True, type="primary" if d.isoformat() in st.session_state.dias_sel else "secondary"):
                if d.isoformat() in st.session_state.dias_sel: st.session_state.dias_sel.remove(d.isoformat())
                else: st.session_state.dias_sel.append(d.isoformat())
                st.rerun()
    if st.session_state.dias_sel:
        st.success(f"Días elegidos: {len(st.session_state.dias_sel)} → {', '.join(st.session_state.dias_sel)}")
        if st.button("Siguiente → Elegir menú", type="primary", use_container_width=True):
            st.session_state.dias_sel=sorted(st.session_state.dias_sel)
            st.session_state.wizard_idx=0
            st.session_state.pedidos={d:{} for d in st.session_state.dias_sel}
            st.rerun()
    st.stop()

# 2 - WIZARD DIA X DIA
dias=sorted(st.session_state.dias_sel)
idx=st.session_state.wizard_idx
if idx >= len(dias):
    # RESUMEN FINAL
    st.markdown("## 🧾 Paso 3: Resumen y Ticket")
    total=0; detalle=[]
    for fecha_iso in dias:
        dia_nombre=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][date.fromisoformat(fecha_iso).weekday()]
        for serv,plato in st.session_state.pedidos.get(fecha_iso,{}).items():
            if plato:
                pr=get_precio(plato,serv)
                total+=pr
                detalle.append((fecha_iso,dia_nombre,serv,plato,pr))
    if not detalle:
        st.warning("No seleccionaste platos"); 
        if st.button("Volver"): st.session_state.wizard_idx=0; st.rerun()
        st.stop()
    df_det=pd.DataFrame(detalle, columns=["Fecha","Día","Servicio","Plato","Precio"])
    st.dataframe(df_det, use_container_width=True)
    st.metric("TOTAL A PAGAR", formato_clp(total))
    st.divider()
    st.markdown("### 💳 Medio de pago")
    medio=st.radio("Elige", ["Transferencia Bancaria","Débito en Casino"], horizontal=True)
    if medio=="Transferencia Bancaria":
        st.info("**Comercial Mamuil Malal Ltda**\nRUT: 76.123.456-7\nBanco Estado\nCuenta Corriente: 12345678\nCorreo: finanzas@alemsi.cl\n\nIndica tu RUT en la transferencia")
    else:
        st.info("Pagarás con débito directamente en el casino. Tu reserva queda en 'Pendiente' hasta pagar.")
    if st.button("✅ FINALIZAR RESERVA SEMANAL - Generar Ticket", type="primary", use_container_width=True):
        conn=get_conn(); cur=conn.cursor()
        vouchers=[]
        for fecha_iso,dia_nombre,serv,plato,pr in detalle:
            codigo=gen_codigo(rut,serv,date.fromisoformat(fecha_iso))
            cur.execute("INSERT INTO solicitudes (rut,fecha,servicio,plato,codigo,precio,estado_pago) VALUES (?,?,?,?,?,?,?)",
                        (rut,fecha_iso,serv,plato,codigo,pr,"Pendiente" if medio=="Débito en Casino" else "Por Validar"))
            vouchers.append(codigo)
            # descuento bodega automático
            descontar_bodega(plato)
        conn.commit(); conn.close()
        st.balloons()
        # --- ENVIO EMAILS AUTOMATICOS ---
        # 1. Al comensal
        try:
            conn_e=get_conn()
            df_e=pd.read_sql_query("SELECT correo FROM comensales WHERE rut=?",conn_e,params=(rut,))
            conn_e.close()
            correo_dest = df_e.iloc[0]['correo'] if not df_e.empty else None
            detalle_html = df_det.to_html(index=False)
            html_ticket = plantilla_ticket(nombre, rut, dias, detalle_html, formato_clp(total), vouchers)
            if correo_dest and "@" in correo_dest:
                ok,msg = enviar_email(correo_dest, f"Ticket Reserva {', '.join(dias)} - Mamuil Malal", html_ticket)
                if ok: st.success(f"📧 Ticket enviado a {correo_dest}")
                else: st.warning(f"No se pudo enviar email comensal: {msg}")
            # 2. A cocina (si existe, ahora usamos gerencia para demo)
            enviar_email("cocina@alemsi.cl", f"Nueva Orden {', '.join(dias)} - {nombre}", html_ticket)
            # 3. A finanzas - TU PEDIDO
            enviar_email("finanzas@alemsi.cl", f"💰 Reserva {formato_clp(total)} - {nombre} - {rut}", html_ticket)
            # 4. A gerencia - TU PEDIDO
            enviar_email("gerencia@alemsi.cl", f"📊 Nueva Reserva Semanal - {nombre} - {formato_clp(total)}", html_ticket)
        except Exception as e:
            st.caption(f"Email no configurado aún: {e}")

        st.markdown(f"""
        <div class="ticket">
        <h2>🎟️ Ticket Reserva Semanal - Mamuil Malal</h2>
        <p><b>Comensal:</b> {nombre} - {rut}</p>
        <p><b>Días:</b> {', '.join(dias)}</p>
        <p><b>Total:</b> {formato_clp(total)} - {medio}</p>
        <p><b>Códigos:</b> {', '.join(vouchers[:6])}...</p>
        <p>Guarda este ticket. Cada código es tu acceso al casino por servicio.</p>
        <hr>
        <small>Orden de servicio enviada a cocina y reporte a finanzas generado automáticamente.</small>
        </div>
        """, unsafe_allow_html=True)
        st.dataframe(df_det, use_container_width=True)
        if st.button("Nueva reserva"):
            st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
    if st.button("← Editar días"):
        st.session_state.dias_sel=[]; st.rerun()
    st.stop()

# mostrar dia actual del wizard
fecha_actual=dias[idx]
dia_obj=date.fromisoformat(fecha_actual)
dia_nombre=["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][dia_obj.weekday()]

st.markdown(f"## 🍽️ Paso 2: Menú del {dia_nombre} {dia_obj.strftime('%d/%m/%Y')} ({idx+1}/{len(dias)})")
st.progress((idx+1)/len(dias))
st.caption("Elige 1 plato por servicio. No queda nada preseleccionado. Si no quieres un servicio, déjalo sin elegir.")

# inicializar dict dia si no existe
if fecha_actual not in st.session_state.pedidos: st.session_state.pedidos[fecha_actual]={}

for servicio in ["Desayuno","Almuerzo","Once","Cena"]:
    st.markdown(f"### {'☀️' if servicio=='Desayuno' else '🍽️' if servicio=='Almuerzo' else '🫖' if servicio=='Once' else '🌙'} {servicio}")
    opciones=MINUTA.get(dia_nombre,{}).get(servicio,[])
    if not opciones:
        conn=get_conn(); dfp=pd.read_sql_query("SELECT nombre FROM platos WHERE servicio=?",conn,params=(servicio,)); conn.close()
        opciones=dfp['nombre'].tolist()[:6]
    cols=st.columns(2)
    for i,plato in enumerate(opciones):
        pr=get_precio(plato,servicio)
        key=f"pl_{fecha_actual}_{servicio}_{plato}"
        sel_actual=st.session_state.pedidos[fecha_actual].get(servicio)
        is_sel=sel_actual==plato
        with cols[i%2]:
            if st.button(f"{plato}\n{formato_clp(pr)}", key=key, use_container_width=True, type="primary" if is_sel else "secondary"):
                # toggle: si ya estaba seleccionado, deselecciona
                if is_sel: del st.session_state.pedidos[fecha_actual][servicio]
                else: st.session_state.pedidos[fecha_actual][servicio]=plato
                st.rerun()
    sel=st.session_state.pedidos[fecha_actual].get(servicio)
    if sel: st.caption(f"✅ Seleccionado: {sel} - {formato_clp(get_precio(sel,servicio))}")
    st.divider()

c1,c2,c3=st.columns(3)
with c1:
    if st.button("← Día anterior", disabled=idx==0, use_container_width=True):
        st.session_state.wizard_idx-=1; st.rerun()
with c2:
    if st.button("Cancelar reserva", use_container_width=True):
        st.session_state.dias_sel=[]; st.session_state.pedidos={}; st.session_state.wizard_idx=0; st.rerun()
with c3:
    if idx < len(dias)-1:
        if st.button("Siguiente día →", type="primary", use_container_width=True):
            st.session_state.wizard_idx+=1; st.rerun()
    else:
        if st.button("Ver resumen → Ticket", type="primary", use_container_width=True):
            st.session_state.wizard_idx+=1; st.rerun()
