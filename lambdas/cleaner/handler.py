import os
import time

import boto3
from boto3.dynamodb.conditions import Key

DST_BUCKET = os.environ["DST_BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]
GSI_NAME = os.environ["GSI_NAME"]
GRACE_MS = 10_000

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(TABLE_NAME)


def handler(_event, _context):
    cutoff = int(time.time() * 1000) - GRACE_MS

    deleted = 0
    last_key = None
    while True:
        params = {
            "IndexName": GSI_NAME,
            "KeyConditionExpression": (
                Key("DeletedFlag").eq("DELETED") & Key("DeletedAt").lt(cutoff)
            ),
        }
        if last_key:
            params["ExclusiveStartKey"] = last_key

        resp = table.query(**params)

        for row in resp["Items"]:
            # S3 first, then DDB: if we crash between them the row stays
            # disowned and the next run reprocesses it (S3 delete is idempotent).
            s3.delete_object(Bucket=DST_BUCKET, Key=row["CopyKey"])
            table.delete_item(
                Key={
                    "OriginalKey": row["OriginalKey"],
                    "CreatedAt": int(row["CreatedAt"]),
                }
            )
            deleted += 1

        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    print(f"cleaned {deleted} rows")
