# ¡Nuevas importaciones!
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge # Para límite de tamaño
import uuid # Para nombres de archivo únicos
from dotenv import load_dotenv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import cx_Oracle
import re
import traceback
import json
from datetime import datetime, time, timedelta
import pandas as pd
import io

load_dotenv()

app = Flask(__name__)
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
cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# --- CONEXIÓN A LA BASE DE DATOS ---
db_user = 'JEFE_LAB'
db_password = 'jefe123'
dsn = 'localhost:1521/XEPDB1'

def get_db_connection():
    # ... (sin cambios)
    try:
        return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
    except cx_Oracle.DatabaseError as e:
        print(f"--- ERROR DE CONEXIÓN A ORACLE: {e} ---")
        traceback.print_exc()
        return None

def rows_to_dicts(cursor, rows):
    # ... (sin cambios)
    column_names = [d[0].upper() for d in cursor.description]
    results = []
    for row in rows:
        row_dict = dict(zip(column_names, row))
        cleaned_dict = {}
        for key, value in row_dict.items():
            if isinstance(value, (datetime, cx_Oracle.Timestamp, timedelta)):
                cleaned_dict[key] = str(value)
            elif isinstance(value, cx_Oracle.LOB):
                cleaned_dict[key] = value.read()
            elif value is None:
                cleaned_dict[key] = None
            else:
                cleaned_dict[key] = value
        results.append(cleaned_dict)
    return results

# --- NUEVA FUNCIÓN: Se ejecuta ANTES de cada petición ---
@app.before_request
def make_session_permanent():
    # Asegura que la sesión sea permanente para que aplique el timeout
    session.permanent = True
    # Flask maneja el reinicio del timer si session.permanent es True
