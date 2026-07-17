"""CDK stack synth tests — verify the CFN templates have the intended shape."""

from aws_cdk import App
from aws_cdk.assertions import Match, Template

from stacks.cleaner_stack import CleanerStack
from stacks.data_stack import DataStack
from stacks.replicator_stack import ReplicatorStack


def _build():
    app = App()
    data = DataStack(app, "TestData")
    replicator = ReplicatorStack(
        app,
        "TestReplicator",
        src_bucket=data.src_bucket,
        dst_bucket=data.dst_bucket,
        table=data.table,
    )
    cleaner = CleanerStack(
        app,
        "TestCleaner",
        dst_bucket=data.dst_bucket,
        table=data.table,
        gsi_name=DataStack.GSI_NAME,
    )
    return data, replicator, cleaner


def test_data_stack_has_two_buckets():
    data, _, _ = _build()
    Template.from_stack(data).resource_count_is("AWS::S3::Bucket", 2)


def test_data_stack_table_has_expected_keys_and_sparse_gsi():
    data, _, _ = _build()
    Template.from_stack(data).has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "OriginalKey", "KeyType": "HASH"},
                {"AttributeName": "CreatedAt", "KeyType": "RANGE"},
            ],
            "GlobalSecondaryIndexes": Match.array_with(
                [
                    Match.object_like(
                        {
                            "IndexName": "DeletedIndex",
                            "KeySchema": [
                                {"AttributeName": "DeletedFlag", "KeyType": "HASH"},
                                {"AttributeName": "DeletedAt", "KeyType": "RANGE"},
                            ],
                        }
                    )
                ]
            ),
        },
    )


def test_src_bucket_has_eventbridge_enabled():
    # CDK renders event_bridge_enabled=True via a custom resource that calls
    # PutBucketNotificationConfiguration at deploy time, not as inline props.
    data, _, _ = _build()
    Template.from_stack(data).has_resource_properties(
        "Custom::S3BucketNotifications",
        Match.object_like(
            {
                "NotificationConfiguration": Match.object_like(
                    {"EventBridgeConfiguration": {}}
                )
            }
        ),
    )


def test_replicator_stack_rule_matches_both_s3_event_types():
    _, replicator, _ = _build()
    Template.from_stack(replicator).has_resource_properties(
        "AWS::Events::Rule",
        Match.object_like(
            {
                "EventPattern": Match.object_like(
                    {
                        "source": ["aws.s3"],
                        "detail-type": ["Object Created", "Object Deleted"],
                    }
                )
            }
        ),
    )


def test_cleaner_stack_has_one_minute_schedule():
    _, _, cleaner = _build()
    Template.from_stack(cleaner).has_resource_properties(
        "AWS::Events::Rule",
        Match.object_like({"ScheduleExpression": "rate(1 minute)"}),
    )
