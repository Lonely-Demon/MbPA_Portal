from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("slots/<int:milestone_instance_id>/", views.DocumentSlotListView.as_view(), name="slot-list"),
    path("upload/", views.DocumentUploadView.as_view(), name="upload"),
    path("<int:pk>/", views.DocumentDetailView.as_view(), name="detail"),
    path("<int:pk>/presigned/", views.PresignedUrlView.as_view(), name="presigned"),
]
