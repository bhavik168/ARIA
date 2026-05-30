# ARIA — Manual AWS Setup Guide

Set up every AWS service by hand through the console. Work top to bottom — each section depends on the one above.

> **Region: us-west-2 (Oregon) for everything.**
> us-west-2 has full Bedrock support including Claude Haiku 3.5, Claude Sonnet 4, and Titan Embeddings V2.

> **Frontend runs locally.** Just `cd frontend && npm run dev`. No hosting needed.

---

## 1. Enable Bedrock Model Access

> Do this first — approval can take a few minutes and you need it before anything else works.

1. Go to **Amazon Bedrock → Model access** (left sidebar)
2. Click **Manage model access**
3. Check these:
   - **Anthropic → Claude Haiku 3.5** (verifier, medical/hazmat protocol interpretation)
   - **Anthropic → Claude Sonnet 4** (after-action report)
   - **Anthropic → Claude Sonnet 4.5** (coordinator synthesis, navigation/medical NLP) — **required**: the coordinator, medical, and navigation Lambdas call `us.anthropic.claude-sonnet-4-5-...`. Without it those calls fail with AccessDenied and silently fall back.
   - **Amazon → Titan Text Embeddings V2**
4. Click **Save changes** — wait for status to show **Access granted**

> The code uses **cross-region inference profile** IDs (the `us.` prefix, e.g. `us.anthropic.claude-sonnet-4-5-20250929-v1:0`). Enabling access in us-west-2 covers these. All model IDs are overridable via the `*_MODEL_ID` env vars on each Lambda if you need to pin a different version.

---

## 2. DynamoDB — 5 Tables

Go to **DynamoDB → Tables → Create table** for each one.

**Default settings for all tables (unless noted otherwise):**
- Billing mode: **On-demand**
- Encryption: **AWS owned key**

---

### Table 1: `aria-incidents`
| Setting | Value |
|---|---|
| Partition key | `incident_id` — String |
| Sort key | `timestamp` — String |
| TTL attribute | `ttl` (turn on under **Additional settings → TTL**) |
| Point-in-time recovery | On |

---

### Table 2: `aria-units`
| Setting | Value |
|---|---|
| Partition key | `unit_id` — String |
| Sort key | `status` — String |
| Point-in-time recovery | On |

**After the table is created**, go to **Indexes → Create index:**
| Setting | Value |
|---|---|
| Index name | `status-type-index` |
| Partition key | `status` — String |
| Sort key | `unit_type` — String |

---

### Table 3: `aria-hospitals`
| Setting | Value |
|---|---|
| Partition key | `hospital_id` — String |
| Sort key | `region` — String |

---

### Table 4: `aria-overrides`
| Setting | Value |
|---|---|
| Partition key | `incident_id` — String |
| Sort key | `timestamp` — String |
| Point-in-time recovery | On |

---

### Table 5: `aria-ws-connections`
| Setting | Value |
|---|---|
| Partition key | `connection_id` — String |
| TTL attribute | `ttl` |

**After the table is created**, go to **Indexes → Create index:**
| Setting | Value |
|---|---|
| Index name | `incident-index` |
| Partition key | `incident_id` — String |

---

## 3. S3 — 1 Bucket

Go to **S3 → Create bucket**. Replace `{account-id}` with your 12-digit AWS account ID.

### Bucket: `aria-{account-id}`
- Block all public access: **On**
- Bucket versioning: **Disabled** (not needed for a demo)
- Encryption: **SSE-S3** (default, already on)

Everything lives inside this one bucket under these folder prefixes:
```
aria-{account-id}/
  knowledge-base/    ← KB source documents
  transcripts/       ← call audio/text
  reports/           ← after-action reports
  agent-logs/        ← Bedrock guardrail logs
```
You don't need to create the folders manually — they're created automatically when the first file is uploaded.

---

## 4. IAM Roles — One Per Lambda

Go to **IAM → Roles → Create role** for each.
- Trusted entity type: **AWS service**
- Use case: **Lambda**

---

### Role 1: `aria-ingest-role`
Attach managed policy: **AWSLambdaBasicExecutionRole**

