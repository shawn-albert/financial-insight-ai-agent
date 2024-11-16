"""
API Construct Implementation for Financial Insight Agent.

This module implements the primary API infrastructure using API Gateway v2 HTTP APIs
and Lambda integrations. It handles authentication, request processing, and
integrates with Bedrock for LLM capabilities.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3

from constructs import Construct

project_root = Path(__file__).parent.parent.parent
from lib.constants.docker import DOCKER_EXCLUDE_PATTERNS

from .auth import Auth
from .usage_analysis import UsageAnalysis


@dataclass
class ApiProps:
    """
    Properties for API construct configuration.

    Attributes:
        database: DynamoDB table for data storage
        auth: Authentication construct instance
        bedrock_region: Region for Bedrock services
        table_access_role: IAM role for table access
        document_bucket: S3 bucket for document storage
        large_message_bucket: S3 bucket for large messages
        enable_mistral: Whether Mistral model support is enabled
        cors_allow_origins: Optional list of allowed CORS origins
        usage_analysis: Optional usage analysis construct instance
    """

    database: dynamodb.ITable
    auth: Auth
    bedrock_region: str
    table_access_role: iam.IRole
    document_bucket: s3.IBucket
    large_message_bucket: s3.IBucket
    enable_mistral: bool
    cors_allow_origins: List[str] = field(default_factory=lambda: ["*"])
    usage_analysis: Optional[UsageAnalysis] = None


class Api(Construct):
    """
    API infrastructure for the Financial Insight Agent.

    This construct creates and manages the HTTP API, Lambda functions,
    and related resources for handling application requests. It includes:
    - HTTP API Gateway with routes
    - Lambda function for request processing
    - IAM roles and permissions
    - Integration with Bedrock
    - CORS configuration

    Attributes:
        api: HTTP API Gateway instance
        handler: Lambda function for request processing
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: ApiProps,
    ) -> None:
        """
        Initialize the API construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for the API
        """
        super().__init__(scope, construct_id)

        handler_role = self._create_handler_role(props)
        self.handler = self._create_handler(props, handler_role)
        self.api = self._create_api(props)

        CfnOutput(
            self,
            "BackendApiUrl",
            value=self.api.api_endpoint,
            description="URL of the backend API endpoint",
        )

    def _create_handler_role(self, props: ApiProps) -> iam.Role:
        """
        Create the IAM role for the Lambda handler.

        Args:
            props: API configuration properties

        Returns:
            IAM role configured with necessary permissions
        """
        handler_role = iam.Role(
            self,
            "HandlerRole",
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

        handler_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["cognito-idp:AdminGetUser"],
                resources=[props.auth.user_pool.user_pool_arn],
            )
        )

        if props.usage_analysis:
            self._add_usage_analysis_permissions(handler_role, props.usage_analysis)

        props.large_message_bucket.grant_read_write(handler_role)

        return handler_role

    def _create_handler(
        self,
        props: ApiProps,
        handler_role: iam.Role,
    ) -> lambda_.IFunction:
        """
        Create the Lambda function handler for API requests.

        Args:
            props: API configuration properties
            handler_role: IAM role for the handler

        Returns:
            Lambda function configured for API handling
        """
        return lambda_.DockerImageFunction(
            self,
            "Handler",
            code=lambda_.DockerImageCode.from_image_asset(
                "../backend",
                file="Dockerfile",
                exclude=DOCKER_EXCLUDE_PATTERNS,
            ),
            memory_size=1024,
            timeout=Duration.minutes(15),
            environment={
                "TABLE_NAME": props.database.table_name,
                "CORS_ALLOW_ORIGINS": ",".join(props.cors_allow_origins),
                "USER_POOL_ID": props.auth.user_pool.user_pool_id,
                "CLIENT_ID": props.auth.client.user_pool_client_id,
                "ACCOUNT": Stack.of(self).account,
                "REGION": Stack.of(self).region,
                "BEDROCK_REGION": props.bedrock_region,
                "TABLE_ACCESS_ROLE_ARN": props.table_access_role.role_arn,
                "DOCUMENT_BUCKET": props.document_bucket.bucket_name,
                "LARGE_MESSAGE_BUCKET": props.large_message_bucket.bucket_name,
                "ENABLE_MISTRAL": str(props.enable_mistral),
                "USAGE_ANALYSIS_DATABASE": (
                    props.usage_analysis.database.database_name
                    if props.usage_analysis
                    else ""
                ),
                "USAGE_ANALYSIS_TABLE": (
                    props.usage_analysis.ddb_export_table.table_name
                    if props.usage_analysis
                    else ""
                ),
                "USAGE_ANALYSIS_WORKGROUP": (
                    props.usage_analysis.workgroup_name if props.usage_analysis else ""
                ),
                "USAGE_ANALYSIS_OUTPUT_LOCATION": (
                    f"s3://{props.usage_analysis.result_output_bucket.bucket_name}"
                    if props.usage_analysis
                    else ""
                ),
            },
            role=handler_role,
        )

    def _create_api(self, props: ApiProps) -> apigwv2.HttpApi:
        """
        Create the HTTP API Gateway.

        Args:
            props: API configuration properties

        Returns:
            Configured HTTP API Gateway instance
        """
        api = apigwv2.HttpApi(
            self,
            "Default",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["*"],
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.HEAD,
                    apigwv2.CorsHttpMethod.OPTIONS,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.PUT,
                    apigwv2.CorsHttpMethod.PATCH,
                    apigwv2.CorsHttpMethod.DELETE,
                ],
                allow_origins=props.cors_allow_origins or ["*"],
                max_age=Duration.days(10),
            ),
        )

        authorizer = authorizers.HttpUserPoolAuthorizer(
            "Authorizer",
            props.auth.user_pool,
            user_pool_clients=[props.auth.client],
        )

        integration = integrations.HttpLambdaIntegration(
            "Integration",
            self.handler,
        )

        api.add_routes(
            path="/{proxy+}",
            integration=integration,
            methods=[
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
                apigwv2.HttpMethod.PUT,
                apigwv2.HttpMethod.PATCH,
                apigwv2.HttpMethod.DELETE,
            ],
            authorizer=authorizer,
        )

        return api

    def _add_usage_analysis_permissions(
        self,
        role: iam.Role,
        usage_analysis: UsageAnalysis,
    ) -> None:
        """
        Add usage analysis permissions to the handler role.

        Args:
            role: IAM role to modify
            usage_analysis: Usage analysis construct instance
        """
        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "athena:GetWorkGroup",
                    "athena:StartQueryExecution",
                    "athena:StopQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:GetDataCatalog",
                ],
                resources=[usage_analysis.workgroup_arn],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["glue:GetDatabase", "glue:GetDatabases"],
                resources=[
                    usage_analysis.database.database_arn,
                    usage_analysis.database.catalog_arn,
                ],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                ],
                resources=[usage_analysis.ddb_export_table.table_arn],
            )
        )

        usage_analysis.result_output_bucket.grant_read_write(role)
        usage_analysis.ddb_bucket.grant_read(role)
