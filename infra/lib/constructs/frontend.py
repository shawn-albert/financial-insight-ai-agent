"""
Frontend Construct Implementation for Financial Insight Agent.

This module implements the frontend infrastructure using CloudFront for content
delivery and S3 for static web hosting. It handles the deployment of the React
application, SSL configuration, and integration with WAF protection.
"""

from dataclasses import dataclass
from typing import List, Optional

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment

from constructs import Construct

from .auth import Auth


@dataclass
class FrontendProps:
    """
    Properties for Frontend construct configuration.

    Attributes:
        access_log_bucket: S3 bucket for access logs
        web_acl_id: ID of the WAF ACL for protection
        enable_mistral: Whether Mistral model support is enabled
        enable_ipv6: Whether IPv6 support is enabled
    """

    access_log_bucket: Optional[s3.IBucket]
    web_acl_id: str
    enable_mistral: bool
    enable_ipv6: bool


class Frontend(Construct):
    """
    Frontend infrastructure for the Financial Insight Agent.

    This construct creates and manages frontend resources including:
    - S3 bucket for static content
    - CloudFront distribution
    - Access logging
    - WAF integration
    - SSL configuration
    - React application deployment

    Attributes:
        asset_bucket: S3 bucket for static assets
        distribution: CloudFront distribution for content delivery
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: FrontendProps,
    ) -> None:
        """
        Initialize the Frontend construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for the frontend
        """
        super().__init__(scope, construct_id)

        self.asset_bucket = s3.Bucket(
            self,
            "AssetBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=props.access_log_bucket,
            server_access_logs_prefix="AssetBucket",
        )

        origin_identity = cloudfront.OriginAccessIdentity(
            self,
            "OriginAccessIdentity",
        )

        distribution_props = {
            "default_behavior": cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    self.asset_bucket,
                    origin_access_identity=origin_identity,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            "error_responses": [
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
            "web_acl_id": props.web_acl_id,
            "enable_ipv6": props.enable_ipv6,
        }

        if not self._should_skip_access_logging(Stack.of(self).region):
            distribution_props["log_bucket"] = props.access_log_bucket
            distribution_props["log_file_prefix"] = "Frontend/"

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            **distribution_props,
        )

    def get_origin(self) -> str:
        """
        Get the origin URL for the frontend application.

        Returns:
            Frontend application origin URL
        """
        return f"https://{self.distribution.distribution_domain_name}"

    def configure_vite_app(
        self,
        backend_api_endpoint: str,
        websocket_api_endpoint: str,
        user_pool_domain_prefix: str,
        enable_mistral: bool,
        auth: Auth,
        identity_providers: Optional[List[dict]] = None,
    ) -> None:
        """
        Configure and deploy the Vite React application.

        Args:
            backend_api_endpoint: URL of the backend API
            websocket_api_endpoint: URL of the WebSocket API
            user_pool_domain_prefix: Prefix for Cognito domain
            enable_mistral: Whether Mistral model is enabled
            auth: Authentication construct instance
            identity_providers: List of identity provider configurations
        """
        region = Stack.of(auth.user_pool).region
        cognito_domain = f"{user_pool_domain_prefix}.auth.{region}.amazoncognito.com"

        build_environment = {
            "VITE_APP_API_ENDPOINT": backend_api_endpoint,
            "VITE_APP_WS_ENDPOINT": websocket_api_endpoint,
            "VITE_APP_USER_POOL_ID": auth.user_pool.user_pool_id,
            "VITE_APP_USER_POOL_CLIENT_ID": auth.client.user_pool_client_id,
            "VITE_APP_ENABLE_MISTRAL": str(enable_mistral),
            "VITE_APP_REGION": region,
            "VITE_APP_USE_STREAMING": "true",
        }

        if identity_providers:
            build_environment.update(
                {
                    "VITE_APP_REDIRECT_SIGNIN_URL": self.get_origin(),
                    "VITE_APP_REDIRECT_SIGNOUT_URL": self.get_origin(),
                    "VITE_APP_COGNITO_DOMAIN": cognito_domain,
                    "VITE_APP_SOCIAL_PROVIDERS": ",".join(
                        provider["service"] for provider in identity_providers
                    ),
                    "VITE_APP_CUSTOM_PROVIDER_ENABLED": str(
                        any(
                            provider["service"] == "oidc"
                            for provider in identity_providers
                        )
                    ),
                    "VITE_APP_CUSTOM_PROVIDER_NAME": next(
                        (
                            provider["service_name"]
                            for provider in identity_providers
                            if provider["service"] == "oidc"
                        ),
                        "",
                    ),
                }
            )

        s3_deployment.BucketDeployment(
            self,
            "ReactDeployment",
            sources=[
                s3_deployment.Source.asset(
                    "../frontend",
                    bundling=s3_deployment.BundlingOptions(
                        image=s3_deployment.BundlingImage.from_asset(
                            "../frontend",
                            file="Dockerfile.build",
                        ),
                        command=[
                            "bash",
                            "-c",
                            "npm ci && npm run build && cp -r dist/* /asset-output/",
                        ],
                        environment=build_environment,
                    ),
                ),
            ],
            destination_bucket=self.asset_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
        )

        if identity_providers:
            CfnOutput(
                self,
                "CognitoDomain",
                value=cognito_domain,
                description="Cognito user pool domain",
            )

    def _should_skip_access_logging(self, region: str) -> bool:
        """
        Determine if access logging should be skipped based on region.

        CloudFront does not support access logging in certain regions.

        Args:
            region: AWS region to check

        Returns:
            True if access logging should be skipped, False otherwise
        """
        skip_logging_regions = [
            "af-south-1",
            "ap-east-1",
            "ap-south-2",
            "ap-southeast-3",
            "ap-southeast-4",
            "ca-west-1",
            "eu-south-1",
            "eu-south-2",
            "eu-central-2",
            "il-central-1",
            "me-central-1",
        ]
        return region in skip_logging_regions
