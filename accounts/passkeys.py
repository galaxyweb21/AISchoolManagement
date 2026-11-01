"""WebAuthn passkey registration and authentication for EduAI.

Biometric verification happens locally on the user's authenticator. EduAI stores
only the public credential material needed to verify signed WebAuthn assertions.
"""
import base64
import hashlib
import json
import logging
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import PasskeyCredential, User

logger = logging.getLogger(__name__)

REGISTRATION_SESSION_KEY = "eduai_webauthn_registration"
AUTHENTICATION_SESSION_KEY = "eduai_webauthn_authentication"
CHALLENGE_TTL_SECONDS = 300
MAX_CREDENTIAL_PAYLOAD_BYTES = 32768


def _b64url_encode(value):
    return base64.urlsafe_b64encode(bytes(value)).decode("ascii").rstrip("=")


def _get_webauthn():
    """Import the optional-at-runtime dependency lazily for safe app startup."""
    try:
        from webauthn import (
            base64url_to_bytes,
            generate_authentication_options,
            generate_registration_options,
            options_to_json,
            verify_authentication_response,
            verify_registration_response,
        )
        from webauthn.helpers.structs import (
            AuthenticatorSelectionCriteria,
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except ImportError as exc:
        logger.exception("WebAuthn dependency is unavailable.")
        raise RuntimeError("Passkey support is not installed on this server.") from exc

    return {
        "base64url_to_bytes": base64url_to_bytes,
        "generate_authentication_options": generate_authentication_options,
        "generate_registration_options": generate_registration_options,
        "options_to_json": options_to_json,
        "verify_authentication_response": verify_authentication_response,
        "verify_registration_response": verify_registration_response,
        "AuthenticatorSelectionCriteria": AuthenticatorSelectionCriteria,
        "PublicKeyCredentialDescriptor": PublicKeyCredentialDescriptor,
        "ResidentKeyRequirement": ResidentKeyRequirement,
        "UserVerificationRequirement": UserVerificationRequirement,
    }


def _json_body(request):
    if len(request.body or b"") > MAX_CREDENTIAL_PAYLOAD_BYTES:
        raise ValueError("The passkey response is too large.")
    data = json.loads((request.body or b"{}").decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid request data.")
    return data


def _normalize_webauthn_origin(value):
    """Validate and normalize a configured browser origin."""
    parsed = urlsplit(str(value or '').strip())
    if (
        parsed.scheme.lower() not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Each WebAuthn origin must be a full origin only, for example "
            "http://localhost:8000 or https://school.onrender.com."
        )
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("A configured WebAuthn origin contains an invalid port.")
    host = parsed.hostname.lower().rstrip(".")
    netloc = host
    if port is not None:
        netloc = "{}:{}".format(host, port)
    return "{}://{}".format(parsed.scheme.lower(), netloc), host, parsed.scheme.lower()


def _validate_webauthn_rp_id(rp_id, origin_host):
    """Ensure an RP ID is a DNS hostname valid for the supplied origin."""
    import ipaddress
    import re

    rp_id = str(rp_id or "").strip().lower().rstrip(".")
    if not rp_id or any(char in rp_id for char in (":", "/", "@", " ", "_")):
        raise ValueError(
            "WEBAUTHN_RP_ID must be a hostname only, e.g. localhost or "
            "school.onrender.com; do not include https://, a port, or a path."
        )
    try:
        ipaddress.ip_address(rp_id)
    except ValueError:
        pass
    else:
        raise ValueError(
            "WebAuthn RP IDs cannot be IP addresses. Use localhost for local testing. "
            "127.0.0.1 cannot be used for passkey registration."
        )
    if rp_id != "localhost" and not re.match(
        r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
        rp_id,
    ):
        raise ValueError("The configured WebAuthn RP ID is not a valid DNS hostname.")
    if not (origin_host == rp_id or origin_host.endswith("." + rp_id)):
        raise ValueError(
            "WEBAUTHN_RP_ID '{}' must match the site hostname '{}' or be its parent domain."
            .format(rp_id, origin_host)
        )
    return rp_id


def _webauthn_relying_party(request):
    """Return a validated RP ID/origin pair for an explicitly allowed browser origin.

    WEBAUTHN_ORIGIN_RP_IDS is a JSON object mapping exact browser origins to RP IDs,
    e.g. {"http://localhost:8000":"localhost"}. When it is empty, the legacy
    single-origin WEBAUTHN_ORIGIN / WEBAUTHN_RP_ID configuration is used.
    """
    raw_origin_map = getattr(settings, "WEBAUTHN_ORIGIN_RP_IDS", "") or os.getenv(
        "WEBAUTHN_ORIGIN_RP_IDS", ""
    )
    origin_map = {}
    if isinstance(raw_origin_map, dict):
        origin_map = raw_origin_map
    elif str(raw_origin_map).strip():
        try:
            parsed_map = json.loads(raw_origin_map)
        except (TypeError, ValueError) as exc:
            raise ValueError("WEBAUTHN_ORIGIN_RP_IDS must be a valid JSON object.") from exc
        if not isinstance(parsed_map, dict):
            raise ValueError("WEBAUTHN_ORIGIN_RP_IDS must be a JSON object mapping origins to RP IDs.")
        origin_map = parsed_map

    request_host = request.get_host()
    current_origin, current_host, current_scheme = _normalize_webauthn_origin(
        "{}://{}".format(request.scheme, request_host)
    )

    if origin_map:
        normalized_map = {}
        for configured, mapped_rp_id in origin_map.items():
            normalized, mapped_host, _mapped_scheme = _normalize_webauthn_origin(configured)
            normalized_map[normalized] = _validate_webauthn_rp_id(mapped_rp_id, mapped_host)
        rp_id = normalized_map.get(current_origin)
        if not rp_id:
            allowed = ", ".join(sorted(normalized_map.keys()))
            raise ValueError(
                "This browser origin is not enabled for passkeys. Open EduAI using one of: {}."
                .format(allowed or "a configured HTTPS hostname")
            )
    else:
        configured_origin = (
            getattr(settings, "WEBAUTHN_ORIGIN", "") or os.getenv("WEBAUTHN_ORIGIN", "")
        ).strip()
        configured_rp_id = (
            getattr(settings, "WEBAUTHN_RP_ID", "") or os.getenv("WEBAUTHN_RP_ID", "")
        ).strip()
        if not configured_origin:
            raise ValueError(
                "Passkey domain is not configured. Set WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN "
                "or WEBAUTHN_ORIGIN_RP_IDS."
            )
        current_configured_origin, configured_host, _configured_scheme = _normalize_webauthn_origin(
            configured_origin
        )
        if current_origin != current_configured_origin:
            raise ValueError(
                "You opened EduAI at '{}', but passkeys are configured for '{}'. "
                "Open the site using the configured hostname."
                .format(current_origin, current_configured_origin)
            )
        rp_id = _validate_webauthn_rp_id(configured_rp_id or configured_host, configured_host)

    # Plain HTTP is permitted only for localhost-family development names and
    # only while DEBUG is enabled. Public/non-local origins must use HTTPS.
    is_localhost_origin = current_host == "localhost" or current_host.endswith(".localhost")
    if current_scheme != "https" and not (settings.DEBUG and is_localhost_origin):
        raise ValueError("Passkeys require HTTPS except for localhost development.")
    if not settings.DEBUG and current_scheme != "https":
        raise ValueError("Passkeys require HTTPS when DEBUG=False.")

    rp_name = (getattr(settings, "WEBAUTHN_RP_NAME", "") or "EduAI").strip() or "EduAI"
    return rp_id, current_origin, rp_name


def _challenge_is_valid(data):
    if not data:
        return False
    issued_at = data.get("issued_at")
    try:
        age = timezone.now().timestamp() - float(issued_at)
        return 0 <= age <= CHALLENGE_TTL_SECONDS
    except (TypeError, ValueError):
        return False


def _api_error(message, status=400):
    return JsonResponse({"success": False, "error": message}, status=status)


@login_required
def passkey_settings(request):
    credentials = PasskeyCredential.objects.filter(user=request.user, is_active=True)
    return render(request, "accounts/passkeys.html", {"passkeys": credentials})


@login_required
@require_POST
def passkey_registration_options(request):
    """Start registration only after the user re-confirms their password."""
    try:
        data = _json_body(request)
        password = data.get("current_password", "")
        if not password or not request.user.check_password(password):
            return _api_error("Your current password is incorrect.", 403)

        device_name = str(data.get("device_name") or "This device").strip()[:120] or "This device"
        api = _get_webauthn()
        rp_id, _origin, rp_name = _webauthn_relying_party(request)
        existing = PasskeyCredential.objects.filter(user=request.user, is_active=True)
        exclude_credentials = [
            api["PublicKeyCredentialDescriptor"](id=api["base64url_to_bytes"](item.credential_id))
            for item in existing
        ]
        options = api["generate_registration_options"](
            rp_id=rp_id,
            rp_name=rp_name,
            user_id=request.user.pk.bytes,
            user_name=request.user.get_username(),
            user_display_name=(request.user.get_full_name() or request.user.get_username())[:64],
            authenticator_selection=api["AuthenticatorSelectionCriteria"](
                resident_key=api["ResidentKeyRequirement"].REQUIRED,
                user_verification=api["UserVerificationRequirement"].REQUIRED,
            ),
            exclude_credentials=exclude_credentials,
        )
        request.session[REGISTRATION_SESSION_KEY] = {
            "challenge": _b64url_encode(options.challenge),
            "issued_at": timezone.now().timestamp(),
            "user_id": str(request.user.pk),
            "device_name": device_name,
            "rp_id": rp_id,
            "origin": _origin,
        }
        request.session.modified = True
        return JsonResponse({"success": True, "publicKey": json.loads(api["options_to_json"](options))})
    except RuntimeError as exc:
        return _api_error(str(exc), 503)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _api_error(str(exc) or "Unable to start passkey registration.")
    except Exception:
        logger.exception("Could not create passkey registration options for user %s", request.user.pk)
        return _api_error("Unable to start passkey registration. Please try again.", 500)


@login_required
@require_POST
def passkey_registration_complete(request):
    try:
        data = _json_body(request)
        credential = data.get("credential")
        if not isinstance(credential, dict):
            return _api_error("Invalid passkey response.")
        if not credential.get("id") or credential.get("rawId") != credential.get("id"):
            return _api_error("The passkey response is invalid.")

        pending = request.session.pop(REGISTRATION_SESSION_KEY, None)
        request.session.modified = True
        if not _challenge_is_valid(pending) or pending.get("user_id") != str(request.user.pk):
            return _api_error("Your registration request expired. Please start again.", 400)

        api = _get_webauthn()
        rp_id, origin, _rp_name = _webauthn_relying_party(request)
        if pending.get("rp_id") != rp_id or pending.get("origin") != origin:
            return _api_error("The browser origin changed during registration. Please start again.", 400)
        verification = api["verify_registration_response"](
            credential=credential,
            expected_challenge=api["base64url_to_bytes"](pending["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )

        transports = credential.get("response", {}).get("transports", [])
        if not isinstance(transports, list):
            transports = []
        transports = [str(value)[:30] for value in transports[:8] if isinstance(value, str)]
        device_type = getattr(verification.credential_device_type, "value", str(verification.credential_device_type))

        encoded_credential_id = _b64url_encode(verification.credential_id)
        credential_id_hash = hashlib.sha256(bytes(verification.credential_id)).hexdigest()
        with transaction.atomic():
            saved = PasskeyCredential.objects.select_for_update().filter(credential_id_hash=credential_id_hash).first()
            if saved and saved.user_id != request.user.pk:
                return _api_error("This passkey is already linked to another account.", 409)
            if saved and saved.is_active:
                return _api_error("This passkey is already registered to your account.", 409)
            if saved:
                saved.credential_id = encoded_credential_id
                saved.credential_id_hash = credential_id_hash
                saved.public_key = verification.credential_public_key
                saved.sign_count = verification.sign_count
                saved.device_name = pending.get("device_name") or "This device"
                saved.transports = transports
                saved.device_type = device_type[:32]
                saved.backed_up = bool(verification.credential_backed_up)
                saved.is_active = True
                saved.last_used_at = None
                saved.save()
            else:
                PasskeyCredential.objects.create(
                    user=request.user,
                    credential_id=encoded_credential_id,
                    credential_id_hash=credential_id_hash,
                    public_key=verification.credential_public_key,
                    sign_count=verification.sign_count,
                    device_name=pending.get("device_name") or "This device",
                    transports=transports,
                    device_type=device_type[:32],
                    backed_up=bool(verification.credential_backed_up),
                )
        return JsonResponse({"success": True, "message": "Passkey added successfully."})
    except RuntimeError as exc:
        return _api_error(str(exc), 503)
    except IntegrityError:
        return _api_error("This passkey is already registered to an account.", 409)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _api_error(str(exc) or "The passkey could not be verified.")
    except Exception:
        logger.exception("Passkey registration verification failed for user %s", request.user.pk)
        return _api_error("The passkey could not be verified. Please try again.", 400)


@require_POST
def passkey_authentication_options(request):
    """Start passwordless authentication; username is optional for discoverable passkeys."""
    try:
        data = _json_body(request)
        username = str(data.get("username") or "").strip()
        api = _get_webauthn()
        rp_id, _origin, _rp_name = _webauthn_relying_party(request)

        kwargs = {
            "rp_id": rp_id,
            "user_verification": api["UserVerificationRequirement"].REQUIRED,
        }
        if username:
            user = User.objects.filter(username__iexact=username, is_active=True).first()
            credentials = PasskeyCredential.objects.filter(user=user, is_active=True) if user else PasskeyCredential.objects.none()
            if not credentials.exists():
                # Keep the response identical for unknown users and users without credentials.
                return _api_error("No passkey is available for that sign-in. Check the username or use your password.", 404)
            kwargs["allow_credentials"] = [
                api["PublicKeyCredentialDescriptor"](id=api["base64url_to_bytes"](item.credential_id))
                for item in credentials
            ]

        options = api["generate_authentication_options"](**kwargs)
        request.session[AUTHENTICATION_SESSION_KEY] = {
            "challenge": _b64url_encode(options.challenge),
            "issued_at": timezone.now().timestamp(),
            "username_supplied": bool(username),
            "rp_id": rp_id,
            "origin": _origin,
        }
        request.session.modified = True
        return JsonResponse({"success": True, "publicKey": json.loads(api["options_to_json"](options))})
    except RuntimeError as exc:
        return _api_error(str(exc), 503)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _api_error(str(exc) or "Unable to start passkey sign-in.")
    except Exception:
        logger.exception("Could not create passkey authentication options.")
        return _api_error("Unable to start passkey sign-in. Please try again.", 500)


@require_POST
def passkey_authentication_verify(request):
    try:
        data = _json_body(request)
        credential = data.get("credential")
        if not isinstance(credential, dict) or not credential.get("id") or credential.get("rawId") != credential.get("id"):
            return _api_error("Invalid passkey response.")

        pending = request.session.pop(AUTHENTICATION_SESSION_KEY, None)
        request.session.modified = True
        if not _challenge_is_valid(pending):
            return _api_error("Your sign-in request expired. Please try again.", 400)

        api = _get_webauthn()
        rp_id, origin, _rp_name = _webauthn_relying_party(request)
        if pending.get("rp_id") != rp_id or pending.get("origin") != origin:
            return _api_error("The browser origin changed during sign-in. Please try again.", 400)
        credential_id_bytes = api["base64url_to_bytes"](credential["id"])
        credential_id_hash = hashlib.sha256(bytes(credential_id_bytes)).hexdigest()
        saved = PasskeyCredential.objects.select_related("user").filter(
            credential_id_hash=credential_id_hash,
            is_active=True,
            user__is_active=True,
        ).first()
        if not saved:
            return _api_error("Passkey sign-in could not be verified. Use your username and password.", 401)

        user_handle = credential.get("response", {}).get("userHandle")
        if not pending.get("username_supplied") and not user_handle:
            return _api_error("The selected passkey did not provide an account handle. Please try again.", 401)
        if user_handle:
            expected_handle = _b64url_encode(saved.user.pk.bytes)
            if user_handle != expected_handle:
                return _api_error("Passkey sign-in could not be verified.", 401)

        verification = api["verify_authentication_response"](
            credential=credential,
            expected_challenge=api["base64url_to_bytes"](pending["challenge"]),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(saved.public_key),
            credential_current_sign_count=saved.sign_count,
            require_user_verification=True,
        )

        saved.sign_count = verification.new_sign_count
        saved.device_type = getattr(verification.credential_device_type, "value", str(verification.credential_device_type))[:32]
        saved.backed_up = bool(verification.credential_backed_up)
        saved.last_used_at = timezone.now()
        saved.save(update_fields=["sign_count", "device_type", "backed_up", "last_used_at"])

        login(request, saved.user, backend="django.contrib.auth.backends.ModelBackend")
        return JsonResponse({"success": True, "redirect_url": resolve_url(settings.LOGIN_REDIRECT_URL)})
    except RuntimeError as exc:
        return _api_error(str(exc), 503)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _api_error(str(exc) or "Passkey sign-in failed.", 400)
    except Exception:
        logger.exception("Passkey authentication failed.")
        return _api_error("Passkey sign-in could not be verified. Please use your password or try again.", 401)


@login_required
@require_POST
def passkey_delete(request, credential_id):
    credential = get_object_or_404(PasskeyCredential, pk=credential_id, user=request.user, is_active=True)
    password = request.POST.get("current_password", "")
    if not password or not check_password(password, request.user.password):
        messages.error(request, "Your current password is incorrect. The passkey was not removed.")
        return redirect("accounts:passkey_settings")

    credential.is_active = False
    credential.save(update_fields=["is_active"])
    messages.success(request, "Passkey removed from this account.")
    return redirect("accounts:passkey_settings")
