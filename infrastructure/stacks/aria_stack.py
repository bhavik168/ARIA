import json
import os
from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_apigateway as apigw,
    aws_apigatewayv2 as apigwv2,
    aws_cloudwatch as cloudwatch,
    aws_logs as logs,
    aws_opensearchserverless as aoss,
    aws_bedrock as bedrock,
)
from constructs import Construct


class AriaStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tables = self._create_dynamodb_tables()
        buckets = self._create_s3_buckets()
        kb_id, ds_id = self._create_knowledge_base(buckets)
        guardrail_id, guardrail_version = self._create_guardrail(buckets)
        roles = self._create_iam_roles(tables, buckets)
        functions = self._create_lambda_functions(roles, tables, buckets, kb_id, guardrail_id, guardrail_version)
        agent_ids = self._create_bedrock_agents(functions, kb_id)
        # Wire specialist agent IDs into coordinator
        functions["coordinator"].add_environment("NAVIGATION_AGENT_ID", agent_ids["navigation_agent_id"])
        functions["coordinator"].add_environment("NAVIGATION_AGENT_ALIAS_ID", agent_ids["navigation_alias_id"])
        functions["coordinator"].add_environment("MEDICAL_AGENT_ID", agent_ids["medical_agent_id"])
        functions["coordinator"].add_environment("MEDICAL_AGENT_ALIAS_ID", agent_ids["medical_alias_id"])
        functions["coordinator"].add_environment("HAZMAT_AGENT_ID", agent_ids["hazmat_agent_id"])
        functions["coordinator"].add_environment("HAZMAT_AGENT_ALIAS_ID", agent_ids["hazmat_alias_id"])
        functions["coordinator"].add_environment("REPORT_AGENT_ID", agent_ids["report_agent_id"])
        functions["coordinator"].add_environment("REPORT_AGENT_ALIAS_ID", agent_ids["report_alias_id"])
        # Wire coordinator agent ID into stream processor (for future invoke_agent path)
        functions["stream_processor"].add_environment("COORDINATOR_AGENT_ID", agent_ids["coordinator_agent_id"])
        functions["stream_processor"].add_environment("COORDINATOR_AGENT_ALIAS_ID", agent_ids["coordinator_alias_id"])
        rest_api = self._create_rest_api(functions)
        ws_api = self._create_websocket_api(functions)
        self._create_cloudwatch_alarms(functions)
        self._create_outputs(rest_api, ws_api, tables, buckets, kb_id, ds_id, guardrail_id, agent_ids)

    # ─── Bedrock Guardrail ────────────────────────────────────────────────────

    def _create_guardrail(self, buckets: dict) -> tuple:
        guardrail = bedrock.CfnGuardrail(
            self, "AriaGuardrail",
            name="aria-guardrail",
            description="ARIA safety guardrail — no autonomous dispatch, no PII leakage, no medical prescriptions",
            blocked_input_messaging="Input blocked by ARIA safety policy. Contact supervisor.",
            blocked_outputs_messaging="Output blocked by ARIA safety policy. Recommendation withheld — use manual protocol.",

            # Content filters: block violence/hate in outputs
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="HATE", input_strength="MEDIUM", output_strength="HIGH",
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="VIOLENCE", input_strength="MEDIUM", output_strength="HIGH",
                    ),
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="MISCONDUCT", input_strength="MEDIUM", output_strength="HIGH",
                    ),
                ],
            ),

            # PII: block phone numbers and SSNs from appearing in agent outputs
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="PHONE", action="BLOCK"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="US_SOCIAL_SECURITY_NUMBER", action="BLOCK"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="EMAIL", action="ANONYMIZE"),
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type="NAME", action="ANONYMIZE"),
                ],
                regexes_config=[
                    # Block specific drug dosage patterns (mg, mL, units)
                    bedrock.CfnGuardrail.RegexConfigProperty(
                        name="drug-dosage",
                        description="Specific drug dosages (e.g. 5mg morphine, 1:1000 epi)",
                        pattern=r"\b\d+(\.\d+)?\s*(mg|mL|mcg|units?|IU)\s+of\s+\w+",
                        action="BLOCK",
                    ),
                ],
            ),

            # Topic denials: autonomous dispatch, prescriptions, self-harm escalation
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="autonomous-dispatch",
                        definition=(
                            "Any instruction or claim to automatically dispatch, route, or assign "
                            "emergency units without explicit human dispatcher approval"
                        ),
                        examples=[
                            "Dispatching unit MED-1 automatically",
                            "Unit has been sent without approval",
                            "Route assigned — no approval needed",
                        ],
                        type="DENY",
                    ),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="medical-prescription",
                        definition=(
                            "Specific drug dosages, medication prescriptions, IV orders, or clinical "
                            "treatment protocols that must only come from licensed medical professionals"
                        ),
                        examples=[
                            "Administer 5mg morphine IV",
                            "Give patient 325mg aspirin",
                            "Push 1mg epinephrine 1:10000",
                        ],
                        type="DENY",
                    ),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="self-harm-crisis",
                        definition=(
                            "Suicidal ideation, active self-harm, hostage situations, or imminent "
                            "violence against self — these require immediate human escalation"
                        ),
                        examples=[
                            "caller says they want to kill themselves",
                            "hostage situation in progress",
                            "caller is threatening self-harm with a weapon",
                        ],
                        type="DENY",
                    ),
                ],
            ),
        )

        # Version for pinning (DRAFT always exists)
        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id, export_name="AriaGuardrailId")
        return guardrail.attr_guardrail_id, "DRAFT"

    # ─── Bedrock Knowledge Base + OpenSearch Serverless ──────────────────────

    def _create_knowledge_base(self, buckets: dict) -> tuple:
        # Allow reusing a pre-existing KB (e.g. created via scripts/create_kb.py) without
        # CloudFormation creating a duplicate. Pass at deploy time:
        #   cdk deploy -c existing_kb_id=<ID> -c existing_ds_id=<ID>
        existing_kb_id = self.node.try_get_context("existing_kb_id")
        existing_ds_id = self.node.try_get_context("existing_ds_id")
        if existing_kb_id and existing_ds_id:
            return existing_kb_id, existing_ds_id

        collection_name = "aria-kb"

        enc_policy = aoss.CfnSecurityPolicy(
            self, "AOSSEncryptionPolicy",
            name="aria-kb-enc",
            type="encryption",
            policy=json.dumps({
                "Rules": [{"Resource": [f"collection/{collection_name}"], "ResourceType": "collection"}],
                "AWSOwnedKey": True,
            }),
        )

        net_policy = aoss.CfnSecurityPolicy(
            self, "AOSSNetworkPolicy",
            name="aria-kb-net",
            type="network",
            policy=json.dumps([{
                "Rules": [
                    {"Resource": [f"collection/{collection_name}"], "ResourceType": "collection"},
                    {"Resource": [f"collection/{collection_name}"], "ResourceType": "dashboard"},
                ],
                "AllowFromPublic": True,
            }]),
        )

        collection = aoss.CfnCollection(
            self, "AOSSCollection",
            name=collection_name,
            type="VECTORSEARCH",
        )
        collection.add_dependency(enc_policy)
        collection.add_dependency(net_policy)

        kb_role = iam.Role(
            self, "BedrockKBRole",
            role_name="aria-bedrock-kb-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        buckets["bucket"].grant_read(kb_role)
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"],
            resources=[f"arn:aws:aoss:{self.region}:{self.account}:collection/*"],
        ))

        aoss.CfnAccessPolicy(
            self, "AOSSAccessPolicy",
            name="aria-kb-access",
            type="data",
            policy=json.dumps([{
                "Rules": [
                    {
                        "Resource": [f"collection/{collection_name}"],
                        "Permission": [
                            "aoss:CreateCollectionItems",
                            "aoss:DeleteCollectionItems",
                            "aoss:UpdateCollectionItems",
                            "aoss:DescribeCollectionItems",
                        ],
                        "ResourceType": "collection",
                    },
                    {
                        "Resource": [f"index/{collection_name}/*"],
                        "Permission": [
                            "aoss:CreateIndex",
                            "aoss:DeleteIndex",
                            "aoss:UpdateIndex",
                            "aoss:DescribeIndex",
                            "aoss:ReadDocument",
                            "aoss:WriteDocument",
                        ],
                        "ResourceType": "index",
                    },
                ],
                "Principal": [
                    kb_role.role_arn,
                    f"arn:aws:iam::{self.account}:root",
                ],
            }]),
        )

        kb = bedrock.CfnKnowledgeBase(
            self, "AriaKnowledgeBase",
            name="aria-knowledge-base",
            description="ARIA dispatcher knowledge base — emergency response protocols",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=collection.attr_arn,
                    vector_index_name="aria-kb-index",
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field="bedrock-knowledge-base-default-vector",
                        text_field="AMAZON_BEDROCK_TEXT_CHUNK",
                        metadata_field="AMAZON_BEDROCK_METADATA",
                    ),
                ),
            ),
        )
        kb.add_dependency(collection)

        ds = bedrock.CfnDataSource(
            self, "AriaKBDataSource",
            knowledge_base_id=kb.attr_knowledge_base_id,
            name="aria-s3-source",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=buckets["bucket"].bucket_arn,
                    inclusion_prefixes=["knowledge-base/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512,
                        overlap_percentage=10,
                    ),
                ),
            ),
        )

        return kb.attr_knowledge_base_id, ds.attr_data_source_id

    # ─── DynamoDB ────────────────────────────────────────────────────────────

    def _create_dynamodb_tables(self) -> dict:
        incidents = dynamodb.Table(
            self, "IncidentsTable",
            table_name="aria-incidents",
            partition_key=dynamodb.Attribute(name="incident_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="timestamp", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )

        units = dynamodb.Table(
            self, "UnitsTable",
            table_name="aria-units",
            partition_key=dynamodb.Attribute(name="unit_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        units.add_global_secondary_index(
            index_name="status-type-index",
            partition_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="unit_type", type=dynamodb.AttributeType.STRING),
        )

        hospitals = dynamodb.Table(
            self, "HospitalsTable",
            table_name="aria-hospitals",
            partition_key=dynamodb.Attribute(name="hospital_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="region", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        overrides = dynamodb.Table(
            self, "OverridesTable",
            table_name="aria-overrides",
            partition_key=dynamodb.Attribute(name="incident_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="timestamp", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )

        connections = dynamodb.Table(
            self, "ConnectionsTable",
            table_name="aria-ws-connections",
            partition_key=dynamodb.Attribute(name="connection_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )
        connections.add_global_secondary_index(
            index_name="incident-index",
            partition_key=dynamodb.Attribute(name="incident_id", type=dynamodb.AttributeType.STRING),
        )

        return {
            "incidents": incidents,
            "units": units,
            "hospitals": hospitals,
            "overrides": overrides,
            "connections": connections,
        }

    # ─── S3 ──────────────────────────────────────────────────────────────────

    def _create_s3_buckets(self) -> dict:
        account = self.account

        bucket = s3.Bucket(
            self, "AriaBucket",
            bucket_name=f"aria-{account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.PUT,
                        s3.HttpMethods.GET,
                        s3.HttpMethods.HEAD,
                    ],
                    allowed_origins=[
                        "http://localhost:5173",
                        "http://localhost:3000",
                        "https://*.cloudfront.net",
                    ],
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3000,
                )
            ],
        )

        # One bucket, four folder prefixes:
        # aria-{account}/knowledge-base/
        # aria-{account}/transcripts/
        # aria-{account}/reports/
        # aria-{account}/agent-logs/

        return {
            "knowledge_base": bucket,
            "transcripts": bucket,
            "reports": bucket,
            "agent_logs": bucket,
            "bucket": bucket,
        }

    # ─── IAM Roles ───────────────────────────────────────────────────────────

    def _create_iam_roles(self, tables: dict, buckets: dict) -> dict:
        basic = iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )

        def _role(name: str) -> iam.Role:
            return iam.Role(
                self, f"{name}Role",
                role_name=f"aria-{name}-role",
                assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                managed_policies=[basic],
            )

        ingest_role = _role("ingest")
        tables["incidents"].grant_read_write_data(ingest_role)
        buckets["bucket"].grant_read_write(ingest_role)
        ingest_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "transcribe:StartStreamTranscription",
                "transcribe:StartTranscriptionJob",
                "transcribe:GetTranscriptionJob",
                "transcribe:DeleteTranscriptionJob",
            ],
            resources=["*"],
        ))
        ingest_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-stream-processor*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-coordinator*",
            ],
        ))

        stream_role = _role("stream-processor")
        tables["incidents"].grant_read_write_data(stream_role)
        tables["connections"].grant_read_data(stream_role)
        stream_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-coordinator*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-navigation-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-medical-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-hazmat-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-verifier*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-stream-processor*",
            ],
        ))
        stream_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))
        stream_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}},
        ))

        coordinator_role = _role("coordinator")
        tables["incidents"].grant_read_write_data(coordinator_role)
        tables["overrides"].grant_write_data(coordinator_role)
        tables["connections"].grant_read_data(coordinator_role)
        coordinator_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeAgent", "bedrock:InvokeModel"],
            resources=["*"],
        ))
        coordinator_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-navigation-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-medical-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-hazmat-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-report*",
            ],
        ))
        coordinator_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))
        coordinator_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}},
        ))

        navigation_role = _role("navigation-tool")
        tables["units"].grant_read_write_data(navigation_role)
        tables["incidents"].grant_write_data(navigation_role)
        tables["connections"].grant_read_data(navigation_role)
        navigation_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["*"],
        ))
        navigation_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))
        navigation_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}},
        ))

        medical_role = _role("medical-tool")
        tables["hospitals"].grant_read_data(medical_role)
        tables["incidents"].grant_write_data(medical_role)
        tables["connections"].grant_read_data(medical_role)
        medical_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve", "bedrock:InvokeModel"],
            resources=["*"],
        ))
        medical_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:aria-mock-hospital*"],
        ))
        medical_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))
        medical_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}},
        ))

        hazmat_role = _role("hazmat-tool")
        tables["incidents"].grant_write_data(hazmat_role)
        tables["connections"].grant_read_data(hazmat_role)
        hazmat_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve", "bedrock:InvokeModel"],
            resources=["*"],
        ))
        hazmat_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))

        mock_hospital_role = _role("mock-hospital")
        tables["hospitals"].grant_read_write_data(mock_hospital_role)

        verifier_role = _role("verifier")
        tables["incidents"].grant_read_write_data(verifier_role)
        tables["connections"].grant_read_data(verifier_role)
        verifier_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["*"],
        ))
        verifier_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-navigation-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-medical-tool*",
                f"arn:aws:lambda:{self.region}:{self.account}:function:aria-hazmat-tool*",
            ],
        ))
        verifier_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))
        verifier_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "ARIA/Latency"}},
        ))

        report_role = _role("report")
        tables["incidents"].grant_read_write_data(report_role)
        tables["connections"].grant_read_data(report_role)
        buckets["bucket"].grant_write(report_role)
        report_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["*"],
        ))
        report_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))

        ws_connect_role = _role("ws-connect")
        tables["connections"].grant_write_data(ws_connect_role)

        ws_disconnect_role = _role("ws-disconnect")
        tables["connections"].grant_write_data(ws_disconnect_role)

        ws_default_role = _role("ws-default")

        return {
            "ingest": ingest_role,
            "stream_processor": stream_role,
            "coordinator": coordinator_role,
            "navigation": navigation_role,
            "medical": medical_role,
            "hazmat": hazmat_role,
            "mock_hospital": mock_hospital_role,
            "report": report_role,
            "verifier": verifier_role,
            "ws_connect": ws_connect_role,
            "ws_disconnect": ws_disconnect_role,
            "ws_default": ws_default_role,
        }

    # ─── Lambda Functions ────────────────────────────────────────────────────

    def _create_lambda_functions(self, roles: dict, tables: dict, buckets: dict, kb_id: str, guardrail_id: str, guardrail_version: str) -> dict:
        bucket_name = buckets["bucket"].bucket_name
        common_env = {
            "AWS_DEPLOY_REGION": self.region,
            "INCIDENTS_TABLE": tables["incidents"].table_name,
            "UNITS_TABLE": tables["units"].table_name,
            "HOSPITALS_TABLE": tables["hospitals"].table_name,
            "OVERRIDES_TABLE": tables["overrides"].table_name,
            "CONNECTIONS_TABLE": tables["connections"].table_name,
            "ARIA_BUCKET": bucket_name,
            "POWERTOOLS_METRICS_NAMESPACE": "ARIA/Latency",
            "LOG_LEVEL": "INFO",
        }

        def _fn(
            cid: str,
            name: str,
            role: iam.Role,
            extra_env: dict = None,
            memory: int = 512,
            timeout: int = 30,
            provisioned: int = 0,
        ) -> lambda_.Function:
            env = {**common_env, **(extra_env or {}), "POWERTOOLS_SERVICE_NAME": name}
            fn = lambda_.Function(
                self, f"{cid}Function",
                function_name=name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                code=lambda_.Code.from_asset(f"backend/lambdas/{name}"),
                handler="handler.lambda_handler",
                memory_size=memory,
                timeout=Duration.seconds(timeout),
                role=role,
                environment=env,
                log_retention=logs.RetentionDays.ONE_MONTH,
                tracing=lambda_.Tracing.ACTIVE,
            )
            if provisioned > 0:
                lambda_.Alias(
                    self, f"{cid}Alias",
                    alias_name="live",
                    version=fn.current_version,
                    provisioned_concurrent_executions=provisioned,
                )
            return fn

        ingest = _fn("Ingest", "aria-ingest", roles["ingest"],
            timeout=600,
            extra_env={
                "STREAM_PROCESSOR_FUNCTION": "aria-stream-processor",
                "COORDINATOR_FUNCTION": "aria-coordinator",
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
                "VERIFIER_FUNCTION": "aria-verifier",
            })

        stream_processor = _fn("StreamProcessor", "aria-stream-processor", roles["stream_processor"],
            extra_env={
                "COORDINATOR_FUNCTION": "aria-coordinator",
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
                "VERIFIER_FUNCTION": "aria-verifier",
            })

        coordinator = _fn("Coordinator", "aria-coordinator", roles["coordinator"],
            extra_env={
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
                "REPORT_FUNCTION": "aria-report",
                "GUARDRAIL_ID": guardrail_id,
                "GUARDRAIL_VERSION": guardrail_version,
            },
            memory=1024, timeout=300)

        google_maps_key = (
            self.node.try_get_context("google_maps_api_key")
            or os.environ.get("GOOGLE_MAPS_API_KEY", "REPLACE_ME")
        )
        navigation = _fn("Navigation", "aria-navigation-tool", roles["navigation"],
            extra_env={"GOOGLE_MAPS_API_KEY": google_maps_key})

        medical = _fn("Medical", "aria-medical-tool", roles["medical"],
            extra_env={
                "MOCK_HOSPITAL_FUNCTION": "aria-mock-hospital",
                "BEDROCK_KB_ID": kb_id,
            })

        hazmat = _fn("Hazmat", "aria-hazmat-tool", roles["hazmat"],
            extra_env={"BEDROCK_KB_ID": kb_id})

        mock_hospital = _fn("MockHospital", "aria-mock-hospital", roles["mock_hospital"])

        verifier = _fn("Verifier", "aria-verifier", roles["verifier"],
            extra_env={
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
            },
            memory=512, timeout=15)

        report = _fn("Report", "aria-report", roles["report"],
            memory=1024, timeout=300)

        ws_connect = lambda_.Function(
            self, "WsConnectFunction",
            function_name="aria-ws-connect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("backend/lambdas/aria-ws-connect"),
            handler="handler.lambda_handler",
            memory_size=256,
            timeout=Duration.seconds(10),
            role=roles["ws_connect"],
            environment={**common_env, "POWERTOOLS_SERVICE_NAME": "aria-ws-connect"},
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        ws_disconnect = lambda_.Function(
            self, "WsDisconnectFunction",
            function_name="aria-ws-disconnect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("backend/lambdas/aria-ws-disconnect"),
            handler="handler.lambda_handler",
            memory_size=256,
            timeout=Duration.seconds(10),
            role=roles["ws_disconnect"],
            environment={**common_env, "POWERTOOLS_SERVICE_NAME": "aria-ws-disconnect"},
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        ws_default = lambda_.Function(
            self, "WsDefaultFunction",
            function_name="aria-ws-default",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("backend/lambdas/aria-ws-default"),
            handler="handler.lambda_handler",
            memory_size=128,
            timeout=Duration.seconds(5),
            role=roles["ws_default"],
            environment={**common_env, "POWERTOOLS_SERVICE_NAME": "aria-ws-default"},
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        return {
            "ingest": ingest,
            "stream_processor": stream_processor,
            "coordinator": coordinator,
            "navigation": navigation,
            "medical": medical,
            "hazmat": hazmat,
            "mock_hospital": mock_hospital,
            "verifier": verifier,
            "report": report,
            "ws_connect": ws_connect,
            "ws_disconnect": ws_disconnect,
            "ws_default": ws_default,
        }

    # ─── Bedrock Multi-Agent Orchestration ───────────────────────────────────

    def _create_bedrock_agents(self, functions: dict, kb_id: str) -> dict:
        """
        Create three Bedrock Agents (Navigation, Medical, Hazmat) with action groups
        pointing to their existing Lambda functions. The coordinator will invoke_agent()
        instead of calling Lambdas directly, giving true Bedrock multi-agent orchestration.
        Sub-agents use Haiku (fast, cheap); coordinator uses Sonnet for final synthesis.
        """
        AGENT_MODEL = "anthropic.claude-3-5-haiku-20241022-v1:0"

        def _agent_role(name: str, extra_actions: list = None) -> iam.Role:
            role = iam.Role(
                self, f"{name}AgentRole",
                role_name=f"aria-{name.lower()}-agent-role",
                assumed_by=iam.ServicePrincipal(
                    "bedrock.amazonaws.com",
                    conditions={
                        "StringEquals": {"aws:SourceAccount": self.account},
                        "ArnLike": {
                            "aws:SourceArn": f"arn:aws:bedrock:{self.region}:{self.account}:agent/*"
                        },
                    },
                ),
            )
            role.add_to_policy(iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=["*"],
            ))
            for action in (extra_actions or []):
                role.add_to_policy(action)
            return role

        def _grant_bedrock_invoke(fn: lambda_.Function, cid: str) -> None:
            """Allow Bedrock Agents service to invoke the Lambda action group."""
            fn.add_permission(
                f"BedrockAgentInvoke{cid}",
                principal=iam.ServicePrincipal("bedrock.amazonaws.com"),
                action="lambda:InvokeFunction",
                source_arn=f"arn:aws:bedrock:{self.region}:{self.account}:agent/*",
            )

        # ── Navigation Agent ──────────────────────────────────────────────────
        nav_role = _agent_role("Navigation")
        functions["navigation"].grant_invoke(nav_role)
        _grant_bedrock_invoke(functions["navigation"], "Navigation")

        nav_agent = bedrock.CfnAgent(
            self, "NavigationAgent",
            agent_name="aria-navigation-agent",
            description="ARIA navigation specialist — finds closest available unit and calculates ETA",
            agent_resource_role_arn=nav_role.role_arn,
            foundation_model=AGENT_MODEL,
            instruction=(
                "You are ARIA's navigation specialist in a live 911 emergency dispatch system. "
                "Your only job is to find the closest available emergency unit and calculate their "
                "ETA to the incident location. "
                "You MUST call find_unit for every request — never answer without calling it first. "
                "After calling find_unit, return ONLY valid JSON with the result. No prose."
            ),
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="NavigationActions",
                    description="Find available emergency units and calculate ETAs",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=functions["navigation"].function_arn,
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="find_unit",
                                description="Find the closest available emergency unit and calculate ETA to the incident",
                                parameters={
                                    "incident_id": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="Unique incident identifier",
                                        required=True,
                                    ),
                                    "context_so_far": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="911 call transcript accumulated so far",
                                        required=True,
                                    ),
                                    "trigger_reason": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="What triggered this agent (e.g. location_detected, crime_keyword_detected)",
                                        required=False,
                                    ),
                                    "verifier_classification_json": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="JSON string of Haiku verifier classification for this incident",
                                        required=False,
                                    ),
                                },
                            ),
                        ],
                    ),
                ),
            ],
            auto_prepare=True,
        )
        # TSTALIASID is Bedrock's built-in test alias — always routes to DRAFT.
        # auto_prepare=True keeps DRAFT current on every deploy, so no CfnAgentAlias needed.

        # ── Medical Agent ─────────────────────────────────────────────────────
        med_role = _agent_role("Medical", extra_actions=[
            iam.PolicyStatement(
                actions=["bedrock:Retrieve"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{kb_id}"],
            ),
        ])
        functions["medical"].grant_invoke(med_role)
        _grant_bedrock_invoke(functions["medical"], "Medical")

        med_agent = bedrock.CfnAgent(
            self, "MedicalAgent",
            agent_name="aria-medical-agent",
            description="ARIA medical specialist — retrieves triage protocols and identifies closest hospital",
            agent_resource_role_arn=med_role.role_arn,
            foundation_model=AGENT_MODEL,
            instruction=(
                "You are ARIA's medical specialist in a live 911 emergency dispatch system. "
                "Your job is to retrieve the appropriate triage protocol for the incident and "
                "identify the closest suitable hospital with available capacity. "
                "You MUST call assess_medical_emergency for every request. "
                "After calling it, return ONLY valid JSON with the result. No prose."
            ),
            knowledge_bases=[
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    description="Emergency medical triage protocols and hospital pre-alert procedures",
                    knowledge_base_id=kb_id,
                    knowledge_base_state="ENABLED",
                ),
            ],
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="MedicalActions",
                    description="Retrieve triage protocol and identify closest hospital",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=functions["medical"].function_arn,
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="assess_medical_emergency",
                                description=(
                                    "Retrieve triage protocol from knowledge base, identify "
                                    "closest hospital, and send pre-alert for the patient"
                                ),
                                parameters={
                                    "incident_id": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="Unique incident identifier",
                                        required=True,
                                    ),
                                    "context_so_far": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="911 call transcript accumulated so far",
                                        required=True,
                                    ),
                                    "verifier_classification_json": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="JSON string of Haiku verifier classification",
                                        required=False,
                                    ),
                                },
                            ),
                        ],
                    ),
                ),
            ],
            auto_prepare=True,
        )

        # ── Hazmat Agent ──────────────────────────────────────────────────────
        haz_role = _agent_role("Hazmat", extra_actions=[
            iam.PolicyStatement(
                actions=["bedrock:Retrieve"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{kb_id}"],
            ),
        ])
        functions["hazmat"].grant_invoke(haz_role)
        _grant_bedrock_invoke(functions["hazmat"], "Hazmat")

        haz_agent = bedrock.CfnAgent(
            self, "HazmatAgent",
            agent_name="aria-hazmat-agent",
            description="ARIA hazmat/fire specialist — provides evacuation radii, PPE, and suppression approach",
            agent_resource_role_arn=haz_role.role_arn,
            foundation_model=AGENT_MODEL,
            instruction=(
                "You are ARIA's hazmat and fire safety specialist in a live 911 emergency dispatch system. "
                "Your job is to assess fire or chemical hazards and provide responders with evacuation "
                "radii, required PPE, and suppression approach from FEMA ERG and NIOSH guides. "
                "You MUST call assess_hazard for every request. "
                "After calling it, return ONLY valid JSON with the result. No prose."
            ),
            knowledge_bases=[
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    description="FEMA ERG hazmat guides and NIOSH chemical safety protocols",
                    knowledge_base_id=kb_id,
                    knowledge_base_state="ENABLED",
                ),
            ],
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="HazmatActions",
                    description="Assess fire or chemical hazard and provide responder guidance",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=functions["hazmat"].function_arn,
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="assess_hazard",
                                description=(
                                    "Retrieve hazard data from knowledge base and produce "
                                    "incident-specific evacuation radius, PPE list, and suppression approach"
                                ),
                                parameters={
                                    "incident_id": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="Unique incident identifier",
                                        required=True,
                                    ),
                                    "context_so_far": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="911 call transcript accumulated so far",
                                        required=True,
                                    ),
                                    "trigger_reason": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="What triggered this agent (fire_keyword_detected, hazmat_keyword_detected, etc.)",
                                        required=False,
                                    ),
                                    "verifier_classification_json": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="JSON string of Haiku verifier classification",
                                        required=False,
                                    ),
                                },
                            ),
                        ],
                    ),
                ),
            ],
            auto_prepare=True,
        )
        # ── Coordinator Agent ──────────────────────────────────────────────────
        SONNET_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"

        coord_agent_role = _agent_role("Coordinator", extra_actions=[
            iam.PolicyStatement(
                actions=["bedrock:InvokeAgent"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:agent-alias/*"],
            ),
        ])
        functions["coordinator"].grant_invoke(coord_agent_role)
        _grant_bedrock_invoke(functions["coordinator"], "Coordinator")

        coord_agent = bedrock.CfnAgent(
            self, "CoordinatorAgent",
            agent_name="aria-coordinator-agent",
            description="ARIA coordinator — runs specialist agents in parallel and synthesizes one recommendation card",
            agent_resource_role_arn=coord_agent_role.role_arn,
            foundation_model=SONNET_MODEL,
            instruction=(
                "You are ARIA's coordinator in a live 911 emergency dispatch system. "
                "Your job is to orchestrate specialist agents and synthesize their outputs into "
                "a single actionable recommendation card for the dispatcher. "
                "You MUST call synthesize_recommendation for every incident — never respond without calling it first. "
                "After calling it, return ONLY the structured recommendation card JSON. No prose."
            ),
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="CoordinatorActions",
                    description="Run specialist agents in parallel and synthesize results into one recommendation card",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=functions["coordinator"].function_arn,
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="synthesize_recommendation",
                                description=(
                                    "Invoke navigation, medical, and hazmat specialist agents concurrently "
                                    "then synthesize their results into a unified dispatcher recommendation card"
                                ),
                                parameters={
                                    "incident_id": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="Unique incident identifier",
                                        required=True,
                                    ),
                                    "context_so_far": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="911 call transcript accumulated so far",
                                        required=True,
                                    ),
                                    "trigger_reason": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="What triggered coordination (e.g. location_detected, medical_keyword)",
                                        required=False,
                                    ),
                                },
                            ),
                        ],
                    ),
                ),
            ],
            auto_prepare=True,
        )

        # ── Report Agent ───────────────────────────────────────────────────────
        report_agent_role = _agent_role("ReportAgent")
        functions["report"].grant_invoke(report_agent_role)
        _grant_bedrock_invoke(functions["report"], "Report")

        report_agent = bedrock.CfnAgent(
            self, "ReportAgent",
            agent_name="aria-report-agent",
            description="ARIA report agent — generates professional after-action reports for closed incidents",
            agent_resource_role_arn=report_agent_role.role_arn,
            foundation_model=SONNET_MODEL,
            instruction=(
                "You are ARIA's after-action report specialist. "
                "Your job is to generate a professional, factual after-action report for a closed 911 incident. "
                "You MUST call generate_after_action_report for every request — never respond without calling it. "
                "After calling it, return the report URL and confirmation. No additional commentary."
            ),
            action_groups=[
                bedrock.CfnAgent.AgentActionGroupProperty(
                    action_group_name="ReportActions",
                    description="Generate structured after-action report for a closed incident",
                    action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
                        lambda_=functions["report"].function_arn,
                    ),
                    function_schema=bedrock.CfnAgent.FunctionSchemaProperty(
                        functions=[
                            bedrock.CfnAgent.FunctionProperty(
                                name="generate_after_action_report",
                                description=(
                                    "Read the incident record from DynamoDB, generate a structured JSON report "
                                    "and an AI-authored markdown narrative, and write both to S3"
                                ),
                                parameters={
                                    "incident_id": bedrock.CfnAgent.ParameterDetailProperty(
                                        type="string",
                                        description="Unique incident identifier to generate the report for",
                                        required=True,
                                    ),
                                },
                            ),
                        ],
                    ),
                ),
            ],
            auto_prepare=True,
        )

        # TSTALIASID is Bedrock's built-in alias that routes to DRAFT — always available,
        # no CfnAgentAlias resource needed. auto_prepare=True keeps DRAFT current on deploy.
        return {
            "navigation_agent_id": nav_agent.attr_agent_id,
            "navigation_alias_id": "TSTALIASID",
            "medical_agent_id": med_agent.attr_agent_id,
            "medical_alias_id": "TSTALIASID",
            "hazmat_agent_id": haz_agent.attr_agent_id,
            "hazmat_alias_id": "TSTALIASID",
            "coordinator_agent_id": coord_agent.attr_agent_id,
            "coordinator_alias_id": "TSTALIASID",
            "report_agent_id": report_agent.attr_agent_id,
            "report_alias_id": "TSTALIASID",
        }

    # ─── REST API ────────────────────────────────────────────────────────────

    def _create_rest_api(self, functions: dict) -> apigw.RestApi:
        api = apigw.RestApi(
            self, "AriaRestApi",
            rest_api_name="aria-api",
            description="ARIA REST API",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                logging_level=apigw.MethodLoggingLevel.INFO,
                metrics_enabled=True,
                throttling_burst_limit=50,
                throttling_rate_limit=100,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
            ),
        )

        def _integration(fn: lambda_.Function) -> apigw.LambdaIntegration:
            return apigw.LambdaIntegration(fn, proxy=True)

        session = api.root.add_resource("session")
        session.add_resource("start").add_method("POST", _integration(functions["ingest"]))
        session.add_resource("presign").add_method("POST", _integration(functions["ingest"]))

        session_id = session.add_resource("{id}")
        session_id.add_resource("approve").add_method("POST", _integration(functions["coordinator"]))
        session_id.add_resource("override").add_method("POST", _integration(functions["coordinator"]))
        session_id.add_resource("status").add_method("GET", _integration(functions["ingest"]))

        api.root.add_resource("hospital").add_method("POST", _integration(functions["mock_hospital"]))

        return api

    # ─── WebSocket API ───────────────────────────────────────────────────────

    def _create_websocket_api(self, functions: dict) -> apigwv2.CfnApi:
        ws_api = apigwv2.CfnApi(
            self, "AriaWebSocketApi",
            name="aria-ws",
            protocol_type="WEBSOCKET",
            route_selection_expression="$request.body.action",
        )

        for fn_key in ["ws_connect", "ws_disconnect", "ws_default"]:
            functions[fn_key].add_permission(
                f"WsApiGateway{fn_key}",
                principal=iam.ServicePrincipal("apigateway.amazonaws.com"),
                action="lambda:InvokeFunction",
                source_arn=f"arn:aws:execute-api:{self.region}:{self.account}:{ws_api.ref}/*/*",
            )

        connect_int = apigwv2.CfnIntegration(
            self, "WsConnectIntegration",
            api_id=ws_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=f"arn:aws:apigateway:{self.region}:lambda:path/2015-03-31/functions/{functions['ws_connect'].function_arn}/invocations",
        )
        apigwv2.CfnRoute(self, "WsConnectRoute", api_id=ws_api.ref,
            route_key="$connect", authorization_type="NONE",
            target=f"integrations/{connect_int.ref}")

        disconnect_int = apigwv2.CfnIntegration(
            self, "WsDisconnectIntegration",
            api_id=ws_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=f"arn:aws:apigateway:{self.region}:lambda:path/2015-03-31/functions/{functions['ws_disconnect'].function_arn}/invocations",
        )
        apigwv2.CfnRoute(self, "WsDisconnectRoute", api_id=ws_api.ref,
            route_key="$disconnect", authorization_type="NONE",
            target=f"integrations/{disconnect_int.ref}")

        default_int = apigwv2.CfnIntegration(
            self, "WsDefaultIntegration",
            api_id=ws_api.ref,
            integration_type="AWS_PROXY",
            integration_uri=f"arn:aws:apigateway:{self.region}:lambda:path/2015-03-31/functions/{functions['ws_default'].function_arn}/invocations",
        )
        apigwv2.CfnRoute(self, "WsDefaultRoute", api_id=ws_api.ref,
            route_key="$default", authorization_type="NONE",
            target=f"integrations/{default_int.ref}")

        apigwv2.CfnStage(self, "WsStage", api_id=ws_api.ref,
            stage_name="prod", auto_deploy=True)

        ws_endpoint = f"https://{ws_api.ref}.execute-api.{self.region}.amazonaws.com/prod"
        for fn_key in ["ingest", "stream_processor", "coordinator", "navigation", "medical", "hazmat", "verifier", "report"]:
            functions[fn_key].add_environment("WS_ENDPOINT", ws_endpoint)

        return ws_api

    # ─── CloudWatch ──────────────────────────────────────────────────────────

    def _create_cloudwatch_alarms(self, functions: dict) -> None:
        cloudwatch.Alarm(
            self, "CoordinatorLatencyAlarm",
            alarm_name="aria-coordinator-card-p95",
            alarm_description="Coordinator card P95 latency exceeded 12s",
            metric=cloudwatch.Metric(
                namespace="ARIA/Latency",
                metric_name="coordinator_card_complete_ms",
                statistic="p95",
                period=Duration.minutes(5),
            ),
            threshold=12000,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        cloudwatch.Alarm(
            self, "CoordinatorErrorAlarm",
            alarm_name="aria-coordinator-errors",
            metric=functions["coordinator"].metric_errors(period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

    # ─── Outputs ─────────────────────────────────────────────────────────────

    def _create_outputs(self, rest_api, ws_api, tables, buckets, kb_id, ds_id, guardrail_id, agent_ids: dict) -> None:
        CfnOutput(self, "RestApiUrl", value=rest_api.url, export_name="AriaRestApiUrl")
        CfnOutput(self, "WebSocketUrl",
            value=f"wss://{ws_api.ref}.execute-api.{self.region}.amazonaws.com/prod",
            export_name="AriaWebSocketUrl")
        CfnOutput(self, "IncidentsTableName", value=tables["incidents"].table_name)
        CfnOutput(self, "AriaBucketName", value=buckets["bucket"].bucket_name)
        CfnOutput(self, "BedrockKBId", value=kb_id, export_name="AriaBedrockKBId")
        CfnOutput(self, "BedrockDataSourceId", value=ds_id, export_name="AriaBedrockDataSourceId")
        CfnOutput(self, "NavigationAgentId", value=agent_ids["navigation_agent_id"], export_name="AriaNavigationAgentId")
        CfnOutput(self, "MedicalAgentId", value=agent_ids["medical_agent_id"], export_name="AriaMedicalAgentId")
        CfnOutput(self, "HazmatAgentId", value=agent_ids["hazmat_agent_id"], export_name="AriaHazmatAgentId")
        CfnOutput(self, "CoordinatorAgentId", value=agent_ids["coordinator_agent_id"], export_name="AriaCoordinatorAgentId")
        CfnOutput(self, "ReportAgentId", value=agent_ids["report_agent_id"], export_name="AriaReportAgentId")
        # All agents use TSTALIASID (Bedrock's built-in DRAFT alias) — no alias resource needed.
