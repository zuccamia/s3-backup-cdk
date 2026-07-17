#!/usr/bin/env python3
import os

from aws_cdk import App, Environment
from stacks.data_stack import DataStack

app = App()

env = Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

DataStack(app, "DataStack", env=env)

app.synth()
