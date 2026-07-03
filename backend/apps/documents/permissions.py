from rest_framework.permissions import BasePermission

from apps.applications.models import ApplicationParty, MilestoneInstance
from apps.documents.models import DocumentUpload


class CanAccessDocument(BasePermission):
    """Allow access if the requesting user is an ApplicationParty on the document's
    application, or is assigned_officer on any MilestoneInstance for it."""

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, DocumentUpload):
            return False
        application = obj.application
        if ApplicationParty.objects.filter(application=application, user=request.user).exists():
            return True
        return MilestoneInstance.objects.filter(
            application=application, assigned_officer=request.user
        ).exists()
