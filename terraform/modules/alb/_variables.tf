variable "name" {
  type        = string
  description = "(Optional) The name of the LB. This name must be unique within your AWS account, can have a maximum of 32 characters, must contain only alphanumeric characters or hyphens, and must not begin or end with a hyphen. If not specified, Terraform will autogenerate a name beginning with tf-lb"
}

variable "load_balancer_type" {
  type        = string
  description = "(Optional) The type of load balancer to create. Possible values are application, gateway, or network. The default value is application"
  default     = "application"
}

variable "ip_address_type" {
  type        = string
  description = "(Optional) The type of IP addresses used by the subnets for your load balancer. The possible values are ipv4 and dualstack"
  default     = "ipv4"
}

variable "desync_mitigation_mode" {
  type        = string
  description = "(Optional) Determines how the load balancer handles requests that might pose a security risk to an application due to HTTP desync. Valid values are monitor, defensive (default), strictest"
  default     = "defensive"
}

variable "security_groups" {
  type        = list(string)
  description = "(Optional) A list of security group IDs to assign to the LB. Only valid for Load Balancers of type application"
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  description = "(Optional) A list of subnet IDs to attach to the LB. Subnets cannot be updated for Load Balancers of type network. Changing this value for load balancers of type network will force a recreation of the resource."
  default     = null
}

variable "access_logs" {
  description = "Map containing access logging configuration for load balancer"
  type        = map(string)
  default     = {}
}

variable "subnet_mappings" {
  type = list(object({
    subnet_id     = string
    allocation_id = string
  }))
  description = "(Optional) A subnet mapping block as documented below."
  default     = []
}

variable "vpc_id" {
  type        = string
  description = "(Optional, Forces new resource) Identifier of the VPC in which to create the target group. Required when target_type is instance, ip or alb. Does not apply when target_type is lambda."
  default     = null
}

variable "target_id" {
  type        = string
  description = "(Required) The ID of the target. This is the Instance ID for an instance, or the container ID for an ECS container. If the target type is ip, specify an IP address. If the target type is lambda, specify the Lambda function ARN. If the target type is alb, specify the ALB ARN."
}

variable "listeners" {
  type = list(object({
    port            = number
    protocol        = string
    target_protocol = string
    target_port     = number
    certificate_arn = optional(string)
  }))
}

variable "tg_name" {
  type        = string
  description = "(Optional) The name of the target group. This name must be unique within your AWS account, can have a maximum of 32 characters, must contain only alphanumeric characters or hyphens, and must not begin or end with a hyphen. If not specified, Terraform will autogenerate a name beginning with tf-tg"
  default     = "tg"
}

variable "health_check_path" {
  type        = string
  description = "(Optional) The destination for the health check request. Required for HTTP/HTTPS health checks. This is only necessary if you want to use a custom health check path, for example for use with lambda functions. Otherwise, the default path is used."
  default     = "/health"
}