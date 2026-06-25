from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="csrf"),
    path("healthz/", views.HealthzView.as_view(), name="healthz"),
]
