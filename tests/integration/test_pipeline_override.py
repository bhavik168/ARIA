"""
Integration test — Dispatcher override flow.

Requires a deployed stack. Set ARIA_INTEGRATION_TEST=1 to run.
"""
import json
import os
import time
import pytest
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
REQUIRES_DEPLOY = pytest.mark.skipif(
    not os.environ.get("ARIA_INTEGRATION_TEST"),
    reason="Set ARIA_INTEGRATION_TEST=1 to run integration tests",
)

QUICK_TRANSCRIPT = [
    {"word": "1420", "speaker": "caller", "delay_ms": 0},
    {"word": "East", "speaker": "caller", "delay_ms": 300},
    {"word": "Pike", "speaker": "caller", "delay_ms": 200},
    {"word": "Street", "speaker": "caller", "delay_ms": 200},
    {"word": "not", "speaker": "caller", "delay_ms": 400},
    {"word": "breathing", "speaker": "caller", "delay_ms": 300},
]


def _invoke_ingest(transcript: list) -> str:
    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": "/session/start",
            "body": json.dumps({"simulation_transcript": transcript}),
        }).encode(),
    )
    result = json.loads(resp["Payload"].read())
    body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
    return body.get("incident_id", "")


def _invoke_override(incident_id: str, reason: str, choice: dict) -> dict:
    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(
        FunctionName="aria-coordinator",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": f"/session/{incident_id}/override",
            "pathParameters": {"id": incident_id},
            "body": json.dumps({
                "override_reason": reason,
                "dispatcher_choice": choice,
                "notes": "Integration test override",
            }),
        }).encode(),
    )
    result = json.loads(resp["Payload"].read())
    return json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result


def _invoke_approve(incident_id: str) -> dict:
    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(
        FunctionName="aria-coordinator",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": f"/session/{incident_id}/approve",
            "pathParameters": {"id": incident_id},
            "body": "{}",
        }).encode(),
    )
    result = json.loads(resp["Payload"].read())
    return json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result


@REQUIRES_DEPLOY
class TestOverridePipeline:
    def test_override_returns_success_status(self):
        incident_id = _invoke_ingest(QUICK_TRANSCRIPT)
        assert incident_id
        time.sleep(5)  # let pipeline start

        result = _invoke_override(
            incident_id,
            reason="Wrong unit type",
            choice={"unit_id": "MED-2", "unit_type": "ambulance"},
        )
        assert result.get("status") == "override_recorded", f"Unexpected: {result}"

    def test_override_written_to_dynamodb(self):
        incident_id = _invoke_ingest(QUICK_TRANSCRIPT)
        assert incident_id
        time.sleep(5)

        _invoke_override(
            incident_id,
            reason="Better route known",
            choice={"unit_id": "MED-3"},
        )
        time.sleep(2)

        ddb = boto3.resource("dynamodb", region_name=REGION)
        overrides = ddb.Table("aria-overrides").query(
            KeyConditionExpression="incident_id = :id",
            ExpressionAttributeValues={":id": incident_id},
        ).get("Items", [])

        assert len(overrides) >= 1
        latest = overrides[-1]
        assert latest["override_reason"] == "Better route known"
        assert latest["incident_id"] == incident_id

    def test_override_preserves_all_reasons(self):
        """All 5 dropdown reasons must be accepted."""
        incident_id = _invoke_ingest(QUICK_TRANSCRIPT)
        assert incident_id
        time.sleep(5)

        for reason in [
            "Wrong unit type",
            "Better route known",
            "Hospital preference",
            "Protocol disagreement",
            "Other",
        ]:
            result = _invoke_override(incident_id, reason=reason, choice={"unit_id": "MED-1"})
            assert result.get("status") == "override_recorded", \
                f"Override rejected for reason '{reason}': {result}"

    def test_approve_sets_dispatcher_approved(self):
        incident_id = _invoke_ingest(QUICK_TRANSCRIPT)
        assert incident_id
        time.sleep(8)  # let pipeline run

        result = _invoke_approve(incident_id)
        assert result.get("status") == "approved", f"Unexpected approve result: {result}"

        ddb = boto3.resource("dynamodb", region_name=REGION)
        item = ddb.Table("aria-incidents").get_item(
            Key={"incident_id": incident_id, "timestamp": "latest"}
        ).get("Item", {})
        assert item.get("dispatcher_approved") is True
