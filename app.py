# ¡Nuevas importaciones!
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge # Para límite de tamaño
import uuid # Para nombres de archivo únicos
from dotenv import load_dotenv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from apscheduler.schedulers.background import BackgroundScheduler
from weasyprint import HTML
import oracledb
import re
import base64
import traceback
import json
from datetime import datetime, time, timedelta
import pandas as pd
from pypdf import PdfWriter, PdfReader
import io
import qrcode
import bcrypt
from flask_cors import CORS


load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = "supersecretkey"

# --- CONFIGURACIÓN PARA SUBIDA DE ARCHIVOS ---
# Carpeta donde se guardarán las fotos de perfil
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'profile_pics')
# Extensiones permitidas
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'} 
# Tamaño máximo permitido (ej: 2MB)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 # 2 Megabytes 
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Crear la carpeta si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# --- FIN CONFIGURACIÓN ---

# --- CONSTANTES DE SEGURIDAD ---
LOCK_MAX_ATTEMPTS = 3
LOCK_TIME_MIN = 5
# --- NUEVA CONSTANTE: TIMEOUT DE INACTIVIDAD ---
INACTIVITY_TIMEOUT_MINUTES = 5 # 5 minutos
# --- FIN NUEVA CONSTANTE ---

# --- NUEVA CONFIGURACIÓN: Vida de la sesión permanente ---
app.permanent_session_lifetime = timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES)
# --- FIN NUEVA CONFIGURACIÓN ---


# Configuración del cliente de Oracle
#cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# --- CONEXIÓN A LA BASE DE DATOS ---
db_user = 'JEFE_LAB'
db_password = 'jefe123'
dsn = 'localhost:1521/XEPDB1'

def get_db_connection(autocommit=False):
    """Crea y retorna una nueva conexión a la base de datos."""
    try:
        conn = oracledb.connect(user=db_user, password=db_password, dsn=dsn)
        # ¡LÍNEA CORREGIDA! Asignamos el autocommit a la connexión.
        conn.autocommit = autocommit 
        # ¡LÍNEA CORREGIDA! Devolvemos la conexión configurada.
        return conn 
    except oracledb.DatabaseError as e:
        print(f"--- ERROR DE CONEXIÓN A ORACLE: {e} ---")
        traceback.print_exc()
        return None
