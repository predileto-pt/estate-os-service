variable "rds_name" {
  type        = string
  description = "RDS Name"
}

# --> RDS Primary
# Subnet Group
variable "db_sg_subnet_ids" {
  type        = list(string)
  description = "Subnets Ids"
}

# Parameter Group
variable "db_pg_family" {
  type        = string
  description = "Parameter Group Family"
  default     = "postgres16"
}

variable "db_pg_parameters" {
  type = list(object({
    name         = string
    value        = any
    apply_method = string
  }))
  description = "Parameters of the Parameter Group"
}

# Instance
variable "db_enable_read_replica" {
  description = "RDS enable read replica"
  type        = bool
  default     = false
}

variable "db_instance_storage_type" {
  type        = string
  description = "Storage Type"
  default     = "gp3"
}

variable "db_instance_allocated_storage" {
  type        = number
  description = "RDS Instance Allocated Storage"
  default     = 20
}

variable "db_instance_storage_iops" {
  type        = number
  description = "(Can only be set when storage_type is io1 or gp3) The amount of provisioned IOPS"
  default     = null
}

variable "db_instance_storage_throughput" {
  type        = number
  description = "(Can only be set when storage_type is gp3) The storage throughput value for the DB instance"
  default     = null
}

variable "db_instance_max_allocated_storage" {
  type        = number
  description = "RDS upper limit to which it can automatically scale the storage"
  default     = 50
}

variable "db_instance_engine" {
  type        = string
  description = "RDS Instance Engine"
  default     = "postgres"
}

variable "db_instance_engine_version" {
  type        = string
  description = "RDS Instance Engine Version"
  default     = "16.4"
}

variable "db_instance_class" {
  type        = string
  description = "RDS Instance Class"
  default     = "db.t4g.micro"
}

variable "db_instance_username" {
  type        = string
  description = "RDS Instance Username"
  default     = "postgres"
}

variable "db_maintenance_window" {
  type        = string
  description = "RDS maintenance window"
  default     = "Sun:07:00-Sun:08:00"
}

variable "db_backup_window" {
  type        = string
  description = "RDS backup window"
  default     = "05:30-06:30"
}

variable "db_backup_retention_period" {
  type        = number
  description = "RDS backup retention period"
  default     = 7
}

variable "db_multi_az" {
  type        = bool
  description = "RDS Multi-AZ Availability"
  default     = false
}

variable "db_encryption_key" {
  type        = string
  description = "RDS Encryption key"
}

variable "db_cloudwatch_logs_exports" {
  type        = list(string)
  description = "RDS Clodwatch logs exports"
  default     = ["postgresql", "upgrade"]
}

variable "db_instance_parameter_vpc_security_group_ids" {
  type        = list(string)
  description = "RDS Instance VPC Security Group IDS"
}

variable "db_apply_immediately" {
  type        = bool
  description = "Specifies whether any database modifications are applied immediately, or during the next maintenance window"
  default     = false
}

variable "db_ca_cert_identifier" {
  type        = string
  description = "Identifier of the CA certificate for the DB instance"
  default     = "rds-ca-rsa4096-g1"
}

variable "db_tags" {
  type        = map(string)
  description = "(Optional) A map of tags to assign to the resource"
  default     = {}
}

# --> RDS Read Replica
# Parameter Group
variable "db_read_replica_pg_parameters" {
  type = list(object(
    {
      name         = string
      value        = any
      apply_method = string
  }))
  description = "Parameters of the Parameter Group for Read Replica"
  default     = []
}

# Instance
variable "db_read_replica_instance_class" {
  type        = string
  description = "RDS Instance Class for Read Replica"
  default     = "db.t4g.micro"
}

variable "db_read_replica_apply_immediately" {
  type        = bool
  description = "Specifies whether any database modifications are applied immediately, or during the next maintenance window"
  default     = false
}