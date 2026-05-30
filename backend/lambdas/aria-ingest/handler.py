"""
aria-ingest — session entry point.

Two modes:
  1. simulation_mode: caller passes { simulation_transcript: [{word, speaker, delay_ms}] }
     — replays words with timing, fires stream-processor per word.
     Use this for demo/testing without real audio hardware.

  2. transcribe_mode: caller passes { audio_file_key: "s3://aria-bucket/..." }
     — starts Amazon Transcribe batch job on the S3 file, polls for completion,
     then replays results through stream-processor word by word.

Both modes return { incident_id, websocket_url } immediately and process async.
"""
import json
import os
import uuid
import time
import boto3
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
metrics = Metrics()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_DEPLOY_REGION"])
transcribe_client = boto3.client("transcribe", region_name=os.environ["AWS_DEPLOY_REGION"])
s3_client = boto3.client("s3", region_name=os.environ["AWS_DEPLOY_REGION"])

INCIDENTS_TABLE = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
STREAM_PROCESSOR_FUNCTION = os.environ["STREAM_PROCESSOR_FUNCTION"]
COORDINATOR_FUNCTION = os.environ.get("COORDINATOR_FUNCTION", "aria-coordinator")
NAVIGATION_FUNCTION = os.environ.get("NAVIGATION_FUNCTION", "aria-navigation-tool")
MEDICAL_FUNCTION = os.environ.get("MEDICAL_FUNCTION", "aria-medical-tool")
HAZMAT_FUNCTION = os.environ.get("HAZMAT_FUNCTION", "aria-hazmat-tool")
VERIFIER_FUNCTION = os.environ.get("VERIFIER_FUNCTION", "aria-verifier")
ARIA_BUCKET = os.environ.get("ARIA_BUCKET", "")


@logger.inject_lambda_context
def lambda_handler(event, context):
    # Self-invoked simulation replay path — fires words after frontend has connected
    if event.get("_replay_simulation"):
        _wait_for_ws_connection(event["incident_id"], max_wait_ms=2000)
        _replay_simulation(
            event["incident_id"],
            event["simulation_transcript"],
            event["t0_ms"],
        )
        return {"status": "ok"}

    # Self-invoked polling path (not an API Gateway request)
    if event.get("_poll_transcribe"):
        result = poll_and_replay_transcript(
            event["incident_id"],
            event["job_name"],
            event["t0_ms"],
        )
        logger.info("poll_and_replay done", extra=result)
        return result

    http_method = event.get("httpMethod", "POST")
    path = event.get("path", "")

    if http_method == "GET" and path.endswith("/warmup"):
        return _warmup()

    if http_method == "GET":
        return _get_status(event)

    if http_method == "POST" and path.endswith("/start"):
        return _start_session(event, context)

    if http_method == "POST" and path.endswith("/presign"):
        return _presign_upload(event)

    return _respond(400, {"error": "Unknown route"})


# ─── Warmup ──────────────────────────────────────────────────────────────────

def _warmup() -> dict:
    """Async-ping all downstream Lambdas so their containers are warm before a real call."""
    fns = [
        STREAM_PROCESSOR_FUNCTION,
        COORDINATOR_FUNCTION,
        NAVIGATION_FUNCTION,
        MEDICAL_FUNCTION,
        HAZMAT_FUNCTION,
        VERIFIER_FUNCTION,
    ]
    for fn in fns:
        try:
            lambda_client.invoke(
                FunctionName=fn,
                InvocationType="Event",
                Payload=b'{"action":"ping"}',
            )
        except Exception as e:
            logger.warning(f"Warmup ping failed for {fn}", exc_info=e)
    logger.info("Warmup pings dispatched", extra={"functions": fns})
    return _respond(200, {"status": "warming"})


# ─── Presign Upload ───────────────────────────────────────────────────────────

def _presign_upload(event: dict) -> dict:
    body = json.loads(event.get("body") or "{}")
    filename = body.get("filename", "audio.wav")
    content_type = body.get("content_type", "audio/wav")
    audio_key = f"uploads/{uuid.uuid4()}/{filename}"

    upload_url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": ARIA_BUCKET, "Key": audio_key, "ContentType": content_type},
        ExpiresIn=300,
    )
    return _respond(200, {"upload_url": upload_url, "audio_key": audio_key})


