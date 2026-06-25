# Cloudflare R2 Storage Setup Runbook

## 1. Create a bucket

1. Log into the [Cloudflare Dashboard](https://dash.cloudflare.com) → **R2 Object Storage**.
2. Click **Create bucket** → name it `mbpa-portal` (or `mbpa-portal-staging`).
3. Set **Location** to `APAC` for lower latency from India.
4. Note your **Account ID** from the R2 overview page.

## 2. Create a scoped API token

1. Go to **R2 → Manage R2 API Tokens → Create API Token**.
2. Permissions: **Object Read & Write** — scoped to the bucket created above.
3. Copy the **Access Key ID** and **Secret Access Key** immediately (shown once).

## 3. Configure CORS (if the frontend uploads directly)

In the bucket settings → **CORS** → add:

```json
[
  {
    "AllowedOrigins": ["https://your-domain.example.gov"],
    "AllowedMethods": ["GET", "PUT", "POST"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3600
  }
]
```

For server-side uploads only (recommended for this portal), CORS is not required.

## 4. Wire environment variables

Add to your `.env` (never commit):

```
R2_ACCOUNT_ID=your-cloudflare-account-id
R2_BUCKET_NAME=mbpa-portal
R2_ACCESS_KEY_ID=your-r2-access-key-id
R2_SECRET_ACCESS_KEY=your-r2-secret-access-key
```

`settings/base.py` reads these and configures `django-storages` with the
`S3Storage` backend pointed at `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`.

## 5. Verify uploads work

```python
# Django shell:
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

path = default_storage.save("test/hello.txt", ContentFile(b"hello R2"))
url = default_storage.url(path)
print(url)  # should be a presigned R2 URL
default_storage.delete(path)
```

## 6. Production notes

- R2 free tier: 10 GB storage, 1 M Class A operations/month, 10 M Class B/month.
- Enable **Object Versioning** once past MVP to protect against accidental deletes.
- `querystring_auth=True` in settings ensures all file URLs are presigned (time-limited)
  rather than publicly accessible — appropriate for sensitive planning documents.
