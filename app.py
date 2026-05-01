import os

from dotenv import load_dotenv
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


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

    print("Incoming message:", incoming_message)
    print("From:", sender_number)

    response = MessagingResponse()
    response.message(
        "Hello, welcome to the clinic chatbot.\n\n"
        "This is Day 4 test response.\n\n"
        "Soon you will be able to:\n"
        "1. Book appointment\n"
        "2. Modify appointment\n"
        "3. Cancel appointment\n"
        "4. Feedback / PQR"
    )

    return str(response)


if __name__ == "__main__":
    app.run(debug=True)