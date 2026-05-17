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
import threading
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
STREAM_PROCESSOR_FUNCTION = os.environ["STREAM_PROCESSOR_FUNCTION"]
ARIA_BUCKET = os.environ.get("ARIA_BUCKET", "")


@logger.inject_lambda_context
def lambda_handler(event, context):
    http_method = event.get("httpMethod", "POST")
    path = event.get("path", "")

    if http_method == "GET":
        return _get_status(event)

    if http_method == "POST" and path.endswith("/start"):
        return _start_session(event, context)

    if http_method == "POST" and path.endswith("/presign"):
        return _presign_upload(event)

    return _respond(400, {"error": "Unknown route"})


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
        # Kick off simulation in background thread — Lambda stays warm during replay
        thread = threading.Thread(
            target=_replay_simulation,
            args=(incident_id, simulation_transcript, t0_ms),
            daemon=True,
        )
        thread.start()
        # Give thread enough time to fire at least first word before Lambda might recycle
        # For longer replays, use a dedicated async Lambda
        thread.join(timeout=min(context.get_remaining_time_in_millis() / 1000 - 2, 30))

        logger.info("Simulation started", extra={"incident_id": incident_id})
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

def _replay_simulation(incident_id: str, transcript: list, t0_ms: int) -> None:
    """
    Replay a scripted transcript through the stream processor.
    Each entry: { word, speaker (optional), delay_ms (optional) }
    """
    first_word_fired = False
    for entry in transcript:
        word = entry.get("word", "").strip()
        if not word:
            continue

        delay_ms = entry.get("delay_ms", 300)
        time.sleep(delay_ms / 1000)

        ts = int(time.time() * 1000)
        payload = {
            "incident_id": incident_id,
            "word": word,
            "speaker_label": entry.get("speaker", "caller"),
            "timestamp_ms": ts,
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
        MediaFormat="wav",  # assumes wav — adjust for mp3/mp4 if needed
        LanguageCode="en-US",
        Settings={
            "ShowSpeakerLabels": True,
            "MaxSpeakerLabels": 2,
        },
        OutputBucketName=ARIA_BUCKET,
        OutputKey=f"transcripts/{incident_id}/{job_name}.json",
        Tags=[{"Key": "incident_id", "Value": incident_id}],
    )

    # Store job name on incident for polling
    table = dynamodb.Table(INCIDENTS_TABLE)
    table.update_item(
        Key={"incident_id": incident_id, "timestamp": "latest"},
        UpdateExpression="SET transcribe_job = :j, t0_ms = :t",
        ExpressionAttributeValues={":j": job_name, ":t": t0_ms},
    )


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

    transcript_uri = resp["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
    words = _fetch_transcript_words(transcript_uri)

    first = True
    for word_item in words:
        word = word_item.get("alternatives", [{}])[0].get("content", "")
        word_type = word_item.get("type", "")
        if word_type == "punctuation" or not word:
            continue

        start_time = float(word_item.get("start_time", 0))
        speaker = word_item.get("speaker_label", "spk_0")
        ts_ms = t0_ms + int(start_time * 1000)

        payload = {
            "incident_id": incident_id,
            "word": word,
            "speaker_label": "caller" if speaker == "spk_0" else "dispatcher",
            "timestamp_ms": ts_ms,
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
    return {"status": "ok", "words_replayed": len(words)}


def _fetch_transcript_words(transcript_uri: str) -> list:
    """Download Transcribe output JSON from S3 and extract word items."""
    # transcript_uri is an S3 URL; parse bucket and key
    parsed = transcript_uri.replace("https://s3.amazonaws.com/", "")
    parts = parsed.split("/", 1)
    if len(parts) < 2:
        return []
    bucket, key = parts[0], parts[1]
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
