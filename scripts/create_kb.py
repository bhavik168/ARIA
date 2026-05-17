#!/usr/bin/env python3
"""
Create the ARIA Bedrock Knowledge Base and all supporting resources from scratch.

Run once. Creates: AOSS policies, collection, vector index, IAM role,
Bedrock Knowledge Base, and S3 data source.

After this completes:
    AWS_PROFILE=aria python scripts/upload_kb_docs.py
    AWS_PROFILE=aria python scripts/sync_knowledge_base.py --wait

Usage:
    AWS_PROFILE=aria python scripts/create_kb.py
"""
import boto3
import json
import sys
import time
import urllib.error
import urllib.request
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = os.environ.get("AWS_REGION", "us-west-2")
COLLECTION_NAME = "aria-kb"
KB_ROLE_NAME = "aria-bedrock-kb-role"
INDEX_NAME = "aria-kb-index"
EMBED_MODEL_ARN = f"arn:aws:bedrock:{REGION}::foundation-model/amazon.titan-embed-text-v2:0"

aoss_client = boto3.client("opensearchserverless", region_name=REGION)
iam_client = boto3.client("iam", region_name=REGION)
bedrock_agent = boto3.client("bedrock-agent", region_name=REGION)

# Auto-detect account ID and derive defaults
ACCOUNT = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
BUCKET_NAME = os.environ.get("ARIA_BUCKET", f"aria-{ACCOUNT}")
IAM_USERNAME = os.environ.get("AWS_IAM_USERNAME", "aria")


def step(msg):
    print(f"\n[+] {msg}")


def signed_urllib_request(method, url, body):
    """Build a urllib Request signed with botocore SigV4Auth (service=aoss)."""
    session = boto3.Session(region_name=REGION)
    aws_request = AWSRequest(method=method, url=url, data=body,
                             headers={"Content-Type": "application/json"})
    SigV4Auth(session.get_credentials(), "aoss", REGION).add_auth(aws_request)
    return urllib.request.Request(url, data=body, headers=dict(aws_request.headers), method=method)


# ── 1. AOSS encryption policy ─────────────────────────────────────────────────
step("Creating AOSS encryption policy")
try:
    aoss_client.create_security_policy(
        name="aria-kb-enc", type="encryption",
        policy=json.dumps({
            "Rules": [{"Resource": [f"collection/{COLLECTION_NAME}"], "ResourceType": "collection"}],
            "AWSOwnedKey": True,
        }),
    )
    print("    ✓ Created")
except aoss_client.exceptions.ConflictException:
    print("    → already exists, skipping.")

# ── 2. AOSS network policy ────────────────────────────────────────────────────
step("Creating AOSS network policy")
try:
    aoss_client.create_security_policy(
        name="aria-kb-net", type="network",
        policy=json.dumps([{
            "Rules": [
                {"Resource": [f"collection/{COLLECTION_NAME}"], "ResourceType": "collection"},
                {"Resource": [f"collection/{COLLECTION_NAME}"], "ResourceType": "dashboard"},
            ],
            "AllowFromPublic": True,
        }]),
    )
    print("    ✓ Created")
except aoss_client.exceptions.ConflictException:
    print("    → already exists, skipping.")

# ── 3. AOSS collection ────────────────────────────────────────────────────────
step("Creating AOSS collection (VECTORSEARCH)")
summaries = aoss_client.list_collections(collectionFilters={"name": COLLECTION_NAME}).get("collectionSummaries", [])
if summaries:
    collection_id = summaries[0]["id"]
    collection_arn = summaries[0]["arn"]
    print(f"    → already exists: {collection_id}")
else:
    resp = aoss_client.create_collection(name=COLLECTION_NAME, type="VECTORSEARCH")
    collection_id = resp["createCollectionDetail"]["id"]
    collection_arn = resp["createCollectionDetail"]["arn"]
    print(f"    ✓ Created: {collection_id}")

