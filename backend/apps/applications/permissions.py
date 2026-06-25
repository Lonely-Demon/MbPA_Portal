from rest_framework.permissions import BasePermission

from .models import MilestoneInstance


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
