module "extraction_queue" {
  source = "../modules/sqs"

  sqs_name                      = "${var.prefix_name}-property-extraction"
  environment                   = "production"
  sqs_visibility_timeout_seconds = 720
  create_dlq                    = true
  sqs_max_receive_count         = 3
}

module "events_queue" {
  source = "../modules/sqs"

  sqs_name                      = "${var.prefix_name}-customers-events"
  environment                   = "production"
  sqs_visibility_timeout_seconds = 30
  create_dlq                    = true
  sqs_max_receive_count         = 5
}
