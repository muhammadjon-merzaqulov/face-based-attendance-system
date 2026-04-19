"""
core/views.py

All application views organised by role section.

Sections:
  1. Common         — dashboard redirect
  2. Admin          — dashboard, students (add/list), teachers (add), logs
  3. Teacher        — dashboard stub (Phase 3)
  4. Student        — dashboard stub (Phase 3)
"""

import base64
import io
import json
import logging

import qrcode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import User, UserRole
from core.decorators import role_required
from core.models import ActivityLog, AttendanceRecord, AttendanceSession, Subject
from celery.result import AsyncResult
from .tasks import process_student_enrollment_task, verify_student_face_task
from core.utils import get_client_ip

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Common
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def dashboard_redirect(request):
    """
    Entry point after login — redirect to the role-appropriate dashboard.
    """
    mapping = {
        UserRole.ADMIN:   'core:admin_dashboard',
        UserRole.TEACHER: 'core:teacher_dashboard',
        UserRole.STUDENT: 'core:student_dashboard',
    }
    dest = mapping.get(request.user.role, 'accounts:login')
    return redirect(dest)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Admin Views
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@role_required('ADMIN')
def admin_dashboard(request):
    """
    Admin overview — system-wide statistics and recent activity log.
    """
    total_students = User.objects.filter(role=UserRole.STUDENT).count()
    total_teachers = User.objects.filter(role=UserRole.TEACHER).count()
    total_subjects = Subject.objects.count()
    enrolled_count = User.objects.filter(
        role=UserRole.STUDENT, face_encodings__isnull=False
    ).count()

    # System-wide attendance percentage
    total_records   = AttendanceRecord.objects.count()
    present_records = AttendanceRecord.objects.filter(
        status=AttendanceRecord.Status.PRESENT
    ).count()
    late_records = AttendanceRecord.objects.filter(
        status=AttendanceRecord.Status.LATE
    ).count()
    score = present_records + (late_records * 0.5)
    attendance_pct = (
        round(score / total_records * 100, 1) if total_records else 0
    )

    recent_logs = ActivityLog.objects.select_related('actor').all()[:8]

    return render(request, 'core/admin/dashboard.html', {
        'page_title':      'Admin Dashboard',
        'total_students':  total_students,
        'total_teachers':  total_teachers,
        'total_subjects':  total_subjects,
        'enrolled_count':  enrolled_count,
        'attendance_pct':  attendance_pct,
        'recent_logs':     recent_logs,
    })


# ── Students ─────────────────────────────────────────────────────────────────

@login_required
@role_required('ADMIN')
def admin_list_students(request):
    """Paginated list of all student accounts with enrollment status."""
    students = (
        User.objects.filter(role=UserRole.STUDENT)
        .order_by('last_name', 'first_name')
    )
    return render(request, 'core/admin/list_students.html', {
        'page_title': 'Manage Students',
        'students':   students,
    })


