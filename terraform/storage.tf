# The "deploy bundle": the stack/ folder zipped and uploaded to a private S3 bucket.
# The server downloads it at boot, checks its SHA-256 fingerprint, and runs Ansible from it.

data "archive_file" "stack" {
  type             = "zip"
  source_dir       = "${path.module}/../stack"
  output_path      = "${path.module}/.build/stack.zip"
  output_file_mode = "0644" # same fingerprint on Windows, macOS and Linux

  # Never ship local-only files (your laptop's test secrets) to AWS.
  excludes = [
    "compose/secrets/**",
    "compose/.env",
    "compose/alertmanager/alertmanager.yml",
    "**/__pycache__/**",
  ]
}

# Files the server needs. A missing (or wrongly capitalised) one stops 'terraform plan'
# with a clear message, instead of a server that boots and then fails to deploy.
locals {
  stack_files = fileset("${path.module}/../stack", "**") # exact, case-sensitive names

  required_stack_files = [
    "ansible/ansible.cfg",
    "ansible/site.yml",
    "ansible/roles/base/handlers/main.yml",
    "ansible/roles/base/tasks/main.yml",
    "ansible/roles/docker/handlers/main.yml",
    "ansible/roles/docker/tasks/main.yml",
    "ansible/roles/stack/tasks/main.yml",
    "ansible/roles/stack/templates/alertmanager.yml.j2",
    "compose/docker-compose.yml",
    "compose/alertmanager/alertmanager.local.yml",
    "compose/alertmanager/templates/sns.tmpl",
    "compose/prometheus/prometheus.yml",
    "compose/prometheus/rules/slo-recording.rules.yml",
    "compose/prometheus/rules/slo-alerts.rules.yml",
    "demo-app/Dockerfile",
    "demo-app/app.py",
  ]

  missing_stack_files = [for f in local.required_stack_files : f if !contains(local.stack_files, f)]
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${var.project}-artifacts-"
  force_destroy = true # it only holds build output, so 'terraform destroy' may empty it
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced" # disables ACLs entirely
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Refuse any request that is not encrypted in transit (plain HTTP).
data "aws_iam_policy_document" "artifacts_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket     = aws_s3_bucket.artifacts.id
  policy     = data.aws_iam_policy_document.artifacts_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

resource "aws_s3_object" "stack" {
  bucket = aws_s3_bucket.artifacts.id
  # The fingerprint is part of the name: any change to stack/ = a new object = a new server.
  key    = "bundles/stack-${data.archive_file.stack.output_sha256}.zip"
  source = data.archive_file.stack.output_path

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.artifacts]

  lifecycle {
    precondition {
      condition     = length(local.missing_stack_files) == 0
      error_message = "These files are missing from the stack folder (names are case-sensitive): ${join(", ", local.missing_stack_files)}. Create them from the guide, then run terraform plan again."
    }
  }
}
