"""
Frontend Construct Implementation for Financial Insight Agent.

This module creates and manages frontend infrastructure using AWS CloudFront
for content delivery and S3 for static web hosting. It handles configuration
of a React frontend application, SSL, WAF, and deployment automation.
"""

from dataclasses import dataclass
from typing import List, Optional

from aws_cdk import BundlingOptions, Duration, RemovalPolicy, Stack, aws_lambda
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment

from constructs import Construct

from .auth import Auth


@dataclass
class FrontendProps:
    """
    Configuration properties for the frontend construct.

    Attributes:
        access_log_bucket: S3 bucket for CloudFront access logs.
        web_acl_id: Web ACL ID for WAF protection.
        enable_mistral: Whether to enable Mistral support.
        enable_ipv6: Whether to enable IPv6.
    """

    access_log_bucket: Optional[s3.IBucket]
    web_acl_id: str
    enable_mistral: bool
    enable_ipv6: bool


class Frontend(Construct):
    """
    Frontend infrastructure construct.

    This construct sets up an S3 bucket and CloudFront distribution for hosting
    a React frontend application, including WAF integration and logging.

    Attributes:
        asset_bucket: S3 bucket used for static asset storage.
        distribution: CloudFront distribution for delivering the assets.
    """

    asset_bucket: s3.Bucket
    distribution: cloudfront.Distribution

    def __init__(
        self, scope: Construct, construct_id: str, props: FrontendProps
    ) -> None:
        """
        Initialize the Frontend construct.

        Args:
            scope: The scope of this construct.
            construct_id: Identifier for the construct.
            props: Configuration properties for the frontend.
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

        origin_identity = cloudfront.OriginAccessIdentity(self, "OriginAccessIdentity")

        self.asset_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{self.asset_bucket.bucket_arn}/*"],
                principals=[
                    iam.CanonicalUserPrincipal(
                        origin_identity.cloud_front_origin_access_identity_s3_canonical_user_id
                    )
                ],
            )
        )

        cache_policy = cloudfront.CachePolicy(
            self,
            "CachePolicy",
            cache_policy_name="CustomCachePolicy",
            default_ttl=Duration.days(1),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.days(365),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    self.asset_bucket, origin_access_identity=origin_identity
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cache_policy,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
            ],
            web_acl_id=props.web_acl_id,
            enable_ipv6=props.enable_ipv6,
            log_bucket=props.access_log_bucket,
            log_file_prefix="Frontend/",
        )

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
            backend_api_endpoint: API endpoint for the backend.
            websocket_api_endpoint: WebSocket endpoint.
            user_pool_domain_prefix: Cognito domain prefix.
            enable_mistral: Enable Mistral support.
            auth: Auth instance for Cognito configurations.
            identity_providers: List of identity provider configurations.
        """
        region = Stack.of(auth.user_pool).region
        cognito_domain = f"{user_pool_domain_prefix}.auth.{region}.amazoncognito.com"

        build_env = {
            "VITE_APP_API_ENDPOINT": backend_api_endpoint,
            "VITE_APP_WS_ENDPOINT": websocket_api_endpoint,
            "VITE_APP_USER_POOL_ID": auth.user_pool.user_pool_id,
            "VITE_APP_USER_POOL_CLIENT_ID": auth.client.user_pool_client_id,
            "VITE_APP_ENABLE_MISTRAL": str(enable_mistral).lower(),
            "VITE_APP_REGION": region,
            "VITE_APP_USE_STREAMING": "true",
        }

        if identity_providers:
            build_env.update(
                {
                    "VITE_APP_REDIRECT_SIGNIN_URL": self.get_origin(),
                    "VITE_APP_REDIRECT_SIGNOUT_URL": self.get_origin(),
                    "VITE_APP_COGNITO_DOMAIN": cognito_domain,
                }
            )

        bundling_docker_image = aws_lambda.Runtime.NODEJS_18_X.bundling_image

        source = s3_deployment.Source.asset(
            path="../frontend",
            bundling=BundlingOptions(
                image=bundling_docker_image,
                command=[
                    "bash",
                    "-c",
                    "npm ci && npm run build && cp -r dist/* /asset-output/",
                ],
                environment=build_env,
                user="root",
            ),
        )

        s3_deployment.BucketDeployment(
            self,
            "FrontendDeployment",
            sources=[source],
            destination_bucket=self.asset_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
            memory_limit=512,
            prune=True,
            retain_on_delete=False,
        )

    def get_origin(self) -> str:
        """
        Retrieve the frontend origin URL.

        Returns:
            The CloudFront distribution domain name.
        """
        return f"https://{self.distribution.distribution_domain_name}"
