from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    path("", views.ApplicationListCreateView.as_view(), name="list-create"),
    path("<str:application_number>/", views.ApplicationDetailView.as_view(), name="detail"),
    path("<str:application_number>/submit/", views.ApplicationSubmitView.as_view(), name="submit"),
    path("<str:application_number>/withdraw/", views.ApplicationWithdrawView.as_view(), name="withdraw"),
    path("<str:application_number>/milestones/", views.MilestoneListView.as_view(), name="milestone-list"),
    path("<str:application_number>/milestones/<int:pk>/action/", views.MilestoneActionView.as_view(), name="milestone-action"),
    path("streams/", views.StreamListView.as_view(), name="stream-list"),
    path("status/", views.StatusLookupView.as_view(), name="status-lookup"),
]