Add inline policy (Actions → Create inline policy → JSON):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::aria-{account-id}/*"
    },
    {
      "Effect": "Allow",
      "Action": ["transcribe:StartStreamTranscription"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-stream-processor*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-coordinator*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-navigation-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-medical-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-hazmat-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-verifier*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-ingest*"
      ]
    }
  ]
}
```

> `aria-ingest` invokes the coordinator at `transcript_complete` and pings the
> downstream functions on `/session/warmup`, so it needs invoke rights on all of
> them (and on itself for the async replay/poll self-invocations).

---

### Role 2: `aria-stream-processor-role`
Attach managed policy: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-coordinator*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-navigation-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-medical-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-hazmat-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-verifier*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-stream-processor*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}}
    }
  ]
}
```

> The stream processor fires the semantic verifier and self-invokes for context
> checkpoints, so it needs invoke rights on `aria-verifier` and `aria-stream-processor`.

---

### Role 3: `aria-coordinator-role`
Attach managed policy: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents/*",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-overrides"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeAgent", "bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-navigation-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-medical-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-hazmat-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-report*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}}
    }
  ]
}
```

---

### Role 4: `aria-navigation-tool-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-units",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-units/index/status-type-index",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}}
    }
  ]
}
```

---

### Role 5: `aria-medical-tool-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-hospitals",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-hospitals/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:Retrieve", "bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "arn:aws:lambda:us-west-2:{account-id}:function:aria-mock-hospital*"
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}}
    }
  ]
}
```

---

### Role 6: `aria-hazmat-tool-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:Retrieve", "bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    }
  ]
}
```

---

### Role 7: `aria-mock-hospital-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-hospitals",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-hospitals/*"
      ]
    }
  ]
}
```

---

### Role 8: `aria-report-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents",
        "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::aria-{account-id}/*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    }
  ]
}
```

> `s3:GetObject` is needed so the report Lambda can issue a **presigned GET URL**
> for the after-action report (the dashboard "Download Report" link).

---

### Role 9: `aria-ws-connect-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections"
    }
  ]
}
```

---

### Role 10: `aria-ws-disconnect-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:DeleteItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections"
    }
  ]
}
```

---

### Role 11: `aria-verifier-role`
Attach: **AWSLambdaBasicExecutionRole**

Inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-incidents"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:us-west-2:{account-id}:table/aria-ws-connections/index/incident-index"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": [
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-navigation-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-medical-tool*",
        "arn:aws:lambda:us-west-2:{account-id}:function:aria-hazmat-tool*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["execute-api:ManageConnections"],
      "Resource": "arn:aws:execute-api:us-west-2:{account-id}:*"
    },
    {
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": "*",
      "Condition": {"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}}
    }
  ]
}
```

> The verifier classifies the transcript with Claude Haiku 3.5, triggers any
> specialist agents the keyword watchers missed, and writes its classification
> back to `aria-incidents` for the coordinator to read.

---

## 5. Lambda Functions — 11 Functions

Go to **Lambda → Create function → Author from scratch**
- Runtime: **Python 3.12**
- Architecture: **x86_64**

For each function: create it, then upload the code file from `backend/lambdas/{function-name}/handler.py` using **Upload from → .zip file** (zip just the handler.py).

**No VPC needed for any function** — Lambda reaches DynamoDB, S3, and Bedrock directly.

---

### Function 1: `aria-ingest`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-ingest-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
UNITS_TABLE                   aria-units
HOSPITALS_TABLE               aria-hospitals
OVERRIDES_TABLE               aria-overrides
CONNECTIONS_TABLE             aria-ws-connections
STREAM_PROCESSOR_FUNCTION     aria-stream-processor
COORDINATOR_FUNCTION          aria-coordinator
NAVIGATION_FUNCTION           aria-navigation-tool
MEDICAL_FUNCTION              aria-medical-tool
HAZMAT_FUNCTION               aria-hazmat-tool
VERIFIER_FUNCTION             aria-verifier
WS_ENDPOINT                   (fill in after WebSocket API is created)
ARIA_BUCKET                   aria-{account-id}
POWERTOOLS_SERVICE_NAME       aria-ingest
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```
Provisioned Concurrency: **5**

> `aria-ingest` fires the coordinator at `transcript_complete` and warms the
> downstream functions on `/session/warmup`, so it needs their names here and
> `lambda:InvokeFunction` rights on them (see Role 1).

---

### Function 2: `aria-stream-processor`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-stream-processor-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
COORDINATOR_FUNCTION          aria-coordinator
NAVIGATION_FUNCTION           aria-navigation-tool
MEDICAL_FUNCTION              aria-medical-tool
HAZMAT_FUNCTION               aria-hazmat-tool
VERIFIER_FUNCTION             aria-verifier
STREAM_PROCESSOR_FUNCTION     aria-stream-processor
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-stream-processor
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```
Provisioned Concurrency: **10**

---

### Function 3: `aria-coordinator`
| Memory | Timeout | Role |
|---|---|---|
| 1024 MB | 300 sec | `aria-coordinator-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
OVERRIDES_TABLE               aria-overrides
CONNECTIONS_TABLE             aria-ws-connections
NAVIGATION_FUNCTION           aria-navigation-tool
MEDICAL_FUNCTION              aria-medical-tool
HAZMAT_FUNCTION               aria-hazmat-tool
REPORT_FUNCTION               aria-report
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-coordinator
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```
Provisioned Concurrency: **5**

---

### Function 4: `aria-navigation-tool`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-navigation-tool-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
UNITS_TABLE                   aria-units
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
GOOGLE_MAPS_API_KEY           (your key from Google Cloud Console)
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-navigation-tool
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```
Provisioned Concurrency: **10**

---

### Function 5: `aria-medical-tool`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-medical-tool-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
HOSPITALS_TABLE               aria-hospitals
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
MOCK_HOSPITAL_FUNCTION        aria-mock-hospital
BEDROCK_KB_ID                 (fill in after Phase 2 — Knowledge Base)
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-medical-tool
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```
Provisioned Concurrency: **10**

---

### Function 6: `aria-hazmat-tool`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-hazmat-tool-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
BEDROCK_KB_ID                 (fill in after Phase 2 — Knowledge Base)
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-hazmat-tool
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```

---

### Function 7: `aria-mock-hospital`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-mock-hospital-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
HOSPITALS_TABLE               aria-hospitals
POWERTOOLS_SERVICE_NAME       aria-mock-hospital
LOG_LEVEL                     INFO
```

---

### Function 8: `aria-report`
| Memory | Timeout | Role |
|---|---|---|
| 1024 MB | 300 sec | `aria-report-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
ARIA_BUCKET                   aria-{account-id}
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-report
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```

---

### Function 9: `aria-ws-connect`
| Memory | Timeout | Role |
|---|---|---|
| 256 MB | 10 sec | `aria-ws-connect-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
CONNECTIONS_TABLE             aria-ws-connections
POWERTOOLS_SERVICE_NAME       aria-ws-connect
LOG_LEVEL                     INFO
```

---

### Function 10: `aria-ws-disconnect`
| Memory | Timeout | Role |
|---|---|---|
| 256 MB | 10 sec | `aria-ws-disconnect-role` |

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
CONNECTIONS_TABLE             aria-ws-connections
POWERTOOLS_SERVICE_NAME       aria-ws-disconnect
LOG_LEVEL                     INFO
```

---

### Function 11: `aria-verifier`
| Memory | Timeout | Role |
|---|---|---|
| 512 MB | 30 sec | `aria-verifier-role` |

Code: `backend/lambdas/aria-verifier/handler.py`

Environment variables:
```
AWS_DEPLOY_REGION             us-west-2
INCIDENTS_TABLE               aria-incidents
CONNECTIONS_TABLE             aria-ws-connections
NAVIGATION_FUNCTION           aria-navigation-tool
MEDICAL_FUNCTION              aria-medical-tool
HAZMAT_FUNCTION               aria-hazmat-tool
WS_ENDPOINT                   (fill in after WebSocket API is created)
POWERTOOLS_SERVICE_NAME       aria-verifier
POWERTOOLS_METRICS_NAMESPACE  ARIA/Latency
LOG_LEVEL                     INFO
```

> Required. The stream processor invokes this every ~10 words. Without it the
> verifier enrichment (severity upgrades, incident-type correction, missed-agent
> triggers) never runs and the coordinator's `verifier_classification` stays empty.

---

## 6. Provisioned Concurrency

> Eliminates cold starts on the 5 functions that must respond instantly.

For each of these functions: `aria-stream-processor`, `aria-ingest`, `aria-coordinator`, `aria-navigation-tool`, `aria-medical-tool`:

1. Lambda function page → **Versions tab** → **Publish new version** → Publish
2. **Aliases tab** → **Create alias**
   - Name: `live`
   - Version: select the one you just published
3. Click the `live` alias → **Configuration tab** → **Provisioned concurrency → Edit**
4. Set the value:

| Function | Provisioned concurrency |
|---|---|
| `aria-stream-processor` | 10 |
| `aria-navigation-tool` | 10 |
| `aria-medical-tool` | 10 |
| `aria-ingest` | 5 |
| `aria-coordinator` | 5 |

> **Cost note:** Each unit costs ~$0.015/hr even when idle. Turn it off when not demoing.

---

## 7. API Gateway — REST API

Go to **API Gateway → Create API → REST API** (not HTTP API, not private)

- API name: `aria-api`
- Endpoint type: **Regional**

### Create these routes:

| Resource path | Method | Lambda function |
|---|---|---|
| `/session/start` | POST | `aria-ingest` |
| `/session/{id}/approve` | POST | `aria-coordinator` |
| `/session/{id}/override` | POST | `aria-coordinator` |
| `/session/{id}/status` | GET | `aria-ingest` |
| `/hospital` | POST | `aria-mock-hospital` |

For each: **Integration type → Lambda function**, check **Use Lambda proxy integration**, enter the function name.

### Enable CORS on each resource:
Select the resource → **Actions → Enable CORS** → click the defaults → **Enable CORS and replace existing CORS headers**

### Deploy:
**Actions → Deploy API** → create a new stage named `prod` → Deploy

Copy the **Invoke URL** shown at the top — looks like:
`https://abc123xyz.execute-api.us-west-2.amazonaws.com/prod`

This is your `VITE_API_URL` for the frontend.

---

## 8. API Gateway — WebSocket API

Go to **API Gateway → Create API → WebSocket API**

- API name: `aria-ws`
- Route selection expression: `$request.body.action`

### Create routes:

| Route key | Integration type | Lambda function |
|---|---|---|
| `$connect` | Lambda | `aria-ws-connect` |
| `$disconnect` | Lambda | `aria-ws-disconnect` |
| `$default` | Lambda | `aria-ws-default` |

> The `$default` route is **required**. The dashboard sends a `{"action":"ping"}`
> keepalive every 20s; without a `$default` integration API Gateway has nowhere to
> route it and can drop the socket. `aria-ws-default` (code:
> `backend/lambdas/aria-ws-default/handler.py`) just acknowledges and returns 200.
> Create it as a small function (256 MB / 10 sec) using the basic
> `AWSLambdaBasicExecutionRole` — it needs no extra permissions.

### Deploy:
**Actions → Deploy** → stage name `prod`

Copy the **WebSocket URL** — looks like:
`wss://def456uvw.execute-api.us-west-2.amazonaws.com/prod`

### Update Lambda env vars:
Go back to all 7 functions that have a `WS_ENDPOINT` env var and fill it in:
`aria-stream-processor`, `aria-coordinator`, `aria-navigation-tool`, `aria-medical-tool`, `aria-hazmat-tool`, `aria-report`, `aria-verifier`

---

## 9. Seed Demo Data

Once everything above is done, run this from your laptop to populate the units and hospitals tables:

```bash
cd ~/aria   # or wherever you cloned the repo
pip install boto3
aws configure --profile aria-dev   # if not done already
python scripts/seed_units.py
```

---

## 10. Run the Frontend Locally

```bash
cd ~/aria/frontend   # or wherever you cloned the repo
npm install
```

Create `frontend/.env.local` (note: the var is `VITE_API_BASE_URL`, which is what
`frontend/src/App.tsx` actually reads — not `VITE_API_URL`):
```
VITE_API_BASE_URL=https://{your-rest-api-id}.execute-api.us-west-2.amazonaws.com/prod
VITE_WS_URL=wss://{your-ws-api-id}.execute-api.us-west-2.amazonaws.com/prod
VITE_MAPBOX_TOKEN={your-mapbox-token}
```

Then:
```bash
npm run dev
```

Open `http://localhost:5173` — that's your dispatcher dashboard.

---

## Completion Checklist

```
[ ] Bedrock model access granted for Claude Haiku 3.5, Sonnet 4, Sonnet 4.5, Titan Embeddings V2
[ ] 5 DynamoDB tables created with correct keys and GSIs
[ ] 1 S3 bucket created (aria-{account-id}) with correct name
[ ] 11 IAM roles created with least-privilege inline policies (incl. aria-verifier-role)
[ ] 11 Lambda functions created — correct memory, timeout, env vars (incl. aria-verifier)
[ ] aria-ws-default function created and wired to the $default route
[ ] Code uploaded to each Lambda function
[ ] Provisioned Concurrency set on 5 critical functions
[ ] REST API deployed — 5 routes wired to Lambda
[ ] WebSocket API deployed — $connect, $disconnect, and $default wired to Lambda
[ ] WS_ENDPOINT env var updated in 7 Lambda functions
[ ] Demo data seeded: python scripts/seed_units.py
[ ] Frontend running at localhost:5173 (VITE_API_BASE_URL / VITE_WS_URL set)
```

**Next: Phase 2 — Knowledge Base**
Upload medical and hazmat documents to S3 and create the Bedrock Knowledge Base.
