EDUAI PASSKEY LOGIN - ENVIRONMENT CONFIGURATION FIX
===================================================

This is a patch for the latest EduAI_Render_Demo_Clean baseline. It includes
Phase 1 passkey registration/login plus corrected, environment-aware RP ID and
origin configuration. Existing username/password login remains available.

WHY THE BROWSER SAID "INVALID DOMAIN"
-------------------------------------
The WebAuthn RP ID must be a hostname only. It must not contain https://, a
port, or a path. It must also match the hostname in the browser address bar.
For local testing, use localhost consistently; do not open the app at
127.0.0.1 when the RP ID is localhost.

CONFIGURATION
-------------
1) LOCAL DEVELOPMENT (runserver)
   In the project's .env set:
       WEBAUTHN_RP_ID=localhost
       WEBAUTHN_ORIGIN=http://localhost:8000
       WEBAUTHN_RP_NAME=EduAI
   Open the app at exactly http://localhost:8000. Do not use
   http://127.0.0.1:8000 for passkey registration under this configuration.

2) DOCKER COMPOSE (included docker-compose.yml)
   The compose file passes these defaults to the web container:
       WEBAUTHN_RP_ID=localhost
       WEBAUTHN_ORIGIN=http://localhost:8000
       WEBAUTHN_RP_NAME=EduAI
   Copy .env.docker.example to .env if needed, then browse from the host
   computer to exactly http://localhost:8000. The internal service names
   such as "web" and "db" are not browser RP IDs.
   If Docker is hosted on another machine and users access it through a public
   hostname, configure that hostname and HTTPS instead; plain HTTP on a LAN IP
   is not a valid passkey deployment.

3) RENDER PRODUCTION
   Render automatically provides RENDER_EXTERNAL_HOSTNAME. The settings now
   derive the defaults from that value:
       WEBAUTHN_RP_ID=<RENDER_EXTERNAL_HOSTNAME>
       WEBAUTHN_ORIGIN=https://<RENDER_EXTERNAL_HOSTNAME>
       WEBAUTHN_RP_NAME=EduAI
   You can set the first two explicitly in Render Environment if preferred.
   Use the exact hostname shown in the Render service URL, without scheme,
   port, or path for RP_ID. ORIGIN includes https:// and no path/trailing slash.
   If you use a custom domain, set RP_ID to that custom hostname and ORIGIN to
   https:// followed by that exact hostname. Keep using the same canonical
   hostname for both registration and login.

IMPORTANT DOMAIN RULES
----------------------
- RP_ID examples: localhost, eduai-school-demo.onrender.com, school.example.com
- ORIGIN examples: http://localhost:8000, https://eduai-school-demo.onrender.com
- Invalid RP_ID examples: https://school.example.com, school.example.com:8000,
  school.example.com/login, 127.0.0.1
- WebAuthn credentials are scoped to the RP ID. Credentials registered on
  localhost do not automatically work on the Render domain. Register a new
  passkey on each environment/device domain.
- If you switch from the Render onrender.com URL to a custom domain later,
  users will need to register a passkey again on the new domain.
- Public/non-local deployments require HTTPS.

INSTALL / UPDATE
----------------
1. Back up the project and database.
2. Extract this patch into the project root, preserving folder paths.
3. Install the updated dependency set in the active environment:
       pip install -r requirements.txt
   WebAuthn is pinned to 2.2.0 for Python 3.8 compatibility. cryptography is
   pinned to 42.0.8 to satisfy the WebAuthn dependency line; the baseline's
   older 38.0.4 pin must not override it.
4. Apply the migration:
       python manage.py migrate accounts
5. Run checks:
       python manage.py check
       python manage.py makemigrations --check --dry-run
       python manage.py test accounts.tests.test_passkeys
6. Restart local/Docker services or redeploy Render.

Docker note: rebuild after updating requirements:
       docker compose build web celery_worker
       docker compose up -d

SECURITY
--------
The uploaded baseline archive included a populated .env file. This patch does
not contain it. Rotate any credentials/secrets that were present in that
archive (Django SECRET_KEY, database password, email credentials, API keys).
Never commit or share a populated .env file. Keep secrets in local environment
files or the deployment provider's secret environment settings.

VALIDATION NOTE
---------------
The patch was assembled against the uploaded baseline and Python syntax was
checked. A full Django test run and real browser/WebAuthn ceremony require the
project's configured virtual environment, database, HTTPS hostname, and a
physical authenticator; those cannot be truthfully certified from this archive
alone. Run the commands above before deploying.
