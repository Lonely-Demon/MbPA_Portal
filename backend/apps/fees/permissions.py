from rest_framework.permissions import BasePermission

from apps.applications.models import Application, ApplicationParty, MilestoneInstance


class CanViewFees(BasePermission):
    """ApplicationParty member OR assigned officer on any MilestoneInstance."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        app = obj if isinstance(obj, Application) else obj.application
        if ApplicationParty.objects.filter(application=app, user=request.user).exists():
            return True
        return MilestoneInstance.objects.filter(
            application=app, assigned_officer=request.user
        ).exists()


class IsOfficerForApplication(BasePermission):
    """User must be the assigned officer on an in-progress MilestoneInstance."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        app = obj if isinstance(obj, Application) else obj.application
        return MilestoneInstance.objects.filter(
            application=app,
            assigned_officer=request.user,
            status=MilestoneInstance.STATUS_IN_PROGRESS,
        ).exists()
