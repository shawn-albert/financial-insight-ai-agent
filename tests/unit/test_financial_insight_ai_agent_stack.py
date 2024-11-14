import aws_cdk as core
import aws_cdk.assertions as assertions

from financial_insight_ai_agent.financial_insight_ai_agent_stack import FinancialInsightAiAgentStack

# example tests. To run these tests, uncomment this file along with the example
# resource in financial_insight_ai_agent/financial_insight_ai_agent_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = FinancialInsightAiAgentStack(app, "financial-insight-ai-agent")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
