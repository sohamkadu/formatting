from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from email_service import send_bulk_email

scheduler = BackgroundScheduler()
scheduler.start()


def cancel_scheduled_email(scheduled_id: int) -> None:
    try:
        scheduler.remove_job(f"email_{scheduled_id}")
    except JobLookupError:
        return


def schedule_bulk_email(
    send_time,
    subject,
    message,
    recipients,
    scheduled_id,
    app,
    attachment_path=None,
    attachment_name=None,
    attachment_mime=None,
):
    def job_wrapper():
        with app.app_context():
            send_bulk_email(
                subject,
                message,
                recipients,
                scheduled_id,
                attachment_path=attachment_path,
                attachment_name=attachment_name,
                attachment_mime=attachment_mime,
            )

    scheduler.add_job(
        job_wrapper,
        trigger="date",
        run_date=send_time,
        id=f"email_{scheduled_id}",
        replace_existing=True,
    )
