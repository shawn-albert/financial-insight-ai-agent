"""
Embeddings Infrastructure for Financial Insight Agent.

This module implements the embeddings infrastructure using AWS Bedrock,
handling the synchronization and management of knowledge base data through
state machines and event processing with full observability and monitoring.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_pipes as pipes
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as sfn_tasks
from cdk_aws_lambda_powertools_layer import LambdaPowertoolsLayer
from lib.utils.constants import DOCKER_EXCLUDE_PATTERNS

from constructs import Construct


@dataclass
class EmbeddingsProps:
    """
    Properties for Embeddings construct configuration.

    Attributes:
        database: DynamoDB table for storing embeddings data
        bedrock_region: Region where Bedrock is available
        table_access_role: IAM role for table access
        document_bucket: S3 bucket for document storage
        custom_bot_project: CodeBuild project for custom bot deployment
        use_standby_replicas: Whether to use standby replicas
    """

    database: dynamodb.ITable
    bedrock_region: str
    table_access_role: iam.IRole
    document_bucket: s3.IBucket
    custom_bot_project: codebuild.IProject
    use_standby_replicas: bool


class LambdaConfig:
    """
    Shared Lambda function configuration.

    This class centralizes Lambda configuration including monitoring,
    insights, logging and performance settings.
    """

    INSIGHTS_LAYER_ARN = (
        "arn:aws:lambda:us-east-1:580247275435:layer:LambdaInsightsExtension-Arm64:20"
    )
    ARCHITECTURE = lambda_.Architecture.ARM_64
    MEMORY_SIZE = 512
    TIMEOUT = Duration.minutes(1)
    LOG_RETENTION = logs.RetentionDays.TWO_WEEKS

    @staticmethod
    def get_lambda_defaults(scope: Construct, function_id: str) -> Dict:
        """
        Get default Lambda configuration with monitoring.

        Args:
            scope: CDK construct scope
            function_id: Function identifier for naming

        Returns:
            Dictionary of Lambda configuration options
        """
        log_group = logs.LogGroup(
            scope,
            f"{function_id}LogGroup",
            retention=LambdaConfig.LOG_RETENTION,
            removal_policy=RemovalPolicy.DESTROY,
        )

        return {
            "architecture": LambdaConfig.ARCHITECTURE,
            "memory_size": LambdaConfig.MEMORY_SIZE,
            "timeout": LambdaConfig.TIMEOUT,
            "insights_version": lambda_.LambdaInsightsVersion.from_insight_version_arn(
                LambdaConfig.INSIGHTS_LAYER_ARN
            ),
            "log_group": log_group,
            "logging_format": lambda_.LoggingFormat.JSON,
            "tracing": lambda_.Tracing.ACTIVE,
        }


class Embeddings(Construct):
    """
    Embeddings infrastructure for the Financial Insight Agent.

    This construct creates and manages embeddings resources including:
    - State machine for embeddings synchronization
    - Event processing pipeline
    - Lambda functions for embeddings operations
    - Knowledge base integration

    All Lambda functions include:
    - AWS Lambda Powertools for structured logging and tracing
    - CloudWatch Lambda Insights for enhanced monitoring
    - X-Ray tracing enabled
    - JSON log format
    - 2 week log retention
    - ARM64 architecture optimization

    Attributes:
        removal_handler: Lambda function for cleanup operations
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: EmbeddingsProps,
    ) -> None:
        """
        Initialize the Embeddings construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for embeddings
        """
        super().__init__(scope, construct_id)

        powertools_layer = LambdaPowertoolsLayer(
            self,
            "PowertoolsLayer",
            version="3.3.0",
            include_extras=True,
            compatible_architectures=[LambdaConfig.ARCHITECTURE],
        )

        lambda_env = {
            "POWERTOOLS_SERVICE_NAME": "financial-insight-embeddings",
            "POWERTOOLS_METRICS_NAMESPACE": "FinancialInsightAgent",
            "LOG_LEVEL": "INFO",
        }

        self._update_sync_status_handler = self._create_lambda(
            "UpdateSyncStatus",
            "embedding_statemachine.bedrock_knowledge_base.update_bot_status.index.handler",
            "Updates bot sync status in DynamoDB during state machine execution",
            powertools_layer,
            lambda_env,
            props,
        )

        self._fetch_stack_output_handler = self._create_lambda(
            "FetchStackOutput",
            "embedding_statemachine.bedrock_knowledge_base.fetch_stack_output.index.handler",
            "Retrieves CloudFormation outputs for knowledge base configuration",
            powertools_layer,
            lambda_env,
            props,
        )

        self._store_knowledge_base_handler = self._create_lambda(
            "StoreKnowledgeBase",
            "embedding_statemachine.bedrock_knowledge_base.store_knowledge_base_id.index.handler",
            "Stores knowledge base IDs and configurations in DynamoDB",
            powertools_layer,
            lambda_env,
            props,
        )

        self._store_guardrail_handler = self._create_lambda(
            "StoreGuardrail",
            "embedding_statemachine.guardrails.store_guardrail_arn.handler",
            "Stores guardrail configurations for knowledge base",
            powertools_layer,
            lambda_env,
            props,
        )

        self._state_machine = self._create_state_machine(props)
        self._setup_event_pipe(props)
        self._setup_removal_handler(props, powertools_layer, lambda_env)

    def _create_lambda(
        self,
        name: str,
        handler_path: str,
        description: str,
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
        props: EmbeddingsProps,
    ) -> lambda_.IFunction:
        """
        Create a Lambda function with production configuration.

        Args:
            name: Name of the Lambda function
            handler_path: Path to the handler function
            description: Function description for better observability
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common environment variables
            props: Embeddings properties

        Returns:
            Configured Lambda function with monitoring
        """
        lambda_defaults = LambdaConfig.get_lambda_defaults(self, name)

        handler_role = iam.Role(
            self,
            f"{name}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )

        handler_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[props.table_access_role.role_arn],
            )
        )

        handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:*"],
                resources=["*"],
            )
        )

        handler_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "CloudWatchLambdaInsightsExecutionRolePolicy"
            )
        )

        handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )

        return lambda_.DockerImageFunction(
            self,
            name,
            code=lambda_.DockerImageCode.from_image_asset(
                "backend",
                file="lambda.Dockerfile",
                cmd=[handler_path],
                exclude=DOCKER_EXCLUDE_PATTERNS,
            ),
            description=description,
            environment={
                **lambda_env,
                "ACCOUNT": Stack.of(self).account,
                "REGION": Stack.of(self).region,
                "BEDROCK_REGION": props.bedrock_region,
                "TABLE_NAME": props.database.table_name,
                "TABLE_ACCESS_ROLE_ARN": props.table_access_role.role_arn,
                "DOCUMENT_BUCKET": props.document_bucket.bucket_name,
            },
            layers=[powertools_layer],
            role=handler_role,
            **lambda_defaults,
        )

    def _create_state_machine(self, props: EmbeddingsProps) -> sfn.StateMachine:
        """
        Create the Step Functions state machine for embeddings synchronization.

        Args:
            props: Embeddings properties

        Returns:
            Configured Step Functions state machine
        """
        extract_first_element = sfn.Pass(
            self,
            "ExtractFirstElement",
            parameters={
                "dynamodb.$": "$[0].dynamodb",
                "eventID.$": "$[0].eventID",
                "eventName.$": "$[0].eventName",
                "eventSource.$": "$[0].eventSource",
                "eventVersion.$": "$[0].eventVersion",
                "awsRegion.$": "$[0].awsRegion",
                "eventSourceARN.$": "$[0].eventSourceARN",
            },
            result_path="$",
        )

        start_custom_bot_build = sfn_tasks.CodeBuildStartBuild(
            self,
            "StartCustomBotBuild",
            project=props.custom_bot_project,
            integration_pattern=sfn.IntegrationPattern.RUN_JOB,
            environment_variables_override={
                "PK": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": sfn.JsonPath.string_at("$.dynamodb.NewImage.PK.S"),
                },
                "SK": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": sfn.JsonPath.string_at("$.dynamodb.NewImage.SK.S"),
                },
                "DOCUMENT_BUCKET": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": props.document_bucket.bucket_name,
                },
                "KNOWLEDGE": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": sfn.JsonPath.string_at(
                        "States.JsonToString($.dynamodb.NewImage.Knowledge.M)"
                    ),
                },
                "BEDROCK_KNOWLEDGE_BASE": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": sfn.JsonPath.string_at(
                        "States.JsonToString($.dynamodb.NewImage.BedrockKnowledgeBase.M)"
                    ),
                },
                "BEDROCK_GUARDRAILS": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": sfn.JsonPath.string_at(
                        "States.JsonToString($.dynamodb.NewImage.GuardrailsParams.M)"
                    ),
                },
                "USE_STANDBY_REPLICAS": {
                    "type": codebuild.BuildEnvironmentVariableType.PLAINTEXT,
                    "value": str(props.use_standby_replicas),
                },
            },
            result_path="$.Build",
        )

        update_sync_status_running = self._create_sync_status_task(
            "UpdateSyncStatusRunning",
            "RUNNING",
        )

        update_sync_status_succeeded = self._create_sync_status_task(
            "UpdateSyncStatusSuccess",
            "SUCCEEDED",
            "Knowledge base sync succeeded",
        )

        update_sync_status_failed = sfn_tasks.LambdaInvoke(
            self,
            "UpdateSyncStatusFailed",
            lambda_function=self._update_sync_status_handler,
            payload=sfn.TaskInput.from_object(
                {
                    "cause.$": "$.Cause",
                }
            ),
            result_path=sfn.JsonPath.DISCARD,
        )

        fallback = update_sync_status_failed.next(
            sfn.Fail(
                self,
                "Fail",
                cause="Knowledge base sync failed",
                error="Knowledge base sync failed",
            )
        )

        fetch_stack_output = sfn_tasks.LambdaInvoke(
            self,
            "FetchStackOutput",
            lambda_function=self._fetch_stack_output_handler,
            payload=sfn.TaskInput.from_object(
                {
                    "pk.$": "$.dynamodb.NewImage.PK.S",
                    "sk.$": "$.dynamodb.NewImage.SK.S",
                }
            ),
            result_path="$.StackOutput",
        )

        store_knowledge_base = sfn_tasks.LambdaInvoke(
            self,
            "StoreKnowledgeBase",
            lambda_function=self._store_knowledge_base_handler,
            payload=sfn.TaskInput.from_object(
                {
                    "pk.$": "$.dynamodb.NewImage.PK.S",
                    "sk.$": "$.dynamodb.NewImage.SK.S",
                    "stack_output.$": "$.StackOutput.Payload",
                }
            ),
            result_path=sfn.JsonPath.DISCARD,
        )

        store_guardrail = sfn_tasks.LambdaInvoke(
            self,
            "StoreGuardrail",
            lambda_function=self._store_guardrail_handler,
            payload=sfn.TaskInput.from_object(
                {
                    "pk.$": "$.dynamodb.NewImage.PK.S",
                    "sk.$": "$.dynamodb.NewImage.SK.S",
                    "stack_output.$": "$.StackOutput.Payload",
                }
            ),
            result_path=sfn.JsonPath.DISCARD,
        )

        start_ingestion = sfn_tasks.CallAwsService(
            self,
            "StartIngestion",
            service="bedrock-agent",
            action="startIngestionJob",
            parameters={
                "dataSourceId": sfn.JsonPath.string_at("$.DataSourceId"),
                "knowledgeBaseId": sfn.JsonPath.string_at("$.KnowledgeBaseId"),
            },
            iam_resources=[
                f"arn:aws:bedrock:{props.bedrock_region}:{Stack.of(self).account}:knowledge-base/*",
            ],
            result_path="$.IngestionJob",
        )

        get_ingestion_status = sfn_tasks.CallAwsService(
            self,
            "GetIngestionStatus",
            service="bedrock-agent",
            action="getIngestionJob",
            parameters={
                "dataSourceId": sfn.JsonPath.string_at(
                    "$.IngestionJob.ingestionJob.dataSourceId"
                ),
                "knowledgeBaseId": sfn.JsonPath.string_at(
                    "$.IngestionJob.ingestionJob.knowledgeBaseId"
                ),
                "ingestionJobId": sfn.JsonPath.string_at(
                    "$.IngestionJob.ingestionJob.ingestionJobId"
                ),
            },
            iam_resources=[
                f"arn:aws:bedrock:{props.bedrock_region}:{Stack.of(self).account}:knowledge-base/*",
            ],
            result_path="$.IngestionJob",
        )

        wait_state = sfn.Wait(
            self,
            "WaitForIngestion",
            time=sfn.WaitTime.duration(Duration.seconds(3)),
        )

        check_ingestion_status = sfn.Choice(self, "CheckIngestionStatus")
        check_ingestion_status.when(
            sfn.Condition.string_equals(
                "$.IngestionJob.ingestionJob.status",
                "COMPLETE",
            ),
            sfn.Pass(self, "IngestionComplete"),
        ).when(
            sfn.Condition.string_equals(
                "$.IngestionJob.ingestionJob.status",
                "FAILED",
            ),
            update_sync_status_failed.next(
                sfn.Fail(
                    self,
                    "IngestionFailed",
                    cause="Ingestion job failed",
                    error="Ingestion job failed",
                )
            ),
        ).otherwise(wait_state.next(get_ingestion_status))

        map_ingestion = sfn.Map(
            self,
            "MapIngestion",
            input_path="$.StackOutput.Payload",
            result_path=sfn.JsonPath.DISCARD,
            max_concurrency=1,
        ).iterator(
            start_ingestion.next(get_ingestion_status).next(check_ingestion_status)
        )

        definition = (
            extract_first_element.next(update_sync_status_running)
            .next(start_custom_bot_build)
            .next(fetch_stack_output)
            .next(store_knowledge_base)
            .next(store_guardrail)
            .next(map_ingestion)
            .next(update_sync_status_succeeded)
        )

        start_custom_bot_build.add_catch(fallback)
        fetch_stack_output.add_catch(fallback)
        store_knowledge_base.add_catch(fallback)
        store_guardrail.add_catch(fallback)

        return sfn.StateMachine(
            self,
            "StateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
        )

    def _setup_event_pipe(self, props: EmbeddingsProps) -> None:
        """
        Set up EventBridge Pipe for DynamoDB stream processing.

        Args:
            props: Embeddings properties
        """
        pipe_log_group = logs.LogGroup(
            self,
            "PipeLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
            retention=logs.RetentionDays.ONE_WEEK,
        )

        pipe_role = iam.Role(
            self,
            "PipeRole",
            assumed_by=iam.ServicePrincipal("pipes.amazonaws.com"),
        )

        pipe_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:DescribeStream",
                    "dynamodb:GetRecords",
                    "dynamodb:GetShardIterator",
                    "dynamodb:ListStreams",
                ],
                resources=[props.database.table_stream_arn],
            )
        )

        pipe_role.add_to_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[self._state_machine.state_machine_arn],
            )
        )

        pipe_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[pipe_log_group.log_group_arn],
            )
        )

        pipes.CfnPipe(
            self,
            "Pipe",
            source=props.database.table_stream_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                dynamo_db_stream_parameters=pipes.CfnPipe.DynamoDBStreamParametersProperty(
                    batch_size=1,
                    starting_position="LATEST",
                    maximum_retry_attempts=1,
                ),
                filter_criteria=pipes.CfnPipe.FilterCriteriaProperty(
                    filters=[
                        pipes.CfnPipe.FilterProperty(
                            pattern='{"dynamodb":{"NewImage":{"SyncStatus":{"S":[{"prefix":"QUEUED"}]}}}}'
                        )
                    ],
                ),
            ),
            target=self._state_machine.state_machine_arn,
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                step_function_state_machine_parameters=pipes.CfnPipe.StepFunctionStateMachineParametersProperty(
                    invocation_type="FIRE_AND_FORGET",
                ),
            ),
            log_configuration=pipes.CfnPipe.PipeLogConfigurationProperty(
                cloudwatch_logs_log_destination=pipes.CfnPipe.CloudwatchLogsLogDestinationProperty(
                    log_group_arn=pipe_log_group.log_group_arn,
                ),
                level="INFO",
            ),
            role_arn=pipe_role.role_arn,
        )

    def _setup_removal_handler(
        self,
        props: EmbeddingsProps,
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
    ) -> None:
        """
        Set up handler for resource removal cleanup.

        Args:
            props: Embeddings properties
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common environment variables
        """
        removal_role = iam.Role(
            self,
            "RemovalHandlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )

        removal_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        removal_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[props.table_access_role.role_arn],
            )
        )

        removal_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResource",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:DeleteStack",
                ],
                resources=["*"],
            )
        )

        props.database.grant_stream_read(removal_role)
        props.document_bucket.grant_read_write(removal_role)

        self.removal_handler = lambda_.DockerImageFunction(
            self,
            "BotRemovalHandler",
            code=lambda_.DockerImageCode.from_image_asset(
                "backend",
                file="lambda.Dockerfile",
                cmd=["app.bot_remove.handler"],
                exclude=DOCKER_EXCLUDE_PATTERNS,
            ),
            architecture=lambda_.Architecture.ARM_64,
            timeout=Duration.minutes(1),
            environment={
                **lambda_env,
                "ACCOUNT": Stack.of(self).account,
                "REGION": Stack.of(self).region,
                "BEDROCK_REGION": props.bedrock_region,
                "TABLE_NAME": props.database.table_name,
                "TABLE_ACCESS_ROLE_ARN": props.table_access_role.role_arn,
                "DOCUMENT_BUCKET": props.document_bucket.bucket_name,
            },
            layers=[powertools_layer],
            role=removal_role,
        )

        self.removal_handler.add_event_source(
            lambda_.DynamoEventSource(
                props.database,
                starting_position=lambda_.StartingPosition.TRIM_HORIZON,
                batch_size=1,
                retry_attempts=2,
                filters=[
                    lambda_.FilterCriteria.filter(
                        {"eventName": lambda_.FilterRule.is_equal("REMOVE")}
                    )
                ],
            )
        )

    def _create_sync_status_task(
        self,
        id: str,
        sync_status: str,
        sync_status_reason: Optional[str] = None,
        last_exec_id_path: Optional[str] = None,
    ) -> sfn_tasks.LambdaInvoke:
        """
        Create a Lambda task for updating sync status.

        Args:
            id: Task identifier
            sync_status: Status to set
            sync_status_reason: Optional reason for status
            last_exec_id_path: Optional path to execution ID

        Returns:
            Lambda invoke task for Step Functions
        """
        payload = {
            "pk.$": "$.dynamodb.NewImage.PK.S",
            "sk.$": "$.dynamodb.NewImage.SK.S",
            "sync_status": sync_status,
            "sync_status_reason": sync_status_reason or "",
        }

        if last_exec_id_path:
            payload["last_exec_id.$"] = last_exec_id_path

        return sfn_tasks.LambdaInvoke(
            self,
            id,
            lambda_function=self._update_sync_status_handler,
            payload=sfn.TaskInput.from_object(payload),
            result_path=sfn.JsonPath.DISCARD,
        )
