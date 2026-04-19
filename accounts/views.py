import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from core.models import ActivityLog
from core.utils import get_client_ip

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Login / Logout
# ─────────────────────────────────────────────────────────────────────────────

def login_view(request):
    """
    Show login page (GET) and authenticate (POST).

    On success → dashboard_redirect resolves the user's role and sends them
    to the right dashboard.
    On failure → re-render login page with an error message.
    """
    if request.user.is_authenticated:
        return redirect('core:dashboard_redirect')

    error = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_active:
                login(request, user)
                logger.info("User '%s' logged in (role=%s).", user.username, user.role)
                ActivityLog.objects.create(
                    actor=user,
                    action="Login",
                    ip_address=get_client_ip(request)
                )
                next_url = request.GET.get('next', '')
                return redirect(next_url if next_url else 'core:dashboard_redirect')
            else:
                error = 'Your account has been disabled. Please contact the administrator.'
        else:
            error = 'Invalid username or password. Please try again.'

    return render(request, 'accounts/login.html', {'error': error})


def logout_view(request):
    """Log the user out and redirect to the login page."""
    if request.user.is_authenticated:
        logger.info("User '%s' logged out.", request.user.username)
        ActivityLog.objects.create(
            actor=request.user,
            action="Logout",
            ip_address=get_client_ip(request)
        )
    logout(request)
    return redirect('accounts:login')


# ─────────────────────────────────────────────────────────────────────────────
# Profile  (all roles: Admin, Teacher, Student)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def profile_view(request):
    """
    View and update user profile.
    Handles two separate actions via a hidden 'action' field:
      • update_info  — name, email, profile picture (upload / remove)
      • change_password — current + new + confirm password
    """
    user = request.user

    if request.method == 'POST':
        action = request.POST.get('action', 'update_info')

        # ── Password change ────────────────────────────────────────────────
        if action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password     = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
            elif len(new_password) < 8:
                messages.error(request, 'New password must be at least 8 characters long.')
            elif new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
            else:
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)   # Keep user logged in
                messages.success(request, 'Password changed successfully.')
                logger.info("User '%s' changed their password.", user.username)

            return redirect('accounts:profile')

        # ── Profile info + picture ─────────────────────────────────────────
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name  = request.POST.get('last_name',  '').strip()
        user.email      = request.POST.get('email',      '').strip()

        # Remove existing picture
        if request.POST.get('remove_picture') == 'true':
            if user.profile_picture:
                user.profile_picture.delete(save=False)
            user.profile_picture = None

        # Upload new picture
        elif 'profile_picture' in request.FILES:
            pic = request.FILES['profile_picture']
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if pic.content_type not in allowed_types:
                messages.error(request, 'Only JPEG, PNG, GIF and WebP images are allowed.')
                return redirect('accounts:profile')
            if pic.size > 5 * 1024 * 1024:   # 5 MB limit
                messages.error(request, 'Image must be smaller than 5 MB.')
                return redirect('accounts:profile')
            if user.profile_picture:
                user.profile_picture.delete(save=False)
            user.profile_picture = pic

        user.save()
        messages.success(request, 'Profile updated successfully.')
        logger.info("User '%s' updated their profile.", user.username)
        return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {
        'page_title': 'My Profile',
    })
