"""
aria-mock-hospital — simulates ER intake response for demo purposes.

Called by aria-medical-tool as an internal endpoint.
Simulates 1–3s processing delay. Returns accepting/preparing/redirected status.
"""
import json
import os
import time
import random
import boto3
from aws_lambda_powertools import Logger

logger = Logger()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
HOSPITALS_TABLE = os.environ["HOSPITALS_TABLE"]

ALTERNATE_HOSPITALS = {
    "H001": "H002",
    "H002": "H003",
    "H003": "H001",
    "H004": "H005",
    "H005": "H004",
}


@logger.inject_lambda_context
def lambda_handler(event, context):
    hospital_id = event.get("hospital_id", "H001")
    patient_condition = event.get("patient_condition", "unknown")
    eta_minutes = event.get("eta_minutes", 7)
    resources_needed = event.get("resources_needed", [])

    # Simulate ER processing delay (1–3s)
    delay = random.uniform(1.0, 3.0)
    time.sleep(delay)

    hospital = _get_hospital(hospital_id)
    capacity = hospital.get("current_capacity", 5)
    max_capacity = hospital.get("max_capacity", 10)
    has_resources = all(
        r in hospital.get("capabilities", []) for r in resources_needed
    )

    if capacity >= max_capacity:
        status = "redirected"
        alternate_id = ALTERNATE_HOSPITALS.get(hospital_id, "H002")
        alternate = _get_hospital(alternate_id)
        notes = f"At capacity. Redirecting to {alternate.get('name', alternate_id)}."
        result = {
            "hospital_id": hospital_id,
            "hospital_name": hospital.get("name", hospital_id),
            "status": status,
            "eta_accepted": False,
            "notes": notes,
            "alternate_hospital_id": alternate_id,
            "alternate_hospital_name": alternate.get("name", alternate_id),
            "processing_delay_s": round(delay, 2),
        }
    elif not has_resources:
        status = "preparing"
        notes = f"Mobilizing required resources: {', '.join(resources_needed)}. ETA to readiness: 2–3 min."
        result = {
            "hospital_id": hospital_id,
            "hospital_name": hospital.get("name", hospital_id),
            "status": status,
            "eta_accepted": True,
            "notes": notes,
            "processing_delay_s": round(delay, 2),
        }
    else:
        status = "accepting"
        notes = f"Bay ready. Patient expected in {eta_minutes} min."
        result = {
            "hospital_id": hospital_id,
            "hospital_name": hospital.get("name", hospital_id),
            "status": status,
            "eta_accepted": True,
            "notes": notes,
            "processing_delay_s": round(delay, 2),
        }
        # Increment capacity counter
        _increment_capacity(hospital_id)

    logger.info("Hospital pre-alert response", extra={"hospital_id": hospital_id, "status": status})
    return result


def _get_hospital(hospital_id: str) -> dict:
    table = dynamodb.Table(HOSPITALS_TABLE)
    resp = table.query(
        KeyConditionExpression="hospital_id = :hid",
        ExpressionAttributeValues={":hid": hospital_id},
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else {"name": hospital_id, "current_capacity": 3, "max_capacity": 10, "capabilities": ["trauma_bay", "icu"]}


def _increment_capacity(hospital_id: str) -> None:
    table = dynamodb.Table(HOSPITALS_TABLE)
    try:
        table.update_item(
            Key={"hospital_id": hospital_id, "region": "us-east-1"},
            UpdateExpression="ADD current_capacity :one",
            ExpressionAttributeValues={":one": 1},
        )
    except Exception as e:
        logger.warning("Could not update hospital capacity", exc_info=e)
