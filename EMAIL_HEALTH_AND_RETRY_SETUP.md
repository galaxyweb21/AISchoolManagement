# EduAI Email Health, Password Reset and Report-Card Delivery

## What was added

- **Email Health** dashboard under AI Engine → Report Cards → Email Health.
- Real SMTP connection/authentication test plus optional real test-message delivery.
- Persistent health-test history.
- Per-parent report-card delivery records with status, attempts, last attempt, next retry and error.
- Automatic report-card email retry with bounded exponential backoff. Default: 3 attempts at approximately 15, 30 and 60 minutes.
- Manual **Retry Now** from the delivery monitor starts a fresh bounded cycle when automatic attempts have been exhausted.
- Release batch counts are refreshed after retries; a batch can move from PARTIAL to COMPLETE after all email failures are resolved.
- `test_email_configuration` management command for Render/local diagnostics.
- The SMTP password is no longer hard-coded in settings. Configure it through environment variables.

## Render environment variables

Set these on the Render web service:

```text
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-sending-gmail@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-gmail-app-password
DEFAULT_FROM_EMAIL=your-sending-gmail@gmail.com
EMAIL_TIMEOUT=15
REPORT_CARD_EMAIL_MAX_RETRIES=3
REPORT_CARD_EMAIL_RETRY_DELAY_MINUTES=15
```

Use a **Gmail App Password**, not the normal Gmail account password. Keep `EMAIL_HOST_PASSWORD` out of GitHub and source files.

## Testing

Run:

```text
python manage.py migrate
python manage.py test_email_configuration test-recipient@example.com
```

Then use **Email Health** in the application to confirm the same configuration through the browser.

## Celery / Render note

Automatic retry and automatic end-of-term release are scheduled through Celery Beat. The code includes the Beat entries, but a Render web service alone does not execute scheduled Celery Beat jobs. For a production deployment, run a Celery worker and Celery Beat (or a supported scheduler/cron service) against the same Redis broker.

On a UAT/free setup without a worker/Beat, the Email Health dashboard and **Retry Now** button remain available, and report-card release can still send immediately during the release request when SMTP is configured.
