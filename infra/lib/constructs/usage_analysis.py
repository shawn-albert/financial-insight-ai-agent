"""
Usage Analysis Construct Implementation for Financial Insight Agent.

This module implements analytics infrastructure using AWS Athena, Glue, and S3
to analyze usage patterns, costs, and performance metrics of the application.
It enables data-driven insights about user behavior and system performance.
"""

from dataclasses import dataclass

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3

from constructs import Construct


@dataclass
class UsageAnalysisProps:
    """
    Properties for Usage Analysis construct configuration.

    Attributes:
        access_log_bucket: S3 bucket for access logs
        source_database: DynamoDB database to analyze
    """

    access_log_bucket: s3.IBucket
    source_database: dynamodb.ITable


class UsageAnalysis(Construct):
    """
    Usage Analysis infrastructure for the Financial Insight Agent.

    This construct creates and manages analytics resources including:
    - Athena workgroups and queries
    - Glue databases and tables
    - S3 buckets for results and data exports
    - IAM roles and permissions

    Attributes:
        workgroup_name: Name of the Athena workgroup
        workgroup_arn: ARN of the Athena workgroup
        database: Glue database for analytics
        ddb_export_table: Glue table for DynamoDB exports
        result_output_bucket: S3 bucket for analysis results
        ddb_bucket: S3 bucket for DynamoDB exports
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: UsageAnalysisProps,
    ) -> None:
        """
        Initialize the Usage Analysis construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for usage analysis
        """
        super().__init__(scope, construct_id)

        self.result_output_bucket = s3.Bucket(
            self,
            "ResultOutputBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=props.access_log_bucket,
            server_access_logs_prefix="UsageAnalysis/Results",
        )

        self.ddb_bucket = s3.Bucket(
            self,
            "DDBExportBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=props.access_log_bucket,
            server_access_logs_prefix="UsageAnalysis/DDBExport",
        )

        self.database = glue.CfnDatabase(
            self,
            "AnalyticsDatabase",
            catalog_id=Stack.of(self).account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=f"financial_insight_analytics_{Stack.of(self).region}",
                description="Database for Financial Insight Agent analytics",
            ),
        )

        self.ddb_export_table = glue.CfnTable(
            self,
            "DDBExportTable",
            catalog_id=Stack.of(self).account,
            database_name=self.database.ref,
            table_input=glue.CfnTable.TableInputProperty(
                name="ddb_exports",
                description="Table for analyzing DynamoDB exports",
                parameters={
                    "classification": "json",
                    "typeOfData": "file",
                },
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    location=f"s3://{self.ddb_bucket.bucket_name}/ddb-exports/",
                    input_format="org.apache.hadoop.mapred.TextInputFormat",
                    output_format="org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library="org.openx.data.jsonserde.JsonSerDe",
                    ),
                    columns=[
                        glue.CfnTable.ColumnProperty(
                            name="pk",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="sk",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="type",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="created_at",
                            type="bigint",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="conversation_id",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="bot_id",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="message_id",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="role",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="content",
                            type="string",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="total_tokens",
                            type="int",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="completion_tokens",
                            type="int",
                        ),
                        glue.CfnTable.ColumnProperty(
                            name="prompt_tokens",
                            type="int",
                        ),
                    ],
                ),
            ),
        )

        workgroup_config = athena.CfnWorkGroup.WorkGroupConfigurationProperty(
            enforce_work_group_configuration=True,
            publish_cloud_watch_metrics_enabled=True,
            result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                output_location=f"s3://{self.result_output_bucket.bucket_name}/query-results/",
            ),
        )

        self.workgroup = athena.CfnWorkGroup(
            self,
            "AnalyticsWorkGroup",
            name=f"financial-insight-analytics-{Stack.of(self).region}",
            description="Workgroup for Financial Insight Agent analytics",
            recursive_delete_option=True,
            state="ENABLED",
            work_group_configuration=workgroup_config,
        )

        self.workgroup_name = self.workgroup.name
        self.workgroup_arn = self.workgroup.attr_arn

        self._grant_export_permissions(props.source_database)

    def _grant_export_permissions(self, source_database: dynamodb.ITable) -> None:
        """
        Grant necessary permissions for DynamoDB export to S3.

        Args:
            source_database: DynamoDB table to export data from
        """
        export_role = iam.Role(
            self,
            "DDBExportRole",
            assumed_by=iam.ServicePrincipal("export.dynamodb.amazonaws.com"),
        )

        self.ddb_bucket.grant_write(export_role)

        export_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:ExportTableToPointInTime",
                ],
                resources=[source_database.table_arn],
            )
        )
