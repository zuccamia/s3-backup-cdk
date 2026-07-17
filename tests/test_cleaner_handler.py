"""Business-logic tests for the Cleaner lambda handler."""

import time

from boto3.dynamodb.conditions import Key


def _now_ms():
    return int(time.time() * 1000)


def _seed_disowned(env, original_key, copy_key, deleted_at):
    env["table"].put_item(
        Item={
            "OriginalKey": original_key,
            "CreatedAt": deleted_at - 100_000,
            "CopyKey": copy_key,
            "DeletedFlag": "DELETED",
            "DeletedAt": deleted_at,
        }
    )
    env["s3"].put_object(Bucket=env["dst_bucket"], Key=copy_key, Body=b"backup")


def test_cleaner_deletes_disowned_past_grace(env, cleaner):
    _seed_disowned(env, "old.txt", "old.txt/1-abc", deleted_at=_now_ms() - 30_000)

    cleaner.handler({}, None)

    assert env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("KeyCount", 0) == 0
    rows = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("old.txt")
    )["Items"]
    assert rows == []


def test_cleaner_skips_within_grace_period(env, cleaner):
    _seed_disowned(env, "fresh.txt", "fresh.txt/1-abc", deleted_at=_now_ms() - 5_000)

    cleaner.handler({}, None)

    assert env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("KeyCount", 0) == 1
    rows = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("fresh.txt")
    )["Items"]
    assert len(rows) == 1


def test_cleaner_ignores_non_disowned_rows(env, cleaner):
    env["table"].put_item(
        Item={
            "OriginalKey": "alive.txt",
            "CreatedAt": _now_ms(),
            "CopyKey": "alive.txt/1-abc",
        }
    )
    env["s3"].put_object(
        Bucket=env["dst_bucket"], Key="alive.txt/1-abc", Body=b"backup"
    )

    cleaner.handler({}, None)

    # Row lacks DeletedFlag so it never enters the sparse GSI.
    assert env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("KeyCount", 0) == 1
    row = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("alive.txt")
    )["Items"][0]
    assert "DeletedFlag" not in row
