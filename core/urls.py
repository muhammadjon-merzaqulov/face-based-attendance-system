from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # ── Common ────────────────────────────────────────────────────────
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('task-status/<str:task_id>/', views.check_task_status, name='check_task_status'),

    # ── Subjects ──────────────────────────────────────────────────────
    path('admin-panel/subjects/',          views.admin_subjects,       name='admin_subjects'),
    path('admin-panel/subjects/add/',      views.admin_add_subject,    name='admin_add_subject'),
    path('admin-panel/subjects/<int:pk>/edit/', views.admin_edit_subject, name='admin_edit_subject'),
    path('admin-panel/subjects/<int:pk>/delete/', views.admin_delete_subject, name='admin_delete_subject'),

    # ── Admin ─────────────────────────────────────────────────────────
    path('admin-panel/',                   views.admin_dashboard,     name='admin_dashboard'),
    path('admin-panel/admins/',            views.admin_list_admins,   name='admin_list_admins'),
    path('admin-panel/admins/add/',        views.admin_add_admin,     name='admin_add_admin'),
    path('admin-panel/students/',          views.admin_list_students,  name='admin_list_students'),
    path('admin-panel/students/add/',      views.admin_add_student,    name='admin_add_student'),
    path('admin-panel/students/<int:pk>/edit/', views.admin_edit_user, name='admin_edit_student'),
    path('admin-panel/teachers/',          views.admin_list_teachers,  name='admin_list_teachers'),
    path('admin-panel/teachers/add/',      views.admin_add_teacher,    name='admin_add_teacher'),
    path('admin-panel/teachers/<int:pk>/edit/', views.admin_edit_user, name='admin_edit_teacher'),
    path('admin-panel/users/<int:pk>/delete/', views.admin_delete_user, name='admin_delete_user'),
    path('admin-panel/logs/',              views.admin_logs,           name='admin_logs'),

    # ── Teacher ───────────────────────────────────────────────────────
    path('teacher/',                       views.teacher_dashboard,      name='teacher_dashboard'),
    path('teacher/subjects/',               views.teacher_subjects,       name='teacher_subjects'),
    path('teacher/subjects/<int:subject_id>/', views.teacher_subject_detail, name='teacher_subject_detail'),
    path('teacher/students/',               views.teacher_students,       name='teacher_students'),
    path('teacher/start-session/<int:subject_id>/', views.teacher_start_session, name='teacher_start_session'),
    path('teacher/live-session/<int:session_id>/',  views.teacher_live_session,  name='teacher_live_session'),
    path('teacher/live-session/<int:session_id>/rotate-pin/', views.teacher_rotate_pin, name='teacher_rotate_pin'),
    path('teacher/live-session/<int:session_id>/poll/', views.teacher_session_poll, name='teacher_session_poll'),
    path('teacher/session/<int:session_id>/end/', views.teacher_end_session, name='teacher_end_session'),
    path('teacher/session/<int:session_id>/detail/', views.teacher_session_detail, name='teacher_session_detail'),
    path('teacher/session/<int:session_id>/update-attendance/', views.teacher_update_attendance, name='teacher_update_attendance'),

    # ── Student ───────────────────────────────────────────────────────
    path('student/',                       views.student_dashboard,      name='student_dashboard'),
    path('student/subjects/',              views.student_subjects,       name='student_subjects'),
    path('student/join/',                  views.student_join_by_pin,    name='student_join_by_pin'),
    path('student/mark-attendance/<int:session_id>/', views.student_mark_attendance, name='student_mark_attendance'),
]
