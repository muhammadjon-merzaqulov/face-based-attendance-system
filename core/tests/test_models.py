import datetime
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from core.models import Subject, AttendanceSession, AttendanceRecord, ActivityLog, generate_pin, qr_code_upload_path

from accounts.models import UserRole

User = get_user_model()

class CoreModelsTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher1', role=UserRole.TEACHER
        )
        self.student1 = User.objects.create_user(
            username='student1', role=UserRole.STUDENT
        )
        self.student2 = User.objects.create_user(
            username='student2', role=UserRole.STUDENT
        )
        self.subject = Subject.objects.create(
            name='Cloud Computing',
            code='CC-101',
            teacher=self.teacher
        )
        self.subject.students.add(self.student1, self.student2)

    def test_subject_creation(self):
        self.assertEqual(self.subject.name, 'Cloud Computing')
        self.assertEqual(self.subject.students.count(), 2)
        self.assertEqual(str(self.subject), 'Cloud Computing [CC-101]')

    def test_generate_pin(self):
        pin = generate_pin()
        self.assertEqual(len(pin), 6)
        self.assertTrue(pin.isdigit())

    def test_attendance_session_creation(self):
        session = AttendanceSession.objects.create(
            subject=self.subject,
            created_by=self.teacher
        )
        self.assertTrue(session.is_active)
        self.assertEqual(len(session.pin_code), 6)
        session_date = session.date.date() if isinstance(session.date, datetime.datetime) else session.date
        self.assertEqual(session_date, timezone.now().date())
        # Test __str__ method without throwing errors
        self.assertIn('Cloud Computing', str(session))

    def test_attendance_record_creation(self):
        session = AttendanceSession.objects.create(subject=self.subject)
        record = AttendanceRecord.objects.create(
            session=session,
            student=self.student1,
            status=AttendanceRecord.Status.ABSENT
        )
        self.assertEqual(record.status, 'ABSENT')
        
        # Test unique constraint (same student in same session)
        with self.assertRaises(IntegrityError):
            AttendanceRecord.objects.create(
                session=session,
                student=self.student1,
                status=AttendanceRecord.Status.PRESENT
            )

    def test_activity_log_creation(self):
        log = ActivityLog.objects.create(
            actor=self.teacher,
            action='Created a session'
        )
        self.assertIn('Created a session', str(log))
        self.assertIn('teacher1', str(log))

    def test_qr_code_upload_path(self):
        session = AttendanceSession.objects.create(subject=self.subject)
        path = qr_code_upload_path(session, 'test.png')
        self.assertEqual(path, f'qr_codes/{session.pk}/test.png')