# ─── Session Start ────────────────────────────────────────────────────────────

def _start_session(event: dict, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    incident_id = str(uuid.uuid4())
    t0_ms = int(time.time() * 1000)

    # Write incident record immediately
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.put_item(Item={
        "incident_id": incident_id,
        "timestamp": "latest",
        "status": "ingesting",
        "t0_ms": t0_ms,
        "ttl": int(time.time()) + (30 * 24 * 3600),
    })

    ws_url = os.environ.get("WS_ENDPOINT", "").replace("https://", "wss://")

    # Determine mode
    simulation_transcript = body.get("simulation_transcript")
    audio_file_key = body.get("audio_file_key", "")

    if simulation_transcript:
        # Async self-invoke so this response returns to the frontend BEFORE words start
        # flowing. The frontend opens the WebSocket, ws-connect registers the connection,
        # and the replay handler waits (via _wait_for_ws_connection) until that
        # registration is visible before firing the first word.
        lambda_client.invoke(
            FunctionName=os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "aria-ingest"),
            InvocationType="Event",
            Payload=json.dumps({
                "_replay_simulation": True,
                "incident_id": incident_id,
                "simulation_transcript": simulation_transcript,
                "t0_ms": t0_ms,
            }).encode(),
        )
        logger.info("Simulation queued async", extra={"incident_id": incident_id})
        return _respond(200, {
            "incident_id": incident_id,
            "websocket_url": ws_url,
            "mode": "simulation",
            "status": "ingesting",
        })

    elif audio_file_key:
        # Start Transcribe batch job asynchronously
        job_name = f"aria-{incident_id[:8]}-{int(time.time())}"
        _start_transcribe_job(incident_id, audio_file_key, job_name, t0_ms)
        logger.info("Transcribe job started", extra={"incident_id": incident_id, "job": job_name})

        # Fire coordinator immediately so agents bootstrap and the frontend shows activity
        # while Transcribe is still running. Coordinator re-fires with real context as words arrive.
        try:
            lambda_client.invoke(
                FunctionName=COORDINATOR_FUNCTION,
                InvocationType="Event",
                Payload=json.dumps({
                    "incident_id": incident_id,
                    "context_so_far": "",
                    "trigger_reason": "session_start",
                }).encode(),
            )
        except Exception as e:
            logger.warning("Failed to fire coordinator at session start", exc_info=e)

        return _respond(200, {
            "incident_id": incident_id,
            "websocket_url": ws_url,
            "mode": "transcribe",
            "transcribe_job": job_name,
            "status": "ingesting",
        })

    else:
        return _respond(400, {"error": "Provide simulation_transcript or audio_file_key"})


# ─── Simulation Mode ──────────────────────────────────────────────────────────

def _wait_for_ws_connection(incident_id: str, max_wait_ms: int = 2000) -> bool:
    """Poll connections table until the frontend WebSocket is registered or timeout."""
    conn_table = dynamodb.Table(CONNECTIONS_TABLE)
    deadline = time.time() + max_wait_ms / 1000
    while time.time() < deadline:
        try:
            items = conn_table.query(
                IndexName="incident-index",
                KeyConditionExpression="incident_id = :iid",
                ExpressionAttributeValues={":iid": incident_id},
            ).get("Items", [])
            if items:
                logger.info("WS connection detected, starting replay", extra={"incident_id": incident_id})
                return True
        except Exception as e:
            # A transient query error shouldn't abort the wait — keep retrying until
            # the deadline so we don't fire the first words before the browser registers.
            logger.warning("WS connection check failed (will retry)", exc_info=e)
        time.sleep(0.15)
    logger.warning("WS connection not detected within timeout, starting replay anyway", extra={"incident_id": incident_id})
    return False


