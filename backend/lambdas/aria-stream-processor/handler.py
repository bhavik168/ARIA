"""
aria-stream-processor — the real-time spine of ARIA.

Receives one stabilized word event at a time from aria-ingest.
Runs all domain watchers in-process (pure Python, zero network).
Fires specialist agents asynchronously on first watcher trigger.
Pushes every word to the dashboard WebSocket immediately.
"""
import json
import os
import re
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

# Module-level clients — connection reuse across warm invocations
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
apigw_mgmt = None  # Initialized lazily with the WS endpoint

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
COORDINATOR_FUNCTION = os.environ.get("COORDINATOR_FUNCTION", "aria-coordinator")
NAVIGATION_FUNCTION = os.environ.get("NAVIGATION_FUNCTION", "aria-navigation-tool")
MEDICAL_FUNCTION = os.environ.get("MEDICAL_FUNCTION", "aria-medical-tool")
HAZMAT_FUNCTION = os.environ.get("HAZMAT_FUNCTION", "aria-hazmat-tool")
VERIFIER_FUNCTION = os.environ.get("VERIFIER_FUNCTION", "aria-verifier")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")

# ─── Domain Watcher Patterns ─────────────────────────────────────────────────

LOCATION_PATTERNS = [
    re.compile(r'\b\d+\s+\w+\s+(Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln)\b', re.I),
    re.compile(r'\b(corner|intersection)\s+of\b', re.I),
    re.compile(r'\b\d{5}\b'),
    re.compile(r'\b(north|south|east|west)\b.*\b(street|avenue|road|drive)\b', re.I),
]

MEDICAL_KEYWORDS = frozenset({
    "not breathing", "chest pain", "unconscious", "heart attack",
    "bleeding", "overdose", "seizure", "choking", "collapsed",
    "unresponsive", "cardiac arrest", "stroke", "not responding",
    "passed out", "can't breathe", "difficulty breathing",
})

FIRE_KEYWORDS = frozenset({
    "fire", "smoke", "burning", "explosion", "flames", "gas leak",
    "on fire", "house fire", "building fire", "structure fire",
})

HAZMAT_KEYWORDS = frozenset({
    "chemical", "fumes", "spill", "toxic", "chlorine", "ammonia",
    "carbon monoxide", "hazmat", "leak", "acid", "biohazard",
})

CRIME_KEYWORDS = frozenset({
    "gun", "shot", "stabbed", "robbery", "weapon", "knife",
    "shooting", "armed", "gunshot", "assault", "attack",
})

SEVERITY_KEYWORDS = frozenset({
    "not moving", "multiple people", "mass casualty", "many victims",
    "several people", "crowd", "dozens",
})

# In-memory context buffer per Lambda execution context (warm invocations reuse this)
_context_buffer: dict[str, str] = {}
_watcher_fired: dict[str, set] = {}  # incident_id → set of fired watcher names
_word_count: dict[str, int] = {}
_word_count_at_fire: dict[str, dict[str, int]] = {}  # incident_id → {watcher: word_count when last fired}

# Watchers re-fire if this many new words arrive after the previous fire and conditions still match.
# This surfaces new information (e.g., a second injury, an escalating hazmat situation) to agents.
REFIRE_THRESHOLD = 40


def _should_refire(incident_id: str, watcher: str, current_count: int) -> bool:
    last = _word_count_at_fire.get(incident_id, {}).get(watcher)
    return last is not None and (current_count - last) >= REFIRE_THRESHOLD


def _record_fire(incident_id: str, watcher: str, current_count: int) -> None:
    _word_count_at_fire.setdefault(incident_id, {})[watcher] = current_count


