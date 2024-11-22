"""
API Publish CodeBuild Infrastructure Module.

This module implements the CodeBuild infrastructure required for publishing APIs. It sets up
a CodeBuild project that can deploy API configurations using AWS CDK, with support for
configurable throttling, quotas, and CORS settings.

The module handles:
- S3 source bucket configuration
- Build environment setup
- IAM permissions and roles
- Build specification for CDK deployment
- Security configuration suppressions
"""

import logging
from dataclasses import dataclass

from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct

logger = logging.getLogger(__name__)


@dataclass
class ApiPublishCodebuildProps:
    """
    Properties for API Publish CodeBuild configuration.

    Attributes:
        source_bucket: S3 bucket containing source code for deployment
    """

    source_bucket: s3.Bucket


class ApiPublishCodebuild(Construct):
    """
    CodeBuild infrastructure for API publishing.

    This construct creates a CodeBuild project configured to deploy API infrastructure
    using AWS CDK. It supports customizable API configurations through environment
    variables and handles necessary IAM permissions.

    Attributes:
        project: CodeBuild project instance for API deployment
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: ApiPublishCodebuildProps,
    ) -> None:
        """
        Initialize ApiPublishCodebuild construct.

        Args:
            scope: CDK construct scope
            construct_id: Unique identifier for this construct
            props: Configuration properties for the CodeBuild project
        """
        super().__init__(scope, construct_id)

        self.project = self._create_project(props.source_bucket)
        self._configure_permissions(props.source_bucket)
        self._add_security_suppressions()

    def _create_project(self, source_bucket: s3.Bucket) -> codebuild.Project:
        """
        Create and configure the CodeBuild project.

        Args:
            source_bucket: S3 bucket containing deployment source code

        Returns:
            Configured CodeBuild project
        """
        return codebuild.Project(
            self,
            "Project",
            source=codebuild.Source.s3(
                bucket=source_bucket,
                path="",
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
            environment_variables={
                "PUBLISHED_API_DEPLOYMENT_STAGE": codebuild.BuildEnvironmentVariable(
                    value="api"
                ),
                "PUBLISHED_API_ID": codebuild.BuildEnvironmentVariable(value="xy1234"),
                "PUBLISHED_API_ALLOWED_ORIGINS": codebuild.BuildEnvironmentVariable(
                    value='["*"]'
                ),
            },
            build_spec=self._create_build_spec(),
        )

    def _create_build_spec(self) -> codebuild.BuildSpec:
        """
        Create the build specification for the CodeBuild project.

        Returns:
            BuildSpec object containing build commands and configuration
        """
        return codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {
                            "nodejs": "18",
                        },
                        "commands": ["npm install -g aws-cdk"],
                        "on-failure": "ABORT",
                    },
                    "build": {
                        "commands": [
                            "cd cdk",
                            "npm ci",
                            # Replace CDK entrypoint
                            "sed -i 's|bin/bedrock-chat.ts|bin/api-publish.ts|' cdk.json",
                            " ".join(
                                [
                                    "cdk deploy --require-approval never",
                                    "ApiPublishmentStack$PUBLISHED_API_ID",
                                    "-c publishedApiThrottleRateLimit=$PUBLISHED_API_THROTTLE_RATE_LIMIT",
                                    "-c publishedApiThrottleBurstLimit=$PUBLISHED_API_THROTTLE_BURST_LIMIT",
                                    "-c publishedApiQuotaLimit=$PUBLISHED_API_QUOTA_LIMIT",
                                    "-c publishedApiQuotaPeriod=$PUBLISHED_API_QUOTA_PERIOD",
                                    "-c publishedApiDeploymentStage=$PUBLISHED_API_DEPLOYMENT_STAGE",
                                    "-c publishedApiId=$PUBLISHED_API_ID",
                                    "-c publishedApiAllowedOrigins=$PUBLISHED_API_ALLOWED_ORIGINS",
                                ]
                            ),
                        ],
                    },
                },
            }
        )

    def _configure_permissions(self, source_bucket: s3.Bucket) -> None:
        """
        Configure IAM permissions for the CodeBuild project.

        Args:
            source_bucket: S3 bucket requiring read access
        """
        source_bucket.grant_read(self.project.role)

        # Allow CDK deployment permissions
        self.project.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=["arn:aws:iam::*:role/cdk-*"],
            )
        )

    def _add_security_suppressions(self) -> None:
        """Add security suppressions for known configuration decisions."""
        NagSuppressions.add_resource_suppressions(
            self.project,
            [
                {
                    "id": "AwsPrototyping-CodeBuildProjectKMSEncryptedArtifacts",
                    "reason": "default: The AWS-managed CMK for Amazon Simple Storage Service (Amazon S3) is used.",
                },
                {
                    "id": "AwsPrototyping-CodeBuildProjectPrivilegedModeDisabled",
                    "reason": "for runnning on the docker daemon on the docker container",
                },
            ],
        )
