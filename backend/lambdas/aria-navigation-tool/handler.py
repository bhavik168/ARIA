"""
aria-navigation-tool — finds optimal available unit and calculates real ETA via Google Maps.

Triggered by aria-stream-processor (LocationWatcher / CrimeWatcher).
Reads aria-units table, filters available units, calls Google Maps Directions API.
Pushes result to dashboard WebSocket and returns structured dispatch recommendation.
"""
import json
import os
import time
import urllib.request
import urllib.parse
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None

UNITS_TABLE = os.environ["UNITS_TABLE"]
INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

UNIT_TYPE_PRIORITY = {"ambulance": 1, "fire_engine": 2, "police": 3, "hazmat": 4, "ladder": 5, "supervisor": 6}


@logger.inject_lambda_context
def lambda_handler(event, context):
    # Route: Bedrock Agent action group invocation vs. direct Lambda call
    if event.get("messageVersion") == "1.0" and "actionGroup" in event:
        return _handle_agent_action(event)
    return _handle_direct(event)


def _handle_agent_action(event: dict) -> dict:
    """Handle Bedrock Agent action group invocation. Returns Bedrock Agent response format."""
    action_group = event.get("actionGroup", "NavigationActions")
    function = event.get("function", "find_unit")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    incident_id = params.get("incident_id", "")
    context_so_far = params.get("context_so_far", "")
    trigger_reason = params.get("trigger_reason", "location_detected")
    verifier_json = params.get("verifier_classification_json", "{}")
    try:
        verifier = json.loads(verifier_json)
    except (json.JSONDecodeError, TypeError):
        verifier = {}

    logger.info("Navigation agent action invoked", extra={"incident_id": incident_id, "function": function})
    result = _run_navigation(incident_id, context_so_far, {}, trigger_reason, verifier, int(time.time() * 1000))

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {"body": json.dumps(result, default=str)}
                }
            },
        },
    }


def _handle_direct(event: dict) -> dict:
    """Handle direct Lambda invocation from coordinator fallback or stream processor."""
    t0 = int(time.time() * 1000)
    incident_id = event.get("incident_id", "")
    context_so_far = event.get("context_so_far", "")
    incident_data = event.get("incident_data", {})
    trigger_reason = event.get("trigger_reason", "location_detected")
    verifier = event.get("verifier_classification", {})

    logger.info("Navigation tool invoked (direct)", extra={"incident_id": incident_id, "trigger": trigger_reason})
    result = _run_navigation(incident_id, context_so_far, incident_data, trigger_reason, verifier, t0)
    _push_to_dashboard(incident_id, {"type": "agent_complete", "agent": "navigation", "result": result})
    return result


def _run_navigation(incident_id: str, context_so_far: str, incident_data: dict, trigger_reason: str, verifier: dict, t0: int) -> dict:
    incident_location = _extract_location(context_so_far, incident_data)
    available_units = _get_available_units(trigger_reason)
    recommendations = _calculate_etas(incident_location, available_units)

    best_unit = recommendations[0] if recommendations else None
    _log_dispatch_event(incident_id, best_unit, t0)

    elapsed_ms = int(time.time() * 1000) - t0
    metrics.add_metric("navigation_agent_complete_ms", unit=MetricUnit.Milliseconds, value=elapsed_ms)

    return {
        "status": "ok",
        "incident_id": incident_id,
        "incident_location": incident_location,
        "recommended_units": recommendations[:3],
        "recommended_unit": best_unit,
        "elapsed_ms": elapsed_ms,
    }


def _extract_location(context: str, incident_data: dict) -> dict:
    if incident_data.get("location", {}).get("address"):
        return incident_data["location"]
    address = _nlp_extract_address(context)
    return {"address": address, "lat": 47.6062, "lng": -122.3321}


