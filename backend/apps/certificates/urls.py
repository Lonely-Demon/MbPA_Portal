from django.urls import path

from . import views

app_name = "certificates"

urlpatterns = [
    path("<str:application_number>/", views.CertificateListView.as_view(), name="list"),
    path(
        "<str:application_number>/<int:pk>/download/",
        views.CertificateDownloadView.as_view(),
        name="download",
    ),
    path(
        "<str:application_number>/<int:pk>/receive-signed/",
        views.CertificateReceiveSignedView.as_view(),
        name="receive-signed",
    ),
]
