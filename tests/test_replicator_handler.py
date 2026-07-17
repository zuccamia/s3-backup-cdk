"""Business-logic tests for the Replicator lambda handler."""

import time

from boto3.dynamodb.conditions import Key


def _s3_event(detail_type, bucket, key):
    return {
        "detail-type": detail_type,
        "detail": {"bucket": {"name": bucket}, "object": {"key": key}},
    }


def test_created_copies_to_dst_and_writes_row(env, replicator):
    env["s3"].put_object(Bucket=env["src_bucket"], Key="hello.txt", Body=b"payload")

    replicator.handler(
        _s3_event("Object Created", env["src_bucket"], "hello.txt"), None
    )

    dst = env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("Contents", [])
    assert len(dst) == 1
    assert dst[0]["Key"].startswith("hello.txt/")

    rows = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("hello.txt")
    )["Items"]
    assert len(rows) == 1
    assert rows[0]["CopyKey"] == dst[0]["Key"]


def test_created_caps_copies_at_three(env, replicator):
    env["s3"].put_object(Bucket=env["src_bucket"], Key="cap.txt", Body=b"payload")

    for _ in range(5):
        replicator.handler(
            _s3_event("Object Created", env["src_bucket"], "cap.txt"), None
        )
        time.sleep(0.02)  # avoid CreatedAt millisecond collision

    dst = env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("Contents", [])
    assert len(dst) == 3

    rows = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("cap.txt")
    )["Items"]
    assert len(rows) == 3
    assert {r["CopyKey"] for r in rows} == {o["Key"] for o in dst}


def test_deleted_marks_all_rows_disowned(env, replicator):
    env["s3"].put_object(Bucket=env["src_bucket"], Key="del.txt", Body=b"payload")
    replicator.handler(_s3_event("Object Created", env["src_bucket"], "del.txt"), None)
    time.sleep(0.02)
    replicator.handler(_s3_event("Object Created", env["src_bucket"], "del.txt"), None)

    replicator.handler(_s3_event("Object Deleted", env["src_bucket"], "del.txt"), None)

    rows = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("del.txt")
    )["Items"]
    assert len(rows) == 2
    for row in rows:
        assert row["DeletedFlag"] == "DELETED"
        assert row["DeletedAt"] > 0

    # Copies stay in Dst; only the Cleaner sweeps them.
    dst = env["s3"].list_objects_v2(Bucket=env["dst_bucket"]).get("Contents", [])
    assert len(dst) == 2


def test_deleted_skips_already_disowned(env, replicator):
    env["s3"].put_object(Bucket=env["src_bucket"], Key="twice.txt", Body=b"payload")
    replicator.handler(
        _s3_event("Object Created", env["src_bucket"], "twice.txt"), None
    )
    replicator.handler(
        _s3_event("Object Deleted", env["src_bucket"], "twice.txt"), None
    )

    first = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("twice.txt")
    )["Items"][0]["DeletedAt"]

    time.sleep(0.02)
    replicator.handler(
        _s3_event("Object Deleted", env["src_bucket"], "twice.txt"), None
    )

    second = env["table"].query(
        KeyConditionExpression=Key("OriginalKey").eq("twice.txt")
    )["Items"][0]["DeletedAt"]
    assert second == first  # skipped, not re-marked