# ── 4. Wait for collection ACTIVE ────────────────────────────────────────────
step("Waiting for collection to become ACTIVE (up to 10 min)")
for i in range(60):
    detail = aoss_client.batch_get_collection(ids=[collection_id])["collectionDetails"][0]
    status = detail["status"]
    print(f"    Status: {status} ({i * 10}s elapsed)")
    if status == "ACTIVE":
        collection_endpoint = detail["collectionEndpoint"]
        print(f"    ✓ Active: {collection_endpoint}")
        break
    if status == "FAILED":
        print("    ✗ Collection failed.", file=sys.stderr)
        sys.exit(1)
    time.sleep(10)
else:
    print("    ✗ Timed out.", file=sys.stderr)
    sys.exit(1)

# ── 5. IAM role for Bedrock KB ────────────────────────────────────────────────
step("Creating IAM role for Bedrock KB")
trust = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "bedrock.amazonaws.com"},
        "Action": "sts:AssumeRole",
        "Condition": {
            "StringEquals": {"aws:SourceAccount": ACCOUNT},
            "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{REGION}:{ACCOUNT}:knowledge-base/*"},
        },
    }],
}
try:
    kb_role_arn = iam_client.create_role(
        RoleName=KB_ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust),
        Description="Bedrock Knowledge Base service role for ARIA",
    )["Role"]["Arn"]
    print(f"    ✓ Created: {kb_role_arn}")
except iam_client.exceptions.EntityAlreadyExistsException:
    kb_role_arn = iam_client.get_role(RoleName=KB_ROLE_NAME)["Role"]["Arn"]
    print(f"    → already exists: {kb_role_arn}")

iam_client.put_role_policy(
    RoleName=KB_ROLE_NAME,
    PolicyName="aria-kb-inline",
    PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{BUCKET_NAME}", f"arn:aws:s3:::{BUCKET_NAME}/knowledge-base/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["aoss:APIAccessAll"],
                "Resource": f"arn:aws:aoss:{REGION}:{ACCOUNT}:collection/*",
            },
            {
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel"],
                "Resource": EMBED_MODEL_ARN,
            },
        ],
    }),
)
print("    ✓ Inline policy attached")

# ── 6. AOSS data access policy ────────────────────────────────────────────────
step("Creating AOSS data access policy")
data_policy = [{
    "Rules": [
        {
            "Resource": [f"collection/{COLLECTION_NAME}"],
            "Permission": [
                "aoss:CreateCollectionItems", "aoss:DeleteCollectionItems",
                "aoss:UpdateCollectionItems", "aoss:DescribeCollectionItems",
            ],
            "ResourceType": "collection",
        },
        {
            "Resource": [f"index/{COLLECTION_NAME}/*"],
            "Permission": [
                "aoss:CreateIndex", "aoss:DeleteIndex", "aoss:UpdateIndex",
                "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument",
            ],
            "ResourceType": "index",
        },
    ],
    "Principal": [
        kb_role_arn,
        f"arn:aws:iam::{ACCOUNT}:root",
        f"arn:aws:iam::{ACCOUNT}:user/{IAM_USERNAME}",
    ],
}]
try:
    aoss_client.create_access_policy(name="aria-kb-access", type="data", policy=json.dumps(data_policy))
    print("    ✓ Created")
except aoss_client.exceptions.ConflictException:
    # Policy exists — update it so the aria user is in the principal list
    existing = aoss_client.get_access_policy(name="aria-kb-access", type="data")
    try:
        aoss_client.update_access_policy(
            name="aria-kb-access", type="data",
            policy=json.dumps(data_policy),
            policyVersion=existing["accessPolicyDetail"]["policyVersion"],
        )
        print("    → updated to include aria user")
    except Exception:
        print("    → already exists, skipping.")

