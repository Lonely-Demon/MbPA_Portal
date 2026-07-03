from rest_framework.permissions import BasePermission

from .models import Application, MilestoneInstance


class IsAssignedOfficer(BasePermission):
    """
    AC-08 object-level permission: only the officer assigned to a
    MilestoneInstance may act on it.

    CRIT: assigned_officer is a nullable FK (SET_NULL when an officer is
    deactivated, and left unset if no active officer covers the required
    role at submission time). Comparing assigned_officer_id == request.user.pk
    directly would let an unauthenticated request (whose .pk is also None)
    pass on any instance with no officer assigned yet, so both sides are
    checked for None explicitly and authentication is required up front.
    """

    message = "You are not the officer assigned to this milestone."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, MilestoneInstance):
            return False
        if obj.assigned_officer_id is None:
            return False
        return obj.assigned_officer_id == request.user.pk


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
