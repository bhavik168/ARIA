#!/usr/bin/env python3
"""
Trigger Bedrock Knowledge Base ingestion job to sync S3 documents into the vector store.

Run after upload_kb_docs.py whenever documents change.

Usage:
    python scripts/sync_knowledge_base.py
    python scripts/sync_knowledge_base.py --wait   # poll until sync completes
"""
import argparse
import boto3
import os
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-west-2")


def get_kb_config() -> tuple:
    kb_id = os.environ.get("BEDROCK_KB_ID")
    ds_id = os.environ.get("BEDROCK_DS_ID")
    if kb_id and ds_id:
        return kb_id, ds_id

    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
        kb_id = kb_id or outputs.get("BedrockKBId")
        ds_id = ds_id or outputs.get("BedrockDataSourceId")
    except Exception as e:
        print(f"WARNING: Could not read CloudFormation outputs: {e}", file=sys.stderr)

    if not kb_id or not ds_id:
        print("ERROR: Set BEDROCK_KB_ID and BEDROCK_DS_ID env vars or deploy the stack first.",
              file=sys.stderr)
        sys.exit(1)
    return kb_id, ds_id


def start_ingestion(kb_id: str, ds_id: str) -> str:
    client = boto3.client("bedrock-agent", region_name=REGION)
    resp = client.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job = resp["ingestionJob"]
    print(f"  ✓ Ingestion job started: {job['ingestionJobId']} (status: {job['status']})")
    return job["ingestionJobId"]


def wait_for_completion(kb_id: str, ds_id: str, job_id: str, timeout: int = 300) -> None:
    client = boto3.client("bedrock-agent", region_name=REGION)
    start = time.time()
    print("  Waiting for ingestion job to complete...")
    while time.time() - start < timeout:
        resp = client.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            ingestionJobId=job_id,
        )
        job = resp["ingestionJob"]
        status = job["status"]
        stats = job.get("statistics", {})
        print(f"  Status: {status} | "
              f"Scanned: {stats.get('numberOfDocumentsScanned', 0)} | "
              f"Indexed: {stats.get('numberOfNewDocumentsIndexed', 0)} | "
              f"Failed: {stats.get('numberOfDocumentsFailed', 0)}")

        if status == "COMPLETE":
            print(f"\n  ✓ Ingestion complete — {stats.get('numberOfNewDocumentsIndexed', 0)} chunks indexed.")
            return
        elif status == "FAILED":
            failures = job.get("failureReasons", [])
            print(f"\n  ✗ Ingestion failed: {failures}", file=sys.stderr)
            sys.exit(1)

        time.sleep(10)

    print(f"\n  ✗ Ingestion timed out after {timeout}s.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger Bedrock KB ingestion job")
    parser.add_argument("--wait", action="store_true", help="Poll until sync completes")
    args = parser.parse_args()

    kb_id, ds_id = get_kb_config()
    print(f"Starting ingestion: KB={kb_id}, DataSource={ds_id}")
    job_id = start_ingestion(kb_id, ds_id)

    if args.wait:
        wait_for_completion(kb_id, ds_id, job_id)
    else:
        print("Run with --wait to poll for completion, or check AWS console.")
