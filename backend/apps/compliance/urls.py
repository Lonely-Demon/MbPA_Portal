from django.urls import path

from . import views

app_name = "compliance"

urlpatterns = [
    path("audit/<str:target_type>/<int:target_id>/", views.AuditEventListView.as_view(), name="audit-list"),
    path("complaints/", views.ComplaintListCreateView.as_view(), name="complaint-list-create"),
    path("complaints/<int:pk>/", views.ComplaintDetailView.as_view(), name="complaint-detail"),
    path("clearances/<str:application_number>/", views.ConditionalClearanceListView.as_view(), name="clearance-list"),
]