@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_add_student(request):
    """
    GET  → Render enrollment form + live camera interface.
    POST → AJAX JSON endpoint that:
             1. Decodes 3 base64 face images.
             2. Extracts ArcFace embeddings via DeepFace.
             3. Averages embedding vectors into one canonical vector.
             4. Creates the User and saves face_encodings + person_id.
             5. Logs the activity.
             6. Returns JSON {success, message} or {success: false, error}.
    """
    # ── GET ──────────────────────────────────────────────────────────────
    if request.method == 'GET':
        return render(request, 'core/admin/add_student.html', {
            'page_title': 'Enroll New Student',
        })

    # ── POST (AJAX) ──────────────────────────────────────────────────────
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {'success': False, 'error': 'Invalid JSON payload.'}, status=400
        )

    # Field extraction
    first_name = data.get('first_name', '').strip()
    last_name  = data.get('last_name',  '').strip()
    username   = data.get('username',   '').strip()
    email      = data.get('email',      '').strip()
    password   = data.get('password',   '')
    images_b64 = data.get('images',     [])   # list of data-URL strings

    # ── Validate required fields ─────────────────────────────────────────
    missing = [f for f, v in [
        ('First Name', first_name), ('Last Name', last_name),
        ('Username',   username),   ('Password',  password),
    ] if not v]
    if missing:
        return JsonResponse(
            {'success': False, 'error': f"Required fields missing: {', '.join(missing)}."},
            status=400,
        )

    if not images_b64:
        return JsonResponse(
            {'success': False, 'error': 'At least 1 face photo is required.'}, status=400
        )

    if User.objects.filter(username=username).exists():
        return JsonResponse(
            {'success': False, 'error': f'Username "{username}" is already taken.'},
            status=409,
        )

    # ── Trigger Celery Task ───────────────────────────────────────────────
    task = process_student_enrollment_task.delay(
        first_name, last_name, username, email, password, images_b64, request.user.id, get_client_ip(request)
    )

    return JsonResponse({
        'success': True,
        'task_id': task.id,
        'message': 'Student enrollment is processing in background...'
    })


# ── Admins ────────────────────────────────────────────────────────────────────

@login_required
@role_required('ADMIN')
def admin_list_admins(request):
    """List all admin accounts."""
    admins = (
        User.objects.filter(role=UserRole.ADMIN)
        .order_by('last_name', 'first_name')
    )
    return render(request, 'core/admin/list_admins.html', {
        'page_title': 'Manage Admins',
        'admins':     admins,
    })

@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_add_admin(request):
    """
    GET  → Render admin creation form.
    POST → AJAX: create Admin account.
    """
    if request.method == 'GET':
        return render(request, 'core/admin/add_admin.html', {
            'page_title': 'Add New Admin',
        })

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    first_name = data.get('first_name', '').strip()
    last_name  = data.get('last_name',  '').strip()
    username   = data.get('username',   '').strip()
    email      = data.get('email',      '').strip()
    password   = data.get('password',   '')

    if not all([first_name, last_name, username, password]):
        return JsonResponse(
            {'success': False, 'error': 'All fields are required.'}, status=400
        )

    if User.objects.filter(username=username).exists():
        return JsonResponse(
            {'success': False, 'error': f'Username "{username}" is already taken.'}, status=409
        )

    new_admin = User.objects.create_user(
        username=username, email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=UserRole.ADMIN, is_staff=True, is_superuser=True
    )
    ActivityLog.objects.create(
        actor  = request.user,
        action = f"Created admin: {new_admin.get_full_name()} (@{new_admin.username}).",
        ip_address = get_client_ip(request)
    )

    return JsonResponse({
        'success': True,
        'message': f'Admin {new_admin.get_full_name()} created successfully!',
    })


# ── Teachers ──────────────────────────────────────────────────────────────────

@login_required
@role_required('ADMIN')
def admin_list_teachers(request):
    """List all teacher accounts."""
    teachers = (
        User.objects.filter(role=UserRole.TEACHER)
        .order_by('last_name', 'first_name')
    )
    return render(request, 'core/admin/list_teachers.html', {
        'page_title': 'Manage Teachers',
        'teachers':   teachers,
    })


@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_add_teacher(request):
    """
    GET  → Render teacher creation form.
    POST → AJAX: create Teacher account (no face enrollment required).
    """
    if request.method == 'GET':
        return render(request, 'core/admin/add_teacher.html', {
            'page_title': 'Add New Teacher',
        })

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    first_name = data.get('first_name', '').strip()
    last_name  = data.get('last_name',  '').strip()
    username   = data.get('username',   '').strip()
    email      = data.get('email',      '').strip()
    password   = data.get('password',   '')

    if not all([first_name, last_name, username, password]):
        return JsonResponse(
            {'success': False, 'error': 'All fields are required.'}, status=400
        )

    if User.objects.filter(username=username).exists():
        return JsonResponse(
            {'success': False, 'error': f'Username "{username}" is already taken.'}, status=409
        )

    teacher = User.objects.create_user(
        username=username, email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=UserRole.TEACHER,
    )
    ActivityLog.objects.create(
        actor  = request.user,
        action = f"Created teacher: {teacher.get_full_name()} (@{teacher.username}).",
        ip_address = get_client_ip(request)
    )

    return JsonResponse({
        'success': True,
        'message': f'Teacher {teacher.get_full_name()} created successfully!',
    })


