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
      description = "ARIMA-3-0-1 UE load forecasting"
      model_key   = "forecast"
      variant     = "AllTraffic"
    }
    state-classifier = {
      description = "k-Means k2 5G core state classification"
      model_key   = "cluster"
      variant     = "AllTraffic"
    }
  }
}

# ── SageMaker Model / Endpoint / Autoscaling ─────────────────────────────────
# COMMENTED OUT — deploy manually after pushing 5g-serving-api image to ECR.
#
# Steps to re-enable:
#   1. docker push <account>.dkr.ecr.<region>.amazonaws.com/5g-core/5g-serving-api:latest
#   2. Set var.sagemaker_container_image to that URI
#   3. Set var.sagemaker_model_bucket to the S3 bucket holding model.tar.gz files
#   4. Uncomment the blocks below and run: terraform apply
#
# resource "aws_sagemaker_model" "models" {
#   for_each           = local.sm_models
#   name               = "${var.project_name}-${each.key}"
#   execution_role_arn = aws_iam_role.sagemaker_execution.arn
#   primary_container {
#     image          = var.sagemaker_container_image
#     model_data_url = "s3://${var.sagemaker_model_bucket}/models/${each.key}/model.tar.gz"
#     environment = {
#       MODEL_NAME       = each.value.model_key
#       MODEL_DIR        = "/opt/ml/model"
#       SAGEMAKER_REGION = var.aws_region
#     }
#   }
#   tags = {
#     Name        = "${var.project_name}-${each.key}"
#     ModelType   = each.value.model_key
#     Description = each.value.description
#   }
# }
#
# resource "aws_sagemaker_endpoint_configuration" "configs" {
#   for_each = local.sm_models
#   name     = "${var.project_name}-${each.key}-config"
#   production_variants {
#     variant_name           = each.value.variant
#     model_name             = aws_sagemaker_model.models[each.key].name
#     initial_instance_count = 1
#     instance_type          = var.sagemaker_instance_type
#     initial_variant_weight = 1
#   }
#   data_capture_config {
#     enable_capture              = true
#     initial_sampling_percentage = 100
#     destination_s3_uri          = "s3://${var.sagemaker_model_bucket}/capture/${each.key}"
#     capture_options { capture_mode = "Input" }
#     capture_options { capture_mode = "Output" }
#   }
#   tags = { Name = "${var.project_name}-${each.key}-config", ModelType = each.value.model_key }
# }
#
# resource "aws_sagemaker_endpoint" "endpoints" {
#   for_each             = local.sm_models
#   name                 = "${var.project_name}-${each.key}"
#   endpoint_config_name = aws_sagemaker_endpoint_configuration.configs[each.key].name
#   tags = { Name = "${var.project_name}-${each.key}", ModelType = each.value.model_key }
# }
#
# resource "aws_appautoscaling_target" "sagemaker" {
#   for_each           = local.sm_models
#   max_capacity       = 3
#   min_capacity       = 1
#   resource_id        = "endpoint/${aws_sagemaker_endpoint.endpoints[each.key].name}/variant/${each.value.variant}"
#   scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
#   service_namespace  = "sagemaker"
# }
#
# resource "aws_appautoscaling_policy" "sagemaker" {
#   for_each           = local.sm_models
#   name               = "${var.project_name}-${each.key}-scaling"
#   policy_type        = "TargetTrackingScaling"
#   resource_id        = aws_appautoscaling_target.sagemaker[each.key].resource_id
#   scalable_dimension = aws_appautoscaling_target.sagemaker[each.key].scalable_dimension
#   service_namespace  = aws_appautoscaling_target.sagemaker[each.key].service_namespace
#   target_tracking_scaling_policy_configuration {
#     target_value = 100
#     predefined_metric_specification {
#       predefined_metric_type = "SageMakerVariantInvocationsPerInstance"
#     }
#     scale_in_cooldown  = 300
#     scale_out_cooldown = 60
#   }
# }