def _replay_simulation(incident_id: str, transcript: list, t0_ms: int) -> None:
    """
    Replay a scripted transcript through the stream processor.
    Each entry: { word, speaker (optional), delay_ms (optional) }
    """
    first_word_fired = False
    accumulated_words: list[str] = []
    for entry in transcript:
        word = entry.get("word", "").strip()
        if not word:
            continue

        delay_ms = entry.get("delay_ms", 300)
        time.sleep(delay_ms / 1000)

        accumulated_words.append(word)
        ts = int(time.time() * 1000)
        payload = {
            "incident_id": incident_id,
            "word": word,
            "speaker_label": entry.get("speaker", "caller"),
            "timestamp_ms": ts,
            # Authoritative cumulative transcript so the stream processor never
            # depends on fragile in-memory state across fan-out containers.
            "context_so_far": " ".join(accumulated_words),
            "word_index": len(accumulated_words),
        }

        try:
            lambda_client.invoke(
                FunctionName=STREAM_PROCESSOR_FUNCTION,
                InvocationType="Event",
                Payload=json.dumps(payload).encode(),
            )
        except Exception as e:
            logger.error("Failed to fire stream-processor", exc_info=e)

        if not first_word_fired:
            first_word_fired = True
            elapsed = ts - t0_ms
            metrics.add_metric("transcribe_first_word_ms", unit=MetricUnit.Milliseconds, value=elapsed)

    # Mark incident as transcription complete
    _update_status(incident_id, "transcript_complete")

    # Invoke coordinator to synthesize final recommendation card
    full_context = " ".join(e.get("word", "") for e in transcript if e.get("word"))
    try:
        lambda_client.invoke(
            FunctionName=COORDINATOR_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({
                "incident_id": incident_id,
                "context_so_far": full_context,
                "trigger_reason": "transcript_complete",
            }).encode(),
        )
    except Exception as e:
        logger.error("Failed to invoke coordinator", exc_info=e)


# ─── Transcribe Batch Mode ────────────────────────────────────────────────────

def _start_transcribe_job(incident_id: str, audio_key: str, job_name: str, t0_ms: int) -> None:
    """Start Amazon Transcribe batch job. Results processed by _poll_and_replay (called externally or via EventBridge)."""
    # Resolve S3 URI
    if audio_key.startswith("s3://"):
        media_uri = audio_key
    else:
        media_uri = f"s3://{ARIA_BUCKET}/{audio_key}"

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        MediaFormat=_media_format_for_key(audio_key),
        LanguageCode="en-US",
        Settings={
            "ShowSpeakerLabels": True,
            "MaxSpeakerLabels": 2,
        },
        OutputBucketName=ARIA_BUCKET,
        OutputKey=f"transcripts/{incident_id}/{job_name}.json",
    )

    # Store job name on incident for polling
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET transcribe_job = :j, t0_ms = :t",
        ExpressionAttributeValues={":j": job_name, ":t": t0_ms},
    )

    # Self-invoke asynchronously to poll Transcribe and replay words
    lambda_client.invoke(
        FunctionName=os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "aria-ingest"),
        InvocationType="Event",
        Payload=json.dumps({
            "_poll_transcribe": True,
            "incident_id": incident_id,
            "job_name": job_name,
            "t0_ms": t0_ms,
        }).encode(),
    )


def _media_format_for_key(audio_key: str) -> str:
    """Pick a valid Amazon Transcribe MediaFormat from the file extension."""
    ext = audio_key.rsplit(".", 1)[-1].lower() if "." in audio_key else "wav"
    # Transcribe accepts: mp3, mp4, wav, flac, ogg, amr, webm
    if ext in ("mp3", "mp4", "wav", "flac", "ogg", "amr", "webm"):
        return ext
    if ext in ("m4a", "mov"):
        return "mp4"
    return "wav"


