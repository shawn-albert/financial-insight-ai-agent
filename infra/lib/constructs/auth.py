"""
Authentication Construct Implementation for Financial Insight Agent.

This module implements authentication and authorization using Amazon Cognito,
supporting multiple identity providers, user groups, and custom triggers for
user management with full observability and monitoring capabilities.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from aws_cdk import CfnOutput, CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_aws_lambda_powertools_layer import LambdaPowertoolsLayer

from constructs import Construct

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class AuthProps:
    """
    Properties for Authentication construct configuration.

    Attributes:
        origin: Frontend application origin URL for OAuth configuration
        user_pool_domain_prefix: Prefix for Cognito domain
        identity_providers: List of identity provider configurations
        allowed_signup_email_domains: List of allowed email domains
        auto_join_user_groups: Groups users automatically join
        self_signup_enabled: Whether self-signup is enabled
    """

    origin: str
    user_pool_domain_prefix: str
    identity_providers: List[dict]
    allowed_signup_email_domains: List[str]
    auto_join_user_groups: List[str]
    self_signup_enabled: bool


class LambdaDefaults:
    """
    Default configurations for Lambda functions.

    This class provides a centralized way to manage common Lambda function
    configurations like architecture, runtime, insights, tracing and logging.
    """

    INSIGHTS_ARN = (
        "arn:aws:lambda:us-east-1:580247275435:layer:LambdaInsightsExtension-Arm64:20"
    )
    ARCHITECTURE = lambda_.Architecture.ARM_64
    RUNTIME = lambda_.Runtime.PYTHON_3_12
    MEMORY_SIZE = 512
    TIMEOUT = Duration.minutes(5)
    LOG_RETENTION = logs.RetentionDays.TWO_WEEKS

    @staticmethod
    def get_common_config(scope: Construct, function_id: str) -> Dict:
        """
        Get common Lambda function configuration.

        Args:
            scope: CDK construct scope
            function_id: Function identifier for log group naming

        Returns:
            Dictionary containing common Lambda configuration
        """
        log_group = logs.LogGroup(
            scope,
            f"{function_id}LogGroup",
            retention=LambdaDefaults.LOG_RETENTION,
            removal_policy=RemovalPolicy.DESTROY,
        )

        return {
            "architecture": LambdaDefaults.ARCHITECTURE,
            "runtime": LambdaDefaults.RUNTIME,
            "memory_size": LambdaDefaults.MEMORY_SIZE,
            "timeout": LambdaDefaults.TIMEOUT,
            "insights_version": lambda_.LambdaInsightsVersion.from_insight_version_arn(
                LambdaDefaults.INSIGHTS_ARN
            ),
            "tracing": lambda_.Tracing.ACTIVE,
            "log_group": log_group,
            "logging_format": lambda_.LoggingFormat.JSON,
        }


class Auth(Construct):
    """
    Authentication infrastructure for the Financial Insight Agent.

    This construct creates and manages Cognito user pools, clients, and identity
    providers. It supports email domain restrictions, automatic group assignment,
    and multiple authentication providers.

    All Lambda functions include:
    - AWS Lambda Powertools for structured logging, tracing and monitoring
    - CloudWatch Lambda Insights for enhanced monitoring
    - X-Ray tracing enabled
    - JSON log format
    - 2 week log retention
    - ARM64 architecture optimization

    Attributes:
        user_pool: Cognito user pool for authentication
        client: Cognito user pool client
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: AuthProps,
    ) -> None:
        """
        Initialize the Authentication construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for authentication
        """
        super().__init__(scope, construct_id)

        if not props.user_pool_domain_prefix:
            raise ValueError("user_pool_domain_prefix must be provided")

        powertools_layer = LambdaPowertoolsLayer(
            self,
            "PowertoolsLayer",
            version="3.3.0",
            include_extras=True,
            compatible_architectures=[LambdaDefaults.ARCHITECTURE],
        )

        lambda_env = {
            "POWERTOOLS_SERVICE_NAME": "financial-insight-auth",
            "POWERTOOLS_METRICS_NAMESPACE": "FinancialInsightAgent",
            "LOG_LEVEL": "INFO",
        }

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            password_policy=cognito.PasswordPolicy(
                require_uppercase=True,
                require_symbols=True,
                require_digits=True,
                min_length=8,
            ),
            self_sign_up_enabled=props.self_signup_enabled
            and not props.identity_providers,
            sign_in_aliases=cognito.SignInAliases(
                username=False,
                email=True,
            ),
            standard_attributes={
                "email": cognito.StandardAttribute(
                    required=True,
                    mutable=True,
                )
            },
            removal_policy=RemovalPolicy.DESTROY,
        )

        client_props = self._configure_client_props(props)
        self.client = self.user_pool.add_client("Client", **client_props)

        self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=props.user_pool_domain_prefix,
            ),
        )

        if props.identity_providers:
            self._configure_identity_providers(props)

        self._create_user_groups()

        if props.auto_join_user_groups:
            self._configure_auto_join_groups(
                props.auto_join_user_groups,
                powertools_layer,
                lambda_env,
            )

        if props.allowed_signup_email_domains:
            self._configure_email_domain_check(
                props.allowed_signup_email_domains,
                powertools_layer,
                lambda_env,
            )

        self._create_outputs(props)

    def _configure_auto_join_groups(
        self,
        groups: List[str],
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
    ) -> None:
        """
        Configure automatic group assignment for new users.

        Args:
            groups: List of groups to automatically join
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common Lambda environment variables
        """
        common_config = LambdaDefaults.get_common_config(self, "AddUserToGroups")

        add_to_groups_function = lambda_.Function(
            self,
            "AddUserToGroups",
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "add_user_to_groups")
            ),
            environment={
                **lambda_env,
                "USER_POOL_ID": self.user_pool.user_pool_id,
                "AUTO_JOIN_USER_GROUPS": json.dumps(groups),
            },
            layers=[powertools_layer],
            description="Automatically adds newly confirmed users to specified Cognito user groups",
            **common_config,
        )

        add_to_groups_function.add_permission(
            "CognitoTrigger",
            principal=iam.ServicePrincipal("cognito-idp.amazonaws.com"),
            source_arn=self.user_pool.user_pool_arn,
        )

        self.user_pool.grant(
            add_to_groups_function,
            "cognito-idp:AdminAddUserToGroup",
        )

        trigger_config = LambdaDefaults.get_common_config(self, "TriggerFunction")
        trigger_function = lambda_.SingletonFunction(
            self,
            "TriggerFunction",
            uuid="a84c6122-180e-48fc-afaf-f4d65da2b370",
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "cognito_trigger")
            ),
            environment={
                **lambda_env,
                "USER_POOL_ID": self.user_pool.user_pool_id,
            },
            layers=[powertools_layer],
            description="Manages Cognito User Pool triggers via CloudFormation custom resources",
            **trigger_config,
        )

        self.user_pool.grant(
            trigger_function,
            "cognito-idp:UpdateUserPool",
            "cognito-idp:DescribeUserPool",
        )

        CustomResource(
            self,
            "CognitoTrigger",
            service_token=trigger_function.function_arn,
            properties={
                "Triggers": {
                    "PostConfirmation": add_to_groups_function.function_arn,
                    "PostAuthentication": add_to_groups_function.function_arn,
                },
            },
        )

    def _configure_email_domain_check(
        self,
        domains: List[str],
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
    ) -> None:
        """
        Configure email domain restriction for signup.

        Args:
            domains: List of allowed email domains
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common Lambda environment variables
        """
        common_config = LambdaDefaults.get_common_config(self, "CheckEmailDomain")

        check_email_function = lambda_.Function(
            self,
            "CheckEmailDomain",
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "check_email_domain")
            ),
            environment={
                **lambda_env,
                "ALLOWED_SIGN_UP_EMAIL_DOMAINS": str(domains),
            },
            layers=[powertools_layer],
            description="Validates email domains during user signup against allowlist",
            **common_config,
        )

        self.user_pool.add_trigger(
            cognito.UserPoolOperation.PRE_SIGN_UP,
            check_email_function,
        )

    def _configure_client_props(self, props: AuthProps) -> dict:
        """
        Configure Cognito user pool client properties.

        Args:
            props: Authentication properties

        Returns:
            Dictionary of client configuration properties
        """
        default_props = {
            "auth_flows": cognito.AuthFlow(
                user_password=True,
                user_srp=True,
                admin_user_password=True,
            ),
            "prevent_user_existence_errors": True,
        }

        if not props.identity_providers:
            return default_props

        return {
            **default_props,
            "o_auth": cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=True,
                ),
                callback_urls=[props.origin],
                logout_urls=[props.origin],
                scopes=[cognito.OAuthScope.EMAIL, cognito.OAuthScope.OPENID],
            ),
            "supported_identity_providers": self._get_supported_providers(
                props.identity_providers
            ),
        }

    def _get_supported_providers(
        self, providers: List[dict]
    ) -> List[cognito.UserPoolClientIdentityProvider]:
        """
        Get list of supported identity providers.

        Args:
            providers: List of identity provider configurations

        Returns:
            List of supported Cognito identity providers
        """
        supported_providers = []

        for provider in providers:
            if provider["service"] == "google":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.GOOGLE
                )
            elif provider["service"] == "facebook":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.FACEBOOK
                )
            elif provider["service"] == "amazon":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.AMAZON
                )
            elif provider["service"] == "apple":
                supported_providers.append(cognito.UserPoolClientIdentityProvider.APPLE)
            elif provider["service"] == "oidc":
                if not provider.get("service_name"):
                    raise ValueError("service_name required for OIDC provider")
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.custom(
                        provider["service_name"]
                    )
                )

        if providers:
            supported_providers.append(cognito.UserPoolClientIdentityProvider.COGNITO)

        return supported_providers

    def _configure_identity_providers(self, props: AuthProps) -> None:
        """
        Configure external identity providers.

        Args:
            props: Authentication properties
        """
        for provider in props.identity_providers:
            secret = secretsmanager.Secret.from_secret_name_v2(
                self,
                f"Secret-{provider['secret_name']}",
                provider["secret_name"],
            )

            client_id = secret.secret_value_from_json("clientId").to_string()
            client_secret = secret.secret_value_from_json("clientSecret")

            if provider["service"] == "google":
                google_provider = cognito.UserPoolIdentityProviderGoogle(
                    self,
                    f"GoogleProvider-{provider['secret_name']}",
                    user_pool=self.user_pool,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=["openid", "email"],
                    attribute_mapping={
                        "email": cognito.ProviderAttribute.GOOGLE_EMAIL,
                    },
                )
                self.client.node.add_dependency(google_provider)

            elif provider["service"] == "oidc":
                issuer_url = secret.secret_value_from_json("issuerUrl").to_string()
                oidc_provider = cognito.UserPoolIdentityProviderOidc(
                    self,
                    f"OidcProvider-{provider['secret_name']}",
                    user_pool=self.user_pool,
                    client_id=client_id,
                    client_secret=client_secret.to_string(),
                    issuer_url=issuer_url,
                    attribute_mapping={
                        "email": cognito.ProviderAttribute.other("EMAIL"),
                    },
                    scopes=["openid", "email"],
                )
                self.client.node.add_dependency(oidc_provider)

    def _create_user_groups(self) -> None:
        """
        Create default user groups in the Cognito user pool.
        """
        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            group_name="Admin",
            user_pool_id=self.user_pool.user_pool_id,
        )

        cognito.CfnUserPoolGroup(
            self,
            "CreatingBotAllowedGroup",
            group_name="CreatingBotAllowed",
            user_pool_id=self.user_pool.user_pool_id,
        )

        cognito.CfnUserPoolGroup(
            self,
            "PublishAllowedGroup",
            group_name="PublishAllowed",
            user_pool_id=self.user_pool.user_pool_id,
        )

    def _create_outputs(self, props: AuthProps) -> None:
        """
        Create CloudFormation outputs for authentication resources.

        Args:
            props: Authentication properties containing configuration values

        Creates outputs for:
        - User pool ID
        - User pool client ID
        - OAuth/IDP configuration if identity providers are enabled
        """
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="ID of the Cognito user pool",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.client.user_pool_client_id,
            description="ID of the Cognito user pool client",
        )

        if props.identity_providers:
            region = Stack.of(self.user_pool).region
            CfnOutput(
                self,
                "ApprovedRedirectURI",
                value=f"https://{props.user_pool_domain_prefix}.auth.{region}.amazoncognito.com/oauth2/idpresponse",
                description="Approved redirect URI for identity providers",
            )
            CfnOutput(
                self,
                "CognitoDomain",
                value=f"{props.user_pool_domain_prefix}.auth.{region}.amazoncognito.com",
                description="Cognito hosted UI domain",
            )
            CfnOutput(
                self,
                "SocialProviders",
                value=",".join(
                    p["service"]
                    for p in props.identity_providers
                    if p["service"] != "oidc"
                ),
                description="Configured social identity providers",
            )
