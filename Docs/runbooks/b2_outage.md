# Runbook: B2 Storage Outage

**Scenario:** Backblaze B2 is unreachable, returning errors, or the bucket credentials
are invalid. Affects document uploads and presigned URL generation.

---

## Symptoms

- `POST /api/documents/upload/` returns HTTP 500.
- `GET /api/documents/<pk>/presigned/` returns HTTP 500 or returns a URL that 404s.
- Django logs show `botocore.exceptions.EndpointResolutionError`, `ClientError: NoSuchBucket`,
  `ClientError: InvalidAccessKeyId`, or connection timeout from `apps/documents/services.py`.

---

## Immediate triage

1. **Check B2 status:** https://status.backblaze.com — look for S3-compatible API incidents.

2. **Check credentials are valid:**
   ```bash
   # From the backend container / server
   python manage.py shell -c "
   from django.conf import settings
   print(settings.B2_KEY_ID[:6], '...', settings.B2_BUCKET_NAME, settings.B2_REGION)
   "
   ```
   If `B2_KEY_ID` looks wrong (wrong prefix, unexpected length) → key rotation issue.

3. **Test connectivity directly:**
   ```bash
   curl -I https://s3.us-west-004.backblazeb2.com
   ```
   Timeout → B2 endpoint unreachable (network or B2 outage).
   HTTP 4xx → credential or bucket configuration issue.

---

## Mitigations by cause

### B2 platform outage (confirmed on status page)

No application-level action. Document uploads and presigned URLs will fail until B2 recovers.

Applicant-facing impact: uploads blocked, "View" buttons for existing documents return broken
presigned URLs. Officer Console "Documents" tab will show empty slots.

**Communication:** Notify affected applicants that document upload is temporarily unavailable.
No data loss — documents already uploaded remain in B2; they are just unreadable until the
service recovers. Presigned URLs have a short TTL and will regenerate once B2 is back.

Once B2 recovers, no application restart is needed — the next upload or presigned URL
request will succeed automatically.

### Invalid credentials (key deleted or rotated)

Credentials are stored in `backend/.env` (see `config/settings/base.py` — these
feed django-storages' S3 backend via `STORAGES["default"]["OPTIONS"]`, not the
legacy top-level `AWS_*` Django settings, which aren't set at all in this
codebase and don't exist on `settings`):
```
B2_KEY_ID=...
B2_APPLICATION_KEY=...
B2_BUCKET_NAME=mbpa-portal
B2_REGION=us-west-004
```

**To rotate:**
1. In the B2 console, create a new Application Key scoped **only** to the `mbpa-portal` bucket
   with Read + Write + Delete + List permissions.
2. Update `B2_KEY_ID` and `B2_APPLICATION_KEY` in `backend/.env`.
3. Restart the application.
4. Delete the old key in the B2 console only **after** confirming the new key works —
   test with a small upload via the API.

> **Note:** Key `K00307mch4U9I8eeuRvhG7g21jIicWg` was exposed in project chat history
> and must be confirmed deleted (not just superseded) in the B2 console before go-live.
> Verify under Account → App Keys that it no longer appears.

### Wrong bucket name or endpoint URL

If the bucket was renamed or the region endpoint changed:
1. Verify bucket name in B2 console matches `B2_BUCKET_NAME`.
2. Verify `B2_REGION` matches your bucket's actual region (the endpoint URL is
   built from it as `https://s3.{B2_REGION}.backblazeb2.com` — there's no
   separate endpoint-URL env var to keep in sync).
3. Update `backend/.env` and restart.

---

## Verification after recovery

```bash
# Test upload (replace <token> with a valid session cookie)
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "X-CSRFToken: <csrf>" \
  -b "sessionid=<session>" \
  -F "file=@/tmp/test.pdf" \
  -F "milestone_instance_id=1"

# Test presigned URL
curl http://localhost:8000/api/documents/1/presigned/ \
  -b "sessionid=<session>"
# Response should contain a signed https://f004.backblazeb2.com/... URL
```

---

## Post-incident

- Confirm B2 key is scoped to `mbpa-portal` bucket only (not account-wide).
- Confirm old/leaked keys are deleted from B2 console.
- Document the outage window and any uploads that failed during it.
- If applicants experienced upload failures, notify them to retry.
