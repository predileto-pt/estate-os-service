###############################################################################
# Lambda — three zip-packaged functions consuming the SQS queues from
# `sqs.tf`. Code + deps deploy via CI (`aws lambda update-function-code`
# for the function zip, `aws lambda publish-layer-version` for the deps
# layer); terraform owns only the function shape.
#
# Why zip (post-ship correction; see ADR-018 addendum):
#   - The existing Dockerfile is FastAPI/uvicorn-only (no awslambdaric,
#     no Lambda Runtime API). Reusing it as a Lambda container image
#     would require dual-mode entrypoint surgery.
#   - Production deps are ~150 MB unzipped — well under the 250 MB
#     zip+layer cap.
#   - Faster cold starts (no ENI + image-layer fetch).
#   - The deps layer is shared by all three functions, so the deploy
#     pipeline builds it once per push.
#
# `data.archive_file.lambda_placeholder` produces a minimal zip that
# satisfies the `filename` attribute at first apply. Until CI runs once,
# the function exists but its code raises on invocation — fine because
# every event source mapping defaults to `enabled = false` via the
# `lambda_consumes_*` flags.
#
# Networking, IAM, concurrency caps, batch_size, queue visibility, and
# the feature-flag rollout are all unchanged from the original spec.
###############################################################################

locals {
  lambda_function_names = {
    extraction      = "${var.prefix_name}-extraction-worker"
    enrichment      = "${var.prefix_name}-enrichment-worker"
    listings_events = "${var.prefix_name}-listings-events-worker"
  }
}

# Placeholder zip used as the initial code body. CI replaces it via
# `aws lambda update-function-code` on the first deploy. The handler
# raises so a misconfigured (CI-never-ran) deploy fails loudly instead
# of silently swallowing events.
data "archive_file" "lambda_placeholder" {
  type        = "zip"
  output_path = "${path.module}/lambda-placeholder.zip"

  source {
    filename = "placeholder.py"
    content  = <<-EOT
      def handler(event, context):
          raise RuntimeError(
              "Lambda placeholder code is still in place. "
              "CI must run `aws lambda update-function-code` to "
              "replace this with the real worker bundle."
          )
    EOT
  }
}

# --- extraction-worker -------------------------------------------------------

resource "aws_lambda_function" "extraction_worker" {
  function_name    = local.lambda_function_names.extraction
  role             = aws_iam_role.lambda_role.arn
  package_type     = "Zip"
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "properties.entrypoints.lambda_extraction.handler"
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  memory_size      = var.lambda_extraction_memory
  timeout          = var.lambda_extraction_timeout

  reserved_concurrent_executions = var.lambda_extraction_reserved_concurrency

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.app_secrets.name
    }
  }

  vpc_config {
    subnet_ids         = module.vpc.logic_subnets_ids
    security_group_ids = [module.lambda_sg.security_group_id]
  }

  # CI is the source of truth for `filename`, `source_code_hash`, and
  # `layers` after the first apply. Terraform-managed updates would race
  # with the deploy workflow and could roll the function back to the
  # placeholder.
  lifecycle {
    ignore_changes = [filename, source_code_hash, layers]
  }
}

resource "aws_cloudwatch_log_group" "extraction_worker" {
  name              = "/aws/lambda/${local.lambda_function_names.extraction}"
  retention_in_days = 30
}

resource "aws_lambda_event_source_mapping" "extraction" {
  event_source_arn = module.extraction_queue.arn
  function_name    = aws_lambda_function.extraction_worker.arn
  batch_size       = 1
  enabled          = var.lambda_consumes_extraction
}

# --- enrichment-worker -------------------------------------------------------

resource "aws_lambda_function" "enrichment_worker" {
  function_name    = local.lambda_function_names.enrichment
  role             = aws_iam_role.lambda_role.arn
  package_type     = "Zip"
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "properties.entrypoints.lambda_enrichment.handler"
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  memory_size      = var.lambda_enrichment_memory
  timeout          = var.lambda_enrichment_timeout

  reserved_concurrent_executions = var.lambda_enrichment_reserved_concurrency

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.app_secrets.name
    }
  }

  vpc_config {
    subnet_ids         = module.vpc.logic_subnets_ids
    security_group_ids = [module.lambda_sg.security_group_id]
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash, layers]
  }
}

resource "aws_cloudwatch_log_group" "enrichment_worker" {
  name              = "/aws/lambda/${local.lambda_function_names.enrichment}"
  retention_in_days = 30
}

resource "aws_lambda_event_source_mapping" "enrichment" {
  event_source_arn = module.enrichment_queue.arn
  function_name    = aws_lambda_function.enrichment_worker.arn
  batch_size       = 1
  enabled          = var.lambda_consumes_enrichment
}

# --- listings-events-worker --------------------------------------------------

resource "aws_lambda_function" "listings_events_worker" {
  function_name    = local.lambda_function_names.listings_events
  role             = aws_iam_role.lambda_role.arn
  package_type     = "Zip"
  filename         = data.archive_file.lambda_placeholder.output_path
  source_code_hash = data.archive_file.lambda_placeholder.output_base64sha256
  handler          = "listings.entrypoints.lambda_events.handler"
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  memory_size      = var.lambda_listings_events_memory
  timeout          = var.lambda_listings_events_timeout

  # Unreserved when the var is -1: passing -1 to AWS means "delete the
  # reservation" rather than "cap at -1". Positive values cap.
  reserved_concurrent_executions = var.lambda_listings_events_reserved_concurrency

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.app_secrets.name
    }
  }

  vpc_config {
    subnet_ids         = module.vpc.logic_subnets_ids
    security_group_ids = [module.lambda_sg.security_group_id]
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash, layers]
  }
}

resource "aws_cloudwatch_log_group" "listings_events_worker" {
  name              = "/aws/lambda/${local.lambda_function_names.listings_events}"
  retention_in_days = 30
}

resource "aws_lambda_event_source_mapping" "listings_events" {
  event_source_arn = module.listings_events_queue.arn
  function_name    = aws_lambda_function.listings_events_worker.arn
  batch_size       = 1
  enabled          = var.lambda_consumes_listings_events
}
