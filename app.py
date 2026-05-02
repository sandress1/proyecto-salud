import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


def send_message(text):
    response = MessagingResponse()
    response.message(text)
    return str(response)


def get_session(whatsapp_number):
    result = db.session.execute(
        db.text("""
            SELECT *
            FROM chat_sessions
            WHERE whatsapp_number = :whatsapp_number
        """),
        {"whatsapp_number": whatsapp_number}
    ).mappings().first()

    if result:
        return result

    db.session.execute(
        db.text("""
            INSERT INTO chat_sessions (whatsapp_number, current_step, temp_data)
            VALUES (:whatsapp_number, 'ASK_ID', '{}'::jsonb)
        """),
        {"whatsapp_number": whatsapp_number}
    )
    db.session.commit()

    return db.session.execute(
        db.text("""
            SELECT *
            FROM chat_sessions
            WHERE whatsapp_number = :whatsapp_number
        """),
        {"whatsapp_number": whatsapp_number}
    ).mappings().first()


def update_session(whatsapp_number, current_step=None, selected_option=None, patient_id=None, temp_data=None):
    db.session.execute(
        db.text("""
            UPDATE chat_sessions
            SET
                current_step = COALESCE(:current_step, current_step),
                selected_option = COALESCE(:selected_option, selected_option),
                patient_id = COALESCE(:patient_id, patient_id),
                temp_data = COALESCE(CAST(:temp_data AS jsonb), temp_data),
                updated_at = CURRENT_TIMESTAMP
            WHERE whatsapp_number = :whatsapp_number
        """),
        {
            "whatsapp_number": whatsapp_number,
            "current_step": current_step,
            "selected_option": selected_option,
            "patient_id": patient_id,
            "temp_data": temp_data,
        }
    )
    db.session.commit()


def reset_session(whatsapp_number):
    db.session.execute(
        db.text("""
            UPDATE chat_sessions
            SET
                current_step = 'ASK_ID',
                selected_option = NULL,
                patient_id = NULL,
                temp_data = '{}'::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE whatsapp_number = :whatsapp_number
        """),
        {"whatsapp_number": whatsapp_number}
    )
    db.session.commit()


def main_menu(patient_name):
    return (
        f"Validación exitosa. Bienvenido/a, {patient_name}.\n\n"
        "Seleccione una opción:\n\n"
        "1. Agendar cita médica\n"
        "2. Modificar cita médica\n"
        "3. Cancelar cita médica\n"
        "4. Registrar PQR o comentario\n\n"
        "Responda con el número de la opción."
    )


@app.route("/")
def home():
    return "Medical WhatsApp Bot is running"


@app.route("/db-test")
def db_test():
    try:
        result = db.session.execute(db.text("SELECT COUNT(*) FROM patients;"))
        patient_count = result.scalar()
        return f"Database connection successful. Patients found: {patient_count}"
    except Exception as error:
        return f"Database connection failed: {str(error)}"


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_message = request.form.get("Body", "").strip()
    sender_number = request.form.get("From", "")

    print("Mensaje recibido:", incoming_message)
    print("Desde:", sender_number)

    session = get_session(sender_number)
    current_step = session["current_step"]

    if incoming_message.lower() in ["hola", "hello", "inicio", "menu", "menú", "reiniciar"]:
        reset_session(sender_number)
        return send_message(
            "Bienvenido/a al sistema de citas médicas por WhatsApp.\n\n"
            "Para continuar, digite su número de documento."
        )

    if current_step == "ASK_ID":
        patient = db.session.execute(
            db.text("""
                SELECT id, full_name, personal_id
                FROM patients
                WHERE personal_id = :personal_id
            """),
            {"personal_id": incoming_message}
        ).mappings().first()

        if not patient:
            return send_message(
                "No encontramos un paciente registrado con ese documento.\n\n"
                "Verifique el número e inténtelo nuevamente."
            )

        update_session(
            sender_number,
            current_step="ASK_BIRTH_DATE",
            temp_data=f'{{"personal_id": "{incoming_message}"}}'
        )

        return send_message(
            "Documento encontrado.\n\n"
            "Ahora digite su fecha de expedición del documento en formato AAAA/MM/DD.\n\n"
            "Ejemplo: 1995/04/12"
        )

    if current_step == "ASK_BIRTH_DATE":
        try:
            birth_date = datetime.strptime(incoming_message, "%Y/%m/%d").date()
        except ValueError:
            return send_message(
                "Formato de fecha incorrecto.\n\n"
                "Digite la fecha en formato AAAA/MM/DD.\n\n"
                "Ejemplo: 1995/04/12"
            )

        temp_data = session["temp_data"]
        personal_id = temp_data.get("personal_id")

        patient = db.session.execute(
            db.text("""
                SELECT id, full_name
                FROM patients
                WHERE personal_id = :personal_id
                AND birth_date = :birth_date
            """),
            {
                "personal_id": personal_id,
                "birth_date": birth_date
            }
        ).mappings().first()

        if not patient:
            reset_session(sender_number)
            return send_message(
                "La fecha de expedición del documento no coincide con el documento registrado.\n\n"
                "Por seguridad, debe iniciar nuevamente.\n\n"
                "Digite su número de documento."
            )

        update_session(
            sender_number,
            current_step="MAIN_MENU",
            patient_id=patient["id"],
            temp_data="{}"
        )

        return send_message(main_menu(patient["full_name"]))

    if current_step == "MAIN_MENU":
        if incoming_message == "1":
            update_session(sender_number, current_step="BOOK_START", selected_option="book")
            return send_message(
                "Ha seleccionado: Agendar cita médica.\n\n"
                "Este flujo se desarrollará en el siguiente día del proyecto."
            )

        if incoming_message == "2":
            update_session(sender_number, current_step="MODIFY_START", selected_option="modify")
            return send_message(
                "Ha seleccionado: Modificar cita médica.\n\n"
                "Este flujo se desarrollará más adelante."
            )

        if incoming_message == "3":
            update_session(sender_number, current_step="CANCEL_START", selected_option="cancel")
            return send_message(
                "Ha seleccionado: Cancelar cita médica.\n\n"
                "Este flujo se desarrollará más adelante."
            )

        if incoming_message == "4":
            update_session(sender_number, current_step="PQR_START", selected_option="feedback")
            return send_message(
                "Ha seleccionado: Registrar PQR o comentario.\n\n"
                "Este flujo se desarrollará más adelante."
            )

        return send_message(
            "Opción no válida.\n\n"
            "Seleccione una opción del menú:\n\n"
            "1. Agendar cita médica\n"
            "2. Modificar cita médica\n"
            "3. Cancelar cita médica\n"
            "4. Registrar PQR o comentario"
        )

    return send_message(
        "No entendí su mensaje.\n\n"
        "Escriba 'hola' para iniciar nuevamente."
    )


if __name__ == "__main__":
    app.run(debug=True)