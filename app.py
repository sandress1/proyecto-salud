import os

from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

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


if __name__ == "__main__":
    app.run(debug=True)