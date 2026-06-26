from drf_spectacular.utils import extend_schema, extend_schema_view
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
    _get_current_assessment,
    assess_fee,
    reassess_fee,
    record_payment,
    verify_payment,
)


def _get_application(kwargs):
    try:
        return Application.objects.get(application_number=kwargs["application_number"])
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