@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_edit_user(request, pk):
    from django.contrib import messages
    target_user = get_object_or_404(User, pk=pk)
    
    # Don't allow editing other admins unless superuser? For simplicity, just text fields.
    if request.method == 'GET':
        return render(request, 'core/admin/edit_user.html', {
            'target_user': target_user,
            'page_title': f'Edit {target_user.get_full_name()}',
        })
        
    # POST
    target_user.first_name = request.POST.get('first_name', '').strip()
    target_user.last_name = request.POST.get('last_name', '').strip()
    target_user.email = request.POST.get('email', '').strip()
    
    new_username = request.POST.get('username', '').strip()
    if new_username and new_username != target_user.username:
        if User.objects.filter(username=new_username).exists():
            messages.error(request, "Username is already taken.")
            if target_user.role == UserRole.STUDENT:
                return redirect('core:admin_edit_student', pk=pk)
            elif target_user.role == UserRole.TEACHER:
                return redirect('core:admin_edit_teacher', pk=pk)
            else:
                return redirect('core:admin_list_admins')
        target_user.username = new_username
        
    password = request.POST.get('password')
    if password:
        target_user.set_password(password)
        
    target_user.save()
    ActivityLog.objects.create(actor=request.user, action=f"Edited user details for @{target_user.username}.", ip_address=get_client_ip(request))
    messages.success(request, f"Updated details for {target_user.get_full_name()} successfully!")
    
    if target_user.role == UserRole.STUDENT:
        return redirect('core:admin_list_students')
    elif target_user.role == UserRole.TEACHER:
        return redirect('core:admin_list_teachers')
    return redirect('core:admin_list_admins')


@login_required
@role_required('ADMIN')
@require_http_methods(['POST', 'GET'])
def admin_delete_user(request, pk):
    from django.contrib import messages
    target_user = get_object_or_404(User, pk=pk)
    
    if target_user == request.user:
        messages.error(request, "You cannot delete yourself.")
        return redirect('core:admin_dashboard')
        
    role = target_user.role
    username = target_user.username
    target_user.delete()
    
    ActivityLog.objects.create(actor=request.user, action=f"Deleted user @{username}.", ip_address=get_client_ip(request))
    messages.success(request, f"User @{username} safely deleted.")
    
    if role == UserRole.STUDENT:
        return redirect('core:admin_list_students')
    elif role == UserRole.TEACHER:
        return redirect('core:admin_list_teachers')
    return redirect('core:admin_list_admins')


# ── Subjects ──────────────────────────────────────────────────────────────────

@login_required
@role_required('ADMIN')
def admin_subjects(request):
    """View and manage subjects."""
    subjects = Subject.objects.select_related('teacher').prefetch_related('students').all()
    return render(request, 'core/admin/subjects.html', {
        'page_title': 'Manage Subjects',
        'subjects':   subjects,
    })


