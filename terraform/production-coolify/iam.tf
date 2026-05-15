###############################################################################
# Coolify ECR reader.
#
# Used by the Hetzner VM host (NOT the api container) to refresh
# `docker login` every ~8h via a systemd timer. ECR auth tokens expire
# every 12h and Hetzner has no IAM instance profile, so this is the
# simplest reliable pull-side auth mechanism. See the runbook for the
# systemd unit text + setup steps.
#
# Concerns are kept separate from the api's S3 user (below) so a leak
# of either doesn't widen the other's scope.
###############################################################################

resource "aws_iam_user" "coolify_ecr_reader" {
  name = "${var.prefix_name}-coolify-ecr-reader"
}

resource "aws_iam_user_policy" "coolify_ecr_reader" {
  name = "${var.prefix_name}-coolify-ecr-read"
  user = aws_iam_user.coolify_ecr_reader.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR auth is account-wide — `GetAuthorizationToken` must be * .
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      # Pull-side reads scoped to this stack's single repo.
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
        ]
        Resource = module.ecr.repository_arn
      }
    ]
  })
}

resource "aws_iam_access_key" "coolify_ecr_reader" {
  user = aws_iam_user.coolify_ecr_reader.name
}

###############################################################################
# API S3 client.
#
# Used by the api container at runtime to read/write `documents_bucket`
# AND `images_bucket`. Credentials surface as AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY in the api + worker containers (set at the
# Coolify project level so compose's `${AWS_ACCESS_KEY_ID}` interpolation
# in x-shared-env resolves).
#
# Permissions scoped to both bucket prefixes only:
#   - GetObject (presigned download URLs, document fetch, image fetch)
#   - PutObject (document + image uploads from the api)
#   - DeleteObject (confirmed at src/shared/adapters/s3_document_storage.py:98)
#
# No ListBucket — no list_objects calls in the codebase today; add if a
# reconciliation workflow needs it. The contracts bucket would join this
# policy when the follow-up spec lands.
###############################################################################

resource "aws_iam_user" "app_s3" {
  name = "${var.prefix_name}-app-s3"
}

resource "aws_iam_user_policy" "app_s3" {
  name = "${var.prefix_name}-app-s3"
  user = aws_iam_user.app_s3.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "${module.documents_bucket.arn}/*",
          "${module.images_bucket.arn}/*",
        ]
      }
    ]
  })
}

resource "aws_iam_access_key" "app_s3" {
  user = aws_iam_user.app_s3.name
}
