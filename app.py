from datetime import datetime
import os
import uuid
import mimetypes
import csv
import io
from scheduler import schedule_bulk_email, cancel_scheduled_email
from flask import Flask, render_template, request, redirect, session, jsonify
from models import db, User, Recipient, EmailHistory, ScheduledEmail
from email_service import send_bulk_email
import config
from werkzeug.utils import secure_filename
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    db.create_all()

    try:
        table_columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(scheduled_email)")).all()
        }
        if "attachment_path" not in table_columns:
            db.session.execute(text("ALTER TABLE scheduled_email ADD COLUMN attachment_path TEXT"))
        if "attachment_name" not in table_columns:
            db.session.execute(text("ALTER TABLE scheduled_email ADD COLUMN attachment_name TEXT"))
        if "attachment_mime" not in table_columns:
            db.session.execute(text("ALTER TABLE scheduled_email ADD COLUMN attachment_mime TEXT"))
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        user = User(email=request.form["email"])
        user.set_password(request.form["password"])
        db.session.add(user)
        db.session.commit()
        return redirect("/login")
    return render_template("signup.html")

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"]).first()
        if user and user.check_password(request.form["password"]):
            session["user_id"] = user.id
            return redirect("/dashboard")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    recipients_count = Recipient.query.filter_by(
        user_id=session["user_id"]
    ).count()

    schedules_count = ScheduledEmail.query.filter_by(
        user_id=session["user_id"]
    ).count()

    user = User.query.get(session["user_id"])

    return render_template(
        "dashboard.html",
        recipients_count=recipients_count,
        schedules_count=schedules_count,
        session_email=user.email,
        active_page="dashboard"
    )

@app.route("/send", methods=["POST"])
def send():
    if "user_id" not in session:
        return redirect("/login")

    selected_recipients = request.form.getlist("recipients")
    subject = request.form["subject"]
    message = request.form["message"]
    send_time_text = (request.form.get("send_time") or "").strip()
    if send_time_text:
        try:
            send_time = datetime.strptime(send_time_text, "%Y-%m-%dT%H:%M")
        except Exception:
            return redirect("/recipients")
    else:
        send_time = datetime.now()

    uploaded_attachment = request.files.get("attachment") or request.files.get("file")
    attachment_db_path = None
    attachment_name = None
    attachment_mime = None
    attachment_file_path = None

    if uploaded_attachment and uploaded_attachment.filename:
        safe_filename = secure_filename(uploaded_attachment.filename)
        detected_mime = (
            uploaded_attachment.mimetype
            or mimetypes.guess_type(safe_filename)[0]
            or "application/octet-stream"
        )

        file_bytes = uploaded_attachment.read()
        if file_bytes and len(file_bytes) > 10 * 1024 * 1024:
            return redirect("/recipients")

        _, ext = os.path.splitext(safe_filename)
        if not ext:
            ext = mimetypes.guess_extension(detected_mime) or ""

        attachments_dir = os.path.join(app.instance_path, "attachments")
        os.makedirs(attachments_dir, exist_ok=True)
        stored_filename = f"{uuid.uuid4().hex}{ext.lower()}"
        saved_file_path = os.path.join(attachments_dir, stored_filename)
        with open(saved_file_path, "wb") as file_handle:
            file_handle.write(file_bytes)

        attachment_db_path = os.path.join("attachments", stored_filename)
        attachment_file_path = saved_file_path
        attachment_name = safe_filename
        attachment_mime = detected_mime

    scheduled = ScheduledEmail(
        subject=subject,
        message=message,
        recipients=",".join(selected_recipients),
        send_time=send_time,
        user_id=session["user_id"],
        status="pending",
        attachment_path=attachment_db_path,
        attachment_name=attachment_name,
        attachment_mime=attachment_mime,
    )

    db.session.add(scheduled)
    db.session.commit()

    now = datetime.now()
    if send_time <= now:
        # Immediate send path when no time is set (or time is in the past).
        send_bulk_email(
            subject,
            message,
            selected_recipients,
            scheduled.id,
            attachment_path=attachment_file_path or attachment_db_path,
            attachment_name=attachment_name,
            attachment_mime=attachment_mime,
        )
    else:
        schedule_bulk_email(
            send_time,
            subject,
            message,
            selected_recipients,
            scheduled.id,
            app,
            attachment_path=attachment_file_path or attachment_db_path,
            attachment_name=attachment_name,
            attachment_mime=attachment_mime,
        )

    return redirect("/schedules")




@app.route("/recipients", methods=["GET", "POST"])
def recipients():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        email = request.form["email"]
        new_recipient = Recipient(
            email=email,
            user_id=session["user_id"]
        )
        db.session.add(new_recipient)
        db.session.commit()

    all_recipients = Recipient.query.filter_by(
        user_id=session["user_id"]
    ).all()

    user = User.query.get(session["user_id"])

    return render_template(
        "recipients.html",
        recipients=all_recipients,
        session_email=user.email,
        active_page="recipients"
    )


@app.route("/recipients/clear", methods=["POST"])
def clear_recipients():
    if "user_id" not in session:
        return redirect("/login")

    Recipient.query.filter_by(user_id=session["user_id"]).delete()
    db.session.commit()
    return redirect("/recipients")


