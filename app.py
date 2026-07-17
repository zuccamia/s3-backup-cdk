#!/usr/bin/env python3
import os

from aws_cdk import App, Environment

from stacks.cleaner_stack import CleanerStack
from stacks.data_stack import DataStack
from stacks.replicator_stack import ReplicatorStack

app = App()

env = Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

data = DataStack(app, "DataStack", env=env)

ReplicatorStack(
    app,
    "ReplicatorStack",
    src_bucket=data.src_bucket,
    dst_bucket=data.dst_bucket,
    table=data.table,
    env=env,
)

CleanerStack(
    app,
    "CleanerStack",
    dst_bucket=data.dst_bucket,
    table=data.table,
    gsi_name=DataStack.GSI_NAME,
    env=env,
)

app.synth()
