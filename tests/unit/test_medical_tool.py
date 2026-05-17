"""Unit tests for aria-medical-tool Lambda handler."""
import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend/lambdas/aria-medical-tool"))


@pytest.fixture(autouse=True)
def aws_mock():
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_tables(sample_hospitals):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    ddb.create_table(
        TableName="aria-hospitals",
        KeySchema=[
            {"AttributeName": "hospital_id", "KeyType": "HASH"},
            {"AttributeName": "region", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "region", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    hospitals_table = ddb.Table("aria-hospitals")
    for h in sample_hospitals:
        hospitals_table.put_item(Item=h)

    ddb.create_table(
        TableName="aria-incidents",
        KeySchema=[
            {"AttributeName": "incident_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "incident_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    ddb.create_table(
        TableName="aria-ws-connections",
        KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "connection_id", "AttributeType": "S"},
            {"AttributeName": "incident_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "incident-index",
            "KeySchema": [{"AttributeName": "incident_id", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )


def _import_handler():
    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler
    return handler


class TestTriageProtocolFallback:
    def test_no_kb_id_returns_default_protocol(self, dynamodb_tables):
        handler = _import_handler()
        protocol, source = handler._retrieve_triage_protocol("not breathing")
        assert len(protocol) > 10
        assert source in ("default-sop", "fallback")

    def test_protocol_contains_abc(self, dynamodb_tables):
        handler = _import_handler()
        protocol, _ = handler._retrieve_triage_protocol("patient collapsed, not breathing")
        # Default protocol mentions ABC (airway, breathing, circulation)
        lower = protocol.lower()
        assert any(term in lower for term in ["airway", "breathing", "abc", "bls", "als"])


class TestHospitalSelection:
    def test_finds_accepting_hospital(self, dynamodb_tables):
        handler = _import_handler()
        hospital = handler._find_closest_hospital({"incident_type": "medical"})
        assert hospital["hospital_id"] in ("H001", "H002")
        assert hospital["er_status"] in ("accepting", "preparing")

    def test_fallback_when_no_hospitals(self):
        # Create empty hospitals table
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="aria-hospitals",
            KeySchema=[
                {"AttributeName": "hospital_id", "KeyType": "HASH"},
                {"AttributeName": "region", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "hospital_id", "AttributeType": "S"},
                {"AttributeName": "region", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        handler = _import_handler()
        hospital = handler._find_closest_hospital({})
        assert "hospital_id" in hospital
        assert "name" in hospital

    def test_hospital_has_required_fields(self, dynamodb_tables):
        handler = _import_handler()
        hospital = handler._find_closest_hospital({"incident_type": "cardiac"})
        assert "hospital_id" in hospital
        assert "name" in hospital
        assert "eta_minutes" in hospital
        assert "er_status" in hospital


class TestPreAlert:
    def test_pre_alert_failure_returns_pending(self, dynamodb_tables):
        handler = _import_handler()
        # No real Lambda — should return pending status
        result = handler._send_pre_alert(
            {"hospital_id": "H001", "eta_minutes": 5},
            {"incident_type": "medical"},
        )
        assert result.get("status") in ("pending", "accepted", "preparing")

    def test_pre_alert_with_mock_hospital(self, dynamodb_tables):
        handler = _import_handler()
        mock_lambda = MagicMock()
        mock_payload = MagicMock()
        mock_payload.read.return_value = json.dumps({"status": "accepted", "bay": "Trauma Bay 2"}).encode()
        mock_lambda.invoke.return_value = {"Payload": mock_payload}

        with patch.object(handler, "lambda_client", mock_lambda):
            result = handler._send_pre_alert(
                {"hospital_id": "H001", "eta_minutes": 5},
                {"incident_type": "cardiac_arrest"},
            )
        assert result["status"] == "accepted"


class TestHandlerInvocation:
    def test_full_handler_returns_ok(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "patient not breathing, chest pain",
            "incident_data": {"incident_type": "medical"},
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["status"] == "ok"
        assert result["incident_id"] == mock_incident_id
        assert "recommended_hospital" in result
        assert "triage_protocol" in result

    def test_handler_includes_elapsed_ms(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "overdose patient",
            "incident_data": {"incident_type": "medical"},
        }
        result = handler.lambda_handler(event, lambda_context)
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0
