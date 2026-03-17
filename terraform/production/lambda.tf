# --- Extraction worker Lambda ---

resource "aws_lambda_function" "extraction_worker" {
  function_name = "${var.prefix_name}-extraction-worker"
  role          = aws_iam_role.lambda_role.arn
  package_type  = "Image"
  image_uri     = local.ecr_image
  architectures = ["arm64"]
  memory_size   = var.lambda_extraction_memory
  timeout       = var.lambda_extraction_timeout

  image_config {
    command = ["property_management.entrypoints.lambda_extraction.handler"]
  }

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.app_secrets.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "extraction_sqs" {
  event_source_arn = module.extraction_queue.arn
  function_name    = aws_lambda_function.extraction_worker.arn
  batch_size       = 1
  enabled          = true
}

resource "aws_cloudwatch_log_group" "extraction_worker" {
  name              = "/aws/lambda/${aws_lambda_function.extraction_worker.function_name}"
  retention_in_days = 30
}

# --- Events worker Lambda ---

resource "aws_lambda_function" "events_worker" {
  function_name = "${var.prefix_name}-events-worker"
  role          = aws_iam_role.lambda_role.arn
  package_type  = "Image"
  image_uri     = local.ecr_image
  architectures = ["arm64"]
  memory_size   = var.lambda_events_memory
  timeout       = var.lambda_events_timeout

  image_config {
    command = ["customer_management.entrypoints.lambda_events.handler"]
  }

  environment {
    variables = {
      SECRET_NAME = aws_secretsmanager_secret.app_secrets.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "events_sqs" {
  event_source_arn = module.events_queue.arn
  function_name    = aws_lambda_function.events_worker.arn
  batch_size       = 1
  enabled          = true
}

resource "aws_cloudwatch_log_group" "events_worker" {
  name              = "/aws/lambda/${aws_lambda_function.events_worker.function_name}"
  retention_in_days = 30
}
