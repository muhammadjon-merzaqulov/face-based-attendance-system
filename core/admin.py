from django.contrib import admin
from django.utils.html import format_html

from .models import ActivityLog, AttendanceRecord, AttendanceSession, Subject


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display  = ('name', 'code', 'teacher', 'student_count', 'created_at')
    list_filter   = ('teacher',)
    search_fields = ('name', 'code', 'teacher__last_name')
    filter_horizontal = ('students',)  # Fancy dual-list widget for M2M

    @admin.display(description='# Students')
    def student_count(self, obj: Subject) -> int:
        return obj.students.count()


# ---------------------------------------------------------------------------
# AttendanceSession
# ---------------------------------------------------------------------------

@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display  = ('subject', 'date', 'pin_code', 'created_by', 'is_active', 'created_at')
    list_filter   = ('is_active', 'subject', 'date')
    search_fields = ('pin_code', 'subject__name', 'created_by__last_name')
    readonly_fields = ('pin_code', 'created_at', 'qr_code_preview')
    ordering = ('-created_at',)

    @admin.display(description='QR Preview')
    def qr_code_preview(self, obj: AttendanceSession):
        if obj.qr_code:
            return format_html(
                '<img src="{}" width="100" height="100" />', obj.qr_code.url
            )
        return "No QR code yet."


# ---------------------------------------------------------------------------
# AttendanceRecord (inline for Session)
# ---------------------------------------------------------------------------

class AttendanceRecordInline(admin.TabularInline):
    model  = AttendanceRecord
    extra  = 0
    fields = ('student', 'status', 'timestamp')
    readonly_fields = ('timestamp',)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display  = ('student', 'session', 'status', 'timestamp')
    list_filter   = ('status', 'session__subject', 'session__date')
    search_fields = ('student__last_name', 'student__username', 'session__pin_code')
    ordering = ('-session__date',)

    @admin.display(description='Status')
    def coloured_status(self, obj: AttendanceRecord) -> str:
        colour = 'green' if obj.status == AttendanceRecord.Status.PRESENT else 'crimson'
        return format_html(
            '<strong style="color: {};">{}</strong>',
            colour,
            obj.get_status_display(),
        )


# ---------------------------------------------------------------------------
# ActivityLog
# ---------------------------------------------------------------------------

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display  = ('timestamp', 'actor', 'action')
    list_filter   = ('actor',)
    search_fields = ('action', 'actor__username')
    readonly_fields = ('actor', 'action', 'timestamp')

    def has_add_permission(self, request) -> bool:
        return False  # Logs are created by the system, not manually

    def has_change_permission(self, request, obj=None) -> bool:
        return False  # Immutable audit trail
