variable "prefix_name" {
  type    = string
  default = "estate-os-service-prod"
}

variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "ecr_image_tag" {
  type    = string
  default = "latest"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "volume_size" {
  type    = string
  default = "20"
}

variable "key_name" {
  type        = string
  description = "SSH key pair name for the EC2 instance"
}

variable "domain_name" {
  type    = string
  default = "api.predileto.pt"
}

# --- Bastion host (ADR-018) ---
#
# BYOK pattern (matches raz-consulting-services/compliance-agent-service):
# the operator pastes their own laptop's SSH public key here. Terraform
# never generates or stores a private key. The bastion is the single
# SSH entry point into the private subnets; from there, ProxyJump to
# the API EC2 by its private IP.

variable "bastion_public_key" {
  type        = string
  description = "OpenSSH-formatted public key paste, e.g. 'ssh-ed25519 AAAAC3... user@host'. Registered as an aws_key_pair so the bastion can authenticate the operator's SSH client. No private key is stored by Terraform."
}

variable "bastion_allowed_cidr" {
  type        = string
  default     = "0.0.0.0/0"
  description = "CIDR allowed to SSH into the bastion. Default is open (relies on key auth); tighten to a developer's /32 in production.tfvars for less open exposure."
}

# --- Lambda worker functions (ADR-018) ---
#
# Three image-based Lambdas consume the SQS queues defined in `sqs.tf`.
# Each `lambda_consumes_*` flag gates the corresponding event source
# mapping — flags default to `false` so the initial `terraform apply`
# creates the functions without subscribing them. Flip to `true` in
# `production.tfvars` once a function is confirmed deployable.

variable "lambda_consumes_extraction" {
  type        = bool
  description = "Enable the SQS event source mapping for the extraction-worker Lambda."
  default     = false
}

variable "lambda_consumes_enrichment" {
  type        = bool
  description = "Enable the SQS event source mapping for the enrichment-worker Lambda."
  default     = false
}

variable "lambda_consumes_listings_events" {
  type        = bool
  description = "Enable the SQS event source mapping for the listings-events-worker Lambda."
  default     = false
}

# Per-function sizing. Memory caps drive Lambda's vCPU allocation; bump
# extraction up if Reducto + OpenAI processing becomes CPU-bound.

variable "lambda_extraction_memory" {
  type    = number
  default = 2048
}

variable "lambda_extraction_timeout" {
  type    = number
  default = 720
}

variable "lambda_extraction_reserved_concurrency" {
  type        = number
  description = "Set to -1 to skip reservation (default); positive integers cap concurrency. Used to defend Reducto + OpenAI rate limits. New AWS accounts have a low total Lambda concurrency limit; request a quota increase before setting > 0."
  default     = -1
}

variable "lambda_enrichment_memory" {
  type    = number
  default = 1024
}

variable "lambda_enrichment_timeout" {
  type        = number
  description = "Hard cap is 900 s (Lambda max). enrichment_queue visibility matches."
  default     = 900
}

variable "lambda_enrichment_reserved_concurrency" {
  type        = number
  description = "Set to -1 to skip reservation (default); positive integers cap concurrency. Used to defend Google Places quota. New AWS accounts have a low total Lambda concurrency limit; request a quota increase before setting > 0."
  default     = -1
}

variable "lambda_listings_events_memory" {
  type    = number
  default = 512
}

variable "lambda_listings_events_timeout" {
  type    = number
  default = 60
}

# Unreserved — the listings projector is cheap, idempotent, and only
# writes to internal DB + Pinecone. Set to -1 here to mean "no
# reservation"; positive values apply a cap.
variable "lambda_listings_events_reserved_concurrency" {
  type        = number
  description = "Set to -1 to skip reservation (default); positive integers cap concurrency."
  default     = -1
}
