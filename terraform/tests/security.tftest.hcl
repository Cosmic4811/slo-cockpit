# Terraform tests with a FAKE AWS provider: no account, no credentials, no cost.
# Run from the terraform folder:  terraform init -backend=false  then  terraform test

mock_provider "aws" {
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_ec2_instance_type" {
    defaults = { supported_architectures = ["x86_64"] }
  }
  mock_data "aws_ec2_instance_type_offerings" {
    defaults = { locations = ["us-east-1a", "us-east-1b"] }
  }
  mock_data "aws_subnets" {
    defaults = { ids = ["subnet-0bbbbbbbbbbbbbbbb", "subnet-0aaaaaaaaaaaaaaaa"] }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-0123456789abcdef0" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { id = "slo-cockpit-artifacts-test", arn = "arn:aws:s3:::slo-cockpit-artifacts-test" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-east-1:123456789012:slo-cockpit-alerts" }
  }
  mock_resource "aws_ssm_parameter" {
    defaults = { arn = "arn:aws:ssm:us-east-1:123456789012:parameter/slo-cockpit/test" }
  }
}

variables {
  alert_email = "test@example.com"
}

run "server_is_locked_down" {
  command = apply # "apply" against the fake provider: nothing real is created

  assert {
    condition     = aws_instance.cockpit.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 must be required (blocks SSRF credential theft)."
  }
  assert {
    condition     = aws_instance.cockpit.root_block_device[0].encrypted
    error_message = "The disk must be encrypted."
  }
  assert {
    condition     = aws_instance.cockpit.subnet_id == "subnet-0aaaaaaaaaaaaaaaa"
    error_message = "The server should use the first default subnet (sorted)."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.artifacts.restrict_public_buckets && aws_s3_bucket_public_access_block.artifacts.block_public_policy
    error_message = "The bundle bucket must block all public access."
  }
}

run "first_boot_script_is_clean" {
  command = apply

  assert {
    condition     = !strcontains(local.user_data, "\r")
    error_message = "User data must use Linux line endings."
  }
  assert {
    condition     = strcontains(local.user_data, "BUNDLE_SHA256=${data.archive_file.stack.output_sha256}")
    error_message = "User data must pin the exact bundle fingerprint."
  }
  assert {
    condition     = length(local.user_data) < 16384
    error_message = "EC2 user data is limited to 16 KB."
  }
  assert {
    condition     = !strcontains(lower(local.user_data), "password=")
    error_message = "No secret values may appear in user data."
  }
}

run "rejects_an_invalid_email" {
  command = plan

  variables {
    alert_email = "not-an-email"
  }

  expect_failures = [var.alert_email]
}
