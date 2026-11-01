from django.test import RequestFactory, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.urls import reverse

from accounts.passkeys import _webauthn_relying_party
from accounts.middleware import LocalhostCanonicalHostMiddleware
from accounts.models import PasskeyCredential



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


class PasskeyPrivacyAndDeviceExperienceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="passkey-test-user",
            password="Strong-Test-Password-123!",
        )

    def test_device_management_explains_local_biometric_processing(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:passkey_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "never your face image, fingerprint or biometric template")
        self.assertContains(response, "Your phone")
        self.assertContains(response, "Windows Hello PIN")

    def test_passkey_model_does_not_define_biometric_storage_fields(self):
        field_names = {field.name.lower() for field in PasskeyCredential._meta.get_fields()}
        forbidden_terms = ("face_image", "face_template", "fingerprint", "biometric_template")
        self.assertFalse(
            any(term in field_name for term in forbidden_terms for field_name in field_names),
            "PasskeyCredential must never store raw biometric data.",
        )

    @override_settings(DEBUG=True)
    def test_local_ipv4_requests_redirect_to_localhost(self):
        request = RequestFactory().get("/accounts/login/?next=/dashboard/", HTTP_HOST="127.0.0.1:8000")
        middleware = LocalhostCanonicalHostMiddleware(lambda req: HttpResponse("ok"))
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://localhost:8000/accounts/login/?next=/dashboard/")

    @override_settings(DEBUG=False)
    def test_production_requests_are_not_rewritten_by_local_middleware(self):
        request = RequestFactory().get("/", HTTP_HOST="example.com")
        middleware = LocalhostCanonicalHostMiddleware(lambda req: HttpResponse("ok"))
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
