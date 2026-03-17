# --> Subnet Public - Presentation
resource "aws_subnet" "this-presentation-subnets" {
  count                   = length(var.presentation_subnets)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = element(var.presentation_subnets, count.index)
  availability_zone       = element(data.aws_availability_zones.available.names, count.index)
  map_public_ip_on_launch = true

  tags = merge(
    {
      Name = "${var.network_name}-presentation-subnet-${count.index + 1}"
    },
    var.presentation_subnet_tags
  )
}

# --> Subnet Private - Logic
resource "aws_subnet" "this-logic-subnets" {
  count                   = length(var.logic_subnets)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = element(var.logic_subnets, count.index)
  availability_zone       = element(data.aws_availability_zones.available.names, count.index)
  map_public_ip_on_launch = false

  tags = merge(
    {
      Name = "${var.network_name}-logic-subnet-${count.index + 1}"
    },
    var.logic_subnet_tags
  )
}

# --> Subnet Private - Data
resource "aws_subnet" "this-data-subnets" {
  count                   = length(var.data_subnets)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = element(var.data_subnets, count.index)
  availability_zone       = element(data.aws_availability_zones.available.names, count.index)
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.network_name}-data-subnet-${count.index + 1}"
  }
}