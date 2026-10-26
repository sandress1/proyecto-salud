**1. ++Funcionalidades**++ 

El chatbot clínico de WhatsApp permite realizar las siguientes operaciones:

1. Validación de pacientes mediante número de documento de identidad y fecha de nacimiento en formato AAAA/MM/DD.
2. Agendamiento de citas médicas, seleccionando especialidad, médico y horario disponible.
3. Modificación de citas médicas existentes, permitiendo seleccionar un nuevo horario.
4. Cancelación de citas médicas y liberación del horario correspondiente.
5. Registro de peticiones, quejas, reclamos, sugerencias y comentarios (PQR) con su radicado y estado actual.  


**2. ++Tecnologías usadas**++

- Python: El lenguaje de programación principal.
- Flask: El servidor y el que realiza el procesamiento de las solicitudes del chatbot
- PostgreSQL: El almacenamiento de pacientes, médicos, especialidades, horarios, citas y PQR.
- Flask-SQLAlchemy: Conexión y ejecución de operaciones en la base de datos.
- Twilio WhatsApp Sandbox: Comunicación del chatbot mediante WhatsApp.
- ngrok: Conexión del servidor local con Twilio.
- Git: Control de versiones del proyecto.
- GitHub: Almacenamiento y respaldo del código.  


**3 ++Seguridad y funcionamiento del sistema**++

El proyecto incorpora las siguientes características:

- Validación de pacientes mediante número de documento de identidad y fecha de nacimiento antes de acceder al menú.
-  Uso de consultas  para realizar operaciones en PostgreSQL.
- Tablas en la base de datos para el agendamiento, modificación y cancelación de citas médicas.
- Protección contra la reserva simultánea de un mismo horario mediante restricciones y bloqueos en PostgreSQL.
- Verificación de que las citas médicas pertenecen al paciente autenticado.
- Almacenamiento de las credenciales de conexión mediante variables de entorno.
- Gestión de los estados de conversación mediante la tabla de sesiones de chat.
- Limpieza de los datos temporales.
- Modo debugging de Flask desactivado para mejorar la seguridad del chatbot y evitar exponer información interna del sistema.  


**4. ++Limitaciones del proyecto**++

Se utilizan pacientes y datos ficticios pero realistas para las pruebas y demostraciones.

El chatbot usa un sistema por medio de Twilio WhatsApp Sandbox y un servidor Flask ejecutado de manera local.
