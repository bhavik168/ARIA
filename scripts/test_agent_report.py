#!/usr/bin/env python3
"""
Test aria-report — creates a synthetic incident in DynamoDB and generates an after-action report.

Usage:
    python scripts/test_agent_report.py
    python scripts/test_agent_report.py --incident-id <existing-id>   # generate report for real incident
"""
import argparse
import boto3
import json
import sys
import time
import uuid

REGION = "us-east-1"


def seed_synthetic_incident(table) -> str:
    """Write a complete synthetic incident record so report has data to work with."""
    incident_id = f"test-report-{int(time.time())}"
    t0 = int(time.time() * 1000) - 45000  # pretend call started 45s ago

    table.put_item(Item={
        "incident_id": incident_id,
        "timestamp": "latest",
        "status": "recommendation_complete",
        "incident_type": "medical",
        "severity": "critical",
        "t0_ms": t0,
        "ttl": int(time.time()) + 3600,
        "navigation_at_ms": t0 + 7200,
        "medical_at_ms": t0 + 9800,
        "recommendation_ready_at_ms": t0 + 11500,
        "approved_at_ms": t0 + 18000,
        "dispatcher_approved": True,
        "navigation_result": {
            "unit_id": "MED-1",
            "unit_type": "ambulance",
            "eta_minutes": 5,
            "turn_by_turn_url": "https://www.google.com/maps/dir/47.6038,-122.3301/47.6148,-122.3130",
        },
        "medical_result": {
            "triage_protocol": "ALS dispatch — cardiac arrest protocol. Priority 1.",
            "recommended_hospital": {
                "hospital_id": "H001",
                "name": "Harborview Medical Center",
                "eta_minutes": 5,
                "er_status": "accepting",
            },
            "pre_alert_status": {
                "status": "accepting",
                "hospital_name": "Harborview Medical Center",
                "notes": "Bay ready. Patient expected in 5 min.",
            },
            "source_document": "knowledge-base/medical/dispatch_guide.md",
        },
        "recommendation_card": {
            "incident_id": incident_id,
            "incident_type": "medical",
            "severity": "critical",
            "summary": "Adult male collapsed, not breathing at 1420 E Pike St, Capitol Hill",
            "recommended_unit": {"unit_id": "MED-1", "unit_type": "ambulance", "eta_minutes": 5},
            "recommended_hospital": {"hospital_id": "H001", "name": "Harborview Medical Center", "eta_minutes": 5},
            "ai_confidence": "high",
            "reasoning_summary": "Cardiac arrest at residential address. ALS + Harborview (only burn/cardiac center in region).",
            "requires_approval": True,
        },
        "audio_file_key": "audio-samples/sim_cardiac_arrest.json",
    })
    return incident_id


def run_test(incident_id: str | None) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    lambda_client = boto3.client("lambda", region_name=REGION)

    incidents_table = dynamodb.Table("aria-incidents")

    if not incident_id:
        print("No incident ID provided — seeding a synthetic incident...")
        incident_id = seed_synthetic_incident(incidents_table)
        print(f"  Synthetic incident: {incident_id}")
    else:
        print(f"Using existing incident: {incident_id}")

    payload = {
        "incident_id": incident_id,
        "action": "generate_report",
    }

    print(f"\nInvoking aria-report...")
    t0 = time.time()
    resp = lambda_client.invoke(
        FunctionName="aria-report",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    elapsed = round((time.time() - t0) * 1000)
    result = json.loads(resp["Payload"].read())

    print(f"Elapsed: {elapsed}ms")
    print(f"Status:  {result.get('status')}")
    print(f"Report URL: {result.get('report_url', 'N/A')}")
    print()

    # Check DynamoDB was updated
    item = incidents_table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    ).get("Items", [{}])[0]

    print(f"DynamoDB report_generated: {item.get('report_generated', 'N/A')}")
    print(f"  report_s3_key: {item.get('report_s3_key', 'N/A')}")
    print(f"  report_md_key: {item.get('report_md_key', 'N/A')}")

    # Validate
    errors = []
    if result.get("status") != "ok":
        errors.append(f"status was '{result.get('status')}', expected 'ok'")
    if not item.get("report_generated"):
        errors.append("report_generated not set in DynamoDB")

    print()
    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ Report agent test passed")
        print(f"  Report generated in {elapsed}ms")
        rt = item.get("recommendation_card", {})
        if rt:
            print(f"  Incident type: {rt.get('incident_type')} | Severity: {rt.get('severity')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test aria-report Lambda")
    parser.add_argument("--incident-id", help="Existing incident ID to generate report for")
    args = parser.parse_args()
    run_test(args.incident_id)
