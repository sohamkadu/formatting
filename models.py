from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Recipient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

class ScheduledEmail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200))
    message = db.Column(db.Text)
    recipients = db.Column(db.Text)
    send_time = db.Column(db.DateTime)
    user_id = db.Column(db.Integer)

    attachment_path = db.Column(db.Text, nullable=True)
    attachment_name = db.Column(db.Text, nullable=True)
    attachment_mime = db.Column(db.Text, nullable=True)

    status = db.Column(db.String(20), default="pending")

class EmailHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(255))
    message = db.Column(db.Text)
    recipients = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, nullable=False)
