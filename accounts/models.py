from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


# ---------------------------------------------------------------------------
# Role choices – kept as a top-level class so other modules can import them
# ---------------------------------------------------------------------------
class UserRole(models.TextChoices):
    ADMIN   = 'ADMIN',   'Admin'
    TEACHER = 'TEACHER', 'Teacher'
    STUDENT = 'STUDENT', 'Student'


def profile_picture_upload_path(instance, filename):
    """Store profile pictures under media/profile_pics/<user_id>/filename."""
    return f'profile_pics/{instance.pk}/{filename}'


class CustomUserManager(UserManager):
    """
    Override default manager to ensure that `createsuperuser` CLI 
    allocates the ADMIN role, so superusers don't get trapped as STUDENTs.
    """
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', UserRole.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Central user model.  All three roles (Admin, Teacher, Student) share
    this model – the `role` field gates which views they can access.
    """
    
    objects = CustomUserManager()

    role = models.CharField(
        max_length=10,
        choices=UserRole.choices,
        default=UserRole.STUDENT,
        help_text="Determines the user's access level and dashboard.",
    )

    profile_picture = models.ImageField(
        upload_to=profile_picture_upload_path,
        null=True,
        blank=True,
        help_text="Optional profile photo shown in the UI. Does not affect Azure.",
    )

    # Populated during face enrollment (folder identifier for disk images)
    azure_person_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Person folder ID in local face_db. Set during enrollment.",
    )

    # Averaged ArcFace embedding vector (list of 512 floats) computed from
    # the 3 enrollment photos. Used for fast real-time attendance verification.
    face_encodings = models.JSONField(
        null=True,
        blank=True,
        help_text="Averaged face embedding vector (512 floats) for recognition.",
    )

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------
    @property
    def is_admin_role(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_teacher(self) -> bool:
        return self.role == UserRole.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == UserRole.STUDENT

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.username

    def __str__(self) -> str:
        return f"{self.full_name} ({self.get_role_display()})"

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['last_name', 'first_name']
