# --> VPC
variable "network_name" {
  type        = string
  description = "Name to describe the network and resources"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC Network CIDR range. Ex: 10.1.0.0/16"
}


# --> Subnet Public - Presentation 
variable "presentation_subnets" {
  description = "List of CIDR blocks for subnets (presentation)"
  type        = list(string)
}

# --> Subnet Private - Logic
variable "logic_subnets" {
  description = "List of CIDR blocks for subnets (logic)"
  type        = list(string)
}

# --> Subnet Private - Data
variable "data_subnets" {
  description = "List of CIDR blocks for subnets (data)"
  type        = list(string)
}

# --> Tags
variable "presentation_subnet_tags" {
  description = "Add tags in presentation subnet"
}

variable "logic_subnet_tags" {
  description = "Add tags in presentation subnet"
}

variable "enable_nat_gateway" {
  type        = bool
  default     = true
  description = "Enable or disable the creation of a NAT Gateway"
}

variable "enable_ec2_nat_gateway" {
  type        = bool
  default     = false
  description = "Enable or disable the creation of a NAT Gateway"
}

variable "ec2_nat_gateway_id" {
  type        = string
  description = "NAT Gateway ID"
  default     = null
}