# Facts looked up from AWS (nothing here creates anything).

data "aws_partition" "current" {}

# The default VPC that every AWS account has: no NAT gateway or other paid networking needed.
data "aws_vpc" "default" {
  default = true
}

# Only use availability zones that actually sell the chosen instance type.
data "aws_ec2_instance_type_offerings" "available" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.available.locations
  }
}

data "aws_ec2_instance_type" "selected" {
  instance_type = var.instance_type
}

locals {
  is_arm    = contains(data.aws_ec2_instance_type.selected.supported_architectures, "arm64")
  subnet_id = try(sort(data.aws_subnets.default.ids)[0], null)
}

# Newest Ubuntu 24.04 LTS image from Canonical (099720109477 is Canonical's official AWS account).
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-${local.is_arm ? "arm64" : "amd64"}-server-*"]
  }
  filter {
    name   = "architecture"
    values = [local.is_arm ? "arm64" : "x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