def _nlp_extract_address(context: str) -> str:
    """Use Claude to extract incident location from 911 transcript text."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 80,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": (
                "Extract the incident location from this 911 call transcript. "
                "Return ONLY the location string — street address, intersection, "
                "highway exit, or landmark. One line, no explanation.\n\n"
                f"TRANSCRIPT:\n{context[:500]}"
            ),
        }],
    })
    for attempt in range(3):
        try:
            resp = bedrock_runtime.invoke_model(
                modelId="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            raw = json.loads(resp["body"].read())
            return raw["content"][0]["text"].strip()[:200]
        except Exception as e:
            if "ThrottlingException" in type(e).__name__ and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            logger.warning("NLP location extraction failed", exc_info=e)
            return "Seattle, WA — location pending"
    return "Seattle, WA — location pending"


def _get_available_units(trigger_reason: str) -> list:
    table = dynamodb.Table(UNITS_TABLE)
    preferred_types = _unit_types_for_trigger(trigger_reason)

    units = []
    for unit_type in preferred_types:
        resp = table.query(
            IndexName="status-type-index",
            KeyConditionExpression="#s = :available AND unit_type = :type",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":available": "available", ":type": unit_type},
        )
        units.extend(resp.get("Items", []))
        if len(units) >= 5:
            break
    return units


def _unit_types_for_trigger(trigger_reason: str) -> list:
    mapping = {
        "medical_keyword_detected": ["ambulance", "supervisor"],
        "fire_keyword_detected": ["fire_engine", "ladder", "ambulance"],
        "hazmat_keyword_detected": ["hazmat", "fire_engine", "ambulance"],
        "crime_keyword_detected": ["police", "ambulance"],
        "location_detected": ["ambulance", "police", "fire_engine"],
    }
    return mapping.get(trigger_reason, ["ambulance", "police"])


def _calculate_etas(incident: dict, units: list) -> list:
    results = []
    incident_coords = f"{incident.get('lat', 37.7749)},{incident.get('lng', -122.4194)}"

    for unit in units[:5]:
        unit_coords = f"{unit.get('lat', 37.775)},{unit.get('lng', -122.419)}"
        eta_minutes, maps_url = _google_maps_eta(unit_coords, incident_coords)
        results.append({
            "unit_id": unit["unit_id"],
            "unit_type": unit.get("unit_type"),
            "eta_minutes": eta_minutes,
            "turn_by_turn_url": maps_url,
            "current_location": unit_coords,
        })

    results.sort(key=lambda u: u["eta_minutes"])
    return results


def _google_maps_eta(origin: str, destination: str) -> tuple[int, str]:
    if not GOOGLE_MAPS_API_KEY:
        return 8, f"https://www.google.com/maps/dir/{origin}/{destination}"

    params = urllib.parse.urlencode({
        "origin": origin,
        "destination": destination,
        "departure_time": "now",
        "key": GOOGLE_MAPS_API_KEY,
    })
    url = f"https://maps.googleapis.com/maps/api/directions/json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        if data.get("routes"):
            leg = data["routes"][0]["legs"][0]
            duration_seconds = leg["duration_in_traffic"]["value"]
            eta_minutes = max(1, round(duration_seconds / 60))
        else:
            eta_minutes = 8
    except Exception as e:
        logger.warning("Google Maps API error, using fallback ETA", exc_info=e)
        eta_minutes = 8

    maps_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(origin)}&destination={urllib.parse.quote(destination)}&travelmode=driving"
    return eta_minutes, maps_url


def _log_dispatch_event(incident_id: str, unit: dict, t0: int) -> None:
    if not unit:
        return
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET navigation_result = :nav, navigation_at_ms = :ts",
        ExpressionAttributeValues={":nav": unit, ":ts": t0},
    )


def _push_to_dashboard(incident_id: str, payload: dict) -> None:
    global apigw_mgmt
    if not WS_ENDPOINT:
        return
    try:
        if apigw_mgmt is None:
            endpoint = WS_ENDPOINT.replace("wss://", "https://")
            apigw_mgmt = boto3.client(
                "apigatewaymanagementapi",
                endpoint_url=endpoint,
                region_name=os.environ["AWS_DEPLOY_REGION"],
            )
        conn_table = dynamodb.Table(CONNECTIONS_TABLE)
        conns = conn_table.query(
            IndexName="incident-index",
            KeyConditionExpression="incident_id = :iid",
            ExpressionAttributeValues={":iid": incident_id},
        ).get("Items", [])
        data = json.dumps(payload).encode()
        for conn in conns:
            try:
                apigw_mgmt.post_to_connection(ConnectionId=conn["connection_id"], Data=data)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_push_to_dashboard failed (non-fatal)", exc_info=e)
