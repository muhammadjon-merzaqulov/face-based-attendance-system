from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Extends the built-in UserAdmin to surface the three custom fields:
    role, profile_picture, and azure_person_id.
    """

    # Columns shown in the list view
    list_display = (
        'username', 'full_name', 'role', 'email',
        'is_active', 'azure_status', 'date_joined',
    )
    list_filter  = ('role', 'is_active', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('last_name', 'first_name')

    # Add our custom fields to the edit/add form fieldsets
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Attendance System', {
            'fields': ('role', 'profile_picture', 'azure_person_id'),
        }),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Attendance System', {
            'fields': ('role', 'profile_picture'),
        }),
    )

    # ------------------------------------------------------------------
    # Custom display methods
    # ------------------------------------------------------------------

    @admin.display(description='Name')
    def full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.username

    @admin.display(description='Azure Enrolled?', boolean=False)
    def azure_status(self, obj: User) -> str:
        if obj.azure_person_id:
            return format_html(
                '<span style="color: green; font-weight: bold;">✔ Enrolled</span>'
            )
        return format_html(
            '<span style="color: #999;">— Not enrolled</span>'
        )
