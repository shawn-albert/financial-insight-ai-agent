"""
Financial Insight Agent Main Stack Implementation.

This module implements the main application stack for the Financial Insight Agent,
coordinating all the components including authentication, API, database, and frontend
resources.
"""

from dataclasses import dataclass
from typing import List

from aws_cdk import CfnOutput, RemovalPolicy, Stack, StackProps
from aws_cdk import aws_s3 as s3
from constructs import Construct
from lib.constructs.api import Api, ApiProps
from lib.constructs.auth import Auth, AuthProps
from lib.constructs.database import Database, DatabaseProps
from lib.constructs.frontend import Frontend, FrontendProps
from lib.constructs.websocket import WebSocket, WebSocketProps


@dataclass
class FinancialInsightAgentStackProps(StackProps):
    """
    Properties for the main Financial Insight Agent Stack.

    Attributes:
        bedrock_region: Region where Bedrock is available
        web_acl_id: ID of the WAF ACL for protection
        enable_ipv6: Whether IPv6 support is enabled
        identity_providers: List of identity providers for authentication
        user_pool_domain_prefix: Prefix for Cognito domain
        allowed_signup_email_domains: List of allowed email domains for signup
        auto_join_user_groups: Groups users automatically join
        enable_mistral: Whether Mistral model support is enabled
        self_signup_enabled: Whether self-signup is allowed
        document_bucket: S3 bucket for storing documents
        use_standby_replicas: Whether to use standby replicas
        enable_bedrock_cross_region_inference: Enable cross-region Bedrock
    """

    bedrock_region: str
    web_acl_id: str
    enable_ipv6: bool
    identity_providers: List[dict]
    user_pool_domain_prefix: str
    allowed_signup_email_domains: List[str]
    auto_join_user_groups: List[str]
    enable_mistral: bool
    self_signup_enabled: bool
    document_bucket: s3.IBucket
    use_standby_replicas: bool
    enable_bedrock_cross_region_inference: bool


class FinancialInsightAgentStack(Stack):
    """
    Main stack for the Financial Insight Agent application.

    This stack coordinates all the components of the application including:
    - Authentication and authorization
    - API and WebSocket endpoints
    - Database resources
    - Frontend deployment
    - Document storage
    - Analytics and monitoring

    Attributes:
        access_log_bucket: Central bucket for access logging
        frontend: Frontend deployment construct
        auth: Authentication construct
        database: Database construct
        api: API construct
        websocket: WebSocket construct
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bedrock_region: str,
        web_acl_id: str,
        enable_ipv6: bool,
        identity_providers: List[dict],
        user_pool_domain_prefix: str,
        allowed_signup_email_domains: List[str],
        auto_join_user_groups: List[str],
        enable_mistral: bool,
        self_signup_enabled: bool,
        document_bucket: s3.IBucket,
        use_standby_replicas: bool,
        enable_bedrock_cross_region_inference: bool,
        **kwargs,
    ) -> None:
        """
        Initialize the Financial Insight Agent Stack.

        Args:
            scope: The CDK scope for resource creation
            construct_id: Unique identifier for the stack
            bedrock_region: Region where Bedrock is available
            web_acl_id: ID of the WAF ACL for protection
            enable_ipv6: Whether IPv6 support is enabled
            identity_providers: List of identity providers for authentication
            user_pool_domain_prefix: Prefix for Cognito domain
            allowed_signup_email_domains: List of allowed email domains for signup
            auto_join_user_groups: Groups users automatically join
            enable_mistral: Whether Mistral model support is enabled
            self_signup_enabled: Whether self-signup is allowed
            document_bucket: S3 bucket for storing documents
            use_standby_replicas: Whether to use standby replicas
            enable_bedrock_cross_region_inference: Enable cross-region Bedrock
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.access_log_bucket = s3.Bucket(
            self,
            "AccessLogBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            auto_delete_objects=True,
        )

        self.frontend = Frontend(
            self,
            "Frontend",
            FrontendProps(
                access_log_bucket=self.access_log_bucket,
                web_acl_id=web_acl_id,
                enable_mistral=enable_mistral,
                enable_ipv6=enable_ipv6,
            ),
        )

        self.auth = Auth(
            self,
            "Auth",
            AuthProps(
                origin=self.frontend.get_origin(),
                user_pool_domain_prefix=user_pool_domain_prefix,
                identity_providers=identity_providers,
                allowed_signup_email_domains=allowed_signup_email_domains,
                auto_join_user_groups=auto_join_user_groups,
                self_signup_enabled=self_signup_enabled,
            ),
        )

        self.database = Database(
            self,
            "Database",
            DatabaseProps(point_in_time_recovery=True),
        )

        large_message_bucket = s3.Bucket(
            self,
            "LargeMessageBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            auto_delete_objects=True,
            server_access_logs_bucket=self.access_log_bucket,
            server_access_logs_prefix="LargeMessageBucket",
        )

        self.api = Api(
            self,
            "Api",
            ApiProps(
                database=self.database.table,
                auth=self.auth,
                bedrock_region=bedrock_region,
                table_access_role=self.database.table_access_role,
                document_bucket=document_bucket,
                large_message_bucket=large_message_bucket,
                enable_mistral=enable_mistral,
            ),
        )

        self.websocket = WebSocket(
            self,
            "WebSocket",
            WebSocketProps(
                database=self.database.table,
                auth=self.auth,
                bedrock_region=bedrock_region,
                table_access_role=self.database.table_access_role,
                websocket_session_table=self.database.websocket_session_table,
                document_bucket=document_bucket,
                large_message_bucket=large_message_bucket,
                access_log_bucket=self.access_log_bucket,
                enable_mistral=enable_mistral,
                enable_bedrock_cross_region_inference=enable_bedrock_cross_region_inference,
            ),
        )

        document_bucket.grant_read_write(self.api.handler)

        self.frontend.configure_vite_app(
            backend_api_endpoint=self.api.api.api_endpoint,
            websocket_api_endpoint=self.websocket.api_endpoint,
            user_pool_domain_prefix=user_pool_domain_prefix,
            enable_mistral=enable_mistral,
            auth=self.auth,
        )

        CfnOutput(
            self,
            "DocumentBucketName",
            value=document_bucket.bucket_name,
            description="Name of the document storage bucket",
        )

        CfnOutput(
            self,
            "FrontendURL",
            value=self.frontend.get_origin(),
            description="URL of the frontend application",
        )
