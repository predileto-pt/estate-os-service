# --> RDS Primary
resource "random_password" "this" {
  length           = 16
  special          = true
  override_special = "!&"
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.rds_name}-pg-${var.db_pg_family}"
  family = var.db_pg_family

  dynamic "parameter" {
    for_each = var.db_pg_parameters
    content {
      name         = parameter.value.name
      value        = parameter.value.value
      apply_method = parameter.value.apply_method
    }
  }
}

resource "aws_db_subnet_group" "this" {
  name       = local.rds_subnet_group
  subnet_ids = var.db_sg_subnet_ids

  tags = {
    Name = local.rds_subnet_group
  }
}

resource "aws_db_instance" "this" {
  deletion_protection                 = true
  storage_type                        = var.db_instance_storage_type
  allocated_storage                   = var.db_instance_allocated_storage
  iops                                = var.db_instance_storage_iops
  storage_throughput                  = var.db_instance_storage_throughput
  max_allocated_storage               = var.db_instance_max_allocated_storage
  engine                              = var.db_instance_engine
  engine_version                      = var.db_instance_engine_version
  instance_class                      = var.db_instance_class
  identifier                          = var.rds_name
  username                            = var.db_instance_username
  password                            = random_password.this.result
  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = false
  maintenance_window                  = var.db_maintenance_window
  backup_window                       = var.db_backup_window
  backup_retention_period             = var.db_backup_retention_period
  copy_tags_to_snapshot               = true
  multi_az                            = var.db_multi_az
  storage_encrypted                   = true
  kms_key_id                          = var.db_encryption_key
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = var.db_cloudwatch_logs_exports
  parameter_group_name                = aws_db_parameter_group.this.name
  db_subnet_group_name                = aws_db_subnet_group.this.name
  vpc_security_group_ids              = var.db_instance_parameter_vpc_security_group_ids
  skip_final_snapshot                 = false
  ca_cert_identifier                  = var.db_ca_cert_identifier
  final_snapshot_identifier           = "${var.rds_name}-final-snapshot"
  apply_immediately                   = var.db_apply_immediately
  tags                                = var.db_tags
}

# --> RDS Read Replica
resource "aws_db_parameter_group" "read_replica" {
  count = var.db_enable_read_replica ? 1 : 0

  name   = local.rds_parameter_group
  family = var.db_pg_family

  dynamic "parameter" {
    for_each = var.db_read_replica_pg_parameters
    content {
      name         = parameter.value.name
      value        = parameter.value.value
      apply_method = parameter.value.apply_method
    }
  }
}

resource "aws_db_instance" "read_replica" {
  count = var.db_enable_read_replica ? 1 : 0

  replicate_source_db                 = aws_db_instance.this.id
  instance_class                      = var.db_read_replica_instance_class
  identifier                          = var.rds_name
  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = false
  maintenance_window                  = var.db_maintenance_window
  multi_az                            = false
  storage_encrypted                   = true
  kms_key_id                          = var.db_encryption_key
  performance_insights_enabled        = true
  enabled_cloudwatch_logs_exports     = var.db_cloudwatch_logs_exports
  parameter_group_name                = aws_db_parameter_group.read_replica[count.index].name
  apply_immediately                   = var.db_read_replica_apply_immediately
  skip_final_snapshot                 = true
}