from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import UserRole

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            username='jdoe',
            email='jdoe@demo.com',
            password='password123',
            first_name='John',
            last_name='Doe',
            role=UserRole.STUDENT,
        )
        self.assertEqual(user.username, 'jdoe')
        self.assertEqual(user.email, 'jdoe@demo.com')
        self.assertTrue(user.check_password('password123'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.role, 'STUDENT')

    def test_create_superuser(self):
        admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@demo.com',
            password='password123',
            role=UserRole.ADMIN,
        )
        self.assertEqual(admin_user.username, 'admin')
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)
        self.assertEqual(admin_user.role, 'ADMIN')

    def test_face_encodings_field(self):
        # Verify JSON field saves and retrieves list correctly
        test_encoding = [0.1, -0.2, 0.45, 0.0]
        user = User.objects.create_user(username='test_enc', password='abc', role='STUDENT')
        user.face_encodings = test_encoding
        user.save()

        fetched = User.objects.get(username='test_enc')
        self.assertEqual(fetched.face_encodings, test_encoding)


class AuthViewTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='student1', password='pass', role=UserRole.STUDENT
        )

    def test_login_view_get(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_login_view_post_success(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'student1',
            'password': 'pass',
        })
        # After successful login, app redirects to dashboard mapper
        self.assertRedirects(response, reverse('core:dashboard_redirect'), fetch_redirect_response=False)

    def test_login_view_post_failure(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'student1',
            'password': 'wrongpassword',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid username or password')

    def test_logout_view(self):
        self.client.login(username='student1', password='pass')
        response = self.client.get(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))
