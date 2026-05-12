resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "github_actions" {
  name = "${var.prefix_name}-github-actions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:predileto-pt/estate-os-service:environment:production",
              "repo:predileto-pt/estate-os-service:ref:refs/heads/main",
            ]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_ecr" {
  name = "${var.prefix_name}-github-ecr"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = module.ecr.repository_arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "${var.prefix_name}-github-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EC2 redeploy via SSM (`docker compose pull + up`).
      {
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation",
        ]
        Resource = [
          "arn:aws:ec2:${var.aws_region}:${local.account_id}:instance/${module.ec2.instance_id}",
          "arn:aws:ssm:${var.aws_region}:${local.account_id}:document/AWS-RunShellScript",
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
        ]
      },
      # EC2 lookup by tag — needed for the SSM step's instance resolver
      # (`aws ec2 describe-instances --filters Name=tag:Name,...`).
      {
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      },
      # Lambda worker deploys (ADR-018, zip + layer model). The CI step
      # publishes a new deps layer + updates each function's code +
      # attaches the new layer. `wait function-updated` polls
      # GetFunction/GetFunctionConfiguration.
      {
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
        ]
        Resource = [
          aws_lambda_function.extraction_worker.arn,
          aws_lambda_function.enrichment_worker.arn,
          aws_lambda_function.listings_events_worker.arn,
        ]
      },
      # Layer publishing — scoped by layer name pattern. One shared
      # deps layer for all three functions; the `*` allows successive
      # versions (`${name}:1`, `${name}:2`, ...).
      {
        Effect   = "Allow"
        Action   = "lambda:PublishLayerVersion"
        Resource = "arn:aws:lambda:${var.aws_region}:${local.account_id}:layer:${var.prefix_name}-deps*"
      },
    ]
  })
}