@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_add_subject(request):
    """Create a new subject and assign teacher and students."""
    from django.contrib import messages
    
    if request.method == 'GET':
        teachers = User.objects.filter(role=UserRole.TEACHER).order_by('last_name', 'first_name')
        students = User.objects.filter(role=UserRole.STUDENT).order_by('last_name', 'first_name')
        
        return render(request, 'core/admin/add_subject.html', {
            'page_title': 'Add New Subject',
            'teachers': teachers,
            'students': students,
        })
        
    # POST handling
    name = request.POST.get('name', '').strip()
    code = request.POST.get('code', '').strip()
    teacher_id = request.POST.get('teacher')
    student_ids = request.POST.getlist('students')  # multiple select
    
    if not name:
        messages.error(request, "Subject name is required.")
        return redirect('core:admin_add_subject')
        
    teacher = None
    if teacher_id:
        teacher = User.objects.filter(pk=teacher_id, role=UserRole.TEACHER).first()
        
    subject = Subject.objects.create(
        name=name,
        code=code,
        teacher=teacher
    )
    
    if student_ids:
        assigned_students = User.objects.filter(pk__in=student_ids, role=UserRole.STUDENT)
        subject.students.set(assigned_students)
        
    ActivityLog.objects.create(
        actor=request.user,
        action=f"Created subject: {subject.name} with {subject.students.count()} students.",
        ip_address=get_client_ip(request)
    )
    
    messages.success(request, f"Subject '{subject.name}' created successfully!")
    return redirect('core:admin_subjects')


@login_required
@role_required('ADMIN')
@require_http_methods(['GET', 'POST'])
def admin_edit_subject(request, pk):
    from django.contrib import messages
    subject = get_object_or_404(Subject, pk=pk)
    
    if request.method == 'GET':
        teachers = User.objects.filter(role=UserRole.TEACHER).order_by('last_name')
        students = User.objects.filter(role=UserRole.STUDENT).order_by('last_name')
        enrolled_ids = list(subject.students.values_list('id', flat=True))
        
        return render(request, 'core/admin/edit_subject.html', {
            'page_title': f'Edit {subject.name}',
            'subject': subject,
            'teachers': teachers,
            'students': students,
            'enrolled_ids': enrolled_ids,
        })
        
    subject.name = request.POST.get('name', '').strip()
    subject.code = request.POST.get('code', '').strip()
    
    teacher_id = request.POST.get('teacher')
    subject.teacher = User.objects.filter(pk=teacher_id, role=UserRole.TEACHER).first() if teacher_id else None
    
    student_ids = request.POST.getlist('students')
    if student_ids:
        subject.students.set(User.objects.filter(pk__in=student_ids, role=UserRole.STUDENT))
    else:
        subject.students.clear()
        
    subject.save()
    ActivityLog.objects.create(actor=request.user, action=f"Modified subject: {subject.name}.", ip_address=get_client_ip(request))
    messages.success(request, f"Subject '{subject.name}' updated successfully!")
    return redirect('core:admin_subjects')


@login_required
@role_required('ADMIN')
@require_http_methods(['POST', 'GET'])
def admin_delete_subject(request, pk):
    from django.contrib import messages
    subject = get_object_or_404(Subject, pk=pk)
    name = subject.name
    subject.delete()
    
    ActivityLog.objects.create(actor=request.user, action=f"Deleted subject: {name}.", ip_address=get_client_ip(request))
    messages.success(request, f"Subject '{name}' deleted permanently.")
    return redirect('core:admin_subjects')


# ── Activity Logs ─────────────────────────────────────────────────────────────

