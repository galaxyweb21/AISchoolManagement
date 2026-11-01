EDUAI PASSKEY MULTI-ORIGIN LOCAL CONFIGURATION PATCH
====================================================

This patch is built against the uploaded EduAI_Render_Demo_Clean baseline.
It allows two explicitly approved local browser origins, each with its own
matching WebAuthn RP ID, while keeping production origins separately configured.
Username/password login remains unchanged.

SUPPORTED LOCAL ADDRESSES
-------------------------
Use either of these addresses for passkey registration and sign-in:

  http://localhost:8000
  http://eduai.localhost:8000

Each uses its own matching WebAuthn RP ID: "localhost" for the first address and
"eduai.localhost" for the second. This avoids relying on browser-specific
subdomain handling for the special localhost domain. The alternative hostname
is included in Django ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS for DEBUG/local use.

IMPORTANT: http://127.0.0.1:8000 is intentionally NOT supported for passkeys.
WebAuthn RP IDs must be domain names; browsers reject IP addresses as RP IDs.
You may still use 127.0.0.1 for ordinary pages/password login, but use one of
the two supported localhost names for passkey operations.

CONFIGURATION
-------------
The settings automatically provide this development allowlist when DEBUG is
True and the app is not running on Render:

  WEBAUTHN_ORIGIN_RP_IDS={"http://localhost:8000":"localhost","http://eduai.localhost:8000":"eduai.localhost"}

The variable is a JSON object mapping exact browser origins to RP IDs. If you
use a different local port, update the origin keys to include that port.
Do not add arbitrary origins or user-controlled hostnames to this mapping.

LOCAL / DOCKER
--------------
For local runserver, open either supported URL above.
For Docker Compose, the web container receives the same local mapping by
Django's DEBUG default. If you set WEBAUTHN_ORIGIN_RP_IDS in .env, use the JSON
mapping above. Ensure ALLOWED_HOSTS includes eduai.localhost when explicitly
overridden; the DEBUG settings append it automatically.

Docker commands after applying the patch:
  docker compose build --no-cache web celery_worker
  docker compose up -d

RENDER PRODUCTION
-----------------
Render must use its canonical HTTPS service hostname. The existing
RENDER_EXTERNAL_HOSTNAME fallback remains in place:
  WEBAUTHN_RP_ID=<RENDER_EXTERNAL_HOSTNAME>
  WEBAUTHN_ORIGIN=https://<RENDER_EXTERNAL_HOSTNAME>

Leave WEBAUTHN_ORIGIN_RP_IDS unset on Render to use the existing single-origin
configuration. For a custom domain, set WEBAUTHN_RP_ID to the exact hostname
and WEBAUTHN_ORIGIN to https:// followed by that hostname. Do not include a
scheme, port, or path in RP_ID. Public deployments require HTTPS.

SECURITY DETAILS
----------------
- Origins are allowlisted exactly (scheme, hostname, and port).
- RP IDs are validated as DNS hostnames and must match the origin host or be
  its parent domain.
- HTTP is accepted only for localhost-family origins while DEBUG=True.
- The RP ID and origin are stored with each issued challenge and checked again
  during completion, preventing a ceremony from switching browser origins.
- 127.0.0.1 is not configured as an RP ID.
- The two local hostnames have separate RP IDs, so register a passkey separately
  when switching between localhost and eduai.localhost.
- Local and production RP IDs are different; users register separately in
  each environment.

APPLY AND VERIFY
----------------
1. Back up the project.
2. Extract the patch into the project root, preserving folder structure.
3. Run:
     python manage.py check
     python manage.py test accounts.tests.test_passkeys
4. For Docker, rebuild the web and worker images using the commands above.
5. Open http://localhost:8000 or http://eduai.localhost:8000 and register a
   passkey under Account Settings > Passkeys & Device Security.

This patch does not include or modify the populated .env file. Keep secrets
out of source archives and rotate credentials previously exposed in shared
archives.

VALIDATION NOTE
---------------
Python syntax and ZIP integrity are checked when the patch is packaged. A full
Django test run and a real browser/authenticator ceremony must be performed in
the project's configured environment.