@app.route("/upload", methods=["POST"])
def upload_recipients_csv():
    if "user_id" not in session:
        return redirect("/login")

    csv_file = request.files.get("file")
    if csv_file is None or csv_file.filename == "":
        return redirect("/recipients")

    try:
        csv_bytes = csv_file.read()
        text = csv_bytes.decode("utf-8-sig", errors="replace")
    except Exception:
        return redirect("/recipients")

    if not text.strip():
        return redirect("/recipients")

    sample_text = text[:2048]
    try:
        # Restrict delimiter detection to common CSV separators.
        # Without this, Sniffer can mis-detect letters (e.g., the "l" in "gmail")
        # as a delimiter when all rows share that character.
        csv_dialect = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
    except Exception:
        csv_dialect = csv.excel

    csv_reader = csv.reader(io.StringIO(text), csv_dialect)
    rows = [row for row in csv_reader if any(cell.strip() for cell in row)]
    if not rows:
        return redirect("/recipients")

    header_cells = [cell.strip() for cell in rows[0]]
    header_lower = [cell.lower() for cell in header_cells]

    email_col_index = 0
    if "email" in header_lower:
        email_col_index = header_lower.index("email")
        data_rows = rows[1:]
    elif "e-mail" in header_lower:
        email_col_index = header_lower.index("e-mail")
        data_rows = rows[1:]
    else:
        data_rows = rows

    # Normalize + de-duplicate (case-insensitive)
    candidate_emails: list[str] = []
    for row in data_rows:
        if email_col_index >= len(row):
            continue
        email = row[email_col_index].strip()
        if not email or "@" not in email:
            continue

        candidate_emails.append(email)

    if not candidate_emails:
        return redirect("/recipients")

    user_id = session["user_id"]
    existing = {
        r.email.strip().lower()
        for r in Recipient.query.filter_by(user_id=user_id).all()
        if r.email
    }

    to_insert: list[Recipient] = []
    seen: set[str] = set()
    for email in candidate_emails:
        normalized = email.strip()
        key = normalized.lower()
        if key in existing or key in seen:
            continue

        seen.add(key)
        to_insert.append(Recipient(email=normalized, user_id=user_id))

    if to_insert:
        db.session.bulk_save_objects(to_insert)
        db.session.commit()

    return redirect("/recipients")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/schedules")
def schedules():
    if "user_id" not in session:
        return redirect("/login")

    upcoming = ScheduledEmail.query.filter_by(
        user_id=session["user_id"]
    ).order_by(ScheduledEmail.send_time.asc()).all()

    user = User.query.get(session["user_id"])

    return render_template(
        "schedules.html",
        schedules=upcoming,
        active_page="schedules",
        session_email=user.email
    )

@app.route("/api/schedules/status")
def api_schedules_status():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    schedules = ScheduledEmail.query.filter_by(
        user_id=session["user_id"]
    ).all()
    
    return jsonify({
        "schedules": [
            {
                "id": s.id,
                "status": s.status
            }
            for s in schedules
        ]
    })


@app.route("/schedules/<int:scheduled_id>/update", methods=["POST"])
def update_schedule(scheduled_id: int):
    if "user_id" not in session:
        return redirect("/login")

    scheduled = ScheduledEmail.query.get(scheduled_id)
    if scheduled is None or scheduled.user_id != session["user_id"]:
        return redirect("/schedules")

    if scheduled.status != "pending":
        return redirect("/schedules")

    try:
        new_send_time = datetime.strptime(request.form["send_time"], "%Y-%m-%dT%H:%M")
    except Exception:
        return redirect("/schedules")

    new_message = request.form.get("message")
    if new_message is not None and new_message.strip():
        scheduled.message = new_message

    scheduled.send_time = new_send_time
    db.session.commit()

    recipient_emails = [r for r in (scheduled.recipients or "").split(",") if r]
    attachment_file_path = None
    if scheduled.attachment_path:
        # attachment_path stored relative to instance folder (e.g., attachments/xyz.pdf)
        attachment_file_path = os.path.join(app.instance_path, scheduled.attachment_path)

    schedule_bulk_email(
        new_send_time,
        scheduled.subject,
        scheduled.message,
        recipient_emails,
        scheduled.id,
        app,
        attachment_path=attachment_file_path,
        attachment_name=scheduled.attachment_name,
        attachment_mime=scheduled.attachment_mime,
    )

    return redirect("/schedules")


@app.route("/schedules/<int:scheduled_id>/delete", methods=["POST"])
def delete_schedule(scheduled_id: int):
    if "user_id" not in session:
        return redirect("/login")

    scheduled = ScheduledEmail.query.get(scheduled_id)
    if scheduled is None or scheduled.user_id != session["user_id"]:
        return redirect("/schedules")

    cancel_scheduled_email(scheduled_id)

    db.session.delete(scheduled)
    db.session.commit()

    return redirect("/schedules")


@app.route("/schedules/delete-selected", methods=["POST"])
def delete_selected_schedules():
    if "user_id" not in session:
        return redirect("/login")

    selected_ids_text = request.form.getlist("schedule_ids")
    if not selected_ids_text:
        return redirect("/schedules")

    selected_ids: list[int] = []
    for value in selected_ids_text:
        try:
            selected_ids.append(int(value))
        except Exception:
            continue

    if not selected_ids:
        return redirect("/schedules")

    schedules_to_delete = ScheduledEmail.query.filter(
        ScheduledEmail.user_id == session["user_id"],
        ScheduledEmail.id.in_(selected_ids),
    ).all()

    for item in schedules_to_delete:
        cancel_scheduled_email(item.id)
        db.session.delete(item)

    db.session.commit()
    return redirect("/schedules")

@app.route("/reset")
def reset():
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]

    for s in ScheduledEmail.query.filter_by(user_id=user_id).all():
        cancel_scheduled_email(s.id)

    Recipient.query.filter_by(user_id=user_id).delete()

    ScheduledEmail.query.filter_by(user_id=user_id).delete()

    EmailHistory.query.filter_by(user_id=user_id).delete()

    db.session.commit()
    
    return redirect("/dashboard")







if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(debug=True, port=port)

