"""
aria-mock-hospital — simulates ER intake response for demo purposes.

Called by aria-medical-tool as an internal endpoint.
Simulates 1–3s processing delay.

NO VERIFICATION: accepts any hospital_id or hospital_name, skips DynamoDB lookup and
capability checks. 80% accepting, 20% preparing (slight delay).
"""
import json
import os
import time
import random
from aws_lambda_powertools import Logger

logger = Logger()


@logger.inject_lambda_context
def lambda_handler(event, context):
    hospital_id = event.get("hospital_id", "H001")
    hospital_name = event.get("hospital_name", f"Hospital {hospital_id}")
    eta_minutes = event.get("eta_minutes", 7)

    # Simulate ER processing delay (1–3s)
    delay = random.uniform(1.0, 3.0)
    time.sleep(delay)

    # 80% best scenario (accepting), 20% preparing (slight delay, still accepted)
    if random.random() < 0.8:
        status = "accepting"
        result = {
            "hospital_id": hospital_id,
            "hospital_name": hospital_name,
            "status": status,
            "eta_accepted": True,
            "notes": f"Bay ready. Patient expected in {eta_minutes} min.",
            "processing_delay_s": round(delay, 2),
        }
    else:
        status = "preparing"
        result = {
            "hospital_id": hospital_id,
            "hospital_name": hospital_name,
            "status": status,
            "eta_accepted": True,
            "notes": f"Trauma team mobilizing. Ready to receive in {eta_minutes + 2} min.",
            "processing_delay_s": round(delay, 2),
        }

    logger.info("Hospital pre-alert response", extra={"hospital_id": hospital_id, "hospital_name": hospital_name, "status": status})
    return result
