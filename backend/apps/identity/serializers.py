from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(max_length=255)
    aadhaar = serializers.CharField(write_only=True)  # raw — never stored


class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class OtpVerifySerializer(serializers.Serializer):
    token_ref = serializers.CharField(max_length=43)
    code = serializers.CharField(min_length=6, max_length=6)


class OtpResendSerializer(serializers.Serializer):
    token_ref = serializers.CharField(max_length=43)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "username", "user_type", "is_mobile_verified"]
        read_only_fields = ["id", "email", "username", "user_type", "is_mobile_verified"]
