"""Prueba S3 real: bucket privado, integridad, URL firmada y borrado."""
import os
import sys
import urllib.error
import urllib.request
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

client = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"],
                      region_name="us-east-1", config=Config(
                          signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=5, read_timeout=15,
                          retries={"max_attempts": 2}))
phase = os.environ.get("STORAGE_TEST_PHASE", "api")
if phase in ("seed", "verify"):
    bucket = "rac-dev-persistence-test"
    key = "recreation-probe"
    payload = b"RAC persistent volume probe"
    if phase == "seed":
        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
        client.put_object(Bucket=bucket, Key=key, Body=payload)
        print("PASS persistence fixture written")
    else:
        assert client.get_object(Bucket=bucket, Key=key)["Body"].read() == payload
        client.delete_object(Bucket=bucket, Key=key)
        client.delete_bucket(Bucket=bucket)
        print("PASS object survived container recreation")
    sys.exit(0)

with urllib.request.urlopen("http://rustfs:9001/rustfs/console/", timeout=15) as console:
    assert console.status == 200, "Consola no disponible"

bucket = "rac-test-" + uuid.uuid4().hex
key = "profiles/example.jpg"
payload = b"RAC S3 integrity fixture"
client.create_bucket(Bucket=bucket)
try:
    client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="image/jpeg")
    result = client.get_object(Bucket=bucket, Key=key)
    assert result["Body"].read() == payload, "Contenido alterado"
    assert result["ContentType"] == "image/jpeg"
    assert client.head_object(Bucket=bucket, Key=key)["ContentLength"] == len(payload)
    signed = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60)
    with urllib.request.urlopen(signed, timeout=15) as response:
        assert response.read() == payload
    try:
        urllib.request.urlopen(os.environ["S3_ENDPOINT"] + "/" + bucket + "/" + key, timeout=15)
    except urllib.error.HTTPError as error:
        assert error.code == 403, error.code
    else:
        raise AssertionError("Objeto accesible sin autenticación")
    client.delete_object(Bucket=bucket, Key=key)
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 404
    else:
        raise AssertionError("Objeto sigue presente después de borrar")
    print("PASS S3: upload/download, metadata, private bucket, presigned URL, delete")
finally:
    client.delete_object(Bucket=bucket, Key=key)
    client.delete_bucket(Bucket=bucket)
