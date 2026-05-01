###############################################################################
# ecr.tf — ECR repositories for all 5G Core container images
#
# Repositories:
#   Open5GS NFs (12): nrf, amf, smf, upf, udm, udr, ausf, pcf, bsf, nssf, scp, mongodb
#   UERANSIM (2):     gnb, ue
#   ML Serving (1):   5g-serving-api
###############################################################################

locals {
  ecr_repos = [
    "open5gs-nrf",
    "open5gs-amf",
    "open5gs-smf",
    "open5gs-upf",
    "open5gs-udm",
    "open5gs-udr",
    "open5gs-ausf",
    "open5gs-pcf",
    "open5gs-bsf",
    "open5gs-nssf",
    "open5gs-scp",
    "open5gs-mongodb",
    "ueransim-gnb",
    "ueransim-ue",
    "5g-serving-api",
  ]
}

# ── ECR Repositories ─────────────────────────────────────────────────────────

resource "aws_ecr_repository" "repos" {
  for_each = toset(local.ecr_repos)

  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "MUTABLE"   # Allow :latest re-tag during CI/CD

  image_scanning_configuration {
    scan_on_push = var.ecr_scan_on_push
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-${each.key}"
  }
}

# ── Lifecycle Policy — keep newest N images, delete untagged ─────────────────

resource "aws_ecr_lifecycle_policy" "repos" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Remove untagged images older than 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the ${var.ecr_image_retention_count} most recent tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_image_retention_count
        }
        action = { type = "expire" }
      },
    ]
  })
}

# ── Repository Policy — allow EKS node role to pull images ───────────────────
# Attached after the IAM role is created; avoids circular dependency by
# referencing the node group role ARN from iam.tf.

resource "aws_ecr_repository_policy" "eks_pull" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEKSNodePull"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.eks_node_group.arn
        }
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
        ]
      },
      {
        Sid    = "AllowGitHubActionsPush"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.github_actions.arn
        }
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:GetAuthorizationToken",
        ]
      },
    ]
  })
}