@logger.inject_lambda_context
def lambda_handler(event, context):
    incident_id = event.get("incident_id", "")
    word = event.get("word", "")
    speaker = event.get("speaker_label", "caller")
    timestamp_ms = event.get("timestamp_ms", int(time.time() * 1000))

    if not incident_id or not word:
        return {"status": "skipped"}

    # Step 1 — Append to context buffer
    _context_buffer.setdefault(incident_id, "")
    _context_buffer[incident_id] += f" {word}"
    _word_count[incident_id] = _word_count.get(incident_id, 0) + 1
    context_so_far = _context_buffer[incident_id].strip()

    # Async checkpoint write every 10 words (non-blocking)
    if _word_count[incident_id] % 10 == 0:
        _checkpoint_context(incident_id, context_so_far, timestamp_ms)

    # Async semantic verifier every 10 words — runs AI classification in parallel
    # This catches phrases the hardcoded keyword watchers miss (e.g., "my leg is busted")
    if _word_count[incident_id] % 10 == 0:
        _fire_verifier(incident_id, context_so_far, timestamp_ms)

    # Step 2 — Push word to dashboard WebSocket
    _push_to_dashboard(incident_id, {
        "type": "transcript_word",
        "word": word,
        "speaker": speaker,
        "timestamp_ms": timestamp_ms,
        "transcript_so_far": context_so_far,
    })

    # Step 3 — Run domain watchers in-process
    # Watchers fire on first match; they re-fire after REFIRE_THRESHOLD new words if
    # conditions still hold, so agents receive updated context (e.g. new symptoms, new address).
    fired = _watcher_fired.setdefault(incident_id, set())
    context_lower = context_so_far.lower()
    current_count = _word_count[incident_id]

    if _check_location(context_lower):
        if "location" not in fired:
            fired.add("location")
            _record_fire(incident_id, "location", current_count)
            logger.info("LocationWatcher fired", extra={"incident_id": incident_id})
            metrics.add_metric("watcher_location_fired_ms", unit=MetricUnit.Milliseconds, value=timestamp_ms)
            _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "location_detected", timestamp_ms)
        elif _should_refire(incident_id, "location", current_count):
            _record_fire(incident_id, "location", current_count)
            logger.info("LocationWatcher re-fired (new context)", extra={"incident_id": incident_id})
            _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "location_updated", timestamp_ms)

    if _check_keywords(context_lower, MEDICAL_KEYWORDS):
        if "medical" not in fired:
            fired.add("medical")
            _record_fire(incident_id, "medical", current_count)
            logger.info("MedicalWatcher fired", extra={"incident_id": incident_id})
            metrics.add_metric("watcher_medical_fired_ms", unit=MetricUnit.Milliseconds, value=timestamp_ms)
            _fire_agent(MEDICAL_FUNCTION, incident_id, context_so_far, "medical_keyword_detected", timestamp_ms)
        elif _should_refire(incident_id, "medical", current_count):
            _record_fire(incident_id, "medical", current_count)
            logger.info("MedicalWatcher re-fired (new context)", extra={"incident_id": incident_id})
            _fire_agent(MEDICAL_FUNCTION, incident_id, context_so_far, "medical_updated", timestamp_ms)

    if _check_keywords(context_lower, FIRE_KEYWORDS):
        if "fire" not in fired:
            fired.add("fire")
            _record_fire(incident_id, "fire", current_count)
            logger.info("FireWatcher fired", extra={"incident_id": incident_id})
            _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "fire_keyword_detected", timestamp_ms)
        elif _should_refire(incident_id, "fire", current_count):
            _record_fire(incident_id, "fire", current_count)
            logger.info("FireWatcher re-fired (new context)", extra={"incident_id": incident_id})
            _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "fire_updated", timestamp_ms)

    if _check_keywords(context_lower, HAZMAT_KEYWORDS):
        if "hazmat" not in fired:
            fired.add("hazmat")
            _record_fire(incident_id, "hazmat", current_count)
            logger.info("HazmatWatcher fired", extra={"incident_id": incident_id})
            _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "hazmat_keyword_detected", timestamp_ms)
        elif _should_refire(incident_id, "hazmat", current_count):
            _record_fire(incident_id, "hazmat", current_count)
            logger.info("HazmatWatcher re-fired (new context)", extra={"incident_id": incident_id})
            _fire_agent(HAZMAT_FUNCTION, incident_id, context_so_far, "hazmat_updated", timestamp_ms)

    if _check_keywords(context_lower, CRIME_KEYWORDS):
        if "crime" not in fired:
            fired.add("crime")
            _record_fire(incident_id, "crime", current_count)
            logger.info("CrimeWatcher fired", extra={"incident_id": incident_id})
            _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "crime_keyword_detected", timestamp_ms)
        elif _should_refire(incident_id, "crime", current_count):
            _record_fire(incident_id, "crime", current_count)
            logger.info("CrimeWatcher re-fired (new context)", extra={"incident_id": incident_id})
            _fire_agent(NAVIGATION_FUNCTION, incident_id, context_so_far, "crime_updated", timestamp_ms)

    return {"status": "ok", "word": word, "watchers_fired": list(fired)}


def _check_location(text: str) -> bool:
    return any(p.search(text) for p in LOCATION_PATTERNS)


def _check_keywords(text: str, keyword_set: frozenset) -> bool:
    return any(kw in text for kw in keyword_set)


def _fire_agent(function_name: str, incident_id: str, context: str, trigger_reason: str, ts: int) -> None:
    """Async invoke — stream processor returns immediately, agent runs in parallel."""
    payload = {
        "incident_id": incident_id,
        "context_so_far": context,
        "trigger_reason": trigger_reason,
        "triggered_at_ms": ts,
        "source": "stream_processor",
    }
    try:
        lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="Event",  # async — fire and forget
            Payload=json.dumps(payload).encode(),
        )
    except Exception as e:
        logger.error(f"Failed to fire agent {function_name}", exc_info=e)


def _fire_verifier(incident_id: str, context: str, ts: int) -> None:
    """Async invoke semantic verifier — zero latency impact on word stream."""
    if not VERIFIER_FUNCTION:
        return
    payload = {
        "incident_id": incident_id,
        "context_so_far": context,
        "timestamp_ms": ts,
        "source": "stream_processor",
    }
    try:
        lambda_client.invoke(
            FunctionName=VERIFIER_FUNCTION,
            InvocationType="Event",  # async — verifier runs in background
            Payload=json.dumps(payload).encode(),
        )
    except Exception as e:
        logger.error("Failed to fire verifier", exc_info=e)


def _checkpoint_context(incident_id: str, context: str, ts: int) -> None:
    """Async DynamoDB write to persist context in case Lambda recycles."""
    payload = {
        "incident_id": incident_id,
        "context": context,
        "checkpoint_at_ms": ts,
        "action": "checkpoint",
    }
    try:
        lambda_client.invoke(
            FunctionName=os.environ.get("STREAM_PROCESSOR_FUNCTION", "aria-stream-processor"),
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )
    except Exception:
        pass  # Checkpoint failure is non-fatal — context is still in memory


def _push_to_dashboard(incident_id: str, payload: dict) -> None:
    global apigw_mgmt
    if not WS_ENDPOINT:
        return
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
        except apigw_mgmt.exceptions.GoneException:
            conn_table.delete_item(Key={"connection_id": conn["connection_id"]})
        except Exception as e:
            logger.warning("Failed to push to connection", exc_info=e)
