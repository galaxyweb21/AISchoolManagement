from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from accounts.passkeys import _challenge_is_valid, _registration_attachment, _webauthn_relying_party


# These are test-only hostnames. Production ALLOWED_HOSTS remains unchanged.
PASSKEY_TEST_HOSTS = [
    "testserver",
    "localhost",
    "127.0.0.1",  # Test-only: allow Django to pass this host to WebAuthn validation.
    "eduai.localhost",
    "evil.localhost",
    "school.example.com",
    "eduai-demo.onrender.com",
]

# WhiteNoise's manifest storage expects collectstatic to have generated a
# manifest. Template-rendering tests should use the non-manifest backend;
# production continues to use CompressedManifestStaticFilesStorage.
PASSKEY_TEST_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


@override_settings(
    ALLOWED_HOSTS=PASSKEY_TEST_HOSTS,
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES=PASSKEY_TEST_STORAGE,
)
class PasskeyPageTests(TestCase):
    def test_login_page_exposes_passkey_option(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="passkeyLoginButton"')

    def test_passkey_management_requires_login(self):
        response = self.client.get(reverse("accounts:passkey_settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_passkey_authentication_options_requires_post(self):
        response = self.client.get(reverse("accounts:passkey_authentication_options"))
        self.assertEqual(response.status_code, 405)

    def test_passkey_authentication_verify_requires_post(self):
        response = self.client.get(reverse("accounts:passkey_authentication_verify"))
        self.assertEqual(response.status_code, 405)


@override_settings(
    ALLOWED_HOSTS=PASSKEY_TEST_HOSTS,
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    STORAGES=PASSKEY_TEST_STORAGE,
)
class PasskeyOriginAllowlistTests(TestCase):
    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS={
            "http://localhost:8000": "localhost",
            "http://eduai.localhost:8000": "eduai.localhost",
        },
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_localhost_origin_uses_localhost_rp_id(self):
        request = RequestFactory().get("/", HTTP_HOST="localhost:8000")
        self.assertEqual(
            _webauthn_relying_party(request),
            ("localhost", "http://localhost:8000", "EduAI"),
        )

    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS={
            "http://localhost:8000": "localhost",
            "http://eduai.localhost:8000": "eduai.localhost",
        },
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_localhost_subdomain_uses_its_own_rp_id(self):
        request = RequestFactory().get("/", HTTP_HOST="eduai.localhost:8000")
        self.assertEqual(
            _webauthn_relying_party(request),
            ("eduai.localhost", "http://eduai.localhost:8000", "EduAI"),
        )

    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS={
            "http://localhost:8000": "localhost",
            "http://eduai.localhost:8000": "eduai.localhost",
        },
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_ip_address_origin_is_not_allowlisted(self):
        request = RequestFactory().get("/", HTTP_HOST="127.0.0.1:8000")
        with self.assertRaisesMessage(ValueError, "origin is not enabled"):
            _webauthn_relying_party(request)

    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS='{"http://localhost:8000":"localhost"}',
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_unlisted_origin_is_rejected(self):
        request = RequestFactory().get("/", HTTP_HOST="evil.localhost:8000")
        with self.assertRaisesMessage(ValueError, "origin is not enabled"):
            _webauthn_relying_party(request)

    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS='{"http://localhost:8000":"127.0.0.1"}',
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_ip_address_cannot_be_rp_id(self):
        request = RequestFactory().get("/", HTTP_HOST="localhost:8000")
        with self.assertRaisesMessage(ValueError, "cannot be IP addresses"):
            _webauthn_relying_party(request)

    @override_settings(
        DEBUG=False,
        WEBAUTHN_ORIGIN_RP_IDS="",
        WEBAUTHN_ORIGIN="https://eduai-demo.onrender.com",
        WEBAUTHN_RP_ID="eduai-demo.onrender.com",
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_render_single_origin_configuration_remains_supported(self):
        request = RequestFactory().get("/", secure=True, HTTP_HOST="eduai-demo.onrender.com")
        self.assertEqual(
            _webauthn_relying_party(request),
            ("eduai-demo.onrender.com", "https://eduai-demo.onrender.com", "EduAI"),
        )

    @override_settings(
        DEBUG=True,
        WEBAUTHN_ORIGIN_RP_IDS={"http://school.example.com:8000": "school.example.com"},
        WEBAUTHN_RP_NAME="EduAI",
    )
    def test_plain_http_is_not_allowed_for_non_local_domains(self):
        request = RequestFactory().get("/", HTTP_HOST="school.example.com:8000")
        with self.assertRaisesMessage(ValueError, "require HTTPS"):
            _webauthn_relying_party(request)


class PasskeyChallengeSecurityTests(TestCase):
    def test_missing_challenge_is_rejected(self):
        self.assertFalse(_challenge_is_valid(None))
        self.assertFalse(_challenge_is_valid({}))

    def test_unexpired_challenge_is_accepted(self):
        now = timezone.now()
        with patch("accounts.passkeys.timezone.now", return_value=now):
            self.assertTrue(_challenge_is_valid({"issued_at": now.timestamp() - 30}))

    def test_expired_challenge_is_rejected(self):
        now = timezone.now()
        with patch("accounts.passkeys.timezone.now", return_value=now):
            self.assertFalse(_challenge_is_valid({"issued_at": now.timestamp() - 301}))

    def test_future_challenge_is_rejected(self):
        now = timezone.now()
        with patch("accounts.passkeys.timezone.now", return_value=now):
            self.assertFalse(_challenge_is_valid({"issued_at": now.timestamp() + 5}))


class PasskeyAuthenticatorChoiceTests(TestCase):
    class Attachment:
        PLATFORM = "platform-enum"
        CROSS_PLATFORM = "cross-platform-enum"

    def setUp(self):
        self.api = {"AuthenticatorAttachment": self.Attachment}

    def test_platform_choice_preserves_windows_hello(self):
        self.assertEqual(_registration_attachment("platform", self.api), "platform-enum")

    def test_cross_platform_choice_requests_phone_or_security_key(self):
        self.assertEqual(_registration_attachment("cross-platform", self.api), "cross-platform-enum")

    def test_invalid_attachment_choice_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Choose either this device"):
            _registration_attachment("unknown", self.api)
