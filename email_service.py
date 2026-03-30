import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
import mimetypes
import re
from html import unescape, escape
import config
from models import db, ScheduledEmail


def send_bulk_email(
    subject,
    message,
    recipients,
    scheduled_id,
    attachment_path=None,
    attachment_name=None,
    attachment_mime=None,
):
    print(" EMAIL JOB STARTED")
    print("Recipients:", recipients)
    print("Subject:", subject)

    delivery_count = 0

    try:
        server = smtplib.SMTP(config.EMAIL_HOST, config.EMAIL_PORT)
        server.starttls()
        server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
        print(" SMTP LOGIN SUCCESS")

        for email in recipients:
            msg = MIMEMultipart()
            msg["From"] = config.EMAIL_ADDRESS
            msg["To"] = email
            msg["Subject"] = subject

            has_html_tags = bool(re.search(r"<[^>]+>", message or ""))
            if has_html_tags:
                html_body = message
            else:
                html_body = escape(message or "").replace("\n", "<br>")

            text_body = unescape(re.sub(r"<[^>]+>", "", html_body)).strip()
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(text_body, "plain", "utf-8"))
            alt.attach(MIMEText(html_body, "html", "utf-8"))
            msg.attach(alt)

            if attachment_path:
                try:
                    path_to_open = attachment_path
                    if not os.path.isabs(path_to_open):
                        candidate = os.path.join(os.getcwd(), path_to_open)
                        if os.path.exists(candidate):
                            path_to_open = candidate
                        else:
                            candidate = os.path.join(os.getcwd(), "instance", path_to_open)
                            if os.path.exists(candidate):
                                path_to_open = candidate

                    with open(path_to_open, "rb") as f:
                        file_data = f.read()

                    guessed = attachment_mime
                    if not guessed:
                        guessed = mimetypes.guess_type(attachment_name or path_to_open)[0]
                    guessed = guessed or "application/octet-stream"

                    maintype, subtype = "application", "octet-stream"
                    if "/" in guessed:
                        maintype, subtype = guessed.split("/", 1)

                    part = MIMEBase(maintype, subtype)
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    filename = attachment_name or os.path.basename(attachment_path)
                    part.add_header("Content-Disposition", f"attachment; filename=\"{filename}\"")
                    msg.attach(part)
                except Exception as e:
                    print(" ATTACHMENT ERROR:", e)

            try:
                server.sendmail(config.EMAIL_ADDRESS, email, msg.as_string())
                print(" Sent to:", email)
                delivery_count += 1
            except Exception as recipient_error:
                print(" RECIPIENT SEND ERROR:", recipient_error)

        server.quit()
        print(" SMTP CLOSED")
        
        # Update status to sent
        scheduled = ScheduledEmail.query.get(scheduled_id)
        if scheduled:
            scheduled.status = "sent" if delivery_count > 0 else "failed"
            db.session.commit()
            print(" Status updated")

    except Exception as e:
        print(" EMAIL ERROR:", e)
        
        # Update status to failed
        scheduled = ScheduledEmail.query.get(scheduled_id)
        if scheduled:
            scheduled.status = "failed"
            db.session.commit()
            print(" Status updated to FAILED")
        
        raise
