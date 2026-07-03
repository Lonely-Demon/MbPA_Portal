from rest_framework.permissions import BasePermission

from .models import Application, MilestoneInstance


class IsAssignedOfficer(BasePermission):
    """
    AC-08 object-level permission: only the officer assigned to a
    MilestoneInstance may act on it.
    """

    message = "You are not the officer assigned to this milestone."

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, MilestoneInstance):
            return obj.assigned_officer_id == request.user.pk
        return False


class CanAccessApplication(BasePermission):
    """
    Object-level permission for Application instances (CRIT-2/3/4, HIGH-1).

    Grants access to:
      - the user who submitted the application
      - any ApplicationParty member
      - any officer assigned to one of the application's milestone instances
      - admin / staff users

    Returns 404 phrasing so callers can present a uniform "Not found." error
    instead of "Forbidden." to avoid enumerating application existence.
    """

    message = "Not found."

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Application):
            return False
        user = request.user
        if user.is_staff or getattr(user, "user_type", None) == "admin":
            return True
        if obj.submitted_by_id == user.pk:
            return True
        if obj.parties.filter(user=user).exists():
            return True
        if obj.milestone_instances.filter(assigned_officer=user).exists():
            return True
        return False
