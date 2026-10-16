import os
from datetime import datetime

import logging
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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



def book_appointment(patient_id, doctor_id, slot_id):
 
    try:
    
        slot = db.session.execute(
            db.text("""
                SELECT id, doctor_id
                FROM slots
                WHERE id = :slot_id
                  AND doctor_id = :doctor_id
                  AND is_available = TRUE
                  AND start_time > CURRENT_TIMESTAMP
                FOR UPDATE
            """),
            {
                "slot_id": slot_id,
                "doctor_id": doctor_id
            }
        ).mappings().first()

        if not slot:
            db.session.rollback()
            return "unavailable", None

        existing = db.session.execute(
            db.text("""
                SELECT id
                FROM appointments
                WHERE slot_id = :slot_id
                  AND status = 'booked'
            """),
            {"slot_id": slot_id}
        ).first()

        if existing:
            db.session.rollback()
            return "unavailable", None

        appointment_id = db.session.execute(
            db.text("""
                INSERT INTO appointments (
                    patient_id,
                    doctor_id,
                    slot_id,
                    status
                )
                VALUES (
                    :patient_id,
                    :doctor_id,
                    :slot_id,
                    'booked'
                )
                RETURNING id
            """),
            {
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "slot_id": slot_id
            }
        ).scalar_one()

        db.session.execute(
            db.text("""
                UPDATE slots
                SET is_available = FALSE
                WHERE id = :slot_id
            """),
            {"slot_id": slot_id}
        )

        db.session.commit()

        return "success", appointment_id

    except IntegrityError:
        db.session.rollback()
        return "unavailable", None

    except SQLAlchemyError:
        db.session.rollback()
        logging.exception("Error al reservar cita")
        return "error", None



def cancel_appointment(patient_id, appointment_id):
    """
    Cancela una cita futura perteneciente al paciente.

    Retorna:
    ("success", appointment_id)
    ("unavailable", None)
    ("error", None)
    """

    try:
    
        slot = db.session.execute(
            db.text("""
                SELECT s.id
                FROM slots s
                JOIN appointments a ON a.slot_id = s.id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND s.start_time > CURRENT_TIMESTAMP
                FOR UPDATE OF s
            """),
            {
                "appointment_id": appointment_id,
                "patient_id": patient_id
            }
        ).mappings().first()

        if not slot:
            db.session.rollback()
            return "unavailable", None
        result = db.session.execute(
            db.text("""
                UPDATE appointments
                SET status = 'cancelled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :appointment_id
                  AND patient_id = :patient_id
                  AND slot_id = :slot_id
                  AND status = 'booked'
                RETURNING id
            """),
            {
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "slot_id": slot["id"]
            }
        ).scalar_one_or_none()

        if result is None:
            db.session.rollback()
            return "unavailable", None

        db.session.execute(
            db.text("""
                UPDATE slots
                SET is_available = TRUE
                WHERE id = :slot_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM appointments
                      WHERE slot_id = :slot_id
                        AND status = 'booked'
                  )
            """),
            {"slot_id": slot["id"]}
        )

    
        db.session.commit()

        return "success", appointment_id

    except SQLAlchemyError:
        db.session.rollback()
        logging.exception("Error al cancelar cita")
        return "error", None



def modify_appointment(
    patient_id,
    appointment_id,
    old_slot_id,
    new_slot_id
):
    """
    Modifica una cita médica en una transacción segura.

    Retorna:
    ("success", appointment_id)
    ("unavailable", None)
    ("error", None)
    """

    try:
      
        appointment = db.session.execute(
            db.text("""
                SELECT a.id, a.doctor_id, a.slot_id
                FROM appointments a
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND a.slot_id = :old_slot_id
                  AND s.start_time > CURRENT_TIMESTAMP
            """),
            {
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "old_slot_id": old_slot_id
            }
        ).mappings().first()

        if not appointment or old_slot_id == new_slot_id:
            db.session.rollback()
            return "unavailable", None

      
        locked_slots = db.session.execute(
            db.text("""
                SELECT id, doctor_id, start_time, is_available
                FROM slots
                WHERE id IN (:old_slot_id, :new_slot_id)
                ORDER BY id
                FOR UPDATE
            """),
            {
                "old_slot_id": old_slot_id,
                "new_slot_id": new_slot_id
            }
        ).mappings().all()

        slots_by_id = {
            slot["id"]: slot for slot in locked_slots
        }

        old_slot = slots_by_id.get(old_slot_id)
        new_slot = slots_by_id.get(new_slot_id)

        if not old_slot or not new_slot:
            db.session.rollback()
            return "unavailable", None

        current_appointment = db.session.execute(
            db.text("""
                SELECT a.id
                FROM appointments a
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND a.slot_id = :old_slot_id
                  AND s.start_time > CURRENT_TIMESTAMP
                FOR UPDATE OF a
            """),
            {
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "old_slot_id": old_slot_id
            }
        ).mappings().first()

        if not current_appointment:
            db.session.rollback()
            return "unavailable", None

        new_slot_is_future = db.session.execute(
            db.text("""
                SELECT start_time > CURRENT_TIMESTAMP
                FROM slots
                WHERE id = :new_slot_id
            """),
            {"new_slot_id": new_slot_id}
        ).scalar()

       
        if (
            new_slot["doctor_id"] != appointment["doctor_id"]
            or not new_slot["is_available"]
            or not new_slot_is_future
        ):
            db.session.rollback()
            return "unavailable", None

        existing = db.session.execute(
            db.text("""
                SELECT id
                FROM appointments
                WHERE slot_id = :new_slot_id
                  AND status = 'booked'
            """),
            {"new_slot_id": new_slot_id}
        ).first()

        if existing:
            db.session.rollback()
            return "unavailable", None

        result = db.session.execute(
            db.text("""
                UPDATE appointments
                SET slot_id = :new_slot_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :appointment_id
                  AND patient_id = :patient_id
                  AND slot_id = :old_slot_id
                  AND status = 'booked'
                RETURNING id
            """),
            {
                "new_slot_id": new_slot_id,
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "old_slot_id": old_slot_id
            }
        ).scalar_one_or_none()

        if result is None:
            db.session.rollback()
            return "unavailable", None

        db.session.execute(
            db.text("""
                UPDATE slots
                SET is_available = FALSE
                WHERE id = :new_slot_id
            """),
            {"new_slot_id": new_slot_id}
        )

        db.session.execute(
            db.text("""
                UPDATE slots
                SET is_available = TRUE
                WHERE id = :old_slot_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM appointments
                      WHERE slot_id = :old_slot_id
                        AND status = 'booked'
                  )
            """),
            {"old_slot_id": old_slot_id}
        )

        db.session.commit()

        return "success", appointment_id

    except IntegrityError:
        db.session.rollback()
        return "unavailable", None

    except SQLAlchemyError:
        db.session.rollback()
        logging.exception("Error al modificar cita")
        return "error", None







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
            specialties = db.session.execute(
                db.text("""
                    SELECT id, name
                    FROM specialties
                    WHERE is_active = TRUE
                    ORDER BY id
                """)
            ).mappings().all()

            if not specialties:
                return send_message(
                    "En este momento no hay especialidades disponibles.\n\n"
                    "Por favor, intente más tarde."
                )

            options_text = "Ha seleccionado: Agendar cita médica.\n\n"
            options_text += "Seleccione una especialidad:\n\n"

            temp_specialties = {}

            for index, specialty in enumerate(specialties, start=1):
                options_text += f"{index}. {specialty['name']}\n"
                temp_specialties[str(index)] = specialty["id"]

            update_session(
                sender_number,
                current_step="BOOK_SELECT_SPECIALTY",
                selected_option="book",
                temp_data=str(temp_specialties).replace("'", '"')
            )

            return send_message(options_text)

    
    
        if incoming_message == "2":

            appointments = db.session.execute(
                db.text("""
                    SELECT
                        a.id,
                        d.full_name AS doctor_name,
                        sp.name AS specialty_name,
                        s.start_time
                    FROM appointments a
                    JOIN doctors d ON d.id = a.doctor_id
                    JOIN specialties sp ON sp.id = d.specialty_id
                    JOIN slots s ON s.id = a.slot_id
                    WHERE a.patient_id = :patient_id
                      AND a.status = 'booked'
                      AND s.start_time > CURRENT_TIMESTAMP
                    ORDER BY s.start_time, a.id
                """),
                {"patient_id": session["patient_id"]}
            ).mappings().all()

            if not appointments:
                return send_message(
                    "No tiene citas médicas activas "
                    "disponibles para modificar.\n\n"
                    "Escriba 'hola' para iniciar nuevamente."
                )

            import json

            options_text = (
                "Ha seleccionado: Modificar cita médica.\n\n"
                "Estas son sus citas activas:\n\n"
            )

            appointments_map = {}

            for index, appointment in enumerate(appointments, start=1):
                date_text = appointment["start_time"].strftime("%d/%m/%Y")
                time_text = appointment["start_time"].strftime("%H:%M")

                options_text += (
                    f"{index}. {appointment['specialty_name']}\n"
                    f"Médico: {appointment['doctor_name']}\n"
                    f"Fecha: {date_text}\n"
                    f"Hora: {time_text}\n"
                    f"Número de cita: {appointment['id']}\n\n"
                )

                appointments_map[str(index)] = appointment["id"]

            update_session(
                sender_number,
                current_step="MODIFY_SELECT_APPOINTMENT",
                selected_option="modify",
                temp_data=json.dumps({
                    "appointments": appointments_map
                })
            )

            return send_message(
                options_text
                + "Seleccione el número de la cita que desea modificar."
            )



        if incoming_message == "3":

            appointments = db.session.execute(
                db.text("""
                    SELECT
                        a.id,
                        d.full_name AS doctor_name,
                        sp.name AS specialty_name,
                        s.start_time
                    FROM appointments a
                    JOIN doctors d ON d.id = a.doctor_id
                    JOIN specialties sp ON sp.id = d.specialty_id
                    JOIN slots s ON s.id = a.slot_id
                    WHERE a.patient_id = :patient_id
                      AND a.status = 'booked'
                      AND s.start_time > CURRENT_TIMESTAMP
                    ORDER BY s.start_time, a.id
                """),
                {"patient_id": session["patient_id"]}
            ).mappings().all()

            if not appointments:
                return send_message(
                    "No tiene citas médicas activas "
                    "pendientes por cancelar.\n\n"
                    "Escriba 'hola' para volver al menú."
                )

            import json

            options_text = (
                "Ha seleccionado: Cancelar cita médica.\n\n"
                "Estas son sus citas activas:\n\n"
            )

            appointments_map = {}

            for index, appointment in enumerate(appointments, start=1):
                date_text = appointment["start_time"].strftime("%d/%m/%Y")
                time_text = appointment["start_time"].strftime("%H:%M")

                options_text += (
                    f"{index}. {appointment['specialty_name']}\n"
                    f"Médico: {appointment['doctor_name']}\n"
                    f"Fecha: {date_text}\n"
                    f"Hora: {time_text}\n"
                    f"Número de cita: {appointment['id']}\n\n"
                )

                appointments_map[str(index)] = appointment["id"]

            new_temp_data = {
                "appointments": appointments_map
            }

            update_session(
                sender_number,
                current_step="CANCEL_SELECT_APPOINTMENT",
                selected_option="cancel",
                temp_data=json.dumps(new_temp_data)
            )

            return send_message(
                options_text
                + "Seleccione el número de la cita que desea cancelar."
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



    if current_step == "BOOK_SELECT_SPECIALTY":
        temp_data = session["temp_data"]

        selected_specialty_id = temp_data.get(incoming_message)

        if not selected_specialty_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione una especialidad escribiendo solo el número correspondiente."
            )

        specialty = db.session.execute(
            db.text("""
                SELECT id, name
                FROM specialties
                WHERE id = :specialty_id
            """),
            {"specialty_id": selected_specialty_id}
        ).mappings().first()

        doctors = db.session.execute(
            db.text("""
                SELECT id, full_name
                FROM doctors
                WHERE specialty_id = :specialty_id
                AND is_active = TRUE
                ORDER BY id
            """),
            {"specialty_id": selected_specialty_id}
        ).mappings().all()

        if not doctors:
            return send_message(
                f"La especialidad {specialty['name']} no tiene médicos disponibles en este momento.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        options_text = f"Especialidad seleccionada: {specialty['name']}.\n\n"
        options_text += "Seleccione un médico:\n\n"

        temp_doctors = {
            "specialty_id": selected_specialty_id,
            "doctors": {}
        }

        for index, doctor in enumerate(doctors, start=1):
            options_text += f"{index}. {doctor['full_name']}\n"
            temp_doctors["doctors"][str(index)] = doctor["id"]

        update_session(
            sender_number,
            current_step="BOOK_SELECT_DOCTOR",
            temp_data=str(temp_doctors).replace("'", '"')
        )

        return send_message(options_text)


    if current_step == "BOOK_SELECT_DOCTOR":
        temp_data = session["temp_data"]

        doctors_map = temp_data.get("doctors", {})
        selected_doctor_id = doctors_map.get(incoming_message)

        if not selected_doctor_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione un médico escribiendo solo el número correspondiente."
            )

        doctor = db.session.execute(
            db.text("""
                SELECT id, full_name
                FROM doctors
                WHERE id = :doctor_id
                AND is_active = TRUE
            """),
            {"doctor_id": selected_doctor_id}
        ).mappings().first()
        if not doctor:
            return send_message(
                "El médico seleccionado ya no está disponible.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )
        slots = db.session.execute(
            db.text("""
                SELECT id, start_time, end_time
                FROM slots
                WHERE doctor_id = :doctor_id
                AND is_available = TRUE
                AND start_time > CURRENT_TIMESTAMP
                ORDER BY start_time, id
                LIMIT 10
            """),
            {"doctor_id": selected_doctor_id}
        ).mappings().all()

        if not slots:
            return send_message(
                f"Médico seleccionado: {doctor['full_name']}.\n\n"
                "No hay horarios disponibles para este médico.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        import json
        options_text = (
            f"Médico seleccionado: {doctor['full_name']}.\n\n"
            "Horarios disponibles:\n\n"
        )

        slots_map = {}

        for index, slot in enumerate(slots, start=1):
            date_text = slot["start_time"].strftime("%d/%m/%Y")
            time_text = slot["start_time"].strftime("%H:%M")

            options_text += f"{index}. {date_text} - {time_text}\n"
            slots_map[str(index)] = slot["id"]

        options_text += (
            "\nSeleccione el número del horario que desea."
        )
        new_temp_data = {
            "specialty_id": temp_data.get("specialty_id"),
            "doctor_id": selected_doctor_id,
            "slots": slots_map
        }
      
        update_session(
            sender_number,
            current_step="BOOK_SELECT_SLOT",
            temp_data=json.dumps(new_temp_data)
        )


        update_session(
            sender_number,
            current_step="BOOK_SELECT_SLOT",
            temp_data=json.dumps(new_temp_data)
        )

        return send_message(options_text)

    if current_step == "BOOK_SELECT_SLOT":
        temp_data = session["temp_data"]

        slots_map = temp_data.get("slots", {})
        selected_slot_id = slots_map.get(incoming_message)

        if not selected_slot_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione un horario escribiendo solo "
                "el número correspondiente."
            )

        slot = db.session.execute(
            db.text("""
                SELECT id, doctor_id, start_time, end_time
                FROM slots
                WHERE id = :slot_id
                  AND doctor_id = :doctor_id
                  AND is_available = TRUE
                  AND start_time > CURRENT_TIMESTAMP
            """),
            {
                "slot_id": selected_slot_id,
                "doctor_id": temp_data.get("doctor_id")
            }
        ).mappings().first()

        if not slot:
            return send_message(
                "El horario seleccionado ya no está disponible.\n\n"
                "Escriba 'hola' para consultar nuevamente."
            )

        import json

        new_temp_data = {
            "specialty_id": temp_data.get("specialty_id"),
            "doctor_id": temp_data.get("doctor_id"),
            "slot_id": slot["id"]
        }

        update_session(
            sender_number,
            current_step="BOOK_SLOT_SELECTED",
            temp_data=json.dumps(new_temp_data)
        )

      

        details = db.session.execute(
            db.text("""
                SELECT d.full_name AS doctor_name,
                       sp.name AS specialty_name
                FROM doctors d
                JOIN specialties sp
                    ON sp.id = d.specialty_id
                WHERE d.id = :doctor_id
            """),
            {"doctor_id": temp_data.get("doctor_id")}
        ).mappings().first()

        date_text = slot["start_time"].strftime("%d/%m/%Y")
        time_text = slot["start_time"].strftime("%H:%M")

        return send_message(
            "Resumen de su cita médica:\n\n"
            f"Especialidad: {details['specialty_name']}\n"
            f"Médico: {details['doctor_name']}\n"
            f"Fecha: {date_text}\n"
            f"Hora: {time_text}\n\n"
            "¿Desea confirmar esta cita?\n\n"
            "1. Sí, confirmar cita\n"
            "2. No, cancelar proceso\n\n"
            "Responda con 1 o 2."
        )





        return send_message(options_text)

    



    if current_step == "BOOK_SLOT_SELECTED":

        if incoming_message == "2":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="book",
                temp_data="{}"
            )

            return send_message(
                "El proceso de agendamiento fue cancelado.\n\n"
                "No se ha reservado ninguna cita.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        if incoming_message != "1":
            return send_message(
                "Opción no válida.\n\n"
                "1. Sí, confirmar cita\n"
                "2. No, cancelar proceso"
            )

        temp_data = session["temp_data"]

        patient_id = session["patient_id"]
        doctor_id = temp_data.get("doctor_id")
        slot_id = temp_data.get("slot_id")

        if not patient_id or not doctor_id or not slot_id:
            reset_session(sender_number)
            return send_message(
                "No fue posible recuperar los datos de su cita.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        status, appointment_id = book_appointment(
            patient_id,
            doctor_id,
            slot_id
        )

        if status == "unavailable":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="book",
                temp_data="{}"
            )
            return send_message(
                "Lo sentimos. El horario seleccionado "
                "ya no está disponible.\n\n"
                "No se realizó ninguna reserva.\n\n"
                "Escriba 'hola' para elegir otro horario."
            )

        if status == "error":
            return send_message(
                "Ocurrió un error al intentar agendar su cita.\n\n"
                "No se pudo confirmar la reserva.\n"
                "Por favor, intente nuevamente."
            )

        appointment = db.session.execute(
            db.text("""
                SELECT a.id,
                       d.full_name AS doctor_name,
                       sp.name AS specialty_name,
                       s.start_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN specialties sp ON sp.id = d.specialty_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
            """),
            {"appointment_id": appointment_id}
        ).mappings().first()

        date_text = appointment["start_time"].strftime("%d/%m/%Y")
        time_text = appointment["start_time"].strftime("%H:%M")

        update_session(
            sender_number,
            current_step="MAIN_MENU",
            selected_option="book",
            temp_data="{}"
        )

        return send_message(
            "¡Cita médica agendada exitosamente!\n\n"
            f"Número de cita: {appointment_id}\n"
            f"Especialidad: {appointment['specialty_name']}\n"
            f"Médico: {appointment['doctor_name']}\n"
            f"Fecha: {date_text}\n"
            f"Hora: {time_text}\n\n"
            "Su cita ha quedado confirmada.\n\n"
            "Escriba 'hola' para iniciar nuevamente."
        )



    if current_step == "CANCEL_SELECT_APPOINTMENT":

        temp_data = session["temp_data"]

        appointments_map = temp_data.get("appointments", {})
        selected_appointment_id = appointments_map.get(incoming_message)

        if not selected_appointment_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione una cita escribiendo solo "
                "el número correspondiente."
            )

        appointment = db.session.execute(
            db.text("""
                SELECT
                    a.id,
                    d.full_name AS doctor_name,
                    sp.name AS specialty_name,
                    s.start_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN specialties sp ON sp.id = d.specialty_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND s.start_time > CURRENT_TIMESTAMP
            """),
            {
                "appointment_id": selected_appointment_id,
                "patient_id": session["patient_id"]
            }
        ).mappings().first()

        if not appointment:
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="cancel",
                temp_data="{}"
            )

            return send_message(
                "La cita seleccionada ya no está disponible "
                "para cancelación.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        import json

        new_temp_data = {
            "appointment_id": appointment["id"]
        }

        update_session(
            sender_number,
            current_step="CANCEL_CONFIRM",
            selected_option="cancel",
            temp_data=json.dumps(new_temp_data)
        )

        date_text = appointment["start_time"].strftime("%d/%m/%Y")
        time_text = appointment["start_time"].strftime("%H:%M")

        return send_message(
            "Ha seleccionado la siguiente cita:\n\n"
            f"Número de cita: {appointment['id']}\n"
            f"Especialidad: {appointment['specialty_name']}\n"
            f"Médico: {appointment['doctor_name']}\n"
            f"Fecha: {date_text}\n"
            f"Hora: {time_text}\n\n"
            "¿Está seguro de que desea cancelar esta cita?\n\n"
            "1. Sí, cancelar cita\n"
            "2. No, conservar cita\n\n"
            "Responda con 1 o 2."
        )



    if current_step == "CANCEL_CONFIRM":

        if incoming_message == "2":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="cancel",
                temp_data="{}"
            )

            return send_message(
                "Ha decidido conservar su cita médica.\n\n"
                "Su cita continúa confirmada.\n\n"
                "Escriba 'hola' para volver al menú."
            )

        if incoming_message != "1":
            return send_message(
                "Opción no válida.\n\n"
                "1. Sí, cancelar cita\n"
                "2. No, conservar cita"
            )

        temp_data = session["temp_data"]
        appointment_id = temp_data.get("appointment_id")
        patient_id = session["patient_id"]

        if not appointment_id or not patient_id:
            reset_session(sender_number)

            return send_message(
                "No fue posible recuperar los datos "
                "de la cita.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        status, cancelled_id = cancel_appointment(
            patient_id,
            appointment_id
        )

        if status == "unavailable":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="cancel",
                temp_data="{}"
            )

            return send_message(
                "La cita ya fue cancelada o no está "
                "disponible para cancelación.\n\n"
                "No se realizaron cambios.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        if status == "error":
            return send_message(
                "Ocurrió un error al intentar cancelar "
                "su cita médica.\n\n"
                "Por favor, intente nuevamente."
            )

        update_session(
            sender_number,
            current_step="MAIN_MENU",
            selected_option="cancel",
            temp_data="{}"
        )

        return send_message(
            "¡Cita médica cancelada exitosamente!\n\n"
            f"Número de cita: {cancelled_id}\n\n"
            "El horario ha quedado disponible "
            "para otros pacientes.\n\n"
            "Escriba 'hola' para volver al menú."
        )



    if current_step == "MODIFY_SELECT_APPOINTMENT":

        temp_data = session["temp_data"]
        appointments_map = temp_data.get("appointments", {})

        selected_appointment_id = appointments_map.get(incoming_message)

        if not selected_appointment_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione una cita escribiendo solo "
                "el número correspondiente."
            )

        appointment = db.session.execute(
            db.text("""
                SELECT
                    a.id,
                    a.doctor_id,
                    a.slot_id,
                    d.full_name AS doctor_name,
                    sp.name AS specialty_name,
                    s.start_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN specialties sp ON sp.id = d.specialty_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND s.start_time > CURRENT_TIMESTAMP
            """),
            {
                "appointment_id": selected_appointment_id,
                "patient_id": session["patient_id"]
            }
        ).mappings().first()

        if not appointment:
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="modify",
                temp_data="{}"
            )

            return send_message(
                "La cita seleccionada ya no está "
                "disponible para modificación.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        slots = db.session.execute(
            db.text("""
                SELECT id, start_time, end_time
                FROM slots
                WHERE doctor_id = :doctor_id
                  AND is_available = TRUE
                  AND start_time > CURRENT_TIMESTAMP
                  AND id <> :current_slot_id
                ORDER BY start_time, id
                LIMIT 10
            """),
            {
                "doctor_id": appointment["doctor_id"],
                "current_slot_id": appointment["slot_id"]
            }
        ).mappings().all()

        if not slots:
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="modify",
                temp_data="{}"
            )

            return send_message(
                "No hay otros horarios disponibles "
                "para este médico.\n\n"
                "Su cita actual permanece confirmada.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        import json

        options_text = (
            "Ha seleccionado modificar la siguiente cita:\n\n"
            f"Número de cita: {appointment['id']}\n"
            f"Especialidad: {appointment['specialty_name']}\n"
            f"Médico: {appointment['doctor_name']}\n"
            f"Fecha actual: "
            f"{appointment['start_time'].strftime('%d/%m/%Y')}\n"
            f"Hora actual: "
            f"{appointment['start_time'].strftime('%H:%M')}\n\n"
            "Horarios disponibles para cambiar su cita:\n\n"
        )

        slots_map = {}

        for index, slot in enumerate(slots, start=1):
            date_text = slot["start_time"].strftime("%d/%m/%Y")
            time_text = slot["start_time"].strftime("%H:%M")

            options_text += f"{index}. {date_text} - {time_text}\n"

            slots_map[str(index)] = slot["id"]

        options_text += (
            "\nSeleccione el número del nuevo horario."
        )

        new_temp_data = {
            "appointment_id": appointment["id"],
            "doctor_id": appointment["doctor_id"],
            "old_slot_id": appointment["slot_id"],
            "slots": slots_map
        }

        update_session(
            sender_number,
            current_step="MODIFY_SELECT_SLOT",
            selected_option="modify",
            temp_data=json.dumps(new_temp_data)
        )

        return send_message(options_text)



    if current_step == "MODIFY_SELECT_SLOT":

        temp_data = session["temp_data"]
        slots_map = temp_data.get("slots", {})

        selected_slot_id = slots_map.get(incoming_message)

        if not selected_slot_id:
            return send_message(
                "Opción no válida.\n\n"
                "Seleccione un nuevo horario escribiendo "
                "solo el número correspondiente."
            )

        appointment = db.session.execute(
            db.text("""
                SELECT
                    a.id,
                    a.doctor_id,
                    a.slot_id,
                    s.start_time AS old_start_time,
                    d.full_name AS doctor_name,
                    sp.name AS specialty_name
                FROM appointments a
                JOIN slots s ON s.id = a.slot_id
                JOIN doctors d ON d.id = a.doctor_id
                JOIN specialties sp ON sp.id = d.specialty_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
                  AND a.status = 'booked'
                  AND s.start_time > CURRENT_TIMESTAMP
            """),
            {
                "appointment_id": temp_data.get("appointment_id"),
                "patient_id": session["patient_id"]
            }
        ).mappings().first()

        if not appointment:
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="modify",
                temp_data="{}"
            )

            return send_message(
                "La cita original ya no está disponible "
                "para modificación.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        new_slot = db.session.execute(
            db.text("""
                SELECT id, doctor_id, start_time
                FROM slots
                WHERE id = :slot_id
                  AND doctor_id = :doctor_id
                  AND is_available = TRUE
                  AND start_time > CURRENT_TIMESTAMP
            """),
            {
                "slot_id": selected_slot_id,
                "doctor_id": appointment["doctor_id"]
            }
        ).mappings().first()

        if not new_slot:
            return send_message(
                "El nuevo horario seleccionado "
                "ya no está disponible.\n\n"
                "Escriba 'hola' para consultar nuevamente."
            )

        import json

        update_session(
            sender_number,
            current_step="MODIFY_CONFIRM",
            selected_option="modify",
            temp_data=json.dumps({
                "appointment_id": appointment["id"],
                "doctor_id": appointment["doctor_id"],
                "old_slot_id": appointment["slot_id"],
                "new_slot_id": new_slot["id"]
            })
        )

        old_date = appointment["old_start_time"].strftime("%d/%m/%Y")
        old_time = appointment["old_start_time"].strftime("%H:%M")

        new_date = new_slot["start_time"].strftime("%d/%m/%Y")
        new_time = new_slot["start_time"].strftime("%H:%M")

        return send_message(
            "Resumen de modificación de cita médica:\n\n"
            f"Número de cita: {appointment['id']}\n"
            f"Especialidad: {appointment['specialty_name']}\n"
            f"Médico: {appointment['doctor_name']}\n\n"
            f"Horario actual: {old_date} - {old_time}\n"
            f"Nuevo horario: {new_date} - {new_time}\n\n"
            "¿Desea confirmar este cambio?\n\n"
            "1. Sí, confirmar modificación\n"
            "2. No, conservar mi cita actual\n\n"
            "Su cita todavía NO ha sido modificada."
        )



    if current_step == "MODIFY_CONFIRM":

        if incoming_message == "2":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="modify",
                temp_data="{}"
            )

            return send_message(
                "Ha decidido conservar su cita actual.\n\n"
                "No se realizaron modificaciones.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        if incoming_message != "1":
            return send_message(
                "Opción no válida.\n\n"
                "1. Sí, confirmar modificación\n"
                "2. No, conservar mi cita actual"
            )

        temp_data = session["temp_data"]

        patient_id = session["patient_id"]
        appointment_id = temp_data.get("appointment_id")
        old_slot_id = temp_data.get("old_slot_id")
        new_slot_id = temp_data.get("new_slot_id")

        if not all([
            patient_id,
            appointment_id,
            old_slot_id,
            new_slot_id
        ]):
            reset_session(sender_number)

            return send_message(
                "No fue posible recuperar los datos "
                "de la modificación.\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        status, modified_id = modify_appointment(
            patient_id,
            appointment_id,
            old_slot_id,
            new_slot_id
        )

        if status == "unavailable":
            update_session(
                sender_number,
                current_step="MAIN_MENU",
                selected_option="modify",
                temp_data="{}"
            )

            return send_message(
                "No fue posible modificar su cita.\n\n"
                "El horario seleccionado ya no está "
                "disponible o la cita original cambió.\n\n"
                "No se realizó la modificación.\n\n"
                "Escriba 'hola' para consultar "
                "otros horarios."
            )

        if status == "error":
            return send_message(
                "Ocurrió un error al modificar su cita.\n\n"
                "No se pudo confirmar el cambio.\n\n"
                "Por favor, intente nuevamente."
            )

        appointment = db.session.execute(
            db.text("""
                SELECT
                    a.id,
                    d.full_name AS doctor_name,
                    sp.name AS specialty_name,
                    s.start_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN specialties sp ON sp.id = d.specialty_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = :appointment_id
                  AND a.patient_id = :patient_id
            """),
            {
                "appointment_id": modified_id,
                "patient_id": patient_id
            }
        ).mappings().first()

        update_session(
            sender_number,
            current_step="MAIN_MENU",
            selected_option="modify",
            temp_data="{}"
        )

        if not appointment:
            return send_message(
                "La modificación fue guardada correctamente, "
                "pero no fue posible consultar los detalles "
                "de la cita.\n\n"
                f"Número de cita: {modified_id}\n\n"
                "Escriba 'hola' para iniciar nuevamente."
            )

        date_text = appointment["start_time"].strftime(
            "%d/%m/%Y"
        )

        time_text = appointment["start_time"].strftime(
            "%H:%M"
        )

        return send_message(
            "¡Cita médica modificada exitosamente!\n\n"
            f"Número de cita: {modified_id}\n"
            f"Especialidad: {appointment['specialty_name']}\n"
            f"Médico: {appointment['doctor_name']}\n"
            f"Nueva fecha: {date_text}\n"
            f"Nueva hora: {time_text}\n\n"
            "Su cita ha sido actualizada correctamente.\n\n"
            "Escriba 'hola' para volver al menú."
        )

    return send_message(
        "No entendí su mensaje.\n\n"
        "Escriba 'hola' para iniciar nuevamente."
    )

if __name__ == "__main__":
    app.run(debug=True)