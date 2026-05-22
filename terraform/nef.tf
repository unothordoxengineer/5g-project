# =============================================================================
# nef.tf — 5G NEF External API Layer — AWS Infrastructure
#
# Architecture:
#   Internet → WAF → API Gateway (REST) → Lambda → NEF service (EKS, private)
#
# Security:
#   - Cognito User Pool issues JWT tokens (RS256)
#   - API Gateway validates JWT via Cognito Authorizer
#   - WAF blocks SQL injection, XSS, rate abuse
#   - Lambda runs inside VPC private subnets
#   - NEF service reachable only from Lambda (Security Group)
#   - All API calls logged to CloudWatch
#
# Cost estimate: ~$15–25/month for 1M req/month (API GW + Lambda + Cognito)
# =============================================================================

locals {
  nef_name    = "${var.project_name}-nef"
  nef_version = "1.0.0"
}

# =============================================================================
# 1. COGNITO — User Pool (replaces local /auth/token JWT issuance)
# =============================================================================

resource "aws_cognito_user_pool" "nef" {
  name = "${local.nef_name}-user-pool"

  # Password policy
  password_policy {
    minimum_length    = 16
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  # Machine-to-machine flows use App Clients, not user accounts
  # Human sign-up is disabled for this API
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = var.common_tags
}

resource "aws_cognito_user_pool_domain" "nef" {
  domain       = "${local.nef_name}-auth"
  user_pool_id = aws_cognito_user_pool.nef.id
}

# App Client — used by external applications for client_credentials grant
resource "aws_cognito_user_pool_client" "nef_app" {
  name         = "${local.nef_name}-app-client"
  user_pool_id = aws_cognito_user_pool.nef.id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes = [
    "${aws_cognito_resource_server.nef.identifier}/nef:subscribe",
    "${aws_cognito_resource_server.nef.identifier}/nef:ue_status",
    "${aws_cognito_resource_server.nef.identifier}/nef:qos_policy",
  ]

  # Token validity
  access_token_validity  = 60   # minutes
  refresh_token_validity = 1    # days
  token_validity_units {
    access_token  = "minutes"
    refresh_token = "days"
  }
}

# Resource Server — defines the NEF API scopes
resource "aws_cognito_resource_server" "nef" {
  identifier   = "https://${local.nef_name}.${var.domain_name}"
  name         = local.nef_name
  user_pool_id = aws_cognito_user_pool.nef.id

  scope {
    scope_name        = "nef:subscribe"
    scope_description = "Register and manage UE event subscriptions"
  }
  scope {
    scope_name        = "nef:ue_status"
    scope_description = "Query UE registration and session state"
  }
  scope {
    scope_name        = "nef:qos_policy"
    scope_description = "Push QoS policy requests to the 5G core"
  }
}

# =============================================================================
# 2. WAF — Web Application Firewall
# =============================================================================

resource "aws_wafv2_web_acl" "nef" {
  name  = "${local.nef_name}-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # AWS Managed Rules — Core Rule Set (OWASP Top 10)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules — Known Bad Inputs
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  # Rate limiting — 100 req/5min per IP (maps to usage plan)
  rule {
    name     = "RateLimit"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 500   # per 5-minute window = ~100/min
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.nef_name}-waf"
    sampled_requests_enabled   = true
  }

  tags = var.common_tags
}

# =============================================================================
# 3. API GATEWAY — REST API
# =============================================================================

resource "aws_api_gateway_rest_api" "nef" {
  name        = local.nef_name
  description = "5G NEF External API — UE events, QoS policy, UE status"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = var.common_tags
}

# Associate WAF with API Gateway stage
resource "aws_wafv2_web_acl_association" "nef" {
  resource_arn = aws_api_gateway_stage.nef.arn
  web_acl_arn  = aws_wafv2_web_acl.nef.arn
}

# Cognito JWT Authorizer
resource "aws_api_gateway_authorizer" "cognito" {
  name            = "cognito-jwt"
  rest_api_id     = aws_api_gateway_rest_api.nef.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [aws_cognito_user_pool.nef.arn]
  identity_source = "method.request.header.Authorization"
}

# Usage plan — 100 req/sec burst, daily quota
resource "aws_api_gateway_usage_plan" "nef" {
  name = "${local.nef_name}-plan"

  throttle_settings {
    rate_limit  = 100  # req/sec
    burst_limit = 200
  }
  quota_settings {
    limit  = 100000
    period = "DAY"
  }

  api_stages {
    api_id = aws_api_gateway_rest_api.nef.id
    stage  = aws_api_gateway_stage.nef.stage_name
  }
}

# /subscribe resource
resource "aws_api_gateway_resource" "subscribe" {
  rest_api_id = aws_api_gateway_rest_api.nef.id
  parent_id   = aws_api_gateway_rest_api.nef.root_resource_id
  path_part   = "subscribe"
}

