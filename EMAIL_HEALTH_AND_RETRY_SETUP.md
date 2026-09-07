# EduAI Email Health, Password Reset and Report-Card Delivery

## Why SMTP was replaced

The Render Free web service cannot make outbound connections to SMTP ports. The live deployment therefore uses an HTTPS transactional-email API instead of Gmail SMTP. The application keeps Django's normal email interface, so password resets, report cards and future notifications share one delivery path.

## Production provider: Brevo

Brevo provides transactional email through its REST API over HTTPS. The API endpoint is `https://api.brevo.com/v3/smtp/email`; requests authenticate with an API key and require a verified sender.

Create/verify a sender in Brevo, generate an API key, then add these Render environment variables:

```text
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<your Brevo API key>
BREVO_SENDER_EMAIL=<your verified sender address>
BREVO_SENDER_NAME=EduAI School Management
DEFAULT_FROM_EMAIL=<your verified sender address>
EMAIL_API_TIMEOUT=20
REPORT_CARD_EMAIL_MAX_RETRIES=3
REPORT_CARD_EMAIL_RETRY_DELAY_MINUTES=15
```

Never put the API key in GitHub, source files, screenshots or chat.

## Local/offline development

You do **not** need to deploy the project before testing email locally. When `DEBUG=True` and `EMAIL_PROVIDER` is not overridden, settings default to Django's console email backend. The application will run normally and email messages will be printed in the terminal instead of going to the internet.

Recommended local `.env` values:

```text
DEBUG=True
EMAIL_PROVIDER=console
DEFAULT_FROM_EMAIL=no-reply@localhost
```

Then run:

```text
python manage.py migrate
python manage.py runserver
```

Request a password reset in the browser. The reset email, including its reset URL, will appear in the terminal running `runserver`. You can paste that URL into your browser and test the complete password-reset workflow without any external email provider.

You can also test the email backend without opening the browser:

```text
python manage.py email_smoke_test test@example.com
```

With `EMAIL_PROVIDER=console`, this intentionally prints the email locally. If you later set `EMAIL_PROVIDER=brevo` and a valid `BREVO_API_KEY`, the same command sends through Brevo over HTTPS.

## Email Health dashboard

Open **AI Engine → Report Cards → Email Health**. The health test verifies the configured provider and sends a real test message. Delivery records store SENT/FAILED/SKIPPED state, attempt count, error details and next retry time.

## Report-card retry

Automatic retries use exponential backoff (default approximately 15, 30 and 60 minutes). A manual **Retry Now** starts a fresh bounded retry cycle after automatic attempts are exhausted.

The current Render Free web service has no separate Celery worker/Beat service, so scheduled retries require a worker/scheduler if you want them to run automatically. The release request and manual Retry Now remain available.
