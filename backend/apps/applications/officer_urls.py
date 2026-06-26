from django.urls import path

from apps.applications import views

urlpatterns = [
    path("queue/", views.OfficerQueueView.as_view(), name="officer-queue"),
]