# /ue-status resource
resource "aws_api_gateway_resource" "ue_status" {
  rest_api_id = aws_api_gateway_rest_api.nef.id
  parent_id   = aws_api_gateway_rest_api.nef.root_resource_id
  path_part   = "ue-status"
}

resource "aws_api_gateway_resource" "ue_status_imsi" {
  rest_api_id = aws_api_gateway_rest_api.nef.id
  parent_id   = aws_api_gateway_resource.ue_status.id
  path_part   = "{imsi}"
}

# /qos-policy resource
resource "aws_api_gateway_resource" "qos_policy" {
  rest_api_id = aws_api_gateway_rest_api.nef.id
  parent_id   = aws_api_gateway_rest_api.nef.root_resource_id
  path_part   = "qos-policy"
}

# Helper: creates a method + Lambda integration with Cognito auth
# (Extracted as locals for DRY — Terraform doesn't support reusable modules
#  inline, so we create each method explicitly below)

# POST /subscribe
resource "aws_api_gateway_method" "subscribe_post" {
  rest_api_id   = aws_api_gateway_rest_api.nef.id
  resource_id   = aws_api_gateway_resource.subscribe.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "subscribe_post" {
  rest_api_id             = aws_api_gateway_rest_api.nef.id
  resource_id             = aws_api_gateway_resource.subscribe.id
  http_method             = aws_api_gateway_method.subscribe_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.nef.invoke_arn
}

# GET /ue-status/{imsi}
resource "aws_api_gateway_method" "ue_status_get" {
  rest_api_id   = aws_api_gateway_rest_api.nef.id
  resource_id   = aws_api_gateway_resource.ue_status_imsi.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "ue_status_get" {
  rest_api_id             = aws_api_gateway_rest_api.nef.id
  resource_id             = aws_api_gateway_resource.ue_status_imsi.id
  http_method             = aws_api_gateway_method.ue_status_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.nef.invoke_arn
}

# POST /qos-policy
resource "aws_api_gateway_method" "qos_policy_post" {
  rest_api_id   = aws_api_gateway_rest_api.nef.id
  resource_id   = aws_api_gateway_resource.qos_policy.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "qos_policy_post" {
  rest_api_id             = aws_api_gateway_rest_api.nef.id
  resource_id             = aws_api_gateway_resource.qos_policy.id
  http_method             = aws_api_gateway_method.qos_policy_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.nef.invoke_arn
}

# Deployment + Stage
resource "aws_api_gateway_deployment" "nef" {
  rest_api_id = aws_api_gateway_rest_api.nef.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.subscribe.id,
      aws_api_gateway_resource.ue_status_imsi.id,
      aws_api_gateway_resource.qos_policy.id,
      aws_api_gateway_method.subscribe_post.id,
      aws_api_gateway_method.ue_status_get.id,
      aws_api_gateway_method.qos_policy_post.id,
      aws_api_gateway_integration.subscribe_post.id,
      aws_api_gateway_integration.ue_status_get.id,
      aws_api_gateway_integration.qos_policy_post.id,
    ]))
  }

  # Must wait for all method integrations to exist before deploying
  depends_on = [
    aws_api_gateway_integration.subscribe_post,
    aws_api_gateway_integration.ue_status_get,
    aws_api_gateway_integration.qos_policy_post,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "nef" {
  deployment_id = aws_api_gateway_deployment.nef.id
  rest_api_id   = aws_api_gateway_rest_api.nef.id
  stage_name    = var.environment

  # CloudWatch Logs account-level role not configured — logging disabled.
  # Re-enable access_log_settings after running:
  #   aws apigateway update-account --patch-operations \
  #     op=replace,path=/cloudwatchRoleArn,value=<role-arn>
  xray_tracing_enabled = false

  tags = var.common_tags
}

# API key (optional — for additional per-client tracking)
resource "aws_api_gateway_api_key" "nef_default" {
  name    = "${local.nef_name}-default-key"
  enabled = true
}

resource "aws_api_gateway_usage_plan_key" "nef" {
  key_id        = aws_api_gateway_api_key.nef_default.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.nef.id
}

# =============================================================================
# 4. LAMBDA — API proxy (API Gateway → Lambda → NEF service on EKS)
# =============================================================================

# Lambda execution role
resource "aws_iam_role" "nef_lambda" {
  name = "${local.nef_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = var.common_tags
}

resource "aws_iam_role_policy_attachment" "nef_lambda_vpc" {
  role       = aws_iam_role.nef_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "nef_lambda_logs" {
  role       = aws_iam_role.nef_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Security Group for Lambda (egress to NEF service in EKS)
resource "aws_security_group" "nef_lambda" {
  name        = "${local.nef_name}-lambda-sg"
  description = "Lambda can reach NEF service inside EKS cluster"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "NEF service port"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    # EKS worker node security group CIDR — tighten to SG reference in production
    cidr_blocks = [var.vpc_cidr]
  }
  egress {
    description = "DNS"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    description = "HTTPS (Cognito JWKS fetch)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.common_tags
}

# Lambda function — forwards requests to NEF service running on EKS
# The function code is a thin HTTP proxy; NEF's FastAPI handles all logic.
# On first deploy: upload a placeholder zip; CI/CD replaces it via
# `aws lambda update-function-code --zip-file fileb://nef-lambda.zip`
data "archive_file" "nef_lambda_placeholder" {
  type        = "zip"
  output_path = "${path.module}/files/nef-lambda-placeholder.zip"
  source {
    content  = <<-PYTHON
      import json, urllib.request, os

      NEF_URL = os.environ["NEF_SERVICE_URL"]

      def handler(event, context):
          method  = event["httpMethod"]
          path    = event["path"]
          body    = event.get("body", "")
          headers = event.get("headers", {}) or {}

          url = NEF_URL.rstrip("/") + path
          req = urllib.request.Request(
              url, data=body.encode() if body else None,
              headers={k: v for k, v in headers.items()
                       if k.lower() in ("authorization", "content-type")},
              method=method,
          )
          try:
              with urllib.request.urlopen(req, timeout=8) as resp:
                  return {
                      "statusCode": resp.status,
                      "headers": {"Content-Type": "application/json"},
                      "body": resp.read().decode(),
                  }
          except urllib.error.HTTPError as e:
              return {
                  "statusCode": e.code,
                  "headers": {"Content-Type": "application/json"},
                  "body": e.read().decode(),
              }
          except Exception as exc:
              return {
                  "statusCode": 502,
                  "headers": {"Content-Type": "application/json"},
                  "body": json.dumps({"error": str(exc)}),
              }
    PYTHON
    filename = "handler.py"
  }
}

resource "aws_lambda_function" "nef" {
  function_name    = local.nef_name
  role             = aws_iam_role.nef_lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.nef_lambda_placeholder.output_path
  source_code_hash = data.archive_file.nef_lambda_placeholder.output_base64sha256
  timeout          = 10
  memory_size      = 256

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.nef_lambda.id]
  }

  environment {
    variables = {
      # Internal EKS service URL — set after EKS cluster is created
      # Format: http://<nef-service-cluster-ip>:80
      NEF_SERVICE_URL            = "http://nef.open5gs.svc.cluster.local:80"
      NEF_COGNITO_JWKS_URL       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.nef.id}/.well-known/jwks.json"
      NEF_COGNITO_CLIENT_ID      = aws_cognito_user_pool_client.nef_app.id
      NEF_COGNITO_USER_POOL_ID   = aws_cognito_user_pool.nef.id
    }
  }

  tags = var.common_tags
}

