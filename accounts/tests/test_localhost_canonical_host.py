from django.test import TestCase, override_settings


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"],
)
class LocalhostCanonicalHostMiddlewareTests(TestCase):
    def test_redirects_loopback_ip_to_localhost_and_preserves_path_query_and_port(self):
        response = self.client.get(
            "/accounts/profile/settings/?tab=security",
            HTTP_HOST="127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "http://localhost:8000/accounts/profile/settings/?tab=security",
        )

    def test_does_not_redirect_localhost(self):
        response = self.client.get("/healthz/", HTTP_HOST="localhost:8000")
        self.assertNotEqual(response.status_code, 302)


@override_settings(
    DEBUG=False,
    ALLOWED_HOSTS=["testserver", "127.0.0.1", "localhost"],
)
class ProductionHostMiddlewareTests(TestCase):
    def test_does_not_redirect_ip_when_debug_is_false(self):
        response = self.client.get("/healthz/", HTTP_HOST="127.0.0.1:8000")
        self.assertNotEqual(response.status_code, 302)
