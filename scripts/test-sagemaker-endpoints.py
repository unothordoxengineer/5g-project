#!/usr/bin/env python3
"""
test-sagemaker-endpoints.py — Phase 8.6 endpoint smoke tests
Tests all 3 SageMaker endpoints with sample payloads; prints results.
Usage:  python3 scripts/test-sagemaker-endpoints.py
"""
import json
import sys
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ENDPOINTS = {
    "anomaly-detector-endpoint": {
        "payload": {"cpu_upf": 85.0, "upf_replicas": 1, "cpu_amf": 12.5},
        "expected_keys": ["is_anomaly", "anomaly_score"],
    },
    "traffic-forecaster-endpoint": {
        "payload": {"sessions": [45.2, 47.1, 44.8, 50.3, 49.1, 48.7,
                                  52.4, 51.0, 53.2, 50.8, 49.5, 51.3]},
        "expected_keys": ["forecast_6h"],
    },
    "state-classifier-endpoint": {
        "payload": {"cpu_upf": 45.2, "cpu_amf": 12.5,
                    "upf_replicas": 2, "ue_count": 0.0},
        "expected_keys": ["cluster_id", "cluster_name"],
    },
}

smr = boto3.client("sagemaker-runtime", region_name=REGION)
smc = boto3.client("sagemaker", region_name=REGION)

all_pass = True
print("=" * 60)
print("SageMaker Endpoint Smoke Tests — Phase 8.6")
print("=" * 60)

for ep_name, cfg in ENDPOINTS.items():
    print(f"\n[{ep_name}]")
    # Check InService
    try:
        ep_info = smc.describe_endpoint(EndpointName=ep_name)
        ep_status = ep_info["EndpointStatus"]
        if ep_status != "InService":
            print(f"  SKIP — endpoint status: {ep_status} (not InService)")
            all_pass = False
            continue
    except ClientError as e:
        print(f"  ERROR — {e.response['Error']['Message']}")
        all_pass = False
        continue

    # Invoke endpoint
    payload = json.dumps(cfg["payload"])
    try:
        resp = smr.invoke_endpoint(
            EndpointName=ep_name,
            ContentType="application/json",
            Accept="application/json",
            Body=payload.encode(),
        )
        result = json.loads(resp["Body"].read())
        print(f"  Input:  {cfg['payload']}")
        print(f"  Output: {result}")

        # Validate expected keys
        missing = [k for k in cfg["expected_keys"] if k not in result]
        if missing:
            print(f"  FAIL — missing keys: {missing}")
            all_pass = False
        else:
            print(f"  PASS")
    except ClientError as e:
        print(f"  ERROR — {e.response['Error']['Message']}")
        all_pass = False
    except Exception as e:
        print(f"  ERROR — {e}")
        all_pass = False

print("\n" + "=" * 60)
if all_pass:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED — see above")
print("=" * 60)

sys.exit(0 if all_pass else 1)
