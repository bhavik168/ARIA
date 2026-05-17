#!/usr/bin/env python3
"""
Create the vector index in the OpenSearch Serverless collection required by Bedrock KB.

Run this ONCE after `cdk deploy` and before running sync_knowledge_base.py.
Bedrock KB requires the index to exist with the correct field mappings before ingestion.

Usage:
    python scripts/setup_kb_index.py
    python scripts/setup_kb_index.py --collection-endpoint https://xxx.us-east-1.aoss.amazonaws.com
"""
import argparse
import boto3
import json
import sys
import urllib.request
import urllib.parse
import hmac
import hashlib
import datetime

REGION = "us-east-1"
INDEX_NAME = "aria-kb-index"
INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 512,
        }
    },
    "mappings": {
        "properties": {
            "bedrock-knowledge-base-default-vector": {
                "type": "knn_vector",
                "dimension": 1024,  # Titan Embed Text v2 dimension
                "method": {
                    "engine": "faiss",
                    "space_type": "l2",
                    "name": "hnsw",
                    "parameters": {},
                },
            },
            "AMAZON_BEDROCK_TEXT_CHUNK": {
                "type": "text",
                "index": True,
            },
            "AMAZON_BEDROCK_METADATA": {
                "type": "text",
                "index": False,
            },
        }
    },
}


def get_collection_endpoint(override: str = None) -> str:
    if override:
        return override.rstrip("/")
    # Try CloudFormation outputs
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
        if "AOSSCollectionEndpoint" in outputs:
            return outputs["AOSSCollectionEndpoint"].rstrip("/")
    except Exception:
        pass

    # Fall back: look up collection via AOSS client
    try:
        aoss = boto3.client("opensearchserverless", region_name=REGION)
        resp = aoss.list_collections(collectionFilters={"name": "aria-kb"})
        collections = resp.get("collectionSummaries", [])
        if collections:
            cid = collections[0]["id"]
            detail = aoss.batch_get_collection(ids=[cid])["collectionDetails"][0]
            return detail["collectionEndpoint"].rstrip("/")
    except Exception as e:
        print(f"AOSS lookup failed: {e}", file=sys.stderr)

    print("ERROR: Could not determine collection endpoint. Pass --collection-endpoint.", file=sys.stderr)
    sys.exit(1)


def sign_request(method: str, url: str, body: bytes, credentials) -> dict:
    """AWS SigV4 signing for OpenSearch Serverless (service: aoss)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    now = datetime.datetime.utcnow()
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_headers = f"host:{host}\nx-amz-date:{amzdate}\n"
    if credentials.token:
        canonical_headers += f"x-amz-security-token:{credentials.token}\n"
        signed_headers = "host;x-amz-date;x-amz-security-token"
    else:
        signed_headers = "host;x-amz-date"

    canonical_request = "\n".join([
        method, path, "",
        canonical_headers, signed_headers, payload_hash,
    ])

    credential_scope = f"{datestamp}/{REGION}/aoss/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amzdate, credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    def _sign(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(_sign(_sign(f"AWS4{credentials.secret_key}".encode(), datestamp), REGION), "aoss"),
        "aws4_request",
    )
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 Credential={credentials.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": auth,
        "x-amz-date": amzdate,
        "Content-Type": "application/json",
        "Host": host,
    }
    if credentials.token:
        headers["x-amz-security-token"] = credentials.token
    return headers


def create_index(endpoint: str) -> None:
    session = boto3.Session(region_name=REGION)
    credentials = session.get_credentials().get_frozen_credentials()

    url = f"{endpoint}/{INDEX_NAME}"
    body = json.dumps(INDEX_BODY).encode()
    headers = sign_request("PUT", url, body, credentials)

    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f"  ✓ Index '{INDEX_NAME}' created: {result}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        if "resource_already_exists_exception" in body_text.lower():
            print(f"  ✓ Index '{INDEX_NAME}' already exists — skipping.")
        else:
            print(f"  ✗ Failed to create index: {e.code} {body_text}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create AOSS vector index for ARIA KB")
    parser.add_argument("--collection-endpoint", help="AOSS collection endpoint URL")
    args = parser.parse_args()

    endpoint = get_collection_endpoint(args.collection_endpoint)
    print(f"Creating vector index '{INDEX_NAME}' on collection: {endpoint}")
    create_index(endpoint)
    print("\nDone. Next step: run scripts/sync_knowledge_base.py to ingest documents.")