def poll_and_replay_transcript(incident_id: str, job_name: str, t0_ms: int) -> dict:
    """
    Poll Transcribe until complete, then replay words through stream-processor.
    Called from a separate invocation (EventBridge rule or manual trigger for demo).
    """
    deadline = time.time() + 600  # 10-minute max wait
    while time.time() < deadline:
        resp = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        status = resp["TranscriptionJob"]["TranscriptionJobStatus"]
        if status == "COMPLETED":
            break
        elif status == "FAILED":
            reason = resp["TranscriptionJob"].get("FailureReason", "unknown")
            logger.error(f"Transcribe job failed: {reason}")
            return {"status": "failed", "reason": reason}
        time.sleep(5)

    # Read directly from the known S3 key — avoids parsing the URI format
    transcript_key = f"transcripts/{incident_id}/{job_name}.json"
    words, speaker_by_start = _fetch_transcript_words_s3(ARIA_BUCKET, transcript_key)

    first = True
    prev_start = 0.0
    accumulated_words: list[str] = []
    for word_item in words:
        word = word_item.get("alternatives", [{}])[0].get("content", "")
        word_type = word_item.get("type", "")
        if word_type == "punctuation" or not word:
            continue

        start_time = float(word_item.get("start_time", 0))
        # Transcribe stores speaker labels in results.speaker_labels.segments, keyed
        # by item start_time — not on the word items themselves.
        speaker = speaker_by_start.get(word_item.get("start_time"), "spk_0")
        ts_ms = t0_ms + int(start_time * 1000)

        # Pace replay to the real word timing (capped) so the dashboard streams
        # word-by-word in order instead of a single burst of invocations.
        gap = max(0.0, start_time - prev_start)
        prev_start = start_time
        time.sleep(min(gap, 1.0))

        accumulated_words.append(word)
        payload = {
            "incident_id": incident_id,
            "word": word,
            "speaker_label": "caller" if speaker == "spk_0" else "dispatcher",
            "timestamp_ms": ts_ms,
            "context_so_far": " ".join(accumulated_words),
            "word_index": len(accumulated_words),
        }
        lambda_client.invoke(
            FunctionName=STREAM_PROCESSOR_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps(payload).encode(),
        )

        if first:
            first = False
            metrics.add_metric("transcribe_first_word_ms", unit=MetricUnit.Milliseconds,
                               value=ts_ms - t0_ms)

    _update_status(incident_id, "transcript_complete")

    # Invoke coordinator to synthesize final recommendation card (mirrors simulation mode)
    full_context = " ".join(
        w.get("alternatives", [{}])[0].get("content", "")
        for w in words
        if w.get("type") != "punctuation" and w.get("alternatives", [{}])[0].get("content", "")
    )
    try:
        lambda_client.invoke(
            FunctionName=COORDINATOR_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({
                "incident_id": incident_id,
                "context_so_far": full_context,
                "trigger_reason": "transcript_complete",
            }).encode(),
        )
    except Exception as e:
        logger.error("Failed to invoke coordinator after transcribe", exc_info=e)

    return {"status": "ok", "words_replayed": len(words)}


def _fetch_transcript_words_s3(bucket: str, key: str) -> tuple[list, dict]:
    """Fetch Transcribe output from S3.

    Returns (items, speaker_by_start) where speaker_by_start maps an item's
    start_time string to its speaker_label (spk_0, spk_1, ...).
    """
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data = json.loads(resp["Body"].read())
    results = data.get("results", {})
    items = results.get("items", [])

    speaker_by_start: dict[str, str] = {}
    for seg in results.get("speaker_labels", {}).get("segments", []):
        for seg_item in seg.get("items", []):
            start = seg_item.get("start_time")
            label = seg_item.get("speaker_label")
            if start and label:
                speaker_by_start[start] = label
    return items, speaker_by_start


def _fetch_transcript_words(transcript_uri: str) -> list:
    """Download Transcribe output JSON from S3 and extract word items."""
    from urllib.parse import urlparse
    p = urlparse(transcript_uri)
    # handles both path-style (s3.amazonaws.com/bucket/key)
    # and virtual-hosted-style (bucket.s3.region.amazonaws.com/key)
    if p.netloc.endswith("amazonaws.com"):
        host_parts = p.netloc.split(".")
        if host_parts[0] == "s3" or host_parts[0].startswith("s3-"):
            # path-style: host = s3[.region].amazonaws.com, path = /bucket/key
            path_parts = p.path.lstrip("/").split("/", 1)
            bucket, key = path_parts[0], path_parts[1]
        else:
            # virtual-hosted-style: host = bucket.s3[.region].amazonaws.com
            bucket = host_parts[0]
            key = p.path.lstrip("/")
    else:
        return []
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    data = json.loads(resp["Body"].read())
    return data.get("results", {}).get("items", [])


# ─── Status Route ─────────────────────────────────────────────────────────────

def _get_status(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id", "")
    if not incident_id:
        return _respond(400, {"error": "incident_id required"})

    table = dynamodb.Table(INCIDENTS_TABLE)
    result = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = result.get("Items", [])
    if not items:
        return _respond(404, {"error": "Incident not found"})
    return _respond(200, items[0])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _update_status(incident_id: str, status: str) -> None:
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status},
    )


def _respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
