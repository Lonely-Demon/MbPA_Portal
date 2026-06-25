from rest_framework import serializers

from apps.fees.models import FeeAssessment, Payment


class FeeAssessmentReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeAssessment
        fields = [
            "id",
            "scrutiny_fee",
            "security_deposit",
            "debris_deposit",
            "premium_total",
            "total_amount",
            "assessed_at",
            "bua_sqm_snapshot",
            "zonal_rrr_snapshot",
            "is_current",
            "is_locked",
            "locked_at",
        ]


class PaymentReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "challan_reference",
            "claimed_amount",
            "verified_amount",
            "status",
            "payment_date",
            "created_at",
            "verified_at",
            "remarks",
        ]


class PaymentRecordSerializer(serializers.Serializer):
    challan_reference = serializers.CharField(max_length=100)
    claimed_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_date = serializers.DateField()


class PaymentVerifySerializer(serializers.Serializer):
    DECISION_CHOICES = [
        Payment.STATUS_VERIFIED,
        Payment.STATUS_REJECTED,
        Payment.STATUS_MISMATCH,
    ]
    decision = serializers.ChoiceField(choices=DECISION_CHOICES)
    verified_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    remarks = serializers.CharField(allow_blank=True, default="")
