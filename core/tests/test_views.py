import json
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import Subject, AttendanceSession, AttendanceRecord

User = get_user_model()

class CoreViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create users
        self.admin = User.objects.create_superuser(username='admin', password='123', role='ADMIN')
        self.teacher = User.objects.create_user(username='teacher', password='123', role='TEACHER')
        self.student = User.objects.create_user(username='student', password='123', role='STUDENT')
        self.student.face_encodings = [0.1, 0.2]  # Dummy
        self.student.save()

        # Subject and session setup
        self.subject = Subject.objects.create(name='Math 101', teacher=self.teacher)
        self.subject.students.add(self.student)
        
        # Valid Base64 dummy string
        self.dummy_b64_img = "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

    # ── Role Access Control Tests ────────────────────────────────────────────────
    
    def test_dashboard_redirect_admin(self):
        self.client.login(username='admin', password='123')
        resp = self.client.get(reverse('core:dashboard_redirect'))
        self.assertRedirects(resp, reverse('core:admin_dashboard'))

    def test_dashboard_redirect_teacher(self):
        self.client.login(username='teacher', password='123')
        resp = self.client.get(reverse('core:dashboard_redirect'))
        self.assertRedirects(resp, reverse('core:teacher_dashboard'))

    def test_dashboard_redirect_student(self):
        self.client.login(username='student', password='123')
        resp = self.client.get(reverse('core:dashboard_redirect'))
        self.assertRedirects(resp, reverse('core:student_dashboard'))
        
    def test_student_cannot_access_admin(self):
        self.client.login(username='student', password='123')
        # Decorator uses redirect back to student_dashboard for STUDENTS
        resp = self.client.get(reverse('core:admin_dashboard'))
        self.assertRedirects(resp, reverse('core:student_dashboard'))

    # ── Admin Views Tests ────────────────────────────────────────────────────────

    @patch('core.face_utils.extract_face_embeddings')
    def test_admin_add_student_ajax(self, mock_extract):
        self.client.login(username='admin', password='123')
        
        # Needs 3 images to enroll, simulate success list return back
        mock_extract.return_value = [[0.1, 0.2], [0.1, 0.3], [0.2, 0.2]]
        
        with patch('core.face_utils.average_embeddings', return_value=[0.13, 0.23]):
            with patch('core.face_utils.enroll_student', return_value="dummy_folder_id"):
                resp = self.client.post(reverse('core:admin_add_student'), json.dumps({
                    'first_name': 'New',
                    'last_name': 'Kid',
                    'username': 'newkid',
                    'email': 'new@kid.com',
                    'password': 'pass',
                    'images': [self.dummy_b64_img] * 3
                }), content_type='application/json')
            
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        
        # Verify student DB
        new_student = User.objects.get(username='newkid')
        self.assertEqual(new_student.role, 'STUDENT')
        self.assertEqual(len(new_student.face_encodings), 2)
        

    def test_admin_add_teacher_ajax(self):
        self.client.login(username='admin', password='123')
        resp = self.client.post(reverse('core:admin_add_teacher'), json.dumps({
            'first_name': 'Mr',
            'last_name': 'Teach',
            'username': 'mrteach',
            'email': 'mr@teach.com',
            'password': 'pass'
        }), content_type='application/json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertTrue(User.objects.filter(username='mrteach', role='TEACHER').exists())


    # ── Teacher Views Tests ──────────────────────────────────────────────────────

    def test_teacher_start_session(self):
        self.client.login(username='teacher', password='123')
        resp = self.client.post(reverse('core:teacher_start_session', args=[self.subject.pk]))
        
        # Find the newly created session
        session = AttendanceSession.objects.filter(subject=self.subject).first()
        self.assertIsNotNone(session)
        # Verify it redirected to live UI
        self.assertRedirects(resp, reverse('core:teacher_live_session', args=[session.pk]))
        
        # Verify AttendanceRecord was created with ABSENT
        record = session.records.get(student=self.student)
        self.assertEqual(record.status, AttendanceRecord.Status.ABSENT)


    # ── Student Views Tests ──────────────────────────────────────────────────────
    
    def test_student_join_by_pin(self):
        # Create session and explicitly create record
        session = AttendanceSession.objects.create(subject=self.subject, pin_code='999999')
        AttendanceRecord.objects.create(session=session, student=self.student)
        
        self.client.login(username='student', password='123')
        resp = self.client.post(reverse('core:student_join_by_pin'), {'pin_code': '999999'})
        
        # Redirects to attendance marker
        self.assertRedirects(resp, reverse('core:student_mark_attendance', args=[session.pk]))
        
    @patch('core.face_utils.verify_by_encoding')
    def test_student_mark_attendance_post_success(self, mock_verify):
        # Setup session
        session = AttendanceSession.objects.create(subject=self.subject)
        record = AttendanceRecord.objects.create(session=session, student=self.student, status=AttendanceRecord.Status.ABSENT)
        
        # Mock successful DeepFace response
        mock_verify.return_value = {'verified': True, 'distance': 0.1, 'confidence': 0.9}
        
        self.client.login(username='student', password='123')
        resp = self.client.post(reverse('core:student_mark_attendance', args=[session.pk]), json.dumps({
            'image': self.dummy_b64_img
        }), content_type='application/json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        
        # Verify student is PRESENT
        record.refresh_from_db()
        self.assertEqual(record.status, AttendanceRecord.Status.PRESENT)
        self.assertIsNotNone(record.timestamp)
        
    @patch('core.face_utils.verify_by_encoding')
    def test_student_mark_attendance_post_fail(self, mock_verify):
        session = AttendanceSession.objects.create(subject=self.subject)
        record = AttendanceRecord.objects.create(session=session, student=self.student, status=AttendanceRecord.Status.ABSENT)
        
        # Mock failed DeepFace response (someone else's face)
        mock_verify.return_value = None
        
        self.client.login(username='student', password='123')
        resp = self.client.post(reverse('core:student_mark_attendance', args=[session.pk]), json.dumps({
            'image': self.dummy_b64_img
        }), content_type='application/json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['success'])
        
        record.refresh_from_db()
        self.assertEqual(record.status, AttendanceRecord.Status.ABSENT)
