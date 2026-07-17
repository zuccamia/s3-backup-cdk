"""Replicator: S3 events on Src → copy to Dst + update Table T."""

import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as targets
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_s3 as s3
from aws_cdk import Duration, Stack
from constructs import Construct


class ReplicatorStack(Stack):
    FUNCTION_CONSTRUCT_ID = "Replicator"
    RULE_CONSTRUCT_ID = "SrcS3EventRule"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        src_bucket: s3.Bucket,
        dst_bucket: s3.Bucket,
        table: dynamodb.Table,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.function = lambda_.Function(
            self,
            self.FUNCTION_CONSTRUCT_ID,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/replicator"),
            timeout=Duration.seconds(30),
            environment={
                "DST_BUCKET": dst_bucket.bucket_name,
                "TABLE_NAME": table.table_name,
            },
        )

        src_bucket.grant_read(self.function)
        dst_bucket.grant_read_write(self.function)
        dst_bucket.grant_delete(self.function)
        table.grant_read_write_data(self.function)

        # Rule matches both Object Created and Object Deleted on Src only,
        # so Cleaner deletes on Dst never loop back into the Replicator.
        events.Rule(
            self,
            self.RULE_CONSTRUCT_ID,
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created", "Object Deleted"],
                detail={"bucket": {"name": [src_bucket.bucket_name]}},
            ),
            targets=[targets.LambdaFunction(self.function)],
        )
