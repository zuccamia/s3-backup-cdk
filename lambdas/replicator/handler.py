import os
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Key

DST_BUCKET = os.environ["DST_BUCKET"]
TABLE_NAME = os.environ["TABLE_NAME"]
MAX_COPIES = 3

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(TABLE_NAME)


def handler(event, _context):
    detail_type = event.get("detail-type")
    detail = event["detail"]
    src_bucket = detail["bucket"]["name"]
    original_key = detail["object"]["key"]

    if detail_type == "Object Created":
        _on_created(src_bucket, original_key)
    elif detail_type == "Object Deleted":
        _on_deleted(original_key)
    else:
        print(f"ignoring event: {detail_type}")


def _on_created(src_bucket: str, original_key: str) -> None:
    now_ms = int(time.time() * 1000)
    copy_key = f"{original_key}/{now_ms}-{uuid.uuid4()}"

    s3.copy_object(
        Bucket=DST_BUCKET,
        Key=copy_key,
        CopySource={"Bucket": src_bucket, "Key": original_key},
    )

    table.put_item(
        Item={
            "OriginalKey": original_key,
            "CreatedAt": now_ms,
            "CopyKey": copy_key,
        }
    )

    # ConsistentRead so we definitely see the row we just put.
    resp = table.query(
        KeyConditionExpression=Key("OriginalKey").eq(original_key),
        ScanIndexForward=True,
        ConsistentRead=True,
    )
    items = resp["Items"]

    # ConsistentRead guarantees we see the row we just put, so len(items) >= 1
    # in normal operation. If it's ever 0 (concurrent delete or upstream bug),
    # the > MAX_COPIES check falls through — no eviction is the correct no-op.
    if len(items) > MAX_COPIES:
        oldest = items[0]
        s3.delete_object(Bucket=DST_BUCKET, Key=oldest["CopyKey"])
        table.delete_item(
            Key={
                "OriginalKey": oldest["OriginalKey"],
                "CreatedAt": int(oldest["CreatedAt"]),
            }
        )


def _on_deleted(original_key: str) -> None:
    now_ms = int(time.time() * 1000)

    resp = table.query(
        KeyConditionExpression=Key("OriginalKey").eq(original_key),
        ConsistentRead=True,
    )

    for row in resp["Items"]:
        if "DeletedAt" in row:
            continue
        table.update_item(
            Key={
                "OriginalKey": row["OriginalKey"],
                "CreatedAt": int(row["CreatedAt"]),
            },
            UpdateExpression="SET DeletedAt = :ts, DeletedFlag = :flag",
            ExpressionAttributeValues={":ts": now_ms, ":flag": "DELETED"},
        )
