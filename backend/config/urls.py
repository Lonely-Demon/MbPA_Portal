from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    path("api/identity/", include("apps.identity.urls")),
    path("api/applications/", include("apps.applications.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/fees/", include("apps.fees.urls")),
    path("api/certificates/", include("apps.certificates.urls")),
    path("api/compliance/", include("apps.compliance.urls")),
    # OpenAPI schema (dev/staging only; SERVE_INCLUDE_SCHEMA=False in prod)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
