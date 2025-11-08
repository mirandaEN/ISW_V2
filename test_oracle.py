import cx_Oracle

cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")
# Datos de conexión
username = 'JEFE_LAB'         # usuario de Oracle
password = 'jefe123'      # contraseña de Oracle
dsn = 'localhost:1521/XEPDB1'      # service name de base de datos

try:
    # Conectar a la base de datos
    connection = oracledb.connect(username, password, dsn)
    print("¡Conexión exitosa a Oracle!")

    # Crear un cursor para ejecutar consultas
    cursor = connection.cursor()

    # Prueba: listar los usuarios de la tabla usuarios
    cursor.execute("SELECT id_usuario, usuario, tipo FROM usuarios")
    rows = cursor.fetchall()

    print("\nUsuarios registrados en la tabla:")
    for row in rows:
        print(f"ID: {row[0]}, Usuario: {row[1]}, Tipo: {row[2]}")

except oracledb.DatabaseError as e:
    error, = e.args
    print(f"Error al conectar a Oracle: {error.message}")

finally:
    if 'connection' in locals():
        connection.close()
        print("\nConexión cerrada.")
