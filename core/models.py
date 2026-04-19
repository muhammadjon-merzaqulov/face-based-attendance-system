import random
import string

from django.conf import settings
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def qr_code_upload_path(instance, filename):
    """Organise QR codes under media/qr_codes/<session_id>/filename."""
    return f'qr_codes/{instance.pk}/{filename}'


def generate_pin() -> str:
    """Return a random 6-digit numeric PIN string, e.g. '048273'."""
    return ''.join(random.choices(string.digits, k=6))


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------

class Subject(models.Model):
    """
    Represents an academic course/module.

    - One Teacher is responsible for the subject (ForeignKey).
    - Many Students are enrolled (ManyToManyField).
    """
    name = models.CharField(
        max_length=150,
        help_text="Full name of the subject, e.g. 'Cloud Computing 101'.",
    )
    code = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional short subject code, e.g. 'CC-101'.",
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='subjects_taught',
        limit_choices_to={'role': 'TEACHER'},
        help_text="The teacher responsible for this subject.",
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='subjects_enrolled',
        blank=True,
        limit_choices_to={'role': 'STUDENT'},
        help_text="Students enrolled in this subject.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name}" + (f" [{self.code}]" if self.code else "")

    class Meta:
        ordering = ['name']
        verbose_name = 'Subject'
        verbose_name_plural = 'Subjects'


# ---------------------------------------------------------------------------
# AttendanceSession
# ---------------------------------------------------------------------------

class AttendanceSession(models.Model):
    """
    A single attendance-taking session created by a Teacher.

    Workflow:
      1. Teacher clicks "Start Attendance" → session created with PIN + QR.
      2. Students use the PIN/QR to open the face-verification flow.
      3. Teacher clicks "End Session" → is_active set to False.
    """
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='sessions',
        help_text="The subject this session belongs to.",
    )
    date = models.DateField(
        default=timezone.now,
        help_text="The calendar date of the session (auto-set to today).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sessions_created',
        help_text="Teacher who started this session.",
    )

    # --- PIN & QR ---------------------------------------------------------
    pin_code = models.CharField(
        max_length=6,
        unique=True,
        default=generate_pin,
        help_text="6-digit PIN students type to begin attendance.",
    )
    qr_code = models.ImageField(
        upload_to=qr_code_upload_path,
        null=True,
        blank=True,
        help_text="QR code image encoding the PIN for quick scanning.",
    )

    # --- State ------------------------------------------------------------
    is_active = models.BooleanField(
        default=True,
        help_text="While True, students can mark attendance for this session.",
    )

    def __str__(self) -> str:
        return (
            f"{self.subject} | {self.date} | PIN: {self.pin_code}"
            f" | {'Active' if self.is_active else 'Closed'}"
        )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Attendance Session'
        verbose_name_plural = 'Attendance Sessions'


# ---------------------------------------------------------------------------
# AttendanceRecord
# ---------------------------------------------------------------------------

class AttendanceRecord(models.Model):
    """
    One row per student per session – records whether they were Present/Absent.

    Created automatically (as Absent) when session starts, then updated to
    Present by the face-verification view after a successful Azure match.
    """

    class Status(models.TextChoices):
        PRESENT = 'PRESENT', 'Present'
        ABSENT  = 'ABSENT',  'Absent'
        LATE    = 'LATE',    'Late'

    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name='records',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        limit_choices_to={'role': 'STUDENT'},
    )
    timestamp = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The exact moment the student marked attendance (face verified).",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ABSENT,
    )

    def __str__(self) -> str:
        return (
            f"{self.student} | {self.session.subject} "
            f"| {self.session.date} | {self.get_status_display()}"
        )

    class Meta:
        ordering = ['-session__date', 'student__last_name']
        # Prevent duplicate records for the same student in the same session
        unique_together = [('session', 'student')]
        verbose_name = 'Attendance Record'
        verbose_name_plural = 'Attendance Records'


# ---------------------------------------------------------------------------
# ActivityLog  (lightweight audit trail)
# ---------------------------------------------------------------------------

class ActivityLog(models.Model):
    """
    Append-only log of key system events shown on the Admin Logs page.

    Examples:
      - "Student Jane Doe enrolled with Azure face data."
      - "Teacher Bob started session for Cloud Computing 101."
      - "Student Jane Doe marked Present via face recognition."
    """
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
        help_text="The user who triggered the event (null = system).",
    )
    action = models.CharField(
        max_length=300,
        help_text="Short human-readable description of what happened.",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the client that triggered the action."
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        actor_str = str(self.actor) if self.actor else "System"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {actor_str}: {self.action}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
