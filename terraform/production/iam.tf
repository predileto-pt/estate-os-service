###############################################################################
# IAM — EC2 instance profile.
#
# The EC2 hosts the FastAPI app and, optionally (via the `fallback`
# docker-compose profile in `deploy/docker-compose.prod.yml`), the
# worker services when Lambda needs to be bypassed. Workers normally
# run as Lambda functions with a separate execution role
# (`aws_iam_role.lambda_role`, defined below). The EC2 role therefore
# needs publish on the worker queues for the API path *plus* the same
# read/heartbeat permissions used by the Lambda role to cover the
# compose-profile fallback case.
###############################################################################

resource "aws_iam_role" "ec2_role" {
  name = "${var.prefix_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.prefix_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name
}

# SSM Session Manager + agent registration. Required because the EC2
# is in a private subnet — operator shell access is via
# `aws ssm start-session --target <instance-id>`, and the CI's
# `aws ssm send-command` deploys depend on the agent being able to
# register with the SSM service. The managed policy grants exactly the
# perms the SSM agent needs (ssmmessages:* + ec2messages:* + minimal
# ssm read of inventory).
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# CloudWatch — app + worker logs land in /aws/ec2/... log groups.
resource "aws_iam_role_policy" "ec2_cloudwatch" {
  name = "${var.prefix_name}-cloudwatch"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${local.account_id}:*"
      }
    ]
  })
}

# Secrets Manager + KMS — the boot script in `deploy/user_data.sh` reads
# the encrypted `.env` from Secrets Manager.
resource "aws_iam_role_policy" "ec2_secrets" {
  name = "${var.prefix_name}-secrets"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = aws_secretsmanager_secret.app_secrets.arn
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
        ]
        Resource = module.kms.kms_key_arn
      }
    ]
  })
}

# S3 — document storage for property uploads, extraction artifacts, etc.
resource "aws_iam_role_policy" "ec2_s3" {
  name = "${var.prefix_name}-s3"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:HeadObject",
        ]
        Resource = "${module.documents_bucket.arn}/*"
      }
    ]
  })
}

# SQS — the API publishes commands to extraction + enrichment; the
# fallback-profile worker services in docker-compose need Receive/Delete/
# Heartbeat/GetAttributes on all three queues (including listings-events)
# so an operator can take over consumption when Lambda is disabled.
resource "aws_iam_role_policy" "ec2_sqs" {
  name = "${var.prefix_name}-sqs"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sqs:SendMessage"
        Resource = [
          module.extraction_queue.arn,
          module.enrichment_queue.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
        ]
        Resource = [
          module.extraction_queue.arn,
          module.enrichment_queue.arn,
          module.listings_events_queue.arn,
        ]
      }
    ]
  })
}

# SNS — the API publishes PROPERTY_* and PROPERTY_LISTING_* domain
# events to the per-event-type topics provisioned in `sns.tf`. Workers
# publish too (the listings projector emits its own internal events).
resource "aws_iam_role_policy" "ec2_sns" {
  name = "${var.prefix_name}-sns-publish"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sns:Publish"
        Resource = concat(
          [for t in aws_sns_topic.property_events : t.arn],
          [for t in aws_sns_topic.listing_events : t.arn],
        )
      }
    ]
  })
}

# ECR — pull the application image at boot + on every deploy.
resource "aws_iam_role_policy" "ec2_ecr" {
  name = "${var.prefix_name}-ecr"
  role = aws_iam_role.ec2_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = module.ecr.repository_arn
      }
    ]
  })
}

###############################################################################
# IAM — Lambda execution role (ADR-018).
#
# One role shared by all three worker Lambdas — the permission set is
# small enough that splitting per-function would add ceremony without
# tightening the blast radius (the same image runs in each function).
#
# Permissions granted:
#   - SQS receive/delete/heartbeat/GetAttributes on the three worker
#     queues (Lambda runtime needs these to consume).
#   - SNS publish on every PROPERTY_* + PROPERTY_LISTING_* topic so the
#     listings projector can emit follow-on `PROPERTY_LISTING_*` events,
#     and extraction can emit `PROPERTY_CREATED` etc.
#   - Secrets Manager + KMS Decrypt on `app_secrets` — the
#     `lambda_bootstrap` module pulls the JSON blob at cold start to
#     populate process env.
#   - S3 read/write/delete on the documents bucket objects + ListBucket
#     on the bucket itself. The `S3DocumentStorage` adapter uses
#     `put_object`, `get_object`, `head_object`, and `delete_object`;
#     `ListBucket` is added for future-proofing.
#   - `AWSLambdaBasicExecutionRole` managed policy → CloudWatch Logs
#     create/write on `/aws/lambda/<function-name>`.
#   - `AWSLambdaVPCAccessExecutionRole` managed policy → ENI
#     create/describe/delete in the private subnets the Lambdas attach
#     to. Required when `vpc_config` is set on the function.
###############################################################################

resource "aws_iam_role" "lambda_role" {
  name = "${var.prefix_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Required when the function has `vpc_config` set — Lambda manages
# ENIs in the configured subnets and needs ec2:CreateNetworkInterface
# etc. to do so.
resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_sqs" {
  name = "${var.prefix_name}-lambda-sqs"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
        ]
        Resource = [
          module.extraction_queue.arn,
          module.enrichment_queue.arn,
          module.listings_events_queue.arn,
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_sns" {
  name = "${var.prefix_name}-lambda-sns"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sns:Publish"
        Resource = concat(
          [for t in aws_sns_topic.property_events : t.arn],
          [for t in aws_sns_topic.listing_events : t.arn],
        )
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name = "${var.prefix_name}-lambda-secrets"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = aws_secretsmanager_secret.app_secrets.arn
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
        ]
        Resource = module.kms.kms_key_arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_s3" {
  name = "${var.prefix_name}-lambda-s3"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Object-level operations the S3DocumentStorage adapter performs.
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:HeadObject",
          "s3:DeleteObject",
        ]
        Resource = "${module.documents_bucket.arn}/*"
      },
      # Bucket-level listing — not used by the adapter today, but
      # required for any future enumeration workflow (e.g. reconciling
      # uploaded documents against DB rows). Scoped to the bucket ARN
      # itself, not `/*` (S3 distinguishes bucket vs object actions).
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = module.documents_bucket.arn
      }
    ]
  })
}
