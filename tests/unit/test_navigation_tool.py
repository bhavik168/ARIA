"""Unit tests for aria-navigation-tool Lambda handler."""
import importlib.util
import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from moto import mock_aws
import boto3

_HANDLER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend/lambdas/aria-navigation-tool/handler.py"))


@pytest.fixture(autouse=True)
def aws_mock():
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_tables(sample_units):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    # aria-units table
    units_table = ddb.create_table(
        TableName="aria-units",
        KeySchema=[
            {"AttributeName": "unit_id", "KeyType": "HASH"},
            {"AttributeName": "status", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "unit_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "unit_type", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "status-type-index",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "unit_type", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    for u in sample_units:
        units_table.put_item(Item=u)

    # aria-incidents table
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

    # aria-ws-connections table
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
    spec = importlib.util.spec_from_file_location("handler", _HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handler"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestUnitTypeMapping:
    def test_medical_trigger_prefers_ambulance(self, dynamodb_tables):
        handler = _import_handler()
        types = handler._unit_types_for_trigger("medical_keyword_detected")
        assert types[0] == "ambulance"

    def test_fire_trigger_prefers_fire_engine(self, dynamodb_tables):
        handler = _import_handler()
        types = handler._unit_types_for_trigger("fire_keyword_detected")
        assert types[0] == "fire_engine"

    def test_crime_trigger_prefers_police(self, dynamodb_tables):
        handler = _import_handler()
        types = handler._unit_types_for_trigger("crime_keyword_detected")
        assert types[0] == "police"

    def test_unknown_trigger_defaults_to_ambulance(self, dynamodb_tables):
        handler = _import_handler()
        types = handler._unit_types_for_trigger("unknown_trigger")
        assert "ambulance" in types


class TestEtaCalculation:
    def test_no_api_key_returns_fallback_eta(self, dynamodb_tables):
        handler = _import_handler()
        # No GOOGLE_MAPS_API_KEY set (empty string)
        eta, url = handler._google_maps_eta("47.6062,-122.3321", "47.6150,-122.3450")
        assert eta == 8  # fallback
        assert "47.6062" in url or "maps" in url

    def test_eta_returns_positive_minutes(self, dynamodb_tables):
        handler = _import_handler()
        eta, url = handler._google_maps_eta("47.6062,-122.3321", "47.6150,-122.3450")
        assert eta >= 1

    def test_maps_url_contains_destination(self, dynamodb_tables):
        handler = _import_handler()
        _, url = handler._google_maps_eta("47.6062,-122.3321", "47.6150,-122.3450")
        assert "maps" in url.lower()


class TestHandlerInvocation:
    def test_handler_returns_ok_status(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "1420 East Pike Street, not breathing",
            "incident_data": {
                "location": {"address": "1420 E Pike St", "lat": 47.6131, "lng": -122.3148},
                "incident_type": "medical",
            },
            "trigger_reason": "medical_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["status"] == "ok"
        assert result["incident_id"] == mock_incident_id

    def test_handler_returns_recommended_units_list(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "man collapsed on the street",
            "incident_data": {"incident_type": "medical"},
            "trigger_reason": "medical_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert "recommended_units" in result
        assert isinstance(result["recommended_units"], list)

    def test_handler_no_units_returns_none_unit(self, lambda_context, mock_incident_id):
        """When no units match, recommended_unit is None but status is still ok."""
        # Tables exist but no units
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="aria-units",
            KeySchema=[
                {"AttributeName": "unit_id", "KeyType": "HASH"},
                {"AttributeName": "status", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "unit_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "unit_type", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "status-type-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "unit_type", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
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
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "fire at warehouse",
            "incident_data": {"incident_type": "fire"},
            "trigger_reason": "fire_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["status"] == "ok"
        assert result["recommended_unit"] is None
