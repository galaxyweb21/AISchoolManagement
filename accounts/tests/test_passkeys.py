from django.test import TestCase
from django.urls import reverse


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
