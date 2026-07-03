from django.urls import path

from . import views

app_name = "compliance"

urlpatterns = [
    path(
        "audit/<str:target_type>/<int:target_id>/",
        views.AuditEventListView.as_view(),
        name="audit-list",
    ),
    path("complaints/", views.ComplaintListCreateView.as_view(), name="complaint-list-create"),
    path("complaints/<int:pk>/", views.ComplaintDetailView.as_view(), name="complaint-detail"),
    path(
        "erasure-requests/",
        views.ErasureRequestListCreateView.as_view(),
        name="erasure-list-create",
    ),
    path(
        "erasure-requests/<int:pk>/process/",
        views.ErasureRequestProcessView.as_view(),
        name="erasure-process",
    ),
    path(
        "clearances/<str:application_number>/",
        views.ConditionalClearanceListView.as_view(),
        name="clearance-list",
    ),
    path(
        "clearances/<str:application_number>/create/",
        views.ConditionalClearanceCreateView.as_view(),
        name="clearance-create",
    ),
    path(
        "clearances/<int:pk>/fulfill/",
        views.ConditionalClearanceFulfillView.as_view(),
        name="clearance-fulfill",
    ),
]
