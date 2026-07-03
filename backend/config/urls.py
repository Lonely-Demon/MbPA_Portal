from django.conf import settings
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns: list[URLResolver | URLPattern] = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.api.urls")),
    path("api/identity/", include("apps.identity.urls")),
    path("api/applications/", include("apps.applications.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/fees/", include("apps.fees.urls")),
    path("api/certificates/", include("apps.certificates.urls")),
    path("api/compliance/", include("apps.compliance.urls")),
    path("api/officer/", include("apps.applications.officer_urls")),
]

# OpenAPI schema + Swagger UI are mounted ONLY when SERVE_API_SCHEMA is true
# (local/staging). In production the routes do not exist at all — no logged-in
# user can retrieve the full endpoint/model map. Schema generation for committed
# artifacts uses `manage.py spectacular --file`, which needs no live route.
if getattr(settings, "SERVE_API_SCHEMA", False):
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/schema/swagger/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
