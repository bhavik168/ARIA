"""Shared pytest fixtures and environment setup for all unit tests."""
import os
import sys
import json
import pytest
import boto3

# Set all required env vars BEFORE any handler module is imported.
# moto requires AWS_DEFAULT_REGION + fake credentials to work without real AWS.
os.environ.setdefault("AWS_DEPLOY_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("AWS_SECURITY_TOKEN", "test-token")
os.environ.setdefault("AWS_SESSION_TOKEN", "test-token")

os.environ.setdefault("INCIDENTS_TABLE", "aria-incidents")
os.environ.setdefault("UNITS_TABLE", "aria-units")
os.environ.setdefault("HOSPITALS_TABLE", "aria-hospitals")
os.environ.setdefault("CONNECTIONS_TABLE", "aria-ws-connections")
os.environ.setdefault("OVERRIDES_TABLE", "aria-overrides")

os.environ.setdefault("NAVIGATION_FUNCTION", "aria-navigation-tool")
os.environ.setdefault("MEDICAL_FUNCTION", "aria-medical-tool")
os.environ.setdefault("HAZMAT_FUNCTION", "aria-hazmat-tool")
os.environ.setdefault("REPORT_FUNCTION", "aria-report")
os.environ.setdefault("MOCK_HOSPITAL_FUNCTION", "aria-mock-hospital")
os.environ.setdefault("STREAM_PROCESSOR_FUNCTION", "aria-stream-processor")
os.environ.setdefault("VERIFIER_FUNCTION", "aria-verifier")

os.environ.setdefault("BEDROCK_KB_ID", "")
os.environ.setdefault("WS_ENDPOINT", "")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "")
os.environ.setdefault("GUARDRAIL_ID", "")
os.environ.setdefault("GUARDRAIL_VERSION", "DRAFT")
os.environ.setdefault("ARIA_BUCKET", "aria-test-bucket")


class MockLambdaContext:
    function_name = "test-function"
    function_version = "$LATEST"
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:test-function"
    memory_limit_in_mb = 512
    aws_request_id = "test-request-id"
    log_group_name = "/aws/lambda/test-function"
    log_stream_name = "test-stream"
    remaining_time_in_millis = lambda self: 30000


@pytest.fixture
def lambda_context():
    return MockLambdaContext()


@pytest.fixture
def mock_incident_id():
    return "test-incident-001"


@pytest.fixture
def sample_units():
    return [
        {
            "unit_id": "MED-1",
            "unit_type": "ambulance",
            "status": "available",
            "lat": "47.6062",
            "lng": "-122.3321",
            "station": "Station 10",
        },
        {
            "unit_id": "FIRE-1",
            "unit_type": "fire_engine",
            "status": "available",
            "lat": "47.6150",
            "lng": "-122.3450",
            "station": "Station 2",
        },
        {
            "unit_id": "POL-1",
            "unit_type": "police",
            "status": "available",
            "lat": "47.6080",
            "lng": "-122.3380",
            "station": "North Precinct",
        },
    ]


@pytest.fixture
def sample_hospitals():
    return [
        {
            "hospital_id": "H001",
            "name": "Harborview Medical Center",
            "region": "Seattle",
            "er_status": "accepting",
            "distance_minutes": 5,
            "capabilities": ["trauma", "cardiac", "neurology"],
        },
        {
            "hospital_id": "H002",
            "name": "UW Medical Center",
            "region": "Seattle",
            "er_status": "accepting",
            "distance_minutes": 8,
            "capabilities": ["trauma", "cardiac"],
        },
    ]
