# TLDR: Presigned S3 uploads blocked by CORS on LocalStack

## Symptom

Browser blocked PUT requests to presigned S3 upload URLs:

```
Fetch API cannot load http://localhost:4566/property-documents/extractions/...?AWSAccessKeyId=test&Signature=...
due to access control checks.
```

## Root cause

The LocalStack S3 bucket had no CORS configuration. When the browser does a preflight `OPTIONS` request to `localhost:4566` before the `PUT`, S3 returns no `Access-Control-Allow-Origin` header, so the browser blocks the request. Real AWS S3 has the same behavior — CORS must be explicitly configured per bucket.

## Debugging

```bash
# Checked LocalStack logs for init script errors
docker logs customers-dashboard-service-localstack-1

# Found permission error — init script wasn't executable
# Error: [Errno 13] Permission denied: '/etc/localstack/init/ready.d/init.sh'

# Fixed permissions
chmod +x scripts/localstack-init.sh

# After restart, verified CORS was applied
docker exec customers-dashboard-service-localstack-1 \
  awslocal s3api get-bucket-cors --bucket property-documents
```

## Fix

Added CORS configuration to `scripts/localstack-init.sh` after bucket creation:

```bash
awslocal s3api put-bucket-cors --bucket property-documents --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'
```

Also ensured the script is executable (`chmod +x`) since Docker volume mounts can lose the execute bit.

**Note:** For production AWS S3, the same CORS rule needs to be applied to the bucket (via Terraform, console, or CLI). Use specific origins instead of `"*"` in production.