@app.route('/api/dashboard/predictivo')
def api_predictivo():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
    
    cursor = conn.cursor()
    sql = """
        SELECT 
            nombre, 
            tipo,
            horas_uso_acumuladas,
            vida_util_estimada_horas,
            ROUND( (horas_uso_acumuladas * 100.0 / vida_util_estimada_horas) , 2) AS porcentaje_vida_consumida
        FROM 
            MATERIALES
        WHERE 
            CANTIDAD = 1
            AND (horas_uso_acumuladas * 1.0 / vida_util_estimada_horas) > 0.80
        ORDER BY 
            porcentaje_vida_consumida DESC
    """
    
    try:
        cursor.execute(sql)
        # Convertir los resultados de Oracle (tuplas) a diccionarios (JSON)
        columnas = [col[0].lower() for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return jsonify(resultados)
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# --- Función para obtener los datos (como en tu dashboard.js) ---
# (Necesitamos replicar la lógica de tus APIs pero en Python)
def obtener_datos_reporte():
    conn = get_db_connection()
    if not conn:
        print("Tarea programada: No se pudo conectar a la BD")
        return None
    
    datos_reporte = {}
    try:
        cursor = conn.cursor()
        
        # 1. Datos Predictivos
        sql_predictivo = """
            SELECT nombre, tipo, horas_uso_acumuladas, vida_util_estimada_horas,
            ROUND((horas_uso_acumuladas * 100.0 / vida_util_estimada_horas), 2) AS porcentaje_vida_consumida
            FROM MATERIALES
            WHERE CANTIDAD = 1 AND (horas_uso_acumuladas * 1.0 / vida_util_estimada_horas) > 0.80
            ORDER BY porcentaje_vida_consumida DESC
        """
        cursor.execute(sql_predictivo)
        columnas = [col[0].lower() for col in cursor.description]
        datos_reporte['alertas'] = [dict(zip(columnas, row)) for row in cursor.fetchall()]

        # 2. Datos Financieros
        sql_financiero = "SELECT tipo, SUM(CANTIDAD * costo_adquisicion) AS valor_total_stock FROM MATERIALES WHERE CANTIDAD > 1 GROUP BY tipo"
        cursor.execute(sql_financiero)
        columnas = [col[0].lower() for col in cursor.description]
        datos_reporte['financiero'] = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        
        # 3. Datos Top 5
        sql_top5 = "SELECT nombre, horas_uso_acumuladas FROM MATERIALES WHERE CANTIDAD = 1 ORDER BY horas_uso_acumuladas DESC FETCH FIRST 5 ROWS ONLY"
        cursor.execute(sql_top5)
        columnas = [col[0].lower() for col in cursor.description]
        datos_reporte['top5'] = [dict(zip(columnas, row)) for row in cursor.fetchall()]

        # 4. Datos del Admin (Email y Password)
        # (¡Asumimos que el admin tiene ID=1 y una columna 'PASSWORD_REPORTE'!)
        # ¡IMPORTANTE! NUNCA uses la contraseña de login para esto.
        cursor.execute("SELECT EMAIL, PASSWORD FROM USUARIOS WHERE TIPO = 0 AND ID = 1") # Asumimos ID 1 es el admin
        admin_data = cursor.fetchone()
        datos_reporte['admin_email'] = admin_data[0] if admin_data else "correo_admin_default@ejemplo.com"
        datos_reporte['admin_password'] = "albertogomez" # Un password de fallback

        return datos_reporte

    except Exception as e:
        print(f"Error al obtener datos_reporte: {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

# --- La Tarea Programada (¡LA MAGIA!) ---
def tarea_programada_reporte():
    """Esta es la función que se ejecutará cada día a las 10 p.m."""
    print("EJECUTANDO TAREA: Iniciando generación de reporte diario...")
    
    # Usamos 'with app.app_context()' para poder usar 'render_template'
    with app.app_context():
        # 1. Obtener los datos frescos de la BD
        datos = obtener_datos_reporte()
        if not datos:
            print("TAREA FALLIDA: No se pudieron obtener los datos.")
            return

        # 2. Preparar el texto del resumen (como en tu JS)
        num_alertas = len(datos['alertas'])
        valor_total = sum(item['valor_total_stock'] for item in datos['financiero'])
        top_equipo = datos['top5'][0]['nombre'] if datos['top5'] else "N/A"
        
        resumen_texto = f"""
            El análisis predictivo ha identificado {num_alertas} equipos en riesgo de falla 
            que requieren mantenimiento inmediato. El valor total del inventario en stock 
            está valorado en ${valor_total:,.2f} MXN, y el análisis de uso indica 
            que el equipo más solicitado es el {top_equipo}.
        """

        # 3. Renderizar el HTML del PDF en el servidor
        html_string = render_template(
            'reporte_email.html', 
            datos=datos,
            resumen=resumen_texto,
            fecha=datetime.now().strftime('%d/%m/%Y a las %H:%M:%S')
        )
        
        # 4. Convertir HTML a PDF en memoria
        # LÍNEA 203 (Correcta)
        pdf_bytes = HTML(string=html_string,base_url='http://127.0.0.1:5000').write_pdf()

        # 5. Encriptar el PDF
        password_pdf = datos['admin_password'] # ¡La contraseña del admin!
        pdf_encriptado = encriptar_pdf(pdf_bytes, password_pdf)
        
        if not pdf_encriptado:
            print("TAREA FALLIDA: No se pudo encriptar el PDF.")
            return

        # 6. Enviar el correo (usando tu función de SendGrid que ya tienes)
        admin_email = datos['admin_email']
        asunto = f"Reporte Ejecutivo de Labflow - {datetime.now().strftime('%d/%m/%Y')}"
        contenido_html = f"""
            <p>Hola,</p>
            <p>Se adjunta el reporte ejecutivo automático del sistema Labflow para el día de hoy.</p>
            <p>Para abrir el documento, utilice la contraseña de reportes designada (la misma de su perfil de administrador).</p>
            <p>Saludos,<br>Sistema Labflow.</p>
        """

        envio_ok, error = enviar_correo_con_adjunto(
            admin_email, 
            asunto, 
            contenido_html,
            pdf_encriptado,
            "Reporte_Labflow.pdf"
        )

        if envio_ok:
            print("¡TAREA COMPLETA! Reporte encriptado y enviado exitosamente.")
        else:
            print(f"TAREA FALLIDA: Error al enviar correo: {error}")


# --- Configuración e inicio del Programador ---
scheduler = BackgroundScheduler(daemon=True)
# Se ejecuta todos los días a las 22:00 (10 p.m.)
scheduler.add_job(tarea_programada_reporte, 'cron', hour=14, minute=58)
scheduler.start()

@app.route('/api/dashboard/financiero')
def api_financiero():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
        
    cursor = conn.cursor()
    sql = """
        SELECT
            tipo,
            SUM(CANTIDAD * costo_adquisicion) AS valor_total_stock
        FROM
            MATERIALES
        WHERE
            CANTIDAD > 1
        GROUP BY
            tipo
        ORDER BY
            valor_total_stock DESC
    """
    
    try:
        cursor.execute(sql)
        columnas = [col[0].lower() for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return jsonify(resultados)
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route('/api/dashboard/top-activos')
def api_top_activos():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
        
    cursor = conn.cursor()
    sql = """
        SELECT 
            nombre,
            horas_uso_acumuladas
        FROM
            MATERIALES
        WHERE
            CANTIDAD = 1
        ORDER BY
            horas_uso_acumuladas DESC
        FETCH FIRST 5 ROWS ONLY
    """
    
    try:
        cursor.execute(sql)
        columnas = [col[0].lower() for col in cursor.description]
        resultados = [dict(zip(columnas, row)) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        return jsonify(resultados)
    except Exception as e:
        cursor.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# --- (Opcional) Ruta para MOSTRAR tu dashboard.html ---
# Esta ruta cargará tu archivo HTML
@app.route('/dashboard')
def mostrar_dashboard():
    # Asume que tu archivo se llama 'dashboard.html'
    # y está en una carpeta 'templates'
    return render_template('dashboard.html')

def rows_to_dicts(cursor, rows):
    # ... (sin cambios)
    column_names = [d[0].upper() for d in cursor.description]
    results = []
    for row in rows:
        row_dict = dict(zip(column_names, row))
        cleaned_dict = {}
        for key, value in row_dict.items():
            if isinstance(value, (datetime, timedelta)):
                cleaned_dict[key] = str(value)
            elif isinstance(value, oracledb.LOB):
                cleaned_dict[key] = value.read()
            elif value is None:
                cleaned_dict[key] = None
            else:
                cleaned_dict[key] = value
        results.append(cleaned_dict)
    return results

def hash_password(password_texto_plano):
    """Genera un hash seguro de la contraseña."""
    bytes_pw = password_texto_plano.encode('utf-8')
    # --- ¡CAMBIO AQUÍ! ---
    salt = bcrypt.gensalt(rounds=10)
    # --- FIN DEL CAMBIO ---
    hash_pw = bcrypt.hashpw(bytes_pw, salt)
    return hash_pw.decode('utf-8')

def check_password(password_plano, hash_almacenado):
    """Compara un password plano con un hash de bcrypt."""
    try:
        # Asegurarnos que ambos sean 'str' antes de 'encode'
        if not isinstance(password_plano, str) or not isinstance(hash_almacenado, str):
            return False
            
        return bcrypt.checkpw(password_plano.encode('utf-8'), hash_almacenado.encode('utf-8'))
    except Exception as e:
        print(f"Error al checar password (probablemente hash inválido): {e}")
        return False
# --- NUEVA FUNCIÓN: Se ejecuta ANTES de cada petición ---
# --- NUEVA FUNCIÓN: Se ejecuta ANTES de cada petición ---
@app.before_request
def make_session_permanent():
    # Asegura que la sesión sea permanente para que aplique el timeout
    session.permanent = True
# --- FIN NUEVA FUNCIÓN ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- FUNCIONES DE AUTENTICACIÓN (ACTUALIZADA) ---
# --- FUNCIONES DE AUTENTICACIÓN (REEMPLAZAR) ---
# --- FUNCIONES DE AUTENTICACIÓN (REEMPLAZAR) ---
def autenticar_con_bloqueo(usuario, contrasena):
    conn = get_db_connection()
    if not conn: return (False, None, "Error de conexión con la base de datos.")
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, USUARIO, PASSWORD, TIPO, CREADO_EN, INTENTOS_FALLIDOS, BLOQUEADO_HASTA FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        row = cursor.fetchone()
        if not row:
            return (False, None, "Usuario o contraseña incorrectos.")

        id_db, user_db, pwd_db, tipo_db, creado_en_db, intentos_db, bloqueado_hasta_db = row

        # --- Lógica de bloqueo (sin cambios) ---
        if bloqueado_hasta_db is not None and bloqueado_hasta_db > datetime.now():
            cursor.execute("SELECT CEIL((CAST(BLOQUEADO_HASTA AS DATE) - CAST(SYSDATE AS DATE)) * 24 * 60) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
            mins_left = cursor.fetchone()[0]
            return (False, None, f"Cuenta bloqueada. Intenta de nuevo en {int(mins_left) if mins_left and mins_left > 0 else 1} minuto(s).")

        # --- ¡NUEVA LÓGICA DE CONTRASEÑA! ---
        # Comprueba si la contraseña guardada es un hash o texto plano
        password_matches = False
        if pwd_db and pwd_db.startswith('$2b$'):
            # La contraseña es un hash, usamos bcrypt para comparar
            password_matches = check_password(contrasena, pwd_db)
        else:
            # La contraseña es texto plano (sistema antiguo), comparamos directo
            password_matches = (contrasena == pwd_db)
        # --- FIN NUEVA LÓGICA ---

        if password_matches:
            # Éxito: Limpiar intentos
            cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = 0, BLOQUEADO_HASTA = NULL WHERE USUARIO = :usr", usr=usuario)
            
            # --- MEJORA DE SEGURIDAD ---
            # Si el login fue exitoso Y la contraseña era de texto plano,
            # la actualizamos a un hash automáticamente.
            if not (pwd_db and pwd_db.startswith('$2b$')):
                print(f"Actualizando contraseña a hash para el usuario: {user_db}")
                new_hashed_pass = hash_password(contrasena)
                cursor.execute("UPDATE USUARIOS SET PASSWORD = :hash_pw WHERE ID = :id", hash_pw=new_hashed_pass, id=id_db)
            # --- FIN MEJORA ---
            
            conn.commit()
            return (True, {'id': id_db, 'nombre': user_db, 'tipo': tipo_db}, "Acceso concedido.")
        else:
            # Fracaso: Incrementar intentos y bloquear si es necesario
            nuevos_intentos = (intentos_db or 0) + 1 # Manejar NULL
            if nuevos_intentos >= LOCK_MAX_ATTEMPTS:
                cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = :i, BLOQUEADO_HASTA = SYSTIMESTAMP + NUMTODSINTERVAL(:m, 'MINUTE') WHERE USUARIO = :usr", i=nuevos_intentos, m=LOCK_TIME_MIN, usr=usuario)
                msg = f"Usuario o contraseña incorrectos. La cuenta ha sido bloqueada."
            else:
                cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = :i WHERE USUARIO = :usr", i=nuevos_intentos, usr=usuario)
                msg = f"Usuario o contraseña incorrectos. Te quedan {LOCK_MAX_ATTEMPTS - nuevos_intentos} intento(s)."
            conn.commit()
            return (False, None, msg)
            
    except Exception as e:
        print(f"Error Oracle en autenticar_con_bloqueo: {e}"); traceback.print_exc()
        return (False, None, "Error de base de datos. Revisa la consola de Flask.")
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()
        
@app.route("/")
def splash_screen():
    # Simplemente renderiza la nueva plantilla splash.html
    return render_template("splash.html")

# ====================================================================
# --- INICIO: LÓGICA DEL CHATBOT (CORREGIDA) ---
# ====================================================================
# 1. Definimos nuestro "diccionario de conocimiento" (Reglas)
# 1. Definimos nuestro "diccionario de conocimiento" (Reglas)
knowledge_base = {
    # --- FAQs Generales ---
    r".*qu(e|é) es labflow.*": "LabFlow es el sistema de gestión para el laboratorio. Me encargo de ayudar a administrar el inventario, registrar préstamos y llevar un control de los alumnos y auxiliares.",
    r".*qui(e|é)n eres.*": "Soy LabFlow-Bot, el asistente virtual del sistema de gestión del laboratorio. ¡Estoy aquí para ayudarte!",
    r".*qu(e|é) (puedes|sabes) hacer.*|.*para qu(e|é) sirves.*": "Puedo ayudarte con preguntas comunes sobre cómo usar el sistema, por ejemplo: '¿qué hago si el sistema falla?' o '¿cómo registro material nuevo?'. También puedo darte la hora y la fecha.",
    r".*(qui(e|é)n|c(o|ó)mo).*(cread|program|hizo|hicieron|fabric).*": "Fui programado por el increíble equipo de desarrollo de ISW. ¡Un saludo para ellos!",

    # --- Saludos y Cortesía ---
    r".*hola.*|.*buen(a|o)s (dias|tardes|noches).*": "¡Hola! Soy el asistente de LabFlow. ¿En qué puedo ayudarte hoy?",
    r".*adi(o|ó)s.*|.*hasta luego.*": "¡Hasta luego! Que tengas un buen día.",
    r".*gracias.*": "¡De nada! Estoy aquí para ayudar.",
    r".*(ayuda|soporte|duda).*": "Claro, dime tu duda. También puedes contactar al administrador del laboratorio o revisar la sección de 'Soporte'.",

    # --- Preguntas Operativas (Las que ya tenías) ---
    r".*sistema (falla|cae|caido|no (funciona|sirve)).*": "Si el sistema principal falla, no te preocupes. Los auxiliares deben registrar los préstamos manualmente en la bitácora de papel. Notifica al administrador para que reinicie el servidor.",
    r".*(material|equipo).*(nuevo|nueva).*|.*(nuevo|nueva).*(material|equipo).*|.*lleg(o|ó|a).*": "Cuando llegue material nuevo, debe ser registrado en la sección de 'Inventario'. Asegúrate de añadir el 'ID de Material', 'Nombre', 'Categoría' y 'Cantidad' antes de ponerlo disponible para préstamo.",
    r".*(alumno|estudiante).*(inactivo|desactivar|desactive|baja).*|.*(inactivo|desactivar|desactive|baja).*(alumno|estudiante).*": "Si un alumno ya no asiste, puedes cambiar su estatus a 'Inactivo' en la 'Gestión de Alumnos'.",

    # ========================================================
    # --- ¡NUEVAS REGLAS DE AYUDA DEL SISTEMA (CORREGIDAS)! ---
    # ========================================================

    # --- Gestión de Préstamos ---
    r".*c(o|ó)mo.*(pr(e|é)stamo|prestar).*": "Para registrar un préstamo, ve a la pestaña 'Préstamos'. Ingresa el número de control del alumno (esto cargará su nombre). Luego, busca el material en la tabla 'Inventario Disponible' y haz clic en 'Añadir'. Finalmente, presiona 'Registrar Préstamo'.",
    
    # ¡REGLA CORREGIDA! (Añade "devolución")
    r".*c(o|ó)mo.*(devolv|devoluci(o|ó)n).*": "Para una devolución, ve a la pestaña 'Préstamos'. En la lista de 'Préstamos Activos', busca al alumno y haz clic en el botón verde 'Devolver'.",
    
    r".*(alumno|estudiante).*no (sale|aparece).*": "Si un alumno no aparece en la búsqueda, puede ser por dos razones: 1. Aún no se ha registrado en el sistema, o 2. El administrador lo marcó como 'Inactivo' en 'Gestión de Alumnos'.",

    # --- Gestión de Daños ---
    r".*c(o|ó)mo.*reporto un da(ñ|n)o.*": "Para reportar un daño, primero busca el préstamo activo en la pestaña 'Préstamos'. Haz clic en el botón rojo 'Reportar Daño'. Se abrirá un modal donde puedes seleccionar el material específico y la cantidad dañada.",
    
    # ¡REGLA CORREGIDA! (Se quita la parte de "material|equipo" para hacerla más flexible)
    r".*c(o|ó)mo.*(repongo|reponer|administrar).*(da(ñ|n)o|da(ñ|n)ado).*": "Como administrador, debes ir a la pestaña 'Gestión de Daños'. Busca el ítem en la lista 'Daños Pendientes' y, cuando esté reparado o reemplazado, haz clic en 'Marcar Repuesto'. Esto lo devolverá al inventario disponible.",
    
    # --- Gestión de Auxiliares (Admin) ---
    r".*c(o|ó)mo.*(agrego|crear).*(auxiliar|asistente).*": "Para agregar un nuevo auxiliar, el administrador debe ir a la pestaña 'Gestión de Auxiliares' y usar el formulario 'Agregar Nuevo Auxiliar' (a la derecha).",
    
    # --- Reportes (Admin) ---
    r".*d(o|ó)nde.*(reporte|excel|predicciones).*": "Puedes ver los reportes en vivo en la pestaña 'Reportes'. Para un análisis de tendencias, ve a 'Predicciones' (el Dashboard de BI). También puedes descargar un reporte de Excel desde la pestaña 'Reportes'."
}

# 2. Creamos la función que busca la respuesta (Versión de Reglas)
def get_bot_response(user_message):
    user_message = user_message.lower() # Convertimos a minúsculas
    now = datetime.now() # Obtenemos la hora actual una vez

    # --- 1. Lógica Dinámica (Hora y Fecha) ---
    if re.search(r".*qu(e|é) hora es.*|.*(dame|dime) la hora.*", user_message):
        return f"¡Claro! Son las {now.strftime('%I:%M %p')}."

    if re.search(r".*qu(e|é) d(i|í)a es hoy.*|.*(dame|dime) la fecha.*|.*fecha de hoy.*", user_message):
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        dia_semana = dias[now.weekday()]
        mes_anno = meses[now.month - 1]
        return f"Hoy es {dia_semana}, {now.day} de {mes_anno} de {now.year}."

    # --- 2. Lógica Estática (Base de Conocimiento) ---
    # Ahora 'knowledge_base' SÍ está definido
    for pattern, response in knowledge_base.items():
        if re.search(pattern, user_message):
            return response

    # --- 3. Respuesta por Defecto ---
    return "Lo siento, no entendí tu pregunta. ¿Puedes reformularla? También puedes consultar la sección de 'Soporte'."

# 3. Creamos el endpoint (la "API") para el chat
@app.route("/chat", methods=['POST'])
def chat():
    if 'user_id' not in session: # Proteger el endpoint
        return jsonify({'response': 'Error: No autorizado'}), 401
        
    data = request.json
    user_message = data.get('message')
    
    if not user_message:
        return jsonify({'response': 'Error: No hay mensaje'}), 400
        
    bot_response = get_bot_response(user_message)
    
    return jsonify({'response': bot_response})

# --- FIN: LÓGICA DEL CHATBOT ---
# ====================================================================
# ====================================================================
# --- RUTAS PRINCIPALES ---
# --- RUTAS PRINCIPALES ---
@app.route("/login_page", methods=["GET", "POST"])
def login_page(): # Nombre de función cambiado
    if 'user_id' in session:
        if session.get('user_rol') == 'admin':
            return redirect(url_for('interface_admin'))
        else:
            return redirect(url_for('interface_aux'))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()
        
        if not usuario or not contrasena:
            flash("Ambos campos son obligatorios.", "danger")
            return redirect(url_for('login_page')) 
        
        es_valido, datos_usuario, mensaje = autenticar_con_bloqueo(usuario, contrasena)
        
        if es_valido:
            session.permanent = True
            session['user_id'] = datos_usuario['id']
            session['user_rol'] = 'admin' if datos_usuario['tipo'] == 0 else 'auxiliar'
            session['user_nombre'] = datos_usuario['nombre']
            session['login_time_iso'] = datetime.now().isoformat()

            if session.get('user_rol') == 'auxiliar':
                conn = get_db_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        # --- ¡CORRECCIÓN! Volver a REGISTRO_ACTIVIDAD ---
                        cursor.execute("INSERT INTO REGISTRO_ACTIVIDAD (ID, ID_USUARIO, TIPO_ACCION) VALUES (registro_actividad_seq.nextval, :id_usr, 'INICIO_SESION')", id_usr=session['user_id'])
                        conn.commit()
                    except Exception as e: 
                        print(f"Error al registrar actividad: {e}")
                    finally:
                        if 'cursor' in locals() and cursor: cursor.close()
                        if conn: conn.close()

            if datos_usuario['tipo'] == 0: 
                return redirect(url_for("interface_admin"))
            else: 
                return redirect(url_for("interface_aux"))
        
        else:
            flash(mensaje, "danger")
            return redirect(url_for('login_page')) 

    return render_template("inicioAdmin.html")

@app.route('/logout')
def logout():
    alerta_guillermo = None
    if session.get('user_rol') == 'auxiliar' and session.get('user_id'):
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                prestamos_pendientes = 0
                if session.get('user_nombre') == 'Guillermo Alvarez':
                    cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE ID_AUXILIAR = :id_aux AND ESTATUS = 'Activo'", id_aux=session['user_id'])
                    prestamos_pendientes = cursor.fetchone()[0]
                    if prestamos_pendientes > 0:
                        alerta_guillermo = f"¡Alerta, Guillermo! Has cerrado sesión con {prestamos_pendientes} préstamo(s) activo(s)."

                # --- ¡CORRECCIÓN! Volver a REGISTRO_ACTIVIDAD ---
                cursor.execute("INSERT INTO REGISTRO_ACTIVIDAD (ID, ID_USUARIO, TIPO_ACCION, PRESTAMOS_PENDIENTES) VALUES (registro_actividad_seq.nextval, :id_usr, 'CIERRE_SESION', :pendientes)", id_usr=session['user_id'], pendientes=prestamos_pendientes)
                conn.commit()
            except Exception as e: print(f"Error durante el logout: {e}")
            finally:
                if 'cursor' in locals() and cursor: cursor.close()
                if conn: conn.close()
    session.clear()
    if alerta_guillermo:
        flash(alerta_guillermo, "warning")
    flash("Has cerrado sesión exitosamente.", "success")
    return redirect(url_for('login_page'))


@app.route('/profile')
def profile():
    if 'user_id' not in session: 
        return redirect(url_for('login_page'))

    user_info = {
        'nombre': session.get('user_nombre'),
        'rol': session.get('user_rol'),
        'profile_pic_filename': None
    }
       
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT FOTO_PERFIL FROM USUARIOS WHERE ID = :user_id", user_id=session['user_id'])
            result = cursor.fetchone()
            if result and result[0]:
                user_info['profile_pic_filename'] = result[0]
        except Exception as e: print(f"Error al obtener foto de perfil: {e}")
        finally:
            if 'cursor' in locals() and cursor: cursor.close()
            if conn: conn.close()

    context_data = {
        'user_info': user_info,
        'usuario_rol': session.get('user_rol'), 
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template('profile.html', **context_data)
# ====================================================================
# --- INICIO: RUTA PARA CAMBIAR CONTRASEÑA (CORREGIDA) ---
# ====================================================================

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        flash("Tu sesión ha expirado.", "danger")
        return redirect(url_for('login_page'))

    # 1. Obtener datos del formulario
    current_pass = request.form.get('current_password')
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    user_id = session['user_id']

    # 2. Validaciones
    if not current_pass or not new_pass or not confirm_pass:
        flash("Todos los campos son obligatorios.", "danger")
        return redirect(url_for('profile'))
    if new_pass != confirm_pass:
        flash("La nueva contraseña y la confirmación no coinciden.", "danger")
        return redirect(url_for('profile'))
    if len(new_pass) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.", "danger")
        return redirect(url_for('profile'))

    # 3. Lógica de Base de Datos
    conn = get_db_connection() # autocommit=False
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for('profile'))
    
    try:
        cursor = conn.cursor()
        
        # 4. Obtener la contraseña actual del usuario
        cursor.execute("SELECT PASSWORD FROM USUARIOS WHERE ID = :id", id=user_id)
        result = cursor.fetchone()
        if not result:
            flash("Error: Usuario no encontrado.", "danger")
            # Dejamos que 'finally' limpie la conexión
            return redirect(url_for('login_page'))
        
        pwd_db = result[0] 

        # 5. Lógica de verificación
        password_matches = False
        if pwd_db and pwd_db.startswith('$2b$'):
            password_matches = check_password(current_pass, pwd_db)
        else:
            # Compara en texto plano si la contraseña no es un hash
            password_matches = (current_pass == pwd_db)

        # 6. Verificar si la contraseña actual es correcta
        if not password_matches:
            flash("La contraseña actual es incorrecta.", "danger")
            # --- ¡CORRECCIÓN AQUÍ! ---
            # No cerramos la conexión aquí. Dejamos que 'finally' lo haga.
            # cursor.close() <--- ELIMINADO
            # conn.close()   <--- ELIMINADO
            return redirect(url_for('profile'))

        # 7. Si es correcta, hashear y guardar la NUEVA contraseña
        hashed_new_password = hash_password(new_pass)
        
        cursor.execute("""
            UPDATE USUARIOS 
            SET PASSWORD = :hash_pw 
            WHERE ID = :id
        """, hash_pw=hashed_new_password, id=user_id)
        
        conn.commit()
        
        flash("¡Contraseña actualizada con éxito!", "success")
        
    except Exception as e:
        conn.rollback() 
        print(f"Error en change_password: {e}"); traceback.print_exc()
        flash("Error interno al actualizar la contraseña.", "danger")
    finally:
        # 'finally' SIEMPRE se ejecutará, asegurando que cerremos todo.
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

    return redirect(url_for('profile'))
# ====================================================================
# --- FIN: RUTA PARA CAMBIAR CONTRASEÑA ---
# ====================================================================

# --- MANEJADOR DE ERROR 413 CORREGIDO ---
@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(e):
    # ... (código sin cambios) ...
    if request.path == url_for('upload_profile_pic'):
        return jsonify({'success': False, 'error': 'Archivo demasiado grande (Máx 2MB)'}), 413
    flash('Archivo demasiado grande (Máx 2MB).', 'danger')
    if 'user_id' in session: 
        return redirect(url_for('profile'))
    else: 
        return redirect(url_for('login_page'))

# --- RUTAS DE NAVEGACIÓN (MODIFICADAS PARA PASAR TIMEOUT) ---
@app.route("/interface_admin")
def interface_admin():
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for('login_page'))
    
    # --- INICIO DE LA MODIFICACIÓN ---
    
    # 1. Tu contexto original
    context_data = {
        'usuario_rol': session.get('user_rol'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    
    # 2. Lógica para obtener la foto de perfil
    profile_pic_filename = 'default_profile.png' # Valor por defecto
    
    conn = get_db_connection() # Usar la función de conexión
    if conn:
        try:
            cursor = conn.cursor()
            # Asumo que 'user_id' en sesión es el ID de la tabla USUARIOS
            cursor.execute("SELECT FOTO_PERFIL FROM USUARIOS WHERE ID = :user_id", user_id=session['user_id'])
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result and result[0]:
                # Hay una foto en la BD, usamos ese nombre de archivo
                profile_pic_filename = result[0]
                
                # Verificación extra: si el archivo no existe, volvemos al default
                if not os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], profile_pic_filename)):
                    print(f"Advertencia: La BD apunta a '{profile_pic_filename}' pero el archivo no existe. Usando default.")
                    profile_pic_filename = 'default_profile.png'
                    
        except Exception as e:
            print(f"Error al obtener foto de perfil: {e}")
            traceback.print_exc()
            # Si hay error de BD, nos quedamos con la foto por defecto
    
    # 3. Añadir la foto de perfil al contexto
    context_data['profile_pic_filename'] = profile_pic_filename
    
    # 4. Renderizar usando tu nombre de template original y el contexto combinado
    return render_template("interfaceAdmin.html", **context_data) 
    # --- FIN DE LA MODIFICACIÓN ---

@app.route("/interface_aux")
def interface_aux():
    if 'user_id' not in session or session.get('user_rol') == 'auxiliar':
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for('login_page'))
    context_data = {
        'usuario_rol': session.get('user_rol'),
        'login_time_iso': session.get('login_time_iso'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template("interfaceAux.html", **context_data)

# --- RUTA DE SOPORTE TÉCNICO ---
@app.route('/soporte', methods=['GET', 'POST'])
def soporte():
    # ... (código sin cambios)
    if request.method == 'POST':
        nombre = request.form.get('name', '').strip()
        correo_remitente = request.form.get('email', '').strip()
        asunto = request.form.get('subject', '').strip()
        mensaje = request.form.get('message', '').strip()

        errors = []
        # ... validaciones sin cambios ...
        if not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", nombre) or len(nombre) > 100:
            errors.append("El nombre solo debe contener letras y tener un máximo de 100 caracteres.")
        if not re.match(r"[^@]+@[^@]+\.[^@]+", correo_remitente):
            errors.append("El formato del correo electrónico no es válido.")
        if len(asunto) > 150:
            errors.append("El asunto excede el límite de 150 caracteres.")
        if len(mensaje) > 2000:
            errors.append("El mensaje excede el límite de 2000 caracteres.")

        if errors:
            for error in errors: flash(error, "danger")
            return render_template('soporte.html', form_data=request.form)

        guardado_ok, error_db = guardar_mensaje_soporte_db(nombre, correo_remitente, asunto, mensaje)
        # ... manejo de errores y flash sin cambios ...
        if guardado_ok:
            envio_ok, error_correo = enviar_notificacion_sendgrid(nombre, correo_remitente, asunto, mensaje)
            if envio_ok:
                flash("Tu mensaje ha sido enviado con éxito. Te contactaremos pronto.", "success")
            else:
                print(f"--- ERROR AL ENVIAR CORREO CON SENDGRID: {error_correo} ---")
                flash("Tu mensaje fue registrado, pero hubo un error al enviar la notificación. Contacta a un administrador.", "warning")
        else:
            flash(f"Error al registrar el mensaje: {error_db}", "danger")
        return redirect(url_for('soporte'))

    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite (si el usuario está logueado) ---
    context_data = {}
    if 'user_id' in session:
        context_data['inactivity_limit'] = app.permanent_session_lifetime.total_seconds()
        context_data['usuario_rol'] = session.get('user_rol') # Para la barra de navegación si la añades
    return render_template('soporte.html', **context_data)
    # --- FIN ACTUALIZACIÓN ---


# --- FUNCIONES DE AYUDA DE SOPORTE ---
def enviar_notificacion_sendgrid(nombre, correo_remitente, asunto, mensaje):
     # ... (código sin cambios)
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    if not SENDGRID_API_KEY:
        print("--- ERROR: La variable de entorno SENDGRID_API_KEY no está configurada. ---")
        return False, "El servicio de correo no está configurado."
    from_email = 'mirandaneyra1@gmail.com'
    to_email = 'mirandaneyra1@gmail.com'
    html_content = f"""<h3>Has recibido un nuevo mensaje de soporte:</h3><p><strong>De:</strong> {nombre} ({correo_remitente})</p><p><strong>Asunto:</strong> {asunto}</p><hr><p><strong>Mensaje:</strong></p><p>{mensaje.replace(chr(10), '<br>')}</p><hr><p><small>Este mensaje fue enviado desde el formulario de soporte del sistema de laboratorio.</small></p>"""
    message = Mail(from_email=from_email, to_emails=to_email, subject=f"Nuevo Mensaje de Soporte: {asunto}", html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        if 200 <= response.status_code < 300: return True, None
        else:
            print(f"--- ERROR: SendGrid devolvió un error. Código: {response.status_code}, Body: {response.body} ---")
            return False, response.body
    except Exception as e:
        traceback.print_exc()
        return False, str(e)

def guardar_mensaje_soporte_db(nombre, correo, asunto, mensaje):
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO MENSAJES_SOPORTE (NOMBRE_REMITENTE, CORREO_REMITENTE, ASUNTO, MENSAJE) VALUES (:nombre, :correo, :asunto, :mensaje)",
                       nombre=nombre, correo=correo, asunto=asunto, mensaje=mensaje)
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback(); print(f"Error Oracle en guardar_mensaje_soporte_db: {e}"); traceback.print_exc()
        return False, "Ocurrió un error interno."
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
def enviar_correo_con_adjunto(destinatario, asunto, contenido_html, pdf_bytes, nombre_archivo):
    """
    Envía un correo usando SendGrid CON un archivo adjunto (PDF).
    """
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    if not SENDGRID_API_KEY:
        print("--- ERROR (Correo Adjunto): La variable de entorno SENDGRID_API_KEY no está configurada. ---")
        return False, "El servicio de correo no está configurado."

    from_email = 'mirandaneyra1@gmail.com' # Tu correo verificado en SendGrid
    
    # 1. Crear el objeto Mail
    message = Mail(
        from_email=from_email,
        to_emails=destinatario,
        subject=asunto,
        html_content=contenido_html
    )
    
    # 2. Codificar el PDF (que está en bytes) a Base64
    encoded_file = base64.b64encode(pdf_bytes).decode()
    
    # 3. Crear el objeto Attachment
    attachedFile = Attachment(
        FileContent(encoded_file),
        FileName(nombre_archivo),
        FileType('application/pdf'),
        Disposition('attachment')
    )
    
    # 4. Adjuntar el archivo al mensaje
    message.attachment = attachedFile
    
    # 5. Enviar el correo
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        
        if 200 <= response.status_code < 300:
            return True, None
        else:
            print(f"--- ERROR: SendGrid (Adjunto) devolvió un error. Código: {response.status_code}, Body: {response.body} ---")
            return False, response.body
            
    except Exception as e:
        print(f"--- ERROR EXCEPCIÓN (Adjunto): {e} ---")
        traceback.print_exc()
        return False, str(e)
# ====================================================================
# --- INICIO: LÓGICA DE RESTABLECER CONTRASEÑA ---
# ====================================================================

def enviar_correo_reset(email_destinatario, token):
    """Envía un correo de reseteo usando SendGrid."""
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    if not SENDGRID_API_KEY:
        print("--- ERROR: La variable de entorno SENDGRID_API_KEY no está configurada. ---")
        return False, "El servicio de correo no está configurado."

    # ¡IMPORTANTE! _external=True crea la URL completa (http://127.0.0.1:5000/...)
    reset_url = url_for('reset_password', token=token, _external=True)

    from_email = 'mirandaneyra1@gmail.com' # Tu correo de SendGrid
    to_email = email_destinatario          # El correo del usuario
    
    html_content = f"""
    <h3>Hola,</h3>
    <p>Hemos recibido una solicitud para restablecer tu contraseña de LabFlow.</p>
    <p>Haz clic en el siguiente enlace para crear una nueva contraseña:</p>
    <p style="text-align: center; margin: 20px 0;">
        <a href="{reset_url}" style="background-color: #6a5acd; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px;">
            Restablecer Contraseña
        </a>
    </p>
    <p>Si no solicitaste esto, puedes ignorar este correo.</p>
    <p><small>Este enlace expirará en 15 minutos.</small></p>
    """
    
    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject="Restablece tu contraseña de LabFlow",
        html_content=html_content
    )
    
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        if 200 <= response.status_code < 300:
            return True, None
        else:
            print(f"--- ERROR: SendGrid devolvió un error. Código: {response.status_code}, Body: {response.body} ---")
            return False, response.body
    except Exception as e:
        traceback.print_exc()
        return False, str(e)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    """Página para solicitar el reseteo de contraseña."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash("El correo es obligatorio.", "danger")
            return redirect(url_for('forgot_password'))

        conn = get_db_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "danger")
            return redirect(url_for('forgot_password'))
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT ID, USUARIO FROM USUARIOS WHERE EMAIL = :email", email=email)
            user = cursor.fetchone()

            if user:
                user_id, user_nombre = user
                # 1. Generar token
                token = str(uuid.uuid4())
                
                # 2. Guardar token y expiración (15 minutos) en la BD
                cursor.execute("""
                    UPDATE USUARIOS
                    SET RESET_TOKEN = :token,
                        RESET_TOKEN_EXPIRES = SYSTIMESTAMP + NUMTODSINTERVAL(15, 'MINUTE')
                    WHERE ID = :id
                """, token=token, id=user_id)
                conn.commit()
                
                # 3. Enviar correo
                envio_ok, error_correo = enviar_correo_reset(email, token)
                
                if envio_ok:
                    flash("Se ha enviado un enlace a tu correo. Revisa tu bandeja de entrada.", "success")
                else:
                    flash(f"Se encontró tu usuario, pero falló el envío del correo: {error_correo}", "danger")
            
            else:
                # Por seguridad, no revelamos si el correo existe o no
                flash("Si ese correo existe en nuestro sistema, se habrá enviado un enlace.", "success")
                
        except Exception as e:
            conn.rollback()
            print(f"Error en forgot_password: {e}"); traceback.print_exc()
            flash("Error interno al procesar la solicitud.", "danger")
        finally:
            if 'cursor' in locals() and cursor: cursor.close()
            if conn: conn.close()
        
        return redirect(url_for('forgot_password'))

    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Página para ingresar la nueva contraseña."""
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for('login_page'))
    
    user_id = None
    usuario = None
    
    try:
        cursor = conn.cursor()
        # 1. Verificar si el token es válido Y NO ha expirado
        cursor.execute("""
            SELECT ID, USUARIO FROM USUARIOS
            WHERE RESET_TOKEN = :token AND RESET_TOKEN_EXPIRES > SYSTIMESTAMP
        """, token=token)
        user = cursor.fetchone()

        if not user:
            flash("El enlace de reseteo es inválido o ha expirado.", "danger")
            return redirect(url_for('login_page'))
            
        user_id, usuario = user

        if request.method == 'POST':
            new_pass = request.form.get('new_password')
            confirm_pass = request.form.get('confirm_password')

            if not new_pass or not confirm_pass or new_pass != confirm_pass:
                flash("Las contraseñas no coinciden.", "danger")
                return render_template('reset_password.html', token=token, usuario=usuario)
            
            if len(new_pass) < 8:
                flash("La nueva contraseña debe tener al menos 8 caracteres.", "danger")
                return render_template('reset_password.html', token=token, usuario=usuario)

            # 2. Hashear la nueva contraseña
            hashed_new_password = hash_password(new_pass)
            
            # 3. Actualizar la contraseña e invalidar el token
            cursor.execute("""
                UPDATE USUARIOS
                SET PASSWORD = :hash_pw,
                    RESET_TOKEN = NULL,
                    RESET_TOKEN_EXPIRES = NULL,
                    INTENTOS_FALLIDOS = 0,  /* Desbloquear la cuenta */
                    BLOQUEADO_HASTA = NULL
                WHERE ID = :id
            """, hash_pw=hashed_new_password, id=user_id)
            
            conn.commit()
            
            flash("¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.", "success")
            return redirect(url_for('login_page'))

    except Exception as e:
        conn.rollback()
        print(f"Error en reset_password: {e}"); traceback.print_exc()
        flash("Error interno al restablecer la contraseña.", "danger")
        return redirect(url_for('login_page'))
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

    # Si es un GET y el token es válido, muestra la página de reseteo
    return render_template('reset_password.html', token=token, usuario=usuario)

# ====================================================================
# --- FIN: LÓGICA DE RESTABLECER CONTRASEÑA ---
# ====================================================================
# --- RUTA DE REPORTES AVANZADA ---
# --- RUTA DE REPORTES AVANZADA ---
# --- RUTA DE REPORTES AVANZADA ---
# --- RUTA DE REPORTES AVANZADA ---
@app.route('/reportes')
def reportes():
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash('Acceso no autorizado.', 'danger'); return redirect(url_for('login_page'))

    inactivity_limit_value = app.permanent_session_lifetime.total_seconds()

    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger')
        context_data = {
            'datos': {}, 
            'usuario_rol': session.get('user_rol'),
            'inactivity_limit': inactivity_limit_value
        }
        return render_template('reportes_avanzado.html', **context_data)

    datos_dashboard = {}
    try:
        cursor = conn.cursor()
        
        # ... (Tus otras consultas están bien) ...
        cursor.execute("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL NOT IN (SELECT DISTINCT ID_MATERIAL FROM DETALLE_PRESTAMO)")
        datos_dashboard['stock_muerto'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(rd.CANTIDAD_DANADA) AS TOTAL_DANADO FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL_DANADO DESC FETCH FIRST 5 ROWS ONLY")
        datos_dashboard['top_danos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.SEMESTRE, COUNT(p.ID_PRESTAMO) AS TOTAL_PRESTAMOS FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO GROUP BY a.SEMESTRE ORDER BY TOTAL_PRESTAMOS DESC FETCH FIRST 5 ROWS ONLY")
        datos_dashboard['top_semestres'] = rows_to_dicts(cursor, cursor.fetchall())
        query_prestamos_hoy = """
            SELECT p.ID_PRESTAMO, p.FECHA_HORA, p.ESTATUS,
                   u.USUARIO AS AUXILIAR,
                   a.NOMBRE AS ALUMNO, a.NUMEROCONTROL
            FROM PRESTAMOS p
            JOIN USUARIOS u ON p.ID_AUXILIAR = u.ID
            JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO
            WHERE p.FECHA_HORA >= TRUNC(LOCALTIMESTAMP)
            ORDER BY p.FECHA_HORA DESC
        """
        cursor.execute(query_prestamos_hoy)
        datos_dashboard['prestamos_de_hoy'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND (LOCALTIMESTAMP - p.FECHA_HORA) > INTERVAL '1' HOUR ORDER BY p.FECHA_HORA ASC")
        datos_dashboard['prestamos_vencidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE ESTATUS = 'Activo'")
        activos_ahora = cursor.fetchone()[0]
        datos_dashboard['activos_ahora'] = activos_ahora if activos_ahora else 0
        cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE FECHA_HORA >= TRUNC(LOCALTIMESTAMP)")
        total_hoy = cursor.fetchone()[0]
        datos_dashboard['total_prestamos_hoy'] = total_hoy if total_hoy else 0
        cursor.execute("SELECT USUARIO, INTENTOS_FALLIDOS FROM USUARIOS WHERE TIPO = 1 AND INTENTOS_FALLIDOS > 0 ORDER BY INTENTOS_FALLIDOS DESC")
        datos_dashboard['logins_fallidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY")
        datos_dashboard['top_materiales_pedidos'] = rows_to_dicts(cursor, cursor.fetchall())
        
        # --- ¡CORRECCIÓN AQUÍ! ---
        # Volver a REGISTRO_ACTIVIDAD
        query_auxiliares_activos = """
            WITH LastActivity AS (
                SELECT r.ID_USUARIO, r.TIPO_ACCION, r.FECHA_HORA, u.USUARIO,
                    ROW_NUMBER() OVER(PARTITION BY r.ID_USUARIO ORDER BY r.FECHA_HORA DESC) as rn
                FROM REGISTRO_ACTIVIDAD r JOIN USUARIOS u ON r.ID_USUARIO = u.ID WHERE u.TIPO = 1
            ) SELECT USUARIO, FECHA_HORA FROM LastActivity WHERE rn = 1 AND TIPO_ACCION = 'INICIO_SESION' ORDER BY FECHA_HORA ASC
        """
        cursor.execute(query_auxiliares_activos)
        datos_dashboard['auxiliares_activos'] = rows_to_dicts(cursor, cursor.fetchall())
        # --- FIN CORRECCIÓN ---

    except Exception as e:
        flash(f"Error al generar reportes avanzados: {e}", "danger")
        traceback.print_exc()
        datos_dashboard = {} 
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

    context_data = {
        'datos': datos_dashboard,
        'usuario_rol': session.get('user_rol'),
        'inactivity_limit': inactivity_limit_value
    }
    return render_template('reportes_avanzado.html', **context_data)
# --- FIN DE RUTA REPORTES ---

# --- RUTA CORREGIDA PARA DEVOLVER JSON ---
@app.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    # 1. Validar Sesión
    # Asumimos que el admin está cambiando su propia foto
    if 'user_id' not in session:
        # Devuelve un error JSON, 401 = No Autorizado
        return jsonify({'success': False, 'error': 'Sesión no válida o expirada'}), 401

    # 2. Validar Archivo
    if 'profile_pic' not in request.files:
        return jsonify({'success': False, 'error': 'No se encontró el archivo en la solicitud'})
    
    file = request.files['profile_pic']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No se seleccionó ningún archivo'})

    # 3. Validar Extensión
    if not (file and allowed_file(file.filename)):
        return jsonify({'success': False, 'error': 'Tipo de archivo no permitido (Solo png, jpg, jpeg, gif)'})

    # --- Si todo es válido, proceder a guardar ---
    try:
        filename_base = secure_filename(file.filename)
        extension = filename_base.rsplit('.', 1)[1].lower()
        unique_filename = f"user_{session['user_id']}_{uuid.uuid4().hex}.{extension}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Eliminar foto anterior (Tu lógica)
        conn_check = get_db_connection()
        if conn_check:
             cursor_check = conn_check.cursor()
             cursor_check.execute("SELECT FOTO_PERFIL FROM USUARIOS WHERE ID = :user_id", user_id=session['user_id'])
             old_filename_tuple = cursor_check.fetchone()
             cursor_check.close()
             conn_check.close()
             if old_filename_tuple and old_filename_tuple[0]:
                 old_filepath = os.path.join(app.config['UPLOAD_FOLDER'], old_filename_tuple[0])
                 if os.path.exists(old_filepath):
                     os.remove(old_filepath)
        else:
            return jsonify({'success': False, 'error': 'Error de conexión a la BD (al verificar foto)'})

        # Guardar archivo nuevo
        file.save(filepath)
        
        # Actualizar BD (Tu lógica)
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE USUARIOS SET FOTO_PERFIL = :filename WHERE ID = :user_id", 
                           filename=unique_filename, user_id=session['user_id'])
            conn.commit()
            cursor.close()
            conn.close()
            
            # ¡ÉXITO! Devolver la nueva URL de la imagen
            new_image_url = url_for('static', filename=f'profile_pics/{unique_filename}')
            return jsonify({'success': True, 'new_image_url': new_image_url})
        else:
             return jsonify({'success': False, 'error': 'Error de conexión a la BD (al actualizar)'})

    except Exception as e:
        # Capturar cualquier otro error (incluyendo RequestEntityTooLarge si no se maneja por separado)
        traceback.print_exc() # Imprime el error en la consola de Flask
        # Comprobar si fue por tamaño de archivo
        if isinstance(e, RequestEntityTooLarge):
             return jsonify({'success': False, 'error': 'Archivo demasiado grande (Máx 2MB)'}), 413
        return jsonify({'success': False, 'error': f'Error interno del servidor: {e}'})

# --- MANEJADOR DE ERROR 413 CORREGIDO ---
    
@app.route('/descargar_reporte_excel')
def descargar_reporte_excel():
    # Verifica que el usuario sea admin
    if session.get('user_rol') != 'admin':
        return "Acceso no autorizado.", 403

    # Intenta conectar a la BD
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión para generar el reporte.", "danger")
        return redirect(url_for('reportes'))

    try:
        # Prepara el archivo Excel en memoria
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl') 

        # --- HOJAS DE REPORTE EXISTENTES ---
        
        # 1. Préstamos Vencidos
        pd.read_sql("SELECT a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND (LOCALTIMESTAMP - p.FECHA_HORA) > INTERVAL '1' HOUR ORDER BY p.FECHA_HORA ASC", conn).to_excel(writer, sheet_name='Prestamos Vencidos', index=False)
        
        # 2. Materiales Más Dañados
        pd.read_sql("SELECT m.NOMBRE, SUM(rd.CANTIDAD_DANADA) AS TOTAL_DANADO FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL_DANADO DESC", conn).to_excel(writer, sheet_name='Materiales Mas Danados', index=False)
        
        # 3. Top Materiales Pedidos
        pd.read_sql("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY", conn).to_excel(writer, sheet_name='Top Materiales Pedidos', index=False)
        
        # 4. Stock Muerto (Materiales nunca prestados)
        pd.read_sql("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL NOT IN (SELECT DISTINCT ID_MATERIAL FROM DETALLE_PRESTAMO)", conn).to_excel(writer, sheet_name='Stock Muerto', index=False)
        
        # 5. Uso por Semestre
        pd.read_sql("SELECT a.SEMESTRE, COUNT(p.ID_PRESTAMO) AS TOTAL_PRESTAMOS FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO GROUP BY a.SEMESTRE ORDER BY TOTAL_PRESTAMOS DESC", conn).to_excel(writer, sheet_name='Uso por Semestre', index=False)
        
        # 6. Logins Fallidos de Auxiliares
        pd.read_sql("SELECT USUARIO, INTENTOS_FALLIDOS FROM USUARIOS WHERE TIPO = 1 AND INTENTOS_FALLIDOS > 0 ORDER BY INTENTOS_FALLIDOS DESC", conn).to_excel(writer, sheet_name='Logins Fallidos Auxiliares', index=False)

        # --- ¡NUEVA HOJA PARA ALUMNOS! ---
        # 7. Lista Completa de Alumnos
        query_alumnos = """
            SELECT 
                NOMBRE, 
                NUMEROCONTROL, 
                CORREO, 
                ESPECIALIDAD, 
                SEMESTRE, 
                CASE ACTIVO WHEN 1 THEN 'Activo' ELSE 'Inactivo' END AS ESTATUS 
            FROM ALUMNOS 
            ORDER BY NOMBRE
        """
        pd.read_sql(query_alumnos, conn).to_excel(writer, sheet_name='Lista Alumnos', index=False)
        # --- FIN DE NUEVA HOJA ---

        # Cierra el escritor de Excel y prepara el archivo para descarga
        writer.close() 
        output.seek(0) # Regresa al inicio del archivo en memoria

        # Envía el archivo al navegador
        return send_file(
            output, 
            download_name='Reporte_Laboratorio.xlsx', 
            as_attachment=True, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        # Manejo de errores si algo falla durante la generación
        flash(f"Error al generar el archivo Excel: {e}", "danger")
        traceback.print_exc()
        return redirect(url_for('reportes'))
    finally:
        # Asegura que la conexión a la BD se cierre
        if conn: conn.close()

# --- RUTAS Y FUNCIONES DE GESTIÓN DE AUXILIARES ---
@app.route('/gestion_auxiliares')
def gestion_auxiliares():
    # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash("Acceso no autorizado.", "danger"); return redirect(url_for('login_page'))

    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite a la plantilla ---
    auxiliares = obtener_auxiliares_db()
    context_data = {
        'auxiliares': auxiliares,
        'usuario_rol': session.get('user_rol'), # Necesario para mostrar/ocultar botones si aplica
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template('gestion_auxiliares.html', **context_data)
    # --- FIN ACTUALIZACIÓN ---

@app.route('/agregar_auxiliar', methods=['POST'])
def agregar_auxiliar():
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page'))
    
    usuario = request.form.get('usuario', '').strip()
    contrasena = request.form.get('contrasena', '').strip()
    email = request.form.get('email', '').strip().lower() # <-- NUEVA LÍNEA

    if not usuario or not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", usuario):
        flash("El nombre de usuario es obligatorio y solo debe contener letras y espacios.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    
    # <-- INICIO NUEVA VALIDACIÓN -->
    if not email:
        flash("El correo electrónico es obligatorio.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    # <-- FIN NUEVA VALIDACIÓN -->
        
    if not contrasena:
        flash("La contraseña es obligatoria.", "warning"); return redirect(url_for('gestion_auxiliares'))
    
    # <-- CAMBIO AQUÍ: pasamos 'email' a la función -->
    resultado, mensaje = insertar_auxiliar_db(usuario, contrasena, email)
    
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/modificar_auxiliar', methods=['POST'])
def modificar_auxiliar():
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page'))
    
    id_usuario = request.form.get('id_usuario')
    usuario = request.form.get('usuario', '').strip()
    email = request.form.get('email', '').strip().lower() # <-- NUEVA LÍNEA
    contrasena = request.form.get('contrasena', '').strip()
    
    if not id_usuario:
           flash("Falta el ID del usuario a modificar.", "danger"); return redirect(url_for('gestion_auxiliares'))
    if not usuario or not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", usuario):
        flash("El nombre de usuario es obligatorio y solo debe contener letras y espacios.", "warning")
        return redirect(url_for('gestion_auxiliares'))
        
    # <-- INICIO NUEVA VALIDACIÓN -->
    if not email:
        flash("El correo electrónico es obligatorio.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    # <-- FIN NUEVA VALIDACIÓN -->
        
    # <-- CAMBIO AQUÍ: pasamos 'email' a la función -->
    resultado, mensaje = actualizar_auxiliar_db(id_usuario, usuario, contrasena, email)
    
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/eliminar_auxiliar', methods=['POST'])
def eliminar_auxiliar():
     # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page'))
    id_usuario = request.form.get('id_usuario')
    if not id_usuario:
        flash("No se especificó ID para eliminar.", "danger"); return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = eliminar_auxiliar_db(id_usuario)
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/reiniciar_sistema', methods=['POST'])
def reiniciar_sistema():
     # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash("Acción no autorizada.", "danger")
        return redirect(url_for('login_page'))
    confirmacion = request.form.get('confirmacion')
    if confirmacion != 'REINICIAR':
        flash("La palabra de confirmación es incorrecta. No se ha realizado ninguna acción.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = reiniciar_registros_db()
    flash(mensaje, "success" if resultado else "danger")
    return redirect(url_for('gestion_auxiliares'))

def obtener_auxiliares_db():
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        # <-- CAMBIO AQUÍ: seleccionamos EMAIL -->
        cursor.execute("SELECT ID, USUARIO, EMAIL FROM USUARIOS WHERE TIPO = 1 ORDER BY USUARIO")
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener auxiliares: {e}")
        traceback.print_exc()
        return []
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def insertar_auxiliar_db(usuario, contrasena, email): # <-- CAMBIO: Acepta 'email'
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        
        # <-- CAMBIO AQUÍ: Comprobar duplicado de usuario O email -->
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE USUARIO = :usr OR EMAIL = :email", usr=usuario, email=email)
        if cursor.fetchone()[0] > 0:
            return False, f"El usuario '{usuario}' o el correo '{email}' ya existen."
        
        cursor.execute("SELECT NVL(MAX(ID), 0) + 1 FROM USUARIOS")
        nuevo_id_usuario = cursor.fetchone()[0]
        
        password_hasheada = hash_password(contrasena)
        
        # <-- CAMBIO AQUÍ: Insertar 'EMAIL' -->
        cursor.execute(
            "INSERT INTO USUARIOS (ID, USUARIO, PASSWORD, TIPO, EMAIL) VALUES (:id_usr, :usr, :pwd, 1, :email)",
            id_usr=nuevo_id_usuario,
            usr=usuario,
            pwd=password_hasheada,
            email=email # <-- NUEVA LÍNEA
        )
        conn.commit()
        return True, f"Auxiliar '{usuario}' agregado (ID: {nuevo_id_usuario})."
    except Exception as e:
        conn.rollback()
        print(f"Error al insertar auxiliar '{usuario}': {e}")
        traceback.print_exc()
        return False, "Error interno al agregar."
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

def actualizar_auxiliar_db(id_usuario, usuario, contrasena, email): # <-- CAMBIO: Acepta 'email'
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        
        # <-- CAMBIO AQUÍ: Comprobar duplicados (usuario O email) que NO sean el usuario actual -->
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE (USUARIO = :usr OR EMAIL = :email) AND ID != :id_usr", 
                       usr=usuario, email=email, id_usr=id_usuario)
        if cursor.fetchone()[0] > 0: 
            return False, f"El nombre '{usuario}' o el correo '{email}' ya están en uso."
        
        if contrasena: # Si el admin escribió una nueva contraseña
            password_hasheada = hash_password(contrasena)
            
            # <-- CAMBIO AQUÍ: Actualizar 'EMAIL' -->
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr, PASSWORD = :pwd, EMAIL = :email WHERE ID = :id_usr", 
                           usr=usuario, pwd=password_hasheada, email=email, id_usr=id_usuario)
        else: # Si el admin solo cambió el nombre y/o email
        
            # <-- CAMBIO AQUÍ: Actualizar 'EMAIL' -->
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr, EMAIL = :email WHERE ID = :id_usr", 
                           usr=usuario, email=email, id_usr=id_usuario)
            
        conn.commit()
        return (True, "Auxiliar actualizado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except Exception as e:
        conn.rollback()
        print(f"Error al actualizar auxiliar ID {id_usuario}: {e}")
        traceback.print_exc()
        return False, "Error interno al actualizar."
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

def eliminar_auxiliar_db(id_usuario):
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM USUARIOS WHERE ID = :id_usr AND TIPO = 1", id_usr=id_usuario)
        conn.commit()
        return (True, "Auxiliar eliminado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except oracledb.IntegrityError:
        conn.rollback(); return False, "No se puede eliminar, tiene registros asociados (préstamos, etc.)."
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar auxiliar ID {id_usuario}: {e}")
        traceback.print_exc()
        return False, "Error interno al eliminar."
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def reiniciar_registros_db():
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM DETALLE_PRESTAMO")
        cursor.execute("DELETE FROM REGISTRO_DANOS")
        cursor.execute("DELETE FROM PRESTAMOS")
        # --- ¡CORRECCIÓN AQUÍ! ---
        cursor.execute("DELETE FROM REGISTRO_ACTIVIDAD")
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD, CANTIDAD_DANADA = 0")
        conn.commit()
        return True, "El sistema ha sido reiniciado. Todos los préstamos, daños y registros de actividad han sido eliminados."
    except Exception as e:
        conn.rollback()
        print(f"Error al reiniciar el sistema: {e}"); traceback.print_exc()
        return False, "Ocurrió un error interno al intentar reiniciar el sistema."
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
            
@app.route("/bienvenida_registro")
def splash_for_registration():
    # Renderiza la COPIA de splash.html que redirige al registro
    return render_template("splash_registro.html")

# --- RUTAS Y FUNCIONES DE ALUMNOS ---
@app.route("/registro_alumno", methods=["GET", "POST"])
def registro_alumno():
    
    if request.method == "GET":
        return render_template("inicioAlumno.html")

    # --- Captura de datos ---
    nombre = request.form.get("nombre", "").strip()
    numero_control = request.form.get("numero_control", "").strip()
    correo_raw = request.form.get("correo", "").strip()
    especialidad = request.form.get("carrera", "").strip()
    semestre = request.form.get("semestre", "").strip()

    # --- Validación de campos vacíos ---
    if not all([nombre, numero_control, correo_raw, especialidad, semestre]):
        flash("Completa todos los campos.", "warning")
        return render_template("inicioAlumno.html")

    # --- Limpieza y validación del correo ---
    correo_limpio = correo_raw.replace(" ", "").lower()
    DOMINIO_PERMITIDO = "@saltillo.tecnm.mx"

    if not correo_limpio.endswith(DOMINIO_PERMITIDO):
        flash(f"El correo debe ser institucional (terminar en {DOMINIO_PERMITIDO}).", "danger")
        return render_template("inicioAlumno.html")
    
    # --- FIN DEL IF ---
    # Estas líneas deben estar AFUERA del 'if' anterior

    # 1. Usamos 'correo_limpio'
    resultado = registrar_alumno_db(nombre, numero_control, correo_limpio, especialidad, int(semestre))

    if resultado == "duplicado":
        flash("El número de control o correo ya están registrados.", "error")
    elif resultado == "ok":
        flash("Te has registrado con éxito.", "success")
        # Es buena idea redirigir aquí para limpiar el formulario
        return redirect(url_for('registro_alumno')) 
    else:
        flash("Error al registrar alumno. Intenta de nuevo.", "error")

    # Si hay error (duplicado, etc.) se vuelve a cargar la página
    return render_template("inicioAlumno.html")

def registrar_alumno_db(nombre, numero_control, correo, especialidad, semestre):
    # --- ¡MODIFICACIÓN AQUÍ! ---
    conn = get_db_connection()
    if not conn: return "error"
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ALUMNOS WHERE NUMEROCONTROL = :nc OR CORREO = :cr", nc=numero_control, cr=correo)
        if cursor.fetchone()[0] > 0: return "duplicado"
        # Se agrega la columna ACTIVO con valor 1 (numérico)
        cursor.execute(
            "INSERT INTO ALUMNOS (nombre, numerocontrol, correo, especialidad, semestre, ACTIVO) VALUES (:n, :nc, :cr, :e, :s, 1)",
            n=nombre, nc=numero_control, cr=correo, e=especialidad, s=semestre
        )
        conn.commit()
        return "ok"
    except Exception as e: print(f"Error Oracle en registrar_alumno: {e}"); conn.rollback(); return "error"
    finally:
        if conn: cursor.close(); conn.close()
    # --- FIN DE MODIFICACIÓN ---


# --- (NUEVAS RUTAS Y FUNCIONES PARA GESTIÓN DE ALUMNOS) ---
# --- ESTE BLOQUE ES NUEVO ---

# --- Nueva Ruta: Página de Gestión de Alumnos ---
@app.route('/gestion_alumnos')
def gestion_alumnos():
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash("Acceso no autorizado.", "danger"); return redirect(url_for('login_page'))

    alumnos = obtener_todos_alumnos_db()
    
    context_data = {
        'alumnos': alumnos,
        'usuario_rol': session.get('user_rol'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    # Usaremos un nuevo template: gestion_alumnos.html
    return render_template('gestion_alumnos.html', **context_data)

# --- Nueva Ruta: Procesar Modificación de Alumno ---
@app.route('/modificar_alumno', methods=['POST'])
def modificar_alumno():
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        return redirect(url_for('login_page'))

    # 1. Obtener datos del formulario
    id_alumno = request.form.get('id_alumno')
    nombre = request.form.get('nombre', '').strip()
    numero_control_raw = request.form.get('numero_control', '').strip()
    correo_raw = request.form.get('correo', '').strip()
    especialidad = request.form.get('carrera', '').strip()
    semestre = request.form.get('semestre', '').strip()

    # 2. Validar campos vacíos
    if not all([id_alumno, nombre, numero_control_raw, correo_raw, especialidad, semestre]):
        flash("Todos los campos son obligatorios para modificar.", "danger")
        return redirect(url_for('gestion_alumnos'))

    # 3. Aplicar las MISMAS validaciones del registro
    
    # Validación de Nombre (solo letras y espacios)
    if not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", nombre):
        flash("El nombre solo debe contener letras y espacios.", "danger")
        return redirect(url_for('gestion_alumnos'))

    # Validación de Número de Control (8 dígitos o 1 Letra + 8 dígitos)
    numero_control = numero_control_raw.upper()
    if not re.match(r'^([A-Z]\d{8}|\d{8})$', numero_control):
        flash("Formato de Número de Control inválido (ej: 21040350 o L21040350).", "danger")
        return redirect(url_for('gestion_alumnos'))

    # Validación de Correo (dominio y limpieza)
    correo_limpio = correo_raw.replace(" ", "").lower()
    DOMINIO_PERMITIDO = "@saltillo.tecnm.mx"
    if not correo_limpio.endswith(DOMINIO_PERMITIDO):
        flash(f"El correo debe ser institucional (terminar en {DOMINIO_PERMITIDO}).", "danger")
        return redirect(url_for('gestion_alumnos'))

    # 4. Intentar actualizar en la BD
    resultado, mensaje = actualizar_alumno_db(
        id_alumno, nombre, numero_control, correo_limpio, especialidad, int(semestre)
    )

    flash(mensaje, "success" if resultado else "danger")
    return redirect(url_for('gestion_alumnos'))

# --- Nueva Ruta: Activar/Desactivar Alumno ---
@app.route('/desactivar_alumno', methods=['POST'])
def desactivar_alumno():
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        return redirect(url_for('login_page'))
        
    id_alumno = request.form.get('id_alumno')
    if not id_alumno:
        flash("No se especificó el ID del alumno.", "danger")
        return redirect(url_for('gestion_alumnos'))

    resultado, mensaje = cambiar_estatus_alumno_db(id_alumno)
    flash(mensaje, "success" if resultado else "danger")
    return redirect(url_for('gestion_alumnos'))


# --- (Nuevas Funciones de DB para Alumnos) ---

def obtener_todos_alumnos_db():
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        # Se selecciona la columna ACTIVO (numérica)
        cursor.execute("SELECT ID_ALUMNO, NOMBRE, NUMEROCONTROL, CORREO, ESPECIALIDAD, SEMESTRE, ACTIVO FROM ALUMNOS ORDER BY NOMBRE")
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener todos los alumnos: {e}")
        traceback.print_exc()
        return []
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def actualizar_alumno_db(id_alumno, nombre, numero_control, correo, especialidad, semestre):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        # Verificar duplicados (que no sean el alumno mismo)
        cursor.execute(
            "SELECT COUNT(*) FROM ALUMNOS WHERE (NUMEROCONTROL = :nc OR CORREO = :cr) AND ID_ALUMNO != :id_a",
            nc=numero_control, cr=correo, id_a=id_alumno
        )
        if cursor.fetchone()[0] > 0:
            return False, "El N° de Control o Correo ya están registrados por otro alumno."
        
        # Realizar la actualización (no se toca la columna ACTIVO)
        cursor.execute("""
            UPDATE ALUMNOS SET
                NOMBRE = :n,
                NUMEROCONTROL = :nc,
                CORREO = :cr,
                ESPECIALIDAD = :e,
                SEMESTRE = :s
            WHERE ID_ALUMNO = :id_a
        """, n=nombre, nc=numero_control, cr=correo, e=especialidad, s=semestre, id_a=id_alumno)
        
        conn.commit()
        return (True, "Alumno actualizado correctamente.") if cursor.rowcount > 0 else (False, "No se encontró el alumno a modificar.")
    except Exception as e:
        conn.rollback()
        print(f"Error al actualizar alumno ID {id_alumno}: {e}")
        traceback.print_exc()
        return False, "Error interno al actualizar."
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def cambiar_estatus_alumno_db(id_alumno):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        # 1. Ver el estatus actual (1 o 0)
        cursor.execute("SELECT ACTIVO FROM ALUMNOS WHERE ID_ALUMNO = :id_a", id_a=id_alumno)
        res = cursor.fetchone()
        if not res:
            return False, "Alumno no encontrado."
            
        estatus_actual = res[0] # 1 (Activo) o 0 (Inactivo)
        # Invertimos el valor:
        nuevo_estatus_num = 0 if estatus_actual == 1 else 1
        
        # 2. Actualizar al estatus opuesto
        cursor.execute("UPDATE ALUMNOS SET ACTIVO = :est WHERE ID_ALUMNO = :id_a", est=nuevo_estatus_num, id_a=id_alumno)
        conn.commit()
        
        mensaje_amigable = "Inactivo" if nuevo_estatus_num == 0 else "Activo"
        return True, f"Alumno marcado como '{mensaje_amigable}'."
    except Exception as e:
        conn.rollback()
        print(f"Error al cambiar estatus de alumno ID {id_alumno}: {e}")
        traceback.print_exc()
        return False, "Error interno al cambiar estatus."
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

# --- FIN DEL NUEVO BLOQUE DE GESTIÓN DE ALUMNOS ---


# --- RUTAS Y FUNCIONES DE INVENTARIO ---
@app.route('/inventario')
def inventario():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite ---
    context_data = {
        'materiales': obtener_materiales(),
        'usuario_rol': session.get('user_rol'),
        'login_time': session.get('login_time_iso'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template('inventario.html', **context_data)
    # --- FIN ACTUALIZACIÓN ---

def obtener_materiales():
    # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD AS CANTIDAD_TOTAL, CANTIDAD_DISPONIBLE, CANTIDAD_DANADA,
                   (CANTIDAD - CANTIDAD_DISPONIBLE - CANTIDAD_DANADA) AS CANTIDAD_EN_USO,
                   CASE WHEN CANTIDAD_DISPONIBLE = 0 THEN 'Sin stock' WHEN (CANTIDAD - CANTIDAD_DISPONIBLE - CANTIDAD_DANADA) > 0 THEN 'En uso' ELSE 'Disponible' END AS ESTATUS
            FROM MATERIALES ORDER BY ID_MATERIAL
        """)
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener_materiales: {e}"); flash(f"Error al cargar inventario: {str(e).splitlines()[0]}", 'danger'); return []
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

@app.route('/agregar_material', methods=['POST'])
def agregar_material():
    # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    if not nombre or not cantidad:
        flash('Nombre y Cantidad son obligatorios.', 'danger'); return redirect(url_for('inventario'))
    try:
        cantidad_int = int(cantidad)
        if cantidad_int <= 0: raise ValueError
    except ValueError:
        flash('La cantidad debe ser un número entero positivo.', 'danger'); return redirect(url_for('inventario'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('inventario'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT NVL(MAX(ID_MATERIAL), 0) + 1 FROM MATERIALES")
        nuevo_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO MATERIALES (ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, CANTIDAD_DISPONIBLE, CANTIDAD_DANADA) VALUES (:p_id, :n, :t, :m, :c, :cd, 0)", p_id=nuevo_id, n=nombre, t=tipo, m=marca_modelo, c=cantidad, cd=cantidad)
        detalle = f"Se agregaron {cantidad} unidad(es) del nuevo material '{nombre}'."
        cursor.execute("""
            INSERT INTO REGISTRO_MOVIMIENTOS (ID_USUARIO, TIPO_ACCION, ID_MATERIAL_AFECTADO, NOMBRE_MATERIAL_AFECTADO, DETALLE)
            VALUES (:p_uid, 'AGREGAR', :p_mid, :p_mnom, :p_det)""",
            p_uid=session['user_id'], p_mid=nuevo_id, p_mnom=nombre, p_det=detalle)
        conn.commit()
        flash(f'Material "{nombre}" agregado (ID: {nuevo_id}).', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error al agregar material: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('inventario'))

@app.route('/modificar_material', methods=['POST'])
def modificar_material():
    # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    if session.get('user_rol') != 'admin':
        flash('Acción no autorizada. Solo los administradores pueden modificar.', 'danger')
        return redirect(url_for('inventario'))
    id_material = int(request.form.get('id_material'))
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad_nueva = int(request.form.get('cantidad'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('inventario'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT NOMBRE, CANTIDAD, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL = :p_id", p_id=id_material)
        material_actual = cursor.fetchone()
        if not material_actual:
            flash(f'Error: Material con ID {id_material} no encontrado.', 'danger')
            return redirect(url_for('inventario'))
        nombre_antiguo, cantidad_antigua, disponibles_antiguos = material_actual
        diferencia = cantidad_nueva - cantidad_antigua
        if (disponibles_antiguos + diferencia) < 0:
            flash('Error: La nueva cantidad total es menor que la cantidad de material actualmente en préstamo.', 'danger')
            return redirect(url_for('inventario'))
        nueva_cantidad_disponible = disponibles_antiguos + diferencia
        cursor.execute("UPDATE MATERIALES SET NOMBRE = :n, TIPO = :t, MARCA_MODELO = :m, CANTIDAD = :c, CANTIDAD_DISPONIBLE = :cd WHERE ID_MATERIAL = :p_id",
                       n=nombre, t=tipo, m=marca_modelo, c=cantidad_nueva, cd=nueva_cantidad_disponible, p_id=id_material)
        detalle = f"Cantidad total de '{nombre}' cambió de {cantidad_antigua} a {cantidad_nueva}."
        cursor.execute("""
            INSERT INTO REGISTRO_MOVIMIENTOS (ID_USUARIO, TIPO_ACCION, ID_MATERIAL_AFECTADO, NOMBRE_MATERIAL_AFECTADO, DETALLE)
            VALUES (:p_uid, 'MODIFICAR', :p_mid, :p_mnom, :p_det)""",
            p_uid=session['user_id'], p_mid=id_material, p_mnom=nombre, p_det=detalle)
        conn.commit()
        flash(f'Material ID {id_material} modificado.', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Error al modificar material: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('inventario'))

@app.route('/eliminar_material', methods=['POST'])
def eliminar_material():
    # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    if session.get('user_rol') != 'admin':
        flash('Acción no autorizada. Solo los administradores pueden eliminar.', 'danger')
        return redirect(url_for('inventario'))
    id_material = int(request.form.get('id_material'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('inventario'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT NOMBRE FROM MATERIALES WHERE ID_MATERIAL = :p_id", p_id=id_material)
        res = cursor.fetchone()
        if not res:
            flash(f'Error: Material con ID {id_material} no encontrado.', 'danger')
            return redirect(url_for('inventario'))
        nombre_material = res[0]
        cursor.execute("DELETE FROM MATERIALES WHERE ID_MATERIAL = :p_id", p_id=id_material)
        detalle = f"Se eliminó el material '{nombre_material}' (ID: {id_material}) del inventario."
        cursor.execute("""
            INSERT INTO REGISTRO_MOVIMIENTOS (ID_USUARIO, TIPO_ACCION, ID_MATERIAL_AFECTADO, NOMBRE_MATERIAL_AFECTADO, DETALLE)
            VALUES (:p_uid, 'ELIMINAR', :p_mid, :p_mnom, :p_det)""",
            p_uid=session['user_id'], p_mid=id_material, p_mnom=nombre_material, p_det=detalle)
        conn.commit()
        flash(f'Material ID {id_material} eliminado.', 'success')
    except oracledb.IntegrityError:
        conn.rollback()
        flash('Error: No se puede eliminar el material porque tiene préstamos o daños asociados.', 'danger')
    except Exception as e:
        conn.rollback()
        flash(f'Error al eliminar material: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('inventario'))

@app.route('/api/movimientos_inventario')
def movimientos_inventario():
     # ... (código sin cambios)
    if 'user_rol' not in session or session['user_rol'] != 'admin':
        return jsonify({'error': 'No autorizado'}), 403
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Error de conexión'}), 500
    try:
        cursor = conn.cursor()
        query = """
            SELECT rm.TIPO_ACCION, rm.NOMBRE_MATERIAL_AFECTADO, rm.DETALLE, rm.FECHA_MOVIMIENTO, u.USUARIO
            FROM REGISTRO_MOVIMIENTOS rm LEFT JOIN USUARIOS u ON rm.ID_USUARIO = u.ID
            ORDER BY rm.FECHA_MOVIMIENTO DESC FETCH FIRST 50 ROWS ONLY"""
        cursor.execute(query)
        movimientos = rows_to_dicts(cursor, cursor.fetchall())
        return jsonify(movimientos)
    except Exception as e:
        print(f"Error al obtener movimientos de inventario: {e}")
        return jsonify({'error': 'Error interno al obtener el registro'}), 500
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

# --- RUTAS Y FUNCIONES DE PRÉSTAMOS ---
@app.route('/prestamos')
def prestamos():
    # 1. Verificar sesión
    if 'user_id' not in session:
        flash("Por favor, inicia sesión para acceder.", "warning")
        return redirect(url_for('login_page'))

    # 2. Preparar contexto base (incluyendo inactivity_limit)
    #    Tu user_context ya contiene lo necesario para la base y el script
    user_context = {
        'usuario_rol': session.get('user_rol'),
        'login_time_iso': session.get('login_time_iso'), # Para el timer de sesión aux
        'inactivity_limit': app.permanent_session_lifetime.total_seconds() # Para el script de inactividad
        # 'current_user' no parece necesario si usas session['user_nombre'] directamente
    }

    # 3. Preparar variables para los datos de la BD
    materiales_disponibles = []
    materias = []
    maestros = []
    prestamos_con_materiales = [] # Lista final procesada

    # 4. Conectar y obtener datos de la BD
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", 'danger')
        # Pasamos el user_context incluso si hay error de DB
        context_data = {
            'materiales_disponibles': [], 'materias': [], 'maestros': [],
            'prestamos_activos': [],
            **user_context # Incluye rol y inactivity_limit
        }
        return render_template('prestamos.html', **context_data)

    try:
        cursor = conn.cursor()
        # Obtener materiales, materias, maestros (sin cambios)
        cursor.execute("SELECT ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE CANTIDAD_DISPONIBLE > 0 ORDER BY NOMBRE")
        materiales_disponibles = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT ID_MATERIA, NOMBRE_MATERIA FROM MATERIAS ORDER BY NOMBRE_MATERIA")
        materias = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT ID_MAESTRO, NOMBRE_COMPLETO FROM MAESTROS ORDER BY NOMBRE_COMPLETO")
        maestros = rows_to_dicts(cursor, cursor.fetchall())

        # Obtener y procesar préstamos activos (sin cambios)
        cursor.execute("SELECT p.ID_PRESTAMO, a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' ORDER BY p.FECHA_HORA DESC")
        prestamos_activos_base = rows_to_dicts(cursor, cursor.fetchall())

        for prestamo in prestamos_activos_base:
            fecha_str = prestamo.get('FECHA_HORA')
            if fecha_str:
                try:
                    fecha_objeto = datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S.%f') if '.' in fecha_str else datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
                    prestamo['FECHA_HORA_DISPLAY'] = fecha_objeto.strftime('%d/%m/%Y %H:%M')
                except ValueError:
                     prestamo['FECHA_HORA_DISPLAY'] = fecha_str
            else: prestamo['FECHA_HORA_DISPLAY'] = 'N/A'

            cursor.execute("SELECT m.NOMBRE, dp.CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL WHERE dp.ID_PRESTAMO = :id_p", id_p=prestamo['ID_PRESTAMO'])
            materiales_prestados = rows_to_dicts(cursor, cursor.fetchall())
            prestamo['MATERIALES_LISTA'] = ', '.join([f"{m['NOMBRE']} (x{m['CANTIDAD_PRESTADA']})" for m in materiales_prestados])
            prestamos_con_materiales.append(prestamo) # Añadir a la lista final

    except Exception as e:
        error_msg = str(e).splitlines()[0]
        flash(f"Error al cargar datos de préstamos: {error_msg}.", "danger")
        traceback.print_exc()
        prestamos_con_materiales = [] # Asegurar que sea una lista vacía en caso de error
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

    # 5. Combinar datos específicos con contexto base
    context_data = {
         'materiales_disponibles': materiales_disponibles,
         'materias': materias,
         'maestros': maestros,
         'prestamos_activos': prestamos_con_materiales,
         **user_context # ¡Añade todas las claves de user_context aquí!
    }

    # 6. Renderizar la plantilla pasando el contexto combinado
    return render_template('prestamos.html', **context_data)

# --- (Resto de rutas de préstamos sin cambios) ---
@app.route('/api/alumno/<numerocontrol>')
def get_alumno(numerocontrol):
    # --- ¡MODIFICACIÓN AQUÍ! ---
    if 'user_id' not in session: return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Error de base de datos'}), 500
    try:
        cursor = conn.cursor()
        # Se agrega "AND ACTIVO = 1" para no encontrar alumnos inactivos
        cursor.execute(
            "SELECT ID_ALUMNO, NOMBRE, SEMESTRE FROM ALUMNOS WHERE NUMEROCONTROL = :nc AND ACTIVO = 1", 
            nc=numerocontrol
        )
        rows = cursor.fetchall()
        if rows: 
            return jsonify(rows_to_dicts(cursor, rows)[0])
        else: 
            # Mensaje de error actualizado
            return jsonify({'error': 'Alumno no encontrado o inactivo'}), 404
    except Exception as e: 
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: cursor.close(); conn.close()
    # --- FIN DE MODIFICACIÓN ---

@app.route('/api/prestamo/<int:id_prestamo>/materiales')
def get_prestamo_materiales(id_prestamo):
     # ... (código sin cambios)
    if 'user_id' not in session: return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Error de base de datos'}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT m.ID_MATERIAL, m.NOMBRE, dp.CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL WHERE dp.ID_PRESTAMO = :id_p AND dp.CANTIDAD_PRESTADA > 0", id_p=id_prestamo)
        materiales = rows_to_dicts(cursor, cursor.fetchall())
        if not materiales: return jsonify({'error': 'No hay materiales activos para reportar daño en este vale.'}), 404
        return jsonify(materiales)
    except Exception as e:
        print(f"Error API get_prestamo_materiales: {e}"); traceback.print_exc()
        return jsonify({'error': 'Error interno al buscar materiales.'}), 500
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/registrar_prestamo', methods=['POST'])
def registrar_prestamo():
     # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    no_control = request.form.get('no_control', '').strip().upper()
    if not re.match(r'^(\d{8}|[A-Z]\d{8})$', no_control):
        flash("Formato de Número de Control inválido.", 'danger')
        return redirect(url_for('prestamos'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        materiales_seleccionados = json.loads(request.form.get('materiales_seleccionados', '{}'))
        if not materiales_seleccionados:
            flash('No se seleccionó ningún material.', 'warning'); return redirect(url_for('prestamos'))
        
        # IMPORTANTE: La API get_alumno ya filtra por ACTIVO=1,
        # pero hacemos una doble verificación aquí por si acaso.
        cursor.execute("SELECT ID_ALUMNO FROM ALUMNOS WHERE NUMEROCONTROL = :nc AND ACTIVO = 1", nc=no_control)
        result = cursor.fetchone()
        if not result:
            flash(f"Alumno con NC {no_control} no encontrado o está inactivo.", "danger"); return redirect(url_for('prestamos'))
        
        id_alumno = result[0]
        id_prestamo_var = cursor.var(oracledb.NUMBER)
        cursor.execute("INSERT INTO PRESTAMOS (ID_ALUMNO, ID_MATERIA, ID_MAESTRO, ID_AUXILIAR, NUMERO_MESA, ESTATUS, FECHA_HORA) VALUES (:id_a, :id_m, :id_ma, :id_aux, :mesa, 'Activo', LOCALTIMESTAMP) RETURNING ID_PRESTAMO INTO :id_p_out",
                       id_a=id_alumno, id_m=request.form['materia'], id_ma=request.form['maestro'], id_aux=session['user_id'], mesa=request.form.get('mesa'), id_p_out=id_prestamo_var)
        id_nuevo_prestamo = id_prestamo_var.getvalue()[0]
        for id_material, cantidad in materiales_seleccionados.items():
            cursor.execute("INSERT INTO DETALLE_PRESTAMO (ID_PRESTAMO, ID_MATERIAL, CANTIDAD_PRESTADA) VALUES (:p, :m, :c)", p=id_nuevo_prestamo, m=int(id_material), c=int(cantidad))
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE - :c WHERE ID_MATERIAL = :m", c=int(cantidad), m=int(id_material))
        conn.commit()
        flash('Préstamo registrado exitosamente.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar el préstamo: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('prestamos'))

@app.route('/devolver_prestamo', methods=['POST'])
def devolver_prestamo():
     # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    id_prestamo = request.form.get('id_prestamo')
    if not id_prestamo:
        flash("ID de préstamo no proporcionado.", "danger"); return redirect(url_for('prestamos'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_MATERIAL, CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO WHERE ID_PRESTAMO = :id_p", id_p=int(id_prestamo))
        materiales_a_devolver = rows_to_dicts(cursor, cursor.fetchall())
        for material in materiales_a_devolver:
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :c WHERE ID_MATERIAL = :m", c=material['CANTIDAD_PRESTADA'], m=material['ID_MATERIAL'])
        cursor.execute("UPDATE PRESTAMOS SET ESTATUS = 'Devuelto', FECHA_DEVOLUCION = SYSTIMESTAMP WHERE ID_PRESTAMO = :id_p", id_p=int(id_prestamo))
        conn.commit()
        flash('Material devuelto y stock actualizado.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error en la devolución: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('prestamos'))

@app.route('/registrar_dano', methods=['POST'])
def registrar_dano():
     # ... (código sin cambios)
    if 'user_id' not in session: return redirect(url_for('login_page'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        id_prestamo = int(request.form['id_prestamo']); id_material = int(request.form['id_material']); cantidad_danada = int(request.form['cantidad_danada'])
        motivo = request.form.get('motivo'); id_auxiliar = session['user_id']
        cursor = conn.cursor()
        cursor.execute("INSERT INTO REGISTRO_DANOS (ID_DANO, ID_PRESTAMO, ID_MATERIAL, CANTIDAD_DANADA, MOTIVO, ID_AUXILIAR_REGISTRO) VALUES (REGISTRO_DANOS_SEQ.nextval, :id_p, :id_m, :cant, :motivo, :id_aux)",
                       id_p=id_prestamo, id_m=id_material, cant=cantidad_danada, motivo=motivo, id_aux=id_auxiliar)
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DANADA = CANTIDAD_DANADA + :cant WHERE ID_MATERIAL = :id_m", cant=cantidad_danada, id_m=id_material)
        cursor.execute("UPDATE DETALLE_PRESTAMO SET CANTIDAD_PRESTADA = CANTIDAD_PRESTADA - :cant WHERE ID_PRESTAMO = :id_p AND ID_MATERIAL = :id_m",
                       cant=cantidad_danada, id_p=id_prestamo, id_m=id_material)
        conn.commit()
        flash('Daño registrado correctamente.', 'warning')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar el daño: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
    return redirect(url_for('prestamos'))

@app.route('/gestion_danos')
def gestion_danos():
    if 'user_id' not in session:
        flash("Por favor, inicia sesión.", "warning"); return redirect(url_for('login_page'))
    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite ---
    usuario_rol = session.get('user_rol')
    conn = get_db_connection()
    context_base = {
        'usuario_rol': usuario_rol,
        'login_time': session.get('login_time_iso'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    # --- FIN ACTUALIZACIÓN ---
    if not conn:
        flash("Error de conexión.", 'danger');
        return render_template('gestion_danos.html', danos_pendientes=[], **context_base)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rd.ID_DANO, rd.CANTIDAD_DANADA, rd.MOTIVO, rd.FECHA_REGISTRO, rd.ESTATUS_REPOSICION, m.NOMBRE AS NOMBRE_MATERIAL, a.NOMBRE AS NOMBRE_ALUMNO, a.NUMEROCONTROL
            FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL JOIN PRESTAMOS p ON rd.ID_PRESTAMO = p.ID_PRESTAMO JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO
            WHERE rd.ESTATUS_REPOSICION = 'PENDIENTE' ORDER BY rd.FECHA_REGISTRO DESC""")
        danos_pendientes = rows_to_dicts(cursor, cursor.fetchall())
        context_data = {**context_base, 'danos_pendientes': danos_pendientes}
        return render_template('gestion_danos.html', **context_data)
    except Exception as e:
        flash(f"Error al cargar daños pendientes: {e}", "danger"); traceback.print_exc()
        return render_template('gestion_danos.html', danos_pendientes=[], **context_base)
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

@app.route('/reponer_dano', methods=['POST'])
def reponer_dano():
     # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page')) # Solo admin puede reponer
    id_dano = request.form.get('id_dano')
    if not id_dano:
        flash("ID de daño no proporcionado.", "danger"); return redirect(url_for('gestion_danos'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return redirect(url_for('gestion_danos'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_MATERIAL, CANTIDAD_DANADA FROM REGISTRO_DANOS WHERE ID_DANO = :id_d", id_d=int(id_dano))
        dano = cursor.fetchone()
        if not dano:
            flash(f"Registro de daño ID {id_dano} no encontrado.", "danger"); return redirect(url_for('gestion_danos'))
        id_material, cantidad_danada = dano
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :cant, CANTIDAD_DANADA = CANTIDAD_DANADA - :cant WHERE ID_MATERIAL = :id_m",
                       cant=cantidad_danada, id_m=id_material)
        cursor.execute("UPDATE REGISTRO_DANOS SET ESTATUS_REPOSICION = 'REPUESTO' WHERE ID_DANO = :id_d", id_d=int(id_dano))
        conn.commit()
        flash(f'Reposición ID {id_dano} registrada. Se agregaron {cantidad_danada} unidad(es) al stock.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar la reposición: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('gestion_danos'))

# --- RUTA DE UTILIDAD ---
@app.route('/desbloquear/<nombre_usuario>')
def desbloquear_usuario(nombre_usuario):
    # ... (código sin cambios)
    if 'user_id' not in session or session['user_rol'] != 'admin':
        flash("Acción no permitida.", "danger"); return redirect(url_for('interface_admin'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", "danger"); return redirect(url_for('interface_admin'))
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = 0, BLOQUEADO_HASTA = NULL WHERE USUARIO = :usr", usr=nombre_usuario)
        conn.commit()
        if cursor.rowcount > 0: flash(f"Usuario '{nombre_usuario}' desbloqueado.", "success")
        else: flash(f"No se encontró al usuario '{nombre_usuario}'.", "warning")
    except Exception as e: flash(f"Error al desbloquear: {e}", "danger"); conn.rollback()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('interface_admin'))

# --- NUEVA RUTA: Para resetear el timer de inactividad del servidor ---
@app.route('/keepalive')
def keepalive():
    # Esta ruta no hace nada más que ser llamada.
    # El simple hecho de recibir una petición válida reinicia
    # el timer de la sesión de Flask si session.permanent es True.
    if 'user_id' not in session:
         # Si la sesión ya expiró, devuelve un error para que JS lo sepa
         return jsonify(success=False, message="Session expired"), 401
    # Reinicia el timer explícitamente tocando la sesión
    session.modified = True
    return jsonify(success=True)
# --- FIN NUEVA RUTA ---
@app.route('/inventario/qr/<material_id>')
def generate_qr(material_id):
    """
    Genera una imagen de código QR 2D para un ID de material.
    """
    if 'user_id' not in session: # Proteger la ruta
        return "No autorizado", 401

    try:
        # --- LÓGICA DE QR REEMPLAZA A LA DE BARCODE ---
        
        # 1. Configurar el QR
        qr = qrcode.QRCode(
            version=1, # Complejidad (1 es el más simple)
            error_correction=qrcode.constants.ERROR_CORRECT_L, # Nivel de corrección
            box_size=10, # Tamaño de cada "pixel" del QR
            border=4,  # Borde blanco
        )
        
        # 2. Añadir el ID del material como datos
        qr.add_data(material_id)
        qr.make(fit=True)

        # 3. Crear la imagen
        img = qr.make_image(fill_color="black", back_color="white")

        # 4. Crear un buffer en memoria
        buffer = io.BytesIO()
        
        # 5. Guardar la imagen PNG en el buffer
        img.save(buffer, 'PNG')
        
        # 6. Regresar al inicio del buffer
        buffer.seek(0)
        # --- FIN DE LA NUEVA LÓGICA ---

        # 7. Enviar el buffer como un archivo de imagen
        return send_file(buffer, mimetype='image/png')
        
    except Exception as e:
        print(f"Error generando código QR: {e}")
        return "Error al generar imagen", 500

# --- FIN DEL CÓDIGO NUEVO ---
@app.route('/api/get_alumno/<ncontrol>')
def get_alumno_data(ncontrol):
    """
    API endpoint para obtener info de un alumno por Número de Control.
    ¡CORREGIDO para usar las columnas de tu tabla ALUMNOS!
    """
    # Proteger el endpoint (puedes quitar esto si el kiosco no tiene sesión)
    if 'user_id' not in session:
       return jsonify({'error': 'No autorizado'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Error de conexión a BD'}), 500
        
    try:
        cursor = conn.cursor()
        
        # --- CORRECCIÓN ---
        # Usamos las columnas de tu captura: NOMBRE, ESPECIALIDAD, ACTIVO
        cursor.execute("""
            SELECT NOMBRE, ESPECIALIDAD, ACTIVO 
            FROM ALUMNOS 
            WHERE NUMEROCONTROL = :ncontrol
        """, ncontrol=ncontrol)
        
        alumno = cursor.fetchone()
        cursor.close()
        conn.close()

        if alumno:
            # --- CORRECCIÓN ---
            # Tu columna ACTIVO es un NÚMERO (1 para sí, 0 para no)
            if alumno[2] == 0:
                 return jsonify({'error': 'Alumno inactivo'}), 403
            
            # Devolvemos los datos como JSON con los nombres correctos
            return jsonify({
                'NOMBRE': alumno[0],      # Columna NOMBRE
                'ESPECIALIDAD': alumno[1], # Columna ESPECIALIDAD
                'ESTATUS': 'Activo'     # Columna ACTIVO (es 1)
            })
        else:
            return jsonify({'error': 'Alumno no encontrado'}), 404
            
    except Exception as e:
        print(f"Error en /api/get_alumno: {e}")
        traceback.print_exc()
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/log_entrada', methods=['POST'])
def log_entrada_alumno():
    """
    API endpoint para registrar la entrada de un alumno (via escaneo).
    Usa la tabla LOG_ACCESO que acabas de crear.
    """
    if 'user_id' not in session:
       return jsonify({'error': 'No autorizado'}), 401
       
    data = request.json
    ncontrol = data.get('ncontrol')
    
    if not ncontrol:
        return jsonify({'error': 'Número de control no proporcionado'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Error de conexión a BD'}), 500

    try:
        cursor = conn.cursor()
        # Esta consulta ya es correcta para tu nueva tabla LOG_ACCESO
        cursor.execute("""
            INSERT INTO LOG_ACCESO (NUMEROCONTROL, FECHA_HORA_ENTRADA)
            VALUES (:ncontrol, :fecha)
            """,
            ncontrol=ncontrol,
            fecha=datetime.now()
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Entrada registrada'})
        
    except Exception as e:
        # Manejar error de llave foránea (si el alumno no existe)
        if 'ORA-02291' in str(e):
             return jsonify({'error': 'Alumno no encontrado en la base de datos.'}), 404
        
        print(f"Error en /api/log_entrada: {e}")
        traceback.print_exc()
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

# Ruta para MOSTRAR la página del kiosco
@app.route('/kiosco')
def kiosco_page():
    if 'user_id' not in session: # Proteger el acceso al kiosco
        flash("Acceso no autorizado.", "danger")
        return redirect(url_for('login_page'))
        
    # Asume que el HTML de abajo lo guardas como 'registro_kiosk.html'
    return render_template('registro_kiosk.html')

# ====================================================================
# --- INICIO: API DE AUTO-REGISTRO PARA KIOSKO ---
# ====================================================================

@app.route('/api/kiosko/verificar/<string:ncontrol>', methods=['GET'])
def kiosko_verificar_alumno(ncontrol):
    """
    Verifica si un número de control es apto para registrarse.
    1. Revisa que NO esté ya en LABSYS (tabla ALUMNOS).
    2. Revisa que SÍ esté en la BD Maestra (MOCK_CONTROL_ESCOLAR) y esté ACTIVO.
    """
    
    # NOTA: No validamos sesión aquí, ya que el kiosko es público
    # para el auto-registro.
    
    # Limpiamos el ncontrol por si acaso
    num_control_limpio = ncontrol.strip().upper()
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "mensaje": "Error interno del servidor (BD)."}), 500

    cursor = conn.cursor()
    try:
        # 1. Comprobación 1: ¿Ya existe en MI sistema (LABSYS)?
        cursor.execute("SELECT 1 FROM ALUMNOS WHERE NUMEROCONTROL = :num", num=num_control_limpio)
        if cursor.fetchone():
            return jsonify({"status": "error", "mensaje": "Este número de control ya está registrado en el sistema."}), 409 # 409 Conflict

        # 2. Comprobación 2: ¿Existe en la BD "Maestra" (simulada) y está ACTIVO?
        # (Usamos ESPECIALIDAD, como en tu tabla ALUMNOS)
        cursor.execute("""
            SELECT NOMBRE_COMPLETO, CORREO_INSTITUCIONAL, ESPECIALIDAD, SEMESTRE
            FROM MOCK_CONTROL_ESCOLAR 
            WHERE NUMEROCONTROL = :num AND ESTATUS = 'ACTIVO'
        """, num=num_control_limpio)
        
        alumno_maestra = cursor.fetchone()
        
        if alumno_maestra:
            # ¡ÉXITO! Encontramos al alumno. Lo mandamos al Kiosko.
            datos_alumno = {
                "nombre": alumno_maestra[0],
                "correo": alumno_maestra[1],
                "especialidad": alumno_maestra[2], # Coincide con tu BD
                "semestre": alumno_maestra[3]
            }
            return jsonify({"status": "ok", "datos": datos_alumno}), 200
        else:
            # No se encontró en la BD maestra o está inactivo
            return jsonify({"status": "error", "mensaje": "Número de control no encontrado o inactivo. Verifique con Control Escolar."}), 404 # 404 Not Found

    except Exception as e:
        print(f"Error Oracle en kiosko_verificar_alumno: {e}"); 
        traceback.print_exc()
        return jsonify({"status": "error", "mensaje": "Error al consultar la base de datos."}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()

@app.route('/api/kiosko/registrar', methods=['POST'])
def kiosko_registrar_alumno():
    """
    Recibe los datos del Kiosko (ncontrol y password) para crear el usuario final
    en la tabla ALUMNOS de LABSYS.
    """
    data = request.get_json()
    if not data or 'ncontrol' not in data or 'password' not in data:
        return jsonify({"status": "error", "mensaje": "Datos incompletos. Se requiere 'ncontrol' y 'password'."}), 400

    ncontrol = data['ncontrol'].strip().upper()
    password_plano = data['password']

    if len(password_plano) < 8:
         return jsonify({"status": "error", "mensaje": "La contraseña debe tener al menos 8 caracteres."}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "mensaje": "Error interno del servidor (BD)."}), 500

    cursor = conn.cursor()
    try:
        # --- RE-VALIDACIÓN (CRUCIAL) ---
        # Volvemos a hacer las mismas validaciones que en la RUTA 1

        # 1. ¿Ya existe en LABSYS?
        cursor.execute("SELECT 1 FROM ALUMNOS WHERE NUMEROCONTROL = :num", num=ncontrol)
        if cursor.fetchone():
            return jsonify({"status": "error", "mensaje": "Este alumno ya fue registrado. Intente iniciar sesión."}), 409

        # 2. ¿Existe en la BD Maestra y está ACTIVO?
        cursor.execute("""
            SELECT NOMBRE_COMPLETO, CORREO_INSTITUCIONAL, ESPECIALIDAD, SEMESTRE
            FROM MOCK_CONTROL_ESCOLAR 
            WHERE NUMEROCONTROL = :num AND ESTATUS = 'ACTIVO'
        """, num=ncontrol)
        
        alumno_maestra = cursor.fetchone()
        
        if not alumno_maestra:
            return jsonify({"status": "error", "mensaje": "No se puede registrar. Alumno no encontrado o inactivo."}), 404
        
        # --- Si pasa todas las validaciones, procedemos a REGISTRAR ---

        # Hashear la contraseña
        password_hasheada = hash_password(password_plano)
        
        # Extraer los datos de la consulta maestra
        nombre_completo = alumno_maestra[0]
        correo_inst = alumno_maestra[1]
        especialidad = alumno_maestra[2] # Coincide con tu BD
        semestre = alumno_maestra[3]

        # 3. INSERTAR en MI sistema (LABSYS)
        # (Usamos las columnas de tu tabla ALUMNOS + la nueva PASSWORD_HASH y ACTIVO=1)
        cursor.execute("""
            INSERT INTO ALUMNOS (
                NUMEROCONTROL, NOMBRE, CORREO, ESPECIALIDAD, SEMESTRE, 
                PASSWORD_HASH, ACTIVO
            )
            VALUES (:num, :nombre, :correo, :esp, :sem, :pass_hash, 1)
        """, {
            "num": ncontrol,
            "nombre": nombre_completo,
            "correo": correo_inst,
            "esp": especialidad,
            "sem": semestre,
            "pass_hash": password_hasheada
        })
        
        # Confirmar la transacción
        conn.commit()
        
        return jsonify({"status": "ok", "mensaje": f"¡Bienvenido, {nombre_completo}! Registro completado."}), 201 # 201 Created

    except oracledb.IntegrityError as e:
        conn.rollback()
        error, = e.args
        print(f"Error de Integridad en Kiosko: {error.code} - {error.message}")
        traceback.print_exc()
        return jsonify({"status": "error", "mensaje": "Error: El alumno ya existe (Error de integridad)."}), 409
    except Exception as e:
        conn.rollback()
        print(f"Error Oracle en kiosko_registrar_alumno: {e}"); 
        traceback.print_exc()
        return jsonify({"status": "error", "mensaje": "Error al registrar en la base de datos."}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if conn: conn.close()
        
def encriptar_pdf(pdf_bytes_sin_encriptar, password):
    """Toma los bytes de un PDF y le añade una contraseña."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes_sin_encriptar))
        writer = PdfWriter()

        # Copia todas las páginas del PDF original al nuevo
        for page in reader.pages:
            writer.add_page(page)

        # ¡Añade la contraseña!
        writer.encrypt(password)

        # Guarda el PDF encriptado en un buffer de memoria
        buffer_encriptado = io.BytesIO()
        writer.write(buffer_encriptado)
        
        # Regresa los bytes del nuevo PDF encriptado
        return buffer_encriptado.getvalue()
        
    except Exception as e:
        print(f"Error al encriptar PDF: {e}")
        traceback.print_exc()
        return None

# ====================================================================
# --- FIN: API DE AUTO-REGISTRO PARA KIOSKO ---
# ====================================================================

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)