"""
Database Construct Implementation for Financial Insight Agent.

This module implements the database infrastructure using DynamoDB for storing
conversations, bot configurations, and websocket sessions. It also handles
role-based access control and stream configurations.
"""

from dataclasses import dataclass
from typing import Optional

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam

from constructs import Construct


@dataclass
class DatabaseProps:
    """
    Properties for Database construct configuration.

    Attributes:
        point_in_time_recovery: Whether to enable point-in-time recovery for tables
    """

    point_in_time_recovery: Optional[bool] = False


class Database(Construct):
    """
    Database infrastructure for the Financial Insight Agent.

    This construct creates and manages the DynamoDB tables needed for the application:
    - Conversation table for storing chat histories and bot configurations
    - WebSocket session table for handling large message concatenation

    It also configures the necessary IAM roles and permissions for table access.

    Attributes:
        table: Main DynamoDB table for conversations and configurations
        table_access_role: IAM role for accessing the table
        websocket_session_table: Table for WebSocket session management
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: Optional[DatabaseProps] = None,
    ) -> None:
        """
        Initialize the Database construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for the database
        """
        super().__init__(scope, construct_id)

        self.table = dynamodb.Table(
            self,
            "ConversationTable",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            stream=dynamodb.StreamViewType.NEW_IMAGE,
            point_in_time_recovery=props.point_in_time_recovery if props else False,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
        )

        self.table.add_global_secondary_index(
            index_name="SKIndex",
            partition_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
        )

        self.table.add_global_secondary_index(
            index_name="PublicBotIdIndex",
            partition_key=dynamodb.Attribute(
                name="PublicBotId", type=dynamodb.AttributeType.STRING
            ),
        )

        self.table.add_local_secondary_index(
            index_name="LastBotUsedIndex",
            sort_key=dynamodb.Attribute(
                name="LastBotUsed", type=dynamodb.AttributeType.NUMBER
            ),
        )

        self.table_access_role = iam.Role(
            self,
            "TableAccessRole",
            assumed_by=iam.AccountPrincipal(Stack.of(self).account),
        )

        self.table.grant_read_write_data(self.table_access_role)

        self.websocket_session_table = dynamodb.Table(
            self,
            "WebsocketSessionTable",
            partition_key=dynamodb.Attribute(
                name="ConnectionId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="MessagePartId", type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="expire",
        )

        CfnOutput(
            self,
            "ConversationTableName",
            value=self.table.table_name,
            description="Name of the main conversation DynamoDB table",
        )
