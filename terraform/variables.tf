variable "aws_region" {
  description = "AWS region, e.g. us-east-1 (N. Virginia), ap-south-1 (Mumbai), eu-west-2 (London)."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile Terraform uses (the 'slo' profile from the guide). Empty = default credentials."
  type        = string
  default     = "slo"
}

variable "project" {
  description = "Name prefix for every AWS resource."
  type        = string
  default     = "slo-cockpit"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.project))
    error_message = "Use 3-21 lowercase letters, digits or dashes, starting with a letter."
  }
}

variable "alert_email" {
  description = "E-mail address for alerts. AWS sends a confirmation link you must click."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid e-mail address."
  }
}

variable "instance_type" {
  description = "t3.micro (1 GB RAM) by default. t4g.micro is a cheaper ARM option; t3.small has 2 GB."
  type        = string
  default     = "t3.micro"
}

variable "root_volume_gb" {
  description = "Disk size in GB (holds the OS, Docker images, 2 GB swap, metrics and logs)."
  type        = number
  default     = 20

  validation {
    condition     = var.root_volume_gb >= 12 && var.root_volume_gb <= 50
    error_message = "Choose between 12 and 50 GB."
  }
}

variable "swap_size_mb" {
  description = "Swap file size in MB. 1 GB of RAM is tight for this stack, so 2048 is recommended."
  type        = number
  default     = 2048

  validation {
    condition     = var.swap_size_mb >= 0 && var.swap_size_mb <= 4096
    error_message = "Choose between 0 and 4096 MB."
  }
}
