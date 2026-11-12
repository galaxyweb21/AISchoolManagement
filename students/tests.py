from unittest.mock import patch

from django.test import TestCase, RequestFactory

from accounts.models import User
from school.models import School
from students.views import parent_guardian_list


class ParentGuardianSearchTests(TestCase):
    """Regression coverage for multi-word guardian searches."""

    def setUp(self):
        self.school = School.objects.create(
            name='Guardian Search Test School',
            address='Test address',
            contact_email='school@example.test',
            phone_number='0200000000',
        )
        self.admin = User.objects.create_user(
            username='guardian_search_admin',
            email='admin@example.test',
            password='Test-password-123!',
            role='SCHOOL_ADMIN',
            school=self.school,
        )
        User.objects.create_user(
            username='ama_danful',
            email='ama.danful@example.test',
            password='Test-password-123!',
            first_name='Ama',
            last_name='Danful',
            role='PARENT',
            school=self.school,
        )
        User.objects.create_user(
            username='ama_mensah',
            email='ama.mensah@example.test',
            password='Test-password-123!',
            first_name='Ama',
            last_name='Mensah',
            role='PARENT',
            school=self.school,
        )
        User.objects.create_user(
            username='demo_parents',
            email='demo.parents@example.test',
            password='Test-password-123!',
            first_name='Demo',
            last_name='Parents',
            role='PARENT',
            school=self.school,
        )
        self.factory = RequestFactory()

    def _search(self, query):
        request = self.factory.get('/students/parents-guardians/', {'q': query})
        request.user = self.admin
        # Capture the view context without requiring template rendering.
        with patch('students.views.render', side_effect=lambda _request, _template, context: context):
            context = parent_guardian_list(request)
        return list(context['parents'])

    def test_multi_word_name_requires_all_terms(self):
        results = self._search('Ama Danful')
        self.assertEqual([parent.username for parent in results], ['ama_danful'])

    def test_single_word_search_still_matches_partial_names(self):
        results = self._search('Ama')
        self.assertEqual(
            {parent.username for parent in results},
            {'ama_danful', 'ama_mensah'},
        )


class StudentCredentialExposureTests(TestCase):
    """Passwords are returned only at account creation, never by lookup APIs."""

    def setUp(self):
        from datetime import date
        from django.urls import reverse
        from students.models import GradeLevel, Student

        self.school = School.objects.create(
            name='Credential Security Test School',
            address='Test address',
            contact_email='security@example.test',
            phone_number='0200000001',
        )
        self.admin = User.objects.create_user(
            username='credential_admin',
            email='security-admin@example.test',
            password='Test-password-123!',
            role='SCHOOL_ADMIN',
            school=self.school,
        )
        self.student_user = User.objects.create_user(
            username='student_demo_001',
            email='',
            password='Student-password-123!',
            role='STUDENT',
            school=self.school,
            default_password='Student-password-123!',
            first_name='Demo',
            last_name='Student',
        )
        grade, _ = GradeLevel.objects.get_or_create(school=self.school, name='Basic 1')
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number='SEC-TEST-001',
            date_of_birth=date(2015, 1, 1),
            grade_level=grade,
            default_password='Student-password-123!',
        )
        self.url = reverse('students:api_student_credentials', args=[self.student.id])

    def test_credential_lookup_never_returns_passwords(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertNotIn('password', payload['student'])
        self.assertFalse(payload['student']['password_available'])
        self.assertNotIn('password', payload.get('parent') or {})

    def test_credential_lookup_rejects_users_without_management_role(self):
        user = User.objects.create_user(
            username='credential_student',
            password='Test-password-123!',
            role='STUDENT',
            school=self.school,
        )
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
