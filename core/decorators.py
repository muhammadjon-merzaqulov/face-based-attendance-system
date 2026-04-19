"""
Usage:
    from core.decorators import role_required

    @login_required
    @role_required('ADMIN')
    def my_view(request): ...

    # Multiple roles:
    @login_required
    @role_required('ADMIN', 'TEACHER')
    def shared_view(request): ...
"""

from functools import wraps

from django.shortcuts import redirect


def role_required(*roles):
    """
    Decorator that restricts a view to users with one of the specified roles.

    Must be applied AFTER @login_required so that request.user is guaranteed
    to be authenticated.

    If the user's role is not in `roles`:
      - Redirects to their appropriate dashboard (so they aren't stuck).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('accounts:login')

            if request.user.role not in roles:
                # Redirect to the user's own dashboard instead of a 403 page
                role_dashboard_map = {
                    'ADMIN':   'core:admin_dashboard',
                    'TEACHER': 'core:teacher_dashboard',
                    'STUDENT': 'core:student_dashboard',
                }
                dest = role_dashboard_map.get(request.user.role, 'accounts:login')
                return redirect(dest)

            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator
