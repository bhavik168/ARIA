#!/usr/bin/env python3
"""
Upload knowledge-base/ documents to S3 for Bedrock Knowledge Base ingestion.

Usage:
    python scripts/upload_kb_docs.py
    python scripts/upload_kb_docs.py --bucket aria-123456789012  # override bucket name
"""
import argparse
import boto3
import os
import sys
from pathlib import Path

REGION = os.environ.get("AWS_REGION", "us-west-2")
KB_LOCAL_DIR = Path(__file__).parent.parent / "knowledge-base"
S3_PREFIX = "knowledge-base"


def get_bucket_name(override: str = None) -> str:
    if override:
        return override
    # Read from CDK outputs or environment
    bucket = os.environ.get("ARIA_BUCKET")
    if bucket:
        return bucket
    # Try to read from CDK outputs
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "AriaBucketName":
                return output["OutputValue"]
    except Exception:
        pass
    print("ERROR: Could not determine bucket name. Set ARIA_BUCKET env var or pass --bucket.", file=sys.stderr)
    sys.exit(1)


def upload_docs(bucket_name: str) -> None:
    s3 = boto3.client("s3", region_name=REGION)
    uploaded = 0
    skipped = 0

    for doc_path in KB_LOCAL_DIR.rglob("*.md"):
        # Preserve folder structure: knowledge-base/medical/dispatch_guide.md
        relative = doc_path.relative_to(KB_LOCAL_DIR.parent)
        s3_key = str(relative).replace("\\", "/")  # Windows path fix

        s3.upload_file(
            Filename=str(doc_path),
            Bucket=bucket_name,
            Key=s3_key,
            ExtraArgs={"ContentType": "text/markdown"},
        )
        print(f"  ✓ Uploaded: {s3_key}")
        uploaded += 1

    print(f"\n{uploaded} documents uploaded to s3://{bucket_name}/{S3_PREFIX}/")
    print("Next step: run scripts/sync_knowledge_base.py to trigger Bedrock ingestion job.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload ARIA KB docs to S3")
    parser.add_argument("--bucket", help="S3 bucket name (overrides ARIA_BUCKET env var)")
    args = parser.parse_args()

    bucket = get_bucket_name(args.bucket)
    print(f"Uploading knowledge-base/ documents to s3://{bucket}/")
    upload_docs(bucket)
