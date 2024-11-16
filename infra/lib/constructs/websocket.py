"""
WebSocket Construct Implementation for Financial Insight Agent.

This module implements the WebSocket infrastructure using API Gateway v2 WebSocket APIs
for real-time communication, particularly for streaming responses from the LLM.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3

from constructs import Construct

project_root = Path(__file__).parent.parent.parent
from lib.constants.docker import DOCKER_EXCLUDE_PATTERNS

from .auth import Auth


@dataclass
class WebSocketProps:
    """
    Properties for WebSocket construct configuration.

    Attributes:
        database: DynamoDB table for data storage
        auth: Authentication construct instance
        bedrock_region: Region for Bedrock services
        table_access_role: IAM role for table access
        websocket_session_table: DynamoDB table for session management
        document_bucket: S3 bucket for document storage
        large_message_bucket: S3 bucket for large messages
        access_log_bucket: S3 bucket for access logs
        enable_mistral: Whether Mistral model support is enabled
        enable_bedrock_cross_region_inference: Enable cross-region inference
    """

    database: dynamodb.ITable
    auth: Auth
    bedrock_region: str
    table_access_role: iam.IRole
    websocket_session_table: dynamodb.ITable
    document_bucket: s3.IBucket
    large_message_bucket: s3.IBucket
    access_log_bucket: Optional[s3.IBucket]
    enable_mistral: bool
    enable_bedrock_cross_region_inference: bool


class WebSocket(Construct):
    """
    WebSocket infrastructure for the Financial Insight Agent.

    This construct creates and manages WebSocket API resources including:
    - WebSocket API Gateway
    - Lambda function for connection handling
    - Session management
    - Real-time message processing

    Attributes:
        web_socket_api: WebSocket API Gateway instance
        handler: Lambda function for connection handling
        default_stage_name: Name of the default API stage
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: WebSocketProps,
    ) -> None:
        """
        Initialize the WebSocket construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for the WebSocket
        """
        super().__init__(scope, construct_id)
        self.default_stage_name = "dev"

        large_payload_bucket = s3.Bucket(
            self,
            "LargePayloadSupportBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            auto_delete_objects=True,
            server_access_logs_bucket=props.access_log_bucket,
            server_access_logs_prefix="LargePayloadSupportBucket",
            removal_policy=RemovalPolicy.DESTROY,
        )

        handler_role = self._create_handler_role(props, large_payload_bucket)
        self.handler = self._create_handler(props, handler_role, large_payload_bucket)
        self.web_socket_api = self._create_websocket_api()

        CfnOutput(
            self,
            "WebSocketEndpoint",
            value=self.api_endpoint,
            description="WebSocket API endpoint URL",
        )

    def _create_handler_role(
        self,
        props: WebSocketProps,
        large_payload_bucket: s3.IBucket,
    ) -> iam.Role:
        """
        Create the IAM role for the Lambda handler.

        Args:
            props: WebSocket configuration properties
            large_payload_bucket: S3 bucket for large payloads

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

        large_payload_bucket.grant_read(handler_role)
        props.websocket_session_table.grant_read_write_data(handler_role)
        props.large_message_bucket.grant_read_write(handler_role)
        props.document_bucket.grant_read(handler_role)

        return handler_role

    def _create_handler(
        self,
        props: WebSocketProps,
        handler_role: iam.Role,
        large_payload_bucket: s3.IBucket,
    ) -> lambda_.IFunction:
        """
        Create the Lambda function handler for WebSocket connections.

        Args:
            props: WebSocket configuration properties
            handler_role: IAM role for the handler
            large_payload_bucket: S3 bucket for large payloads

        Returns:
            Lambda function configured for WebSocket handling
        """
        return lambda_.DockerImageFunction(
            self,
            "Handler",
            code=lambda_.DockerImageCode.from_image_asset(
                "../backend",
                file="lambda.Dockerfile",
                exclude=DOCKER_EXCLUDE_PATTERNS,
            ),
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "ACCOUNT": Stack.of(self).account,
                "REGION": Stack.of(self).region,
                "USER_POOL_ID": props.auth.user_pool.user_pool_id,
                "CLIENT_ID": props.auth.client.user_pool_client_id,
                "BEDROCK_REGION": props.bedrock_region,
                "TABLE_NAME": props.database.table_name,
                "TABLE_ACCESS_ROLE_ARN": props.table_access_role.role_arn,
                "LARGE_MESSAGE_BUCKET": props.large_message_bucket.bucket_name,
                "LARGE_PAYLOAD_SUPPORT_BUCKET": large_payload_bucket.bucket_name,
                "WEBSOCKET_SESSION_TABLE_NAME": props.websocket_session_table.table_name,
                "ENABLE_MISTRAL": str(props.enable_mistral),
                "ENABLE_BEDROCK_CROSS_REGION_INFERENCE": str(
                    props.enable_bedrock_cross_region_inference
                ),
            },
            role=handler_role,
        )

    def _create_websocket_api(self) -> apigwv2.WebSocketApi:
        """
        Create the WebSocket API Gateway.

        Returns:
            Configured WebSocket API Gateway instance
        """
        websocket_api = apigwv2.WebSocketApi(
            self,
            "WebSocketApi",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration(
                    "ConnectIntegration",
                    self.handler,
                ),
            ),
        )

        route = websocket_api.add_route(
            "$default",
            integration=integrations.WebSocketLambdaIntegration(
                "DefaultIntegration",
                self.handler,
            ),
        )

        stage = apigwv2.WebSocketStage(
            self,
            "WebSocketStage",
            web_socket_api=websocket_api,
            stage_name=self.default_stage_name,
            auto_deploy=True,
        )

        websocket_api.grant_manage_connections(self.handler)

        apigwv2.CfnRouteResponse(
            self,
            "RouteResponse",
            api_id=websocket_api.api_id,
            route_id=route.route_id,
            route_response_key="$default",
        )

        return websocket_api

    @property
    def api_endpoint(self) -> str:
        """
        Get the full WebSocket API endpoint URL.

        Returns:
            WebSocket endpoint URL including stage name
        """
        return f"{self.web_socket_api.api_endpoint}/{self.default_stage_name}"
