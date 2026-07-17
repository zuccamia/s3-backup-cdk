"""Cleaner: EventBridge schedule → sweep disowned rows past the grace period."""

import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_s3 as s3
from aws_cdk import Duration, Stack
from constructs import Construct


class CleanerStack(Stack):
    FUNCTION_CONSTRUCT_ID = "Cleaner"
    SCHEDULE_CONSTRUCT_ID = "CleanerSchedule"
    SCHEDULE_MINUTES = 1

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dst_bucket: s3.Bucket,
        table: dynamodb.Table,
        gsi_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.function = lambda_.Function(
            self,
            self.FUNCTION_CONSTRUCT_ID,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/cleaner"),
            timeout=Duration.seconds(60),
            environment={
                "DST_BUCKET": dst_bucket.bucket_name,
                "TABLE_NAME": table.table_name,
                "GSI_NAME": gsi_name,
            },
        )

        dst_bucket.grant_delete(self.function)
        table.grant_read_write_data(self.function)

        events.Rule(
            self,
            self.SCHEDULE_CONSTRUCT_ID,
            schedule=events.Schedule.rate(Duration.minutes(self.SCHEDULE_MINUTES)),
            targets=[targets.LambdaFunction(self.function)],
        )
