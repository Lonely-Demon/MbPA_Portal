from django.urls import path

from . import views

app_name = "certificates"

urlpatterns = [
    path("<str:application_number>/", views.CertificateView.as_view(), name="detail"),
    path(
        "<str:application_number>/download/",
        views.CertificateDownloadView.as_view(),
        name="download",
    ),
    path("<str:application_number>/verify/", views.CertificateVerifyView.as_view(), name="verify"),
]
