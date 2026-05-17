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
)
from constructs import Construct


class AriaStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        tables = self._create_dynamodb_tables()
        buckets = self._create_s3_buckets()
        roles = self._create_iam_roles(tables, buckets)
        functions = self._create_lambda_functions(roles, tables, buckets)
        rest_api = self._create_rest_api(functions)
        ws_api = self._create_websocket_api(functions)
        self._create_cloudwatch_alarms(functions)
        self._create_outputs(rest_api, ws_api, tables, buckets)

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
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        units = dynamodb.Table(
            self, "UnitsTable",
            table_name="aria-units",
            partition_key=dynamodb.Attribute(name="unit_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="status", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery=True,
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
            point_in_time_recovery=True,
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
        tables["incidents"].grant_write_data(ingest_role)
        buckets["bucket"].grant_write(ingest_role)
        ingest_role.add_to_policy(iam.PolicyStatement(
            actions=["transcribe:StartStreamTranscription"],
            resources=["*"],
        ))
        ingest_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{self.region}:{self.account}:function:aria-stream-processor*"],
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
            actions=["bedrock:Retrieve"],
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
            actions=["bedrock:Retrieve"],
            resources=["*"],
        ))
        hazmat_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*"],
        ))

        mock_hospital_role = _role("mock-hospital")
        tables["hospitals"].grant_read_write_data(mock_hospital_role)

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

        return {
            "ingest": ingest_role,
            "stream_processor": stream_role,
            "coordinator": coordinator_role,
            "navigation": navigation_role,
            "medical": medical_role,
            "hazmat": hazmat_role,
            "mock_hospital": mock_hospital_role,
            "report": report_role,
            "ws_connect": ws_connect_role,
            "ws_disconnect": ws_disconnect_role,
        }

    # ─── Lambda Functions ────────────────────────────────────────────────────

    def _create_lambda_functions(self, roles: dict, tables: dict, buckets: dict) -> dict:
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
                code=lambda_.Code.from_asset(f"../backend/lambdas/{name}"),
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
            extra_env={"STREAM_PROCESSOR_FUNCTION": "aria-stream-processor"})

        stream_processor = _fn("StreamProcessor", "aria-stream-processor", roles["stream_processor"],
            extra_env={
                "COORDINATOR_FUNCTION": "aria-coordinator",
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
            })

        coordinator = _fn("Coordinator", "aria-coordinator", roles["coordinator"],
            extra_env={
                "NAVIGATION_FUNCTION": "aria-navigation-tool",
                "MEDICAL_FUNCTION": "aria-medical-tool",
                "HAZMAT_FUNCTION": "aria-hazmat-tool",
                "REPORT_FUNCTION": "aria-report",
            },
            memory=1024, timeout=300)

        navigation = _fn("Navigation", "aria-navigation-tool", roles["navigation"],
            extra_env={"GOOGLE_MAPS_API_KEY": "REPLACE_ME"})

        medical = _fn("Medical", "aria-medical-tool", roles["medical"],
            extra_env={
                "MOCK_HOSPITAL_FUNCTION": "aria-mock-hospital",
                "BEDROCK_KB_ID": "REPLACE_ME",
            })

        hazmat = _fn("Hazmat", "aria-hazmat-tool", roles["hazmat"],
            extra_env={"BEDROCK_KB_ID": "REPLACE_ME"})

        mock_hospital = _fn("MockHospital", "aria-mock-hospital", roles["mock_hospital"])

        report = _fn("Report", "aria-report", roles["report"],
            memory=1024, timeout=300)

        ws_connect = lambda_.Function(
            self, "WsConnectFunction",
            function_name="aria-ws-connect",
            runtime=lambda_.Runtime.PYTHON_3_12,
            code=lambda_.Code.from_asset("../backend/lambdas/aria-ws-connect"),
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
            code=lambda_.Code.from_asset("../backend/lambdas/aria-ws-disconnect"),
            handler="handler.lambda_handler",
            memory_size=256,
            timeout=Duration.seconds(10),
            role=roles["ws_disconnect"],
            environment={**common_env, "POWERTOOLS_SERVICE_NAME": "aria-ws-disconnect"},
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
            "report": report,
            "ws_connect": ws_connect,
            "ws_disconnect": ws_disconnect,
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

        for fn_key in ["ws_connect", "ws_disconnect"]:
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

        apigwv2.CfnStage(self, "WsStage", api_id=ws_api.ref,
            stage_name="prod", auto_deploy=True)

        ws_endpoint = f"https://{ws_api.ref}.execute-api.{self.region}.amazonaws.com/prod"
        for fn_key in ["stream_processor", "coordinator", "navigation", "medical", "hazmat", "report"]:
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

    def _create_outputs(self, rest_api, ws_api, tables, buckets) -> None:
        CfnOutput(self, "RestApiUrl", value=rest_api.url, export_name="AriaRestApiUrl")
        CfnOutput(self, "WebSocketUrl",
            value=f"wss://{ws_api.ref}.execute-api.{self.region}.amazonaws.com/prod",
            export_name="AriaWebSocketUrl")
        CfnOutput(self, "IncidentsTableName", value=tables["incidents"].table_name)
        CfnOutput(self, "AriaBucketName", value=buckets["bucket"].bucket_name)
