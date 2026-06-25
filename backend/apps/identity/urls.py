from django.urls import path

from . import views

app_name = "identity"

urlpatterns = [
    path("signup/", views.SignupView.as_view(), name="signup"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("otp/verify/", views.OtpVerifyView.as_view(), name="otp-verify"),
    path("otp/resend/", views.OtpResendView.as_view(), name="otp-resend"),
    path("me/", views.MeView.as_view(), name="me"),
]