@login_required
@role_required('ADMIN')
def admin_logs(request):
    """System activity log — paginated or limited, with advanced filtering."""
    from datetime import datetime, time
    from django.utils.timezone import make_aware

    logs = ActivityLog.objects.select_related('actor').all()
    
    user_id = request.GET.get('user_id', '')
    action_query = request.GET.get('action', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if user_id:
        logs = logs.filter(actor_id=user_id)
        
    if action_query:
        logs = logs.filter(action__icontains=action_query)
        
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d")
            df = make_aware(datetime.combine(df, time.min))
            logs = logs.filter(timestamp__gte=df)
        except ValueError:
            pass
            
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            dt = make_aware(datetime.combine(dt, time.max))
            logs = logs.filter(timestamp__lte=dt)
        except ValueError:
            pass

    from django.core.paginator import Paginator
    paginator = Paginator(logs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all users who have triggered an action for the dropdown
    active_users = User.objects.filter(activity_logs__isnull=False).distinct().order_by('last_name', 'first_name')

    return render(request, 'core/admin/logs.html', {
        'page_title': 'Activity Logs',
        'logs':       page_obj,
        'page_obj':   page_obj,
        'active_users': active_users,
        'filters': {
            'user_id': user_id,
            'action': action_query,
            'date_from': date_from,
            'date_to': date_to,
        }
    })


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Teacher Views  (Phase 3 stubs)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@role_required('TEACHER')
def teacher_dashboard(request):
    """Teacher dashboard — KPI cards."""
    teacher  = request.user
    subjects_count = Subject.objects.filter(teacher=teacher).count()

    total_students = (
        User.objects.filter(subjects_enrolled__teacher=teacher)
        .distinct()
        .count()
    )

    return render(request, 'core/teacher/dashboard.html', {
        'page_title':     'Teacher Dashboard',
        'subjects_count': subjects_count,
        'total_students': total_students,
    })


@login_required
@role_required('TEACHER')
def teacher_subjects(request):
    """List all subjects for the teacher."""
    teacher = request.user
    subjects = Subject.objects.filter(teacher=teacher).prefetch_related('students')
    return render(request, 'core/teacher/subjects.html', {
        'page_title': 'My Subjects',
        'subjects': subjects,
    })


@login_required
@role_required('TEACHER')
def teacher_subject_detail(request, subject_id):
    """Show details of a specific subject including past attendance sessions and enrolled student stats."""
    subject = get_object_or_404(Subject, pk=subject_id, teacher=request.user)
    sessions = subject.sessions.all().order_by('-date', '-created_at')
    
    students_stats = []
    subject_students = subject.students.all()
    subject_records = AttendanceRecord.objects.filter(session__subject=subject)

    for st in subject_students:
        s_records = subject_records.filter(student=st)
        total = s_records.count()
        present = s_records.filter(status=AttendanceRecord.Status.PRESENT).count()
        late = s_records.filter(status=AttendanceRecord.Status.LATE).count()
        absent = s_records.filter(status=AttendanceRecord.Status.ABSENT).count()
        score = present + (late * 0.5)
        pct = round((score / total) * 100) if total > 0 else 0
        students_stats.append({
            'student': st,
            'total': total,
            'present': present,
            'late': late,
            'absent': absent,
            'pct': pct
        })
        
    # Sort ascending by percentage
    students_stats.sort(key=lambda x: (x['pct'], x['student'].last_name or ''))
    
    return render(request, 'core/teacher/subject_detail.html', {
        'page_title': subject.name,
        'subject': subject,
        'sessions': sessions,
        'students_stats': students_stats,
    })


@login_required
@role_required('TEACHER')
def teacher_students(request):
    """List all unique students in teacher's subjects and their attendance percentages, including per-subject breakdown."""
    teacher = request.user
    students = User.objects.filter(subjects_enrolled__teacher=teacher, role=UserRole.STUDENT).distinct()
    
    student_data = []
    for st in students:
        records = AttendanceRecord.objects.filter(student=st, session__subject__teacher=teacher)
        total = records.count()
        present = records.filter(status=AttendanceRecord.Status.PRESENT).count()
        late = records.filter(status=AttendanceRecord.Status.LATE).count()
        score = present + (late * 0.5)
        pct = round((score / total) * 100) if total > 0 else 0
        
        # Per-subject breakdown
        subjects_breakdown = []
        st_subjects = st.subjects_enrolled.filter(teacher=teacher)
        for sub in st_subjects:
            sub_records = records.filter(session__subject=sub)
            s_total = sub_records.count()
            s_present = sub_records.filter(status=AttendanceRecord.Status.PRESENT).count()
            s_late = sub_records.filter(status=AttendanceRecord.Status.LATE).count()
            s_absent = sub_records.filter(status=AttendanceRecord.Status.ABSENT).count()
            s_score = s_present + (s_late * 0.5)
            s_pct = round((s_score / s_total) * 100) if s_total > 0 else 0
            
            subjects_breakdown.append({
                'subject_name': sub.name,
                'total': s_total,
                'present': s_present,
                'late': s_late,
                'absent': s_absent,
                'pct': s_pct
            })
            
        student_data.append({
            'student': st,
            'total_sessions': total,
            'present_sessions': present,
            'late_sessions': late,
            'pct': pct,
            'subjects_breakdown': subjects_breakdown
        })
        
    student_data.sort(key=lambda x: x['student'].last_name or '')

    return render(request, 'core/teacher/students.html', {
        'page_title': 'My Students',
        'student_data': student_data,
    })


@login_required
@role_required('TEACHER')
@require_http_methods(['POST'])
def teacher_start_session(request, subject_id):
    """Start an attendance session, generate PIN and QR code."""
    subject = get_object_or_404(Subject, pk=subject_id, teacher=request.user)
    
    # See if there's already an active session today
    session, created = AttendanceSession.objects.get_or_create(
        subject=subject,
        date=timezone.now().date(),
        is_active=True,
        defaults={'created_by': request.user}
    )
    
    # Generate QR dynamically for the new PIN
    qr_url = request.build_absolute_uri(reverse('core:student_join_by_pin') + f'?pin={session.pin_code}')
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    session.qr_code.save(f'session_{session.pk}_qr.png', ContentFile(buffer.getvalue()), save=True)
    
    # Pre-populate AttendanceRecord as ABSENT for all enrolled students
    students = subject.students.all()
    records_to_create = [
        AttendanceRecord(session=session, student=student, status=AttendanceRecord.Status.ABSENT)
        for student in students
    ]
    AttendanceRecord.objects.bulk_create(records_to_create, ignore_conflicts=True)
    
    ActivityLog.objects.create(
        actor=request.user,
        action=f"Started attendance session for {subject.name}.",
        ip_address=get_client_ip(request)
    )

    return redirect('core:teacher_live_session', session_id=session.pk)


@login_required
@role_required('TEACHER')
def teacher_rotate_pin(request, session_id):
    """AJAX endpoint to rotate PIN and QR every 30s so they expire."""
    import os
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    
    # Generate new pin
    from core.models import generate_pin
    session.pin_code = generate_pin()
    
    qr_url = request.build_absolute_uri(reverse('core:student_join_by_pin') + f'?pin={session.pin_code}')
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    
    if session.qr_code:
        try:
            os.remove(session.qr_code.path)
        except OSError:
            pass
            
    session.qr_code.save(f'session_{session.pk}_qr.png', ContentFile(buffer.getvalue()), save=True)
    session.save(update_fields=['pin_code'])
    
    return JsonResponse({
        'success': True,
        'pin_code': session.pin_code,
        'qr_url': session.qr_code.url
    })


@login_required
@role_required('TEACHER')
def teacher_live_session(request, session_id):
    """Display the live projector UI."""
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    
    # Get all records for initial render
    records = session.records.select_related('student').order_by('student__last_name', 'student__first_name')
    
    return render(request, 'core/teacher/live_session.html', {
        'page_title': f'Live Attendance - {session.subject.name}',
        'session': session,
        'records': records,
    })


@login_required
@role_required('TEACHER')
def teacher_session_poll(request, session_id):
    """AJAX endpoint for polling student attendance status."""
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    records = session.records.select_related('student').order_by('student__last_name', 'student__first_name')
    
    data = []
    for r in records:
        data.append({
            'student_id': r.student.pk,
            'name': r.student.get_full_name(),
            'status': r.status,
            'timestamp': r.timestamp.strftime('%H:%M:%S') if r.timestamp else None,
            'initials': f"{r.student.first_name[0].upper()}{r.student.last_name[0].upper()}" if r.student.first_name else 'S'
        })
        
    return JsonResponse({'success': True, 'records': data})


@login_required
@role_required('TEACHER')
def teacher_end_session(request, session_id):
    """End the live session and redirect to session details to edit attendance."""
    import os
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    session.is_active = False

    # Delete QR Code file from disk to save space
    if session.qr_code:
        try:
            if os.path.isfile(session.qr_code.path):
                os.remove(session.qr_code.path)
            session.qr_code = None
        except Exception as e:
            logger.error(f"Error deleting QR code for session {session.pk}: {e}")

    session.save(update_fields=['is_active', 'qr_code'])
    
    from django.contrib import messages
    messages.success(request, f"Attendance session for {session.subject.name} ended. You can now edit records.")
    return redirect('core:teacher_session_detail', session_id=session.pk)


@login_required
@role_required('TEACHER')
def teacher_session_detail(request, session_id):
    """View and edit attendance after a session has ended."""
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    
    records = session.records.select_related('student').order_by('student__last_name', 'student__first_name')
    
    return render(request, 'core/teacher/session_detail.html', {
        'page_title': f'Session Details: {session.subject.name}',
        'session': session,
        'records': records,
    })


@login_required
@role_required('TEACHER')
@require_http_methods(['POST'])
def teacher_update_attendance(request, session_id):
    """AJAX endpoint to update a specific student's attendance record (Present, Late, Absent)."""
    session = get_object_or_404(AttendanceSession, pk=session_id, subject__teacher=request.user)
    
    try:
        data = json.loads(request.body)
        student_id = data.get('student_id')
        status = data.get('status')
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid request payload.'}, status=400)
        
    if status not in [c[0] for c in AttendanceRecord.Status.choices]:
        return JsonResponse({'success': False, 'error': 'Invalid status.'}, status=400)
        
    record = get_object_or_404(AttendanceRecord, session=session, student_id=student_id)
    
    record.status = status
    if status in [AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE]:
        if not record.timestamp:
            record.timestamp = timezone.now()
    else:
        record.timestamp = None
        
    record.save(update_fields=['status', 'timestamp'])
    
    return JsonResponse({'success': True, 'message': 'Attendance updated.'})


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Student Views
# ══════════════════════════════════════════════════════════════════════════════

@login_required
@role_required('STUDENT')
def student_dashboard(request):
    """Student dashboard."""
    student = request.user
    subjects = student.subjects_enrolled.select_related('teacher').all()

    # Calculate overall attendance %
    all_records = AttendanceRecord.objects.filter(student=student)
    total_all = all_records.count()
    present_all = all_records.filter(status=AttendanceRecord.Status.PRESENT).count()
    late_all = all_records.filter(status=AttendanceRecord.Status.LATE).count()
    score_all = present_all + (late_all * 0.5)
    overall_pct = round((score_all / total_all) * 100) if total_all > 0 else 0

    return render(request, 'core/student/dashboard.html', {
        'page_title': 'My Dashboard',
        'subjects_count': subjects.count(),
        'overall_pct': overall_pct,
    })


@login_required
@role_required('STUDENT')
def student_subjects(request):
    """List all enrolled subjects with attendance details."""
    student = request.user
    subjects = student.subjects_enrolled.select_related('teacher').all()

    # Calculate attendance % per subject
    subject_data = []
    for sub in subjects:
        records = AttendanceRecord.objects.filter(student=student, session__subject=sub)
        total = records.count()
        present = records.filter(status=AttendanceRecord.Status.PRESENT).count()
        late = records.filter(status=AttendanceRecord.Status.LATE).count()
        absent = records.filter(status=AttendanceRecord.Status.ABSENT).count()
        score = present + (late * 0.5)
        pct = round((score / total) * 100) if total > 0 else 0
        
        subject_data.append({
            'subject': sub,
            'total': total,
            'present': present,
            'late': late,
            'absent': absent,
            'pct': pct,
        })

    return render(request, 'core/student/subjects.html', {
        'page_title': 'My Subjects',
        'subject_data': subject_data,
    })


@login_required
@role_required('STUDENT')
@require_http_methods(['GET', 'POST'])
def student_join_by_pin(request):
    """Handle joining an attendance session by 6-digit PIN via QR Scan or Input."""
    pin = request.GET.get('pin') or request.POST.get('pin_code', '')
    pin = pin.strip()
    
    session = AttendanceSession.objects.filter(pin_code=pin, is_active=True).first()
    
    if not session:
        messages.error(request, "Invalid or expired session PIN. Please scan the newest QR code on the board.")
        return redirect('core:student_dashboard')
        
    # Mark in session token so they can refresh camera view without losing URL validity
    request.session[f'pin_verified_{session.pk}'] = True
    return redirect('core:student_mark_attendance', session_id=session.pk)


@login_required
@role_required('STUDENT')
@require_http_methods(['GET', 'POST'])
def student_mark_attendance(request, session_id):
    """Handle student face verification."""
    student = request.user
    session = get_object_or_404(AttendanceSession, pk=session_id)
    
    # Must have joined via a valid PIN
    if not request.session.get(f'pin_verified_{session.pk}'):
        messages.error(request, "You must join via an active QR code or PIN provided by the instructor.")
        return redirect('core:student_dashboard')

    
    # Must be enrolled
    if not session.subject.students.filter(pk=student.pk).exists():
        if request.method == 'POST':
            return JsonResponse({'success': False, 'error': 'You are not enrolled in this subject.'}, status=403)
        messages.error(request, 'You are not enrolled in this subject.')
        return redirect('core:student_dashboard')

    # Must be active
    if not session.is_active:
        if request.method == 'POST':
            return JsonResponse({'success': False, 'error': 'This session is no longer active.'}, status=400)
        messages.error(request, 'This session is no longer active.')
        return redirect('core:student_dashboard')
        
    record = get_object_or_404(AttendanceRecord, session=session, student=student)
    
    if request.method == 'GET':
        if record.status == AttendanceRecord.Status.PRESENT:
            messages.success(request, f"You are already marked present for {session.subject.name}.")
            return redirect('core:student_dashboard')
            
        return render(request, 'core/student/mark_attendance.html', {
            'page_title': 'Verify Face',
            'session': session,
        })
        
    # ── POST (AJAX Verification) ──
    try:
        data = json.loads(request.body)
        image_b64 = data.get('image')
    except Exception:
        return JsonResponse({'success': False, 'error': 'Invalid request payload.'}, status=400)
        
    if not image_b64:
        return JsonResponse({'success': False, 'error': 'No image provided.'}, status=400)
        
    try:
        if ',' in image_b64:
            image_b64 = image_b64.split(',', 1)[1]
        base64.b64decode(image_b64) # Test if corrupted
    except Exception:
        return JsonResponse({'success': False, 'error': 'Corrupted image data.'}, status=400)
        
    if not student.face_encodings:
        return JsonResponse({'success': False, 'error': 'You do not have a face enrolled. Contact Admin.'}, status=400)
        
    task = verify_student_face_task.delay(session.pk, student.pk, image_b64, get_client_ip(request))
    
    return JsonResponse({
        'success': True,
        'task_id': task.id,
        'message': 'Verifying face in background...'
    })

@login_required
def check_task_status(request, task_id):
    """AJAX endpoint for frontend to poll Celery task status."""
    task = AsyncResult(task_id)
    if task.state == 'FAILURE':
        response = {
            'state': task.state,
            'success': False,
            'error': str(task.info)
        }
    elif task.state == 'SUCCESS':
        response = {
            'state': task.state,
            'success': task.result.get('success', False),
        }
        if response['success']:
            response['message'] = task.result.get('message', '')
        else:
            response['error'] = task.result.get('error', 'Unknown error occurred.')
    else:
        response = {
            'state': task.state,
            'success': False,
            'message': 'Processing...'
        }
    return JsonResponse(response)