# ── 7. Grant aria IAM user AOSS data-plane access ────────────────────────────
step("Granting aria IAM user aoss:APIAccessAll")
iam_client.put_user_policy(
    UserName=IAM_USERNAME,
    PolicyName="aria-aoss-dataplane",
    PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["aoss:APIAccessAll", "aoss:DashboardsAccessAll"],
            "Resource": f"arn:aws:aoss:{REGION}:{ACCOUNT}:collection/*",
        }],
    }),
)
print("    ✓ Policy attached to aria user")

# ── 8. Create vector index in AOSS ────────────────────────────────────────────
step(f"Creating vector index '{INDEX_NAME}' in AOSS collection")
print("    Waiting 60s for IAM + data access policy to propagate...")
time.sleep(60)

index_body = json.dumps({
    "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 512}},
    "mappings": {
        "properties": {
            "bedrock-knowledge-base-default-vector": {
                "type": "knn_vector",
                "dimension": 1024,
                "method": {"engine": "faiss", "space_type": "l2", "name": "hnsw", "parameters": {}},
            },
            "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text", "index": True},
            "AMAZON_BEDROCK_METADATA": {"type": "text", "index": False},
        }
    },
}).encode()

index_url = f"{collection_endpoint}/{INDEX_NAME}"
req = signed_urllib_request("PUT", index_url, index_body)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"    ✓ Index created: {json.loads(resp.read())}")
except urllib.error.HTTPError as e:
    body_text = e.read().decode()
    if "resource_already_exists_exception" in body_text.lower() or e.code == 403:
        print(f"    → index already exists (or no permission to verify) — continuing.")
    else:
        print(f"    ✗ Failed: {e.code} {body_text}", file=sys.stderr)
        sys.exit(1)

# ── 9. Bedrock Knowledge Base ─────────────────────────────────────────────────
step("Creating Bedrock Knowledge Base")
kb_match = [kb for kb in bedrock_agent.list_knowledge_bases()["knowledgeBaseSummaries"]
            if kb["name"] == "aria-knowledge-base"]
if kb_match:
    kb_id = kb_match[0]["knowledgeBaseId"]
    print(f"    → already exists: {kb_id}")
else:
    print("    Waiting 15s for IAM role to propagate...")
    time.sleep(15)
    kb_resp = bedrock_agent.create_knowledge_base(
        name="aria-knowledge-base",
        description="ARIA dispatcher knowledge base — Seattle / King County protocols",
        roleArn=kb_role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": EMBED_MODEL_ARN},
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": collection_arn,
                "vectorIndexName": INDEX_NAME,
                "fieldMapping": {
                    "vectorField": "bedrock-knowledge-base-default-vector",
                    "textField": "AMAZON_BEDROCK_TEXT_CHUNK",
                    "metadataField": "AMAZON_BEDROCK_METADATA",
                },
            },
        },
    )
    kb_id = kb_resp["knowledgeBase"]["knowledgeBaseId"]
    print(f"    ✓ Created KB: {kb_id}")

# ── 10. S3 data source ────────────────────────────────────────────────────────
step("Creating S3 data source")
ds_match = [ds for ds in bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]
            if ds["name"] == "aria-s3-source"]
if ds_match:
    ds_id = ds_match[0]["dataSourceId"]
    print(f"    → already exists: {ds_id}")
else:
    ds_resp = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name="aria-s3-source",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{BUCKET_NAME}",
                "inclusionPrefixes": ["knowledge-base/"],
            },
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {"maxTokens": 512, "overlapPercentage": 10},
            },
        },
    )
    ds_id = ds_resp["dataSource"]["dataSourceId"]
    print(f"    ✓ Created data source: {ds_id}")

# ── Done ──────────────────────────────────────────────────────────────────────
print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  KB ID          : {kb_id}
  Data Source ID : {ds_id}
  Collection     : {collection_endpoint}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Next steps:
  AWS_PROFILE=aria python scripts/upload_kb_docs.py
  BEDROCK_KB_ID={kb_id} BEDROCK_DS_ID={ds_id} AWS_PROFILE=aria python scripts/sync_knowledge_base.py --wait
""")
