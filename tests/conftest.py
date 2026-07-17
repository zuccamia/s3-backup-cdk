"""Shared fixtures: moto-backed AWS setup and per-test handler loading."""

import importlib.util
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SRC_BUCKET = "test-src"
DST_BUCKET = "test-dst"
TABLE_NAME = "test-backup"
GSI_NAME = "DeletedIndex"

REPO_ROOT = Path(__file__).parent.parent


def _load_handler(name: str):
    # Fresh load per test so module-level boto3 clients bind to the currently
    # active moto mock and env vars.
    path = REPO_ROOT / "lambdas" / name / "handler.py"
    spec = importlib.util.spec_from_file_location(f"{name}_handler_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SRC_BUCKET", SRC_BUCKET)
    monkeypatch.setenv("DST_BUCKET", DST_BUCKET)
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("GSI_NAME", GSI_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=SRC_BUCKET)
        s3.create_bucket(Bucket=DST_BUCKET)

        boto3.client("dynamodb").create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "OriginalKey", "KeyType": "HASH"},
                {"AttributeName": "CreatedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "OriginalKey", "AttributeType": "S"},
                {"AttributeName": "CreatedAt", "AttributeType": "N"},
                {"AttributeName": "DeletedFlag", "AttributeType": "S"},
                {"AttributeName": "DeletedAt", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI_NAME,
                    "KeySchema": [
                        {"AttributeName": "DeletedFlag", "KeyType": "HASH"},
                        {"AttributeName": "DeletedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        yield {
            "s3": s3,
            "table": boto3.resource("dynamodb").Table(TABLE_NAME),
            "src_bucket": SRC_BUCKET,
            "dst_bucket": DST_BUCKET,
        }


@pytest.fixture
def replicator(env):
    return _load_handler("replicator")


@pytest.fixture
def cleaner(env):
    return _load_handler("cleaner")