# --- FIN NUEVA FUNCIÓN ---
# --- FUNCIÓN AUXILIAR PARA VALIDAR EXTENSIÓN ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- FUNCIONES DE AUTENTICACIÓN ---
def autenticar_con_bloqueo(usuario, contrasena):
    # ... (sin cambios)
    conn = get_db_connection()
    if not conn: return (False, None, "Error de conexión con la base de datos.")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, USUARIO, PASSWORD, TIPO, CREADO_EN, INTENTOS_FALLIDOS, BLOQUEADO_HASTA FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        row = cursor.fetchone()
        if not row:
            return (False, None, "Usuario o contraseña incorrectos.")

        id_db, user_db, pwd_db, tipo_db, creado_en_db, intentos_db, bloqueado_hasta_db = row

        if bloqueado_hasta_db is not None and bloqueado_hasta_db > datetime.now():
            cursor.execute("SELECT CEIL((CAST(BLOQUEADO_HASTA AS DATE) - CAST(SYSDATE AS DATE)) * 24 * 60) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
            mins_left = cursor.fetchone()[0]
            return (False, None, f"Cuenta bloqueada. Intenta de nuevo en {int(mins_left) if mins_left and mins_left > 0 else 1} minuto(s).")

        if contrasena == pwd_db:
            cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = 0, BLOQUEADO_HASTA = NULL WHERE USUARIO = :usr", usr=usuario)
            conn.commit()
            return (True, {'id': id_db, 'nombre': user_db, 'tipo': tipo_db}, "Acceso concedido.")
        else:
            nuevos_intentos = intentos_db + 1
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
        if conn: conn.close()
@app.route("/")
def splash_screen():
    # Simplemente renderiza la nueva plantilla splash.html
    return render_template("splash.html")

# --- RUTAS PRINCIPALES ---
@app.route("/login_page", methods=["GET", "POST"])
def login_page(): # Nombre de función cambiado
    # Si ya hay una sesión activa, redirige a la interfaz correspondiente
    # (Esto evita mostrar el login si ya estás logueado)
    if 'user_id' in session:
        if session.get('user_rol') == 'admin':
            return redirect(url_for('interface_admin'))
        else:
            return redirect(url_for('interface_aux'))

    # Si es método POST (envío del formulario)
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()
        
        # Validación básica de campos vacíos
        if not usuario or not contrasena:
            flash("Ambos campos son obligatorios.", "danger")
            # Redirige de vuelta a la PÁGINA DE LOGIN
            return redirect(url_for('login_page')) 
        
        # Intenta autenticar al usuario (con lógica de bloqueo)
        es_valido, datos_usuario, mensaje = autenticar_con_bloqueo(usuario, contrasena)
        
        # Si la autenticación es exitosa
        if es_valido:
            # Configura la sesión
            session.permanent = True # Para que aplique el timeout de inactividad
            session['user_id'] = datos_usuario['id']
            session['user_rol'] = 'admin' if datos_usuario['tipo'] == 0 else 'auxiliar'
            session['user_nombre'] = datos_usuario['nombre']
            session['login_time_iso'] = datetime.now().isoformat()

            # Registra la actividad si es un auxiliar
            if session.get('user_rol') == 'auxiliar':
                conn = get_db_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO REGISTRO_ACTIVIDAD (ID, ID_USUARIO, TIPO_ACCION) VALUES (registro_actividad_seq.nextval, :id_usr, 'INICIO_SESION')", id_usr=session['user_id'])
                        conn.commit()
                    except Exception as e: 
                        print(f"Error al registrar actividad: {e}")
                    finally:
                        if 'cursor' in locals() and cursor: cursor.close()
                        if conn: conn.close() # Asegurar cierre

            # Redirige DIRECTAMENTE a la interfaz correspondiente (ya no hay welcome.html aquí)
            if datos_usuario['tipo'] == 0: 
                return redirect(url_for("profile"))
            else: 
                return redirect(url_for("interface_aux"))
        
        # Si la autenticación falla
        else:
            flash(mensaje, "danger")
            # Redirige de vuelta a la PÁGINA DE LOGIN
            return redirect(url_for('login_page')) 

    # Si es método GET (cargar la página por primera vez)
    # Renderiza el formulario de login (tu plantilla inicioAdmin.html)
    return render_template("inicioAdmin.html")

@app.route('/logout')
def logout():
    # ... (código sin cambios)
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

    # Obtener nombre y rol de la sesión
    user_info = {
        'nombre': session.get('user_nombre'),
        'rol': session.get('user_rol'),
        'profile_pic_filename': None # Inicializar como None
    }
       
    # Buscar el nombre del archivo de la foto en la BD
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT FOTO_PERFIL FROM USUARIOS WHERE ID = :user_id", user_id=session['user_id'])
            result = cursor.fetchone()
            if result and result[0]: # Si hay un nombre de archivo guardado
                user_info['profile_pic_filename'] = result[0]
        except Exception as e:
            print(f"Error al obtener foto de perfil: {e}")
        finally:
            if 'cursor' in locals() and cursor: cursor.close()
            if conn: conn.close()

    context_data = {
        'user_info': user_info, # Pasamos toda la info, incluyendo el filename
        'usuario_rol': session.get('user_rol'), 
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template('profile.html', **context_data)

# --- MANEJADOR DE ERRORES PARA ARCHIVOS GRANDES ---
@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(e):
    flash('El archivo que intentaste subir es demasiado grande (Máximo 2MB).', 'danger')
    # Intenta redirigir a 'profile' si es posible, si no a login
    if 'user_id' in session:
        return redirect(url_for('profile'))
    else:
         return redirect(url_for('login_page'))

# --- RUTAS DE NAVEGACIÓN (MODIFICADAS PARA PASAR TIMEOUT) ---
@app.route("/interface_admin")
def interface_admin():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite ---
    context_data = {
        'usuario_rol': session.get('user_rol'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template("interfaceAdmin.html", **context_data)
    # --- FIN ACTUALIZACIÓN ---

@app.route("/interface_aux")
def interface_aux():
    if 'user_id' not in session: return redirect(url_for('login_page'))
    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite ---
    context_data = {
        'usuario_rol': session.get('user_rol'),
        'login_time': session.get('login_time_iso'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template("interfaceAux.html", **context_data)
    # --- FIN ACTUALIZACIÓN ---

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

# --- RUTA DE REPORTES AVANZADA ---
@app.route('/reportes')
def reportes():
    # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin':
        flash('Acceso no autorizado.', 'danger'); return redirect(url_for('login_page'))

    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return render_template('reportes_avanzado.html', datos={}, usuario_rol=session.get('user_rol'))

    datos_dashboard = {}
    try:
        cursor = conn.cursor()

        # ... (consultas sin cambios) ...
        cursor.execute("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL NOT IN (SELECT DISTINCT ID_MATERIAL FROM DETALLE_PRESTAMO)"); datos_dashboard['stock_muerto'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(rd.CANTIDAD_DANADA) AS TOTAL_DANADO FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL_DANADO DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_danos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.SEMESTRE, COUNT(p.ID_PRESTAMO) AS TOTAL_PRESTAMOS FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO GROUP BY a.SEMESTRE ORDER BY TOTAL_PRESTAMOS DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_semestres'] = rows_to_dicts(cursor, cursor.fetchall())
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
        cursor.execute(query_prestamos_hoy); datos_dashboard['prestamos_de_hoy'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND (LOCALTIMESTAMP - p.FECHA_HORA) > INTERVAL '1' HOUR ORDER BY p.FECHA_HORA ASC"); datos_dashboard['prestamos_vencidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE ESTATUS = 'Activo'");
        activos_ahora = cursor.fetchone()[0];
        datos_dashboard['activos_ahora'] = activos_ahora if activos_ahora else 0
        cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE FECHA_HORA >= TRUNC(LOCALTIMESTAMP)");
        total_hoy = cursor.fetchone()[0];
        datos_dashboard['total_prestamos_hoy'] = total_hoy if total_hoy else 0
        cursor.execute("SELECT USUARIO, INTENTOS_FALLIDOS FROM USUARIOS WHERE TIPO = 1 AND INTENTOS_FALLIDOS > 0 ORDER BY INTENTOS_FALLIDOS DESC"); datos_dashboard['logins_fallidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_materiales_pedidos'] = rows_to_dicts(cursor, cursor.fetchall())
        query_auxiliares_activos = """
            WITH LastActivity AS (
                SELECT r.ID_USUARIO, r.TIPO_ACCION, r.FECHA_HORA, u.USUARIO,
                    ROW_NUMBER() OVER(PARTITION BY r.ID_USUARIO ORDER BY r.FECHA_HORA DESC) as rn
                FROM REGISTRO_ACTIVIDAD r JOIN USUARIOS u ON r.ID_USUARIO = u.ID WHERE u.TIPO = 1
            ) SELECT USUARIO, FECHA_HORA FROM LastActivity WHERE rn = 1 AND TIPO_ACCION = 'INICIO_SESION' ORDER BY FECHA_HORA ASC
        """
        cursor.execute(query_auxiliares_activos)
        datos_dashboard['auxiliares_activos'] = rows_to_dicts(cursor, cursor.fetchall())

    except Exception as e:
        flash(f"Error al generar reportes avanzados: {e}", "danger")
        traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

    # --- ACTUALIZACIÓN (TIMEOUT): Pasar límite a la plantilla de reportes ---
    context_data = {
        'datos': datos_dashboard,
        'usuario_rol': session.get('user_rol'),
        'inactivity_limit': app.permanent_session_lifetime.total_seconds()
    }
    return render_template('reportes_avanzado.html', **context_data)
    # --- FIN ACTUALIZACIÓN ---


# --- RUTA PARA DESCARGAR REPORTE EN EXCEL ---
# --- RUTA PARA DESCARGAR REPORTE EN EXCEL ---
# --- NUEVA RUTA: PROCESAR SUBIDA DE FOTO DE PERFIL ---
@app.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if 'user_id' not in session:
        flash("Debes iniciar sesión para cambiar tu foto.", "danger")
        return redirect(url_for('login_page'))

    # 1. Verificar si se envió un archivo
    if 'profile_pic' not in request.files:
        flash('No se seleccionó ningún archivo.', 'warning')
        return redirect(url_for('profile'))
        
    file = request.files['profile_pic']

    # 2. Verificar si el nombre del archivo está vacío (no se seleccionó nada)
    if file.filename == '':
        flash('No seleccionaste ningún archivo.', 'warning')
        return redirect(url_for('profile'))

    # 3. Validar extensión y guardar
    if file and allowed_file(file.filename):
        # Generar un nombre de archivo seguro y único
        filename_base = secure_filename(file.filename)
        extension = filename_base.rsplit('.', 1)[1].lower()
        # Usamos el ID de usuario + UUID para asegurar unicidad y evitar colisiones
        unique_filename = f"user_{session['user_id']}_{uuid.uuid4().hex}.{extension}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        try:
            # Antes de guardar, eliminar la foto anterior si existe
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
                         print(f"Foto anterior eliminada: {old_filepath}")

            # Guardar el nuevo archivo
            file.save(filepath)
            
            # Actualizar la base de datos
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE USUARIOS SET FOTO_PERFIL = :filename WHERE ID = :user_id", 
                               filename=unique_filename, user_id=session['user_id'])
                conn.commit()
                cursor.close()
                conn.close()
                flash('Foto de perfil actualizada correctamente.', 'success')
            else:
                 flash('Error de conexión al actualizar la base de datos.', 'danger')

        except RequestEntityTooLarge:
             flash('El archivo es demasiado grande (Máximo 2MB).', 'danger')
        except Exception as e:
            flash(f'Ocurrió un error al subir el archivo: {e}', 'danger')
            traceback.print_exc() # Para ver el error en la consola de Flask
            
        return redirect(url_for('profile'))
    else:
        flash('Tipo de archivo no permitido (solo png, jpg, jpeg, gif).', 'danger')
        return redirect(url_for('profile'))
    
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
    # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page'))
    usuario = request.form.get('usuario', '').strip()
    contrasena = request.form.get('contrasena', '').strip()
    if not usuario or not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", usuario):
        flash("El nombre de usuario es obligatorio y solo debe contener letras y espacios.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    if not contrasena:
        flash("La contraseña es obligatoria.", "warning"); return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = insertar_auxiliar_db(usuario, contrasena)
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/modificar_auxiliar', methods=['POST'])
def modificar_auxiliar():
    # ... (código sin cambios)
    if 'user_id' not in session or session.get('user_rol') != 'admin': return redirect(url_for('login_page'))
    id_usuario = request.form.get('id_usuario')
    usuario = request.form.get('usuario', '').strip()
    contrasena = request.form.get('contrasena', '').strip()
    if not id_usuario:
         flash("Falta el ID del usuario a modificar.", "danger"); return redirect(url_for('gestion_auxiliares'))
    if not usuario or not re.match(r"^[a-zA-Z\sñÑáéíóúÁÉÍÓÚ]+$", usuario):
        flash("El nombre de usuario es obligatorio y solo debe contener letras y espacios.", "warning")
        return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = actualizar_auxiliar_db(id_usuario, usuario, contrasena)
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
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, USUARIO FROM USUARIOS WHERE TIPO = 1 ORDER BY USUARIO")
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener auxiliares: {e}")
        traceback.print_exc()
        return []
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def insertar_auxiliar_db(usuario, contrasena):
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        if cursor.fetchone()[0] > 0:
            return False, f"El usuario '{usuario}' ya existe."
        cursor.execute("SELECT NVL(MAX(ID), 0) + 1 FROM USUARIOS")
        nuevo_id_usuario = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO USUARIOS (ID, USUARIO, PASSWORD, TIPO) VALUES (:id_usr, :usr, :pwd, 1)",
            id_usr=nuevo_id_usuario,
            usr=usuario,
            pwd=contrasena
        )
        conn.commit()
        return True, f"Auxiliar '{usuario}' agregado (ID: {nuevo_id_usuario})."
    except Exception as e:
        conn.rollback()
        print(f"Error al insertar auxiliar '{usuario}': {e}")
        traceback.print_exc()
        return False, "Error interno al agregar."
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

def actualizar_auxiliar_db(id_usuario, usuario, contrasena):
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE USUARIO = :usr AND ID != :id_usr", usr=usuario, id_usr=id_usuario)
        if cursor.fetchone()[0] > 0: return False, f"El nombre '{usuario}' ya está en uso."
        if contrasena:
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr, PASSWORD = :pwd WHERE ID = :id_usr", usr=usuario, pwd=contrasena, id_usr=id_usuario)
        else:
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr WHERE ID = :id_usr", usr=usuario, id_usr=id_usuario)
        conn.commit()
        return (True, "Auxiliar actualizado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except Exception as e:
        conn.rollback()
        print(f"Error al actualizar auxiliar ID {id_usuario}: {e}")
        traceback.print_exc()
        return False, "Error interno al actualizar."
    finally:
        if conn:
             if 'cursor' in locals() and cursor: cursor.close()
             conn.close()

def eliminar_auxiliar_db(id_usuario):
     # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM USUARIOS WHERE ID = :id_usr AND TIPO = 1", id_usr=id_usuario)
        conn.commit()
        return (True, "Auxiliar eliminado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except cx_Oracle.IntegrityError:
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
    # ... (código sin cambios)
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM DETALLE_PRESTAMO")
        cursor.execute("DELETE FROM REGISTRO_DANOS")
        cursor.execute("DELETE FROM PRESTAMOS")
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
    except cx_Oracle.IntegrityError:
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
        id_prestamo_var = cursor.var(cx_Oracle.NUMBER)
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


if __name__ == "__main__":
    app.run(debug=True)