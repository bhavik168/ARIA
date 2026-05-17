#!/usr/bin/env python3
"""
Test Bedrock Knowledge Base retrieval with 5 queries covering each document category.

Run after sync_knowledge_base.py completes.

Usage:
    python scripts/test_kb_retrieval.py
"""
import boto3
import os
import sys

REGION = "us-east-1"

TEST_QUERIES = [
    {
        "category": "medical",
        "query": "cardiac arrest dispatch Seattle — which unit do I send and which hospital?",
        "expect_keywords": ["ALS", "Harborview", "cardiac"],
    },
    {
        "category": "hazmat",
        "query": "chlorine gas leak at Port of Seattle — evacuation distance and units to dispatch",
        "expect_keywords": ["chlorine", "evacuation", "hazmat"],
    },
    {
        "category": "hospital",
        "query": "major trauma from stabbing downtown Seattle — which hospital accepts?",
        "expect_keywords": ["Harborview", "trauma", "Level 1"],
    },
    {
        "category": "sops",
        "query": "structure fire in SoDo warehouse — what units does dispatcher send?",
        "expect_keywords": ["fire engine", "ladder", "ALS"],
    },
    {
        "category": "historical",
        "query": "multi-vehicle freeway crash on I-5 Seattle — dispatch pattern",
        "expect_keywords": ["MVC", "freeway", "ALS"],
    },
]


def get_kb_id() -> str:
    kb_id = os.environ.get("BEDROCK_KB_ID")
    if kb_id:
        return kb_id
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "BedrockKBId":
                return output["OutputValue"]
    except Exception:
        pass
    print("ERROR: Set BEDROCK_KB_ID env var or deploy the stack first.", file=sys.stderr)
    sys.exit(1)


def test_retrieval(kb_id: str) -> None:
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)
    passed = 0
    failed = 0

    for test in TEST_QUERIES:
        print(f"\n[{test['category'].upper()}] {test['query']}")
        try:
            resp = client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": test["query"]},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": 3}
                },
            )
            chunks = resp.get("retrievalResults", [])
            if not chunks:
                print("  ✗ No results returned")
                failed += 1
                continue

            top = chunks[0]
            content = top["content"]["text"]
            score = top.get("score", 0)
            source = top.get("location", {}).get("s3Location", {}).get("uri", "unknown")

            print(f"  Score: {score:.4f} | Source: {source.split('/')[-1]}")
            print(f"  Excerpt: {content[:200]}...")

            # Check expected keywords appear in top-3 combined content
            combined = " ".join(c["content"]["text"] for c in chunks).lower()
            missing = [kw for kw in test["expect_keywords"] if kw.lower() not in combined]
            if missing:
                print(f"  ⚠ Missing expected keywords: {missing}")
                failed += 1
            else:
                print(f"  ✓ All expected keywords found in top-3 results")
                passed += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(TEST_QUERIES)} queries")
    if failed > 0:
        print("Check that sync_knowledge_base.py ran successfully and ingestion completed.")
        sys.exit(1)


if __name__ == "__main__":
    kb_id = get_kb_id()
    print(f"Testing KB: {kb_id}\n")
    test_retrieval(kb_id)
