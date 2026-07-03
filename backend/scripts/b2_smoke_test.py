#!/usr/bin/env python3
"""
B2 storage smoke test — put / get / delete against the real bucket, plus a
key-scoping check.

Run from an environment that HAS outbound network access to Backblaze B2 and a
populated backend/.env (B2_KEY_ID, B2_APPLICATION_KEY, B2_BUCKET_NAME, B2_REGION).
This is deliberately standalone (no Django bootstrap needed) so it can be run as a
deployment / incident check:

    cd backend && python scripts/b2_smoke_test.py

Exit code 0 = all checks passed. Non-zero = a check failed (details printed).

What it verifies:
  1. Credentials authenticate against the S3-compatible endpoint.
  2. put_object  -> get_object (round-trip, content matches) -> delete_object.
  3. Key scoping: list_buckets() should return ONLY B2_BUCKET_NAME. If it returns
     other buckets, the application key is account-wide and must be re-scoped to
     the mbpa-portal bucket only (see Docs/runbooks/b2_outage.md).
"""

import os
import sys
import uuid

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    sys.exit("boto3 not installed. Run: pip install -r requirements.txt")


def load_env():
    """Minimal .env loader so this works without django-environ bootstrap."""
    env = dict(os.environ)
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.isfile(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def main():
    env = load_env()
    key_id = env.get("B2_KEY_ID", "")
    app_key = env.get("B2_APPLICATION_KEY", "")
    bucket = env.get("B2_BUCKET_NAME", "mbpa-portal")
    region = env.get("B2_REGION", "")

    if not (key_id and app_key and region):
        sys.exit("Missing B2_KEY_ID / B2_APPLICATION_KEY / B2_REGION in environment or .env")

    endpoint = f"https://s3.{region}.backblazeb2.com"
    print(f"Endpoint : {endpoint}")
    print(f"Bucket   : {bucket}")
    print(f"Key ID   : {key_id[:6]}…{key_id[-4:]}")
    print()

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=app_key,
        config=boto3.session.Config(signature_version="s3v4"),
    )

    failures = []

    # 1. put / get / delete round-trip
    test_key = f"_smoke_test/{uuid.uuid4().hex}.txt"
    payload = b"mbpa-b2-smoke-test"
    try:
        s3.put_object(Bucket=bucket, Key=test_key, Body=payload)
        print(f"[ok]   put_object    {test_key}")

        got = s3.get_object(Bucket=bucket, Key=test_key)["Body"].read()
        if got == payload:
            print("[ok]   get_object    content matches")
        else:
            failures.append("get_object content mismatch")
            print("[FAIL] get_object    content MISMATCH")

        s3.delete_object(Bucket=bucket, Key=test_key)
        print(f"[ok]   delete_object {test_key}")

        # confirm gone
        try:
            s3.head_object(Bucket=bucket, Key=test_key)
            failures.append("object still present after delete")
            print("[FAIL] head_object   object STILL PRESENT after delete")
        except ClientError:
            print("[ok]   head_object   confirmed deleted")
    except ClientError as e:
        failures.append(f"put/get/delete cycle: {e}")
        print(f"[FAIL] round-trip    {e}")

    print()

    # 2. key scoping check
    try:
        buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
        if buckets == [bucket]:
            print(f"[ok]   scoping       key sees only its own bucket: {buckets}")
        elif bucket in buckets and len(buckets) > 1:
            failures.append(f"key is account-wide (sees {buckets})")
            print(f"[FAIL] scoping       key is ACCOUNT-WIDE, sees: {buckets}")
            print("       → re-scope to the mbpa-portal bucket only (Docs/runbooks/b2_outage.md)")
        else:
            print(f"[warn] scoping       list_buckets returned: {buckets} (review manually)")
    except ClientError as e:
        # A tightly bucket-restricted key may be denied list_buckets entirely — that's
        # actually a GOOD sign for scoping, not a failure.
        print(
            f"[ok]   scoping       list_buckets denied ({e.response['Error']['Code']}) "
            "— key is restricted, consistent with bucket-only scope"
        )

    print()
    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("RESULT: PASS — B2 put/get/delete works and key scoping looks correct.")


if __name__ == "__main__":
    main()