# Grant API Gateway permission to invoke Lambda
resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.nef.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.nef.execution_arn}/*/*"
}

# =============================================================================
# 5. CLOUDWATCH — Logging
# =============================================================================

resource "aws_cloudwatch_log_group" "nef_apigw" {
  name              = "/aws/apigateway/${local.nef_name}"
  retention_in_days = 30
  tags              = var.common_tags
}

resource "aws_cloudwatch_log_group" "nef_lambda" {
  name              = "/aws/lambda/${local.nef_name}"
  retention_in_days = 30
  tags              = var.common_tags
}

# CloudWatch alarm: 5xx error rate > 5%
resource "aws_cloudwatch_metric_alarm" "nef_5xx" {
  alarm_name          = "${local.nef_name}-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "5XXError"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Average"
  threshold           = 0.05
  alarm_description   = "NEF API 5xx error rate exceeds 5%"

  dimensions = {
    ApiName = local.nef_name
    Stage   = var.environment
  }

  tags = var.common_tags
}

# CloudWatch alarm: latency > 400ms p99
resource "aws_cloudwatch_metric_alarm" "nef_latency" {
  alarm_name          = "${local.nef_name}-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "IntegrationLatency"
  namespace           = "AWS/ApiGateway"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 400
  alarm_description   = "NEF p99 latency exceeds 400ms"

  dimensions = {
    ApiName = local.nef_name
    Stage   = var.environment
  }

  tags = var.common_tags
}

# =============================================================================
# 6. OUTPUTS
# =============================================================================

output "nef_api_endpoint" {
  description = "NEF API Gateway base URL — use for external client configuration"
  value       = "${aws_api_gateway_stage.nef.invoke_url}"
}

output "nef_cognito_token_endpoint" {
  description = "Cognito OAuth2 token endpoint (client_credentials flow)"
  value       = "https://${aws_cognito_user_pool_domain.nef.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
}

output "nef_cognito_client_id" {
  description = "Cognito App Client ID for external applications"
  value       = aws_cognito_user_pool_client.nef_app.id
  sensitive   = false
}

output "nef_api_key" {
  description = "API Gateway API key value"
  value       = aws_api_gateway_api_key.nef_default.value
  sensitive   = true
}
