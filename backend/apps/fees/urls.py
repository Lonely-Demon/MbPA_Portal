from django.urls import path

from . import views

app_name = "fees"

urlpatterns = [
    path(
        "<str:application_number>/assessment/",
        views.FeeAssessmentView.as_view(),
        name="assessment",
    ),
    path(
        "<str:application_number>/payments/",
        views.PaymentListView.as_view(),
        name="payment-list",
    ),
    path(
        "<str:application_number>/payments/record/",
        views.PaymentRecordView.as_view(),
        name="payment-record",
    ),
    path(
        "<str:application_number>/payments/<int:pk>/verify/",
        views.PaymentVerifyView.as_view(),
        name="payment-verify",
    ),
]
