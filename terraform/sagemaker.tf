###############################################################################
# sagemaker.tf — SageMaker real-time endpoints for all 3 ML models
#
# Models
#   1. anomaly-detector   — Isolation Forest (IF)
#   2. load-forecaster    — ARIMA(3,0,1)
#   3. state-classifier   — k-Means (k=2)
#
# Architecture
#   Each model: SageMaker Model → Endpoint Configuration → Endpoint
#   All three share the same 5g-serving-api container image from ECR; the
#   MODEL_NAME env var tells the container which pkl to load.
###############################################################################

locals {
  sm_models = {
    anomaly-detector = {
      description = "Isolation Forest anomaly detection"
      model_key   = "anomaly"
      variant     = "AllTraffic"
    }
    load-forecaster = {
      description = "ARIMA(3,0,1) UE load forecasting"
      model_key   = "forecast"
      variant     = "AllTraffic"
    }
    state-classifier = {
      description = "k-Means (k=2) 5G core state classification"
      model_key   = "cluster"
      variant     = "AllTraffic"
    }
  }
}

# ── SageMaker Model definitions ───────────────────────────────────────────────

resource "aws_sagemaker_model" "models" {
  for_each = local.sm_models

  name               = "${var.project_name}-${each.key}"
  execution_role_arn = aws_iam_role.sagemaker_execution.arn

  primary_container {
    # The same FastAPI image that runs in-cluster; SageMaker calls /invocations
    image = var.sagemaker_container_image != "" ? var.sagemaker_container_image : (
      "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}/5g-serving-api:latest"
    )

    # Model artifact — the packed ml/models/ directory as model.tar.gz in S3
    model_data_url = var.sagemaker_model_bucket != "" ? (
      "s3://${var.sagemaker_model_bucket}/models/${each.key}/model.tar.gz"
    ) : null

    environment = {
      MODEL_NAME       = each.value.model_key
      MODEL_DIR        = "/opt/ml/model"
      SAGEMAKER_REGION = var.aws_region
    }
  }

  tags = {
    Name        = "${var.project_name}-${each.key}"
    ModelType   = each.value.model_key
    Description = each.value.description
  }
}

# ── Endpoint Configurations ───────────────────────────────────────────────────

resource "aws_sagemaker_endpoint_configuration" "configs" {
  for_each = local.sm_models

  name = "${var.project_name}-${each.key}-config"

  production_variants {
    variant_name           = each.value.variant
    model_name             = aws_sagemaker_model.models[each.key].name
    initial_instance_count = 1
    instance_type          = var.sagemaker_instance_type

    # Start with 100 % traffic on a single variant
    initial_variant_weight = 1
  }

  # Enable data capture for model monitoring (writes to S3)
  data_capture_config {
    enable_capture              = true
    initial_sampling_percentage = 100
    destination_s3_uri = var.sagemaker_model_bucket != "" ? (
      "s3://${var.sagemaker_model_bucket}/capture/${each.key}"
    ) : "s3://placeholder-bucket/capture/${each.key}"

    capture_options {
      capture_mode = "Input"
    }
    capture_options {
      capture_mode = "Output"
    }
  }

  tags = {
    Name      = "${var.project_name}-${each.key}-config"
    ModelType = each.value.model_key
  }
}

# ── Endpoints ─────────────────────────────────────────────────────────────────

resource "aws_sagemaker_endpoint" "endpoints" {
  for_each = local.sm_models

  name                 = "${var.project_name}-${each.key}"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.configs[each.key].name

  tags = {
    Name      = "${var.project_name}-${each.key}"
    ModelType = each.value.model_key
  }
}

# ── Auto-scaling for SageMaker endpoints ─────────────────────────────────────
# Scale between 1–3 instances; triggered when SageMaker:InvocationsPerInstance > 100

resource "aws_appautoscaling_target" "sagemaker" {
  for_each = local.sm_models

  max_capacity       = 3
  min_capacity       = 1
  resource_id        = "endpoint/${aws_sagemaker_endpoint.endpoints[each.key].name}/variant/${each.value.variant}"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  service_namespace  = "sagemaker"
}

resource "aws_appautoscaling_policy" "sagemaker" {
  for_each = local.sm_models

  name               = "${var.project_name}-${each.key}-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.sagemaker[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.sagemaker[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.sagemaker[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 100   # invocations per instance per minute

    predefined_metric_specification {
      predefined_metric_type = "SageMakerVariantInvocationsPerInstance"
    }

    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
