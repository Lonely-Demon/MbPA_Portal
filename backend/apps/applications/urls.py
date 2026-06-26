from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    # Literal paths first — must precede any <str:...> capture patterns
    path("streams/", views.StreamListView.as_view(), name="stream-list"),
    path("status/", views.StatusLookupView.as_view(), name="status-lookup"),
    path("", views.ApplicationListCreateView.as_view(), name="list-create"),
    # Integer-PK routes for pre-submission access (application_number is blank on drafts)
    path("<int:pk>/", views.ApplicationDetailView.as_view(), name="detail"),
    path("<int:pk>/submit/", views.ApplicationSubmitView.as_view(), name="submit"),
    # Withdrawal only applies post-submission (application_number is set by then)
    path(
        "<str:application_number>/withdraw/",
        views.ApplicationWithdrawView.as_view(),
        name="withdraw",
    ),
    # Officer console routes — always post-submission
    path(
        "<str:application_number>/milestones/",
        views.MilestoneListView.as_view(),
        name="milestone-list",
    ),
    path(
        "<str:application_number>/milestones/<int:pk>/action/",
        views.MilestoneActionView.as_view(),
        name="milestone-action",
    ),
]
