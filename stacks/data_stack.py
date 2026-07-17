"""Storage stack: Src bucket, Dst bucket, backup Table T + sparse GSI."""

import aws_cdk.aws_dynamodb as dynamodb
import aws_cdk.aws_s3 as s3
from aws_cdk import CfnOutput, RemovalPolicy, Stack
from constructs import Construct


class DataStack(Stack):
    SRC_BUCKET_CONSTRUCT_ID = "SrcBucket"
    DST_BUCKET_CONSTRUCT_ID = "DstBucket"
    TABLE_CONSTRUCT_ID = "BackupTable"
    GSI_NAME = "DeletedIndex"

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Src has EventBridge enabled so the Replicator rule can subscribe.
        self.src_bucket = s3.Bucket(
            self,
            self.SRC_BUCKET_CONSTRUCT_ID,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            event_bridge_enabled=True,
        )

        self.dst_bucket = s3.Bucket(
            self,
            self.DST_BUCKET_CONSTRUCT_ID,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.table = dynamodb.Table(
            self,
            self.TABLE_CONSTRUCT_ID,
            partition_key=dynamodb.Attribute(
                name="OriginalKey", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="CreatedAt", type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Sparse GSI: only rows with DeletedFlag set appear here, so the
        # Cleaner can Query the disowned set directly without a Scan.
        self.table.add_global_secondary_index(
            index_name=self.GSI_NAME,
            partition_key=dynamodb.Attribute(
                name="DeletedFlag", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="DeletedAt", type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        CfnOutput(self, "SrcBucketName", value=self.src_bucket.bucket_name)
        CfnOutput(self, "DstBucketName", value=self.dst_bucket.bucket_name)
        CfnOutput(self, "TableName", value=self.table.table_name)
        CfnOutput(self, "GsiName", value=self.GSI_NAME)
