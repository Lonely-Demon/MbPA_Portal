from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.fees.permissions import CanViewFees, IsOfficerForApplication
from apps.fees.serializers import (
    FeeAssessmentReadSerializer,
    PaymentReadSerializer,
    PaymentRecordSerializer,
    PaymentVerifySerializer,
)
from apps.fees.services import (
    _compute_fee_breakdown,
    _get_current_assessment,
    assess_fee,
    reassess_fee,
    record_payment,
    verify_payment,
)


class FeeEstimateView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        responses={
            200: inline_serializer(
                "FeeEstimateResponse",
                {
                    "scrutiny_fee": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                    "security_deposit": drf_serializers.DecimalField(
                        max_digits=14, decimal_places=2
                    ),
                    "debris_deposit": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                    "premium_total": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                    "total_amount": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                    "non_binding": drf_serializers.BooleanField(),
                },
            )
        }
    )
    def get(self, request):
        def _decimal(key, required=True):
            raw = request.query_params.get(key, "").strip()
            if not raw:
                if required:
                    return None, f"{key} is required."
                return None, None
            try:
                return Decimal(raw), None
            except InvalidOperation:
                return None, f"{key} must be a valid decimal number."

        bua, err = _decimal("proposed_bua_sqm")
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        plot, err = _decimal("plot_area_sqm")
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        rrr, err = _decimal("zonal_rrr")
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        open_space, err = _decimal("open_space_shortfall_sqm", required=False)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        parking, err = _decimal("parking_waiver_sqm", required=False)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)

        bd = _compute_fee_breakdown(
            proposed_bua_sqm=bua,
            plot_area_sqm=plot,
            zonal_rrr=rrr,
            open_space_shortfall_sqm=open_space,
            parking_waiver_sqm=parking,
        )
        return Response(
            {
                "scrutiny_fee": str(bd["scrutiny_fee"]),
                "security_deposit": str(bd["security_deposit"]),
                "debris_deposit": str(bd["debris_deposit"]),
                "premium_total": str(bd["premium_total"]),
                "total_amount": str(bd["total_amount"]),
                "non_binding": True,
            }
        )


def _get_application(kwargs):
    try:
        return Application.objects.get(
            application_number=kwargs["application_number"], deleted_at__isnull=True
        )
    except Application.DoesNotExist:
        return None


@extend_schema_view(
    get=extend_schema(responses=FeeAssessmentReadSerializer),
    post=extend_schema(
        request={},
        responses={200: FeeAssessmentReadSerializer, 201: FeeAssessmentReadSerializer},
    ),
)
class FeeAssessmentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_number):
        app = _get_application({"application_number": application_number})
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, app)

        assessment = _get_current_assessment(app)
        if assessment is None:
            return Response(
                {"detail": "No fee assessment exists for this application."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(FeeAssessmentReadSerializer(assessment).data)

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsOfficerForApplication()]
        return [IsAuthenticated(), CanViewFees()]

    def post(self, request, application_number):
        app = _get_application({"application_number": application_number})
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, app)

        existing = _get_current_assessment(app)
        if existing is not None:
            assessment = reassess_fee(application=app, assessed_by=request.user)
            return Response(FeeAssessmentReadSerializer(assessment).data, status=status.HTTP_200_OK)
        else:
            assessment = assess_fee(application=app, assessed_by=request.user)
            return Response(
                FeeAssessmentReadSerializer(assessment).data, status=status.HTTP_201_CREATED
            )


class PaymentListView(APIView):
    permission_classes = [IsAuthenticated, CanViewFees]

    @extend_schema(responses=PaymentReadSerializer(many=True))
    def get(self, request, application_number):
        app = _get_application({"application_number": application_number})
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, app)

        payments = app.payments.all().order_by("-created_at")
        return Response(PaymentReadSerializer(payments, many=True).data)


class PaymentRecordView(APIView):
    permission_classes = [IsAuthenticated, CanViewFees]

    @extend_schema(request=PaymentRecordSerializer, responses={201: PaymentReadSerializer})
    def post(self, request, application_number):
        app = _get_application({"application_number": application_number})
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, app)

        ser = PaymentRecordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        payment = record_payment(
            application=app,
            challan_reference=d["challan_reference"],
            claimed_amount=d["claimed_amount"],
            payment_date=d["payment_date"],
            recorded_by=request.user,
        )
        return Response(PaymentReadSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentVerifyView(APIView):
    permission_classes = [IsAuthenticated, IsOfficerForApplication]

    @extend_schema(request=PaymentVerifySerializer, responses=PaymentReadSerializer)
    def patch(self, request, application_number, pk):
        app = _get_application({"application_number": application_number})
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, app)

        try:
            payment = app.payments.get(pk=pk)
        except app.payments.model.DoesNotExist:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = PaymentVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        updated = verify_payment(
            payment=payment,
            decision=d["decision"],
            verified_amount=d["verified_amount"],
            verified_by=request.user,
            remarks=d.get("remarks", ""),
        )
        return Response(PaymentReadSerializer(updated).data)
