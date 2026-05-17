#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.aria_stack import AriaStack

app = cdk.App()

AriaStack(
    app,
    "AriaStack",
    env=cdk.Environment(
        account=os.environ.get("AWS_ACCOUNT_ID", os.environ.get("CDK_DEFAULT_ACCOUNT")),
        region=os.environ.get("AWS_REGION", "us-west-2"),
    ),
    description="ARIA — Autonomous Response Intelligence Assistant (AWSHacks 2026)",
)

cdk.Tags.of(app).add("Project", "ARIA")

app.synth()
