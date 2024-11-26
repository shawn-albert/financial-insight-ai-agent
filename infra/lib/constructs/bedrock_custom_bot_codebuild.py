"""
Bedrock Custom Bot CodeBuild Infrastructure Module.

This module implements the CodeBuild infrastructure required for deploying custom Bedrock
bots. It handles the setup and configuration of CodeBuild projects that can deploy
custom bot configurations using AWS CDK, with support for knowledge bases and guardrails.

The module provides functionality for:
- S3 source configuration
- Build environment setup
- Environment variable management
- IAM role and permission configuration
- Security suppression handling
- Bot ID extraction and deployment
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
class BedrockCustomBotCodebuildProps:
    """
    Properties for Bedrock Custom Bot CodeBuild configuration.

    Attributes:
        source_bucket: S3 bucket containing the source code for deployment
    """

    source_bucket: s3.Bucket


class BedrockCustomBotCodebuild(Construct):
    """
    CodeBuild infrastructure for Bedrock Custom Bot deployment.

    This construct creates a CodeBuild project configured to deploy custom Bedrock
    bot infrastructure using AWS CDK. It manages environment variables, permissions,
    and build specifications required for bot deployment.

    Attributes:
        project: CodeBuild project instance for bot deployment
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: BedrockCustomBotCodebuildProps,
    ) -> None:
        """
        Initialize BedrockCustomBotCodebuild construct.

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
            Configured CodeBuild project for bot deployment
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
                "PK": codebuild.BuildEnvironmentVariable(value=""),
                "SK": codebuild.BuildEnvironmentVariable(value=""),
                "BEDROCK_CLAUDE_CHAT_DOCUMENT_BUCKET_NAME": codebuild.BuildEnvironmentVariable(
                    value=""
                ),
                "KNOWLEDGE": codebuild.BuildEnvironmentVariable(value=""),
                "BEDROCK_KNOWLEDGE_BASE": codebuild.BuildEnvironmentVariable(value=""),
                "BEDROCK_GUARDRAILS": codebuild.BuildEnvironmentVariable(value=""),
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
                            "export BOT_ID=$(echo $SK | awk -F'#' '{print $3}')",
                            "sed -i 's|bin/bedrock-chat.ts|bin/bedrock-custom-bot.ts|' cdk.json",
                            "cdk deploy --require-approval never BrChatKbStack$BOT_ID",
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
                    "reason": "for running on the docker daemon on the docker container",
                },
            ],
        )
