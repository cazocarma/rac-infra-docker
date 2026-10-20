"""Idempotent private bucket and least-privilege IAM provisioning (DEV)."""
import json
import os
import uuid
import urllib.error
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request

import boto3
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials
from botocore.exceptions import ClientError

endpoint = os.environ.get("S3_ENDPOINT", "http://rustfs:9000")
root = Credentials(os.environ["AWS_ACCESS_KEY_ID"], os.environ["AWS_SECRET_ACCESS_KEY"])
bucket = os.environ["PROFILE_S3_BUCKET"]
access = os.environ["PROFILE_S3_ACCESS_KEY"]
secret = os.environ["PROFILE_S3_SECRET_KEY"]
if access == root.access_key or secret == root.secret_key:
    raise RuntimeError("Application credentials must differ from administrator")

def admin(path, body=None, method="PUT", **query):
    url = endpoint + "/rustfs/admin/v3/" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else b""
    request = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
    S3SigV4Auth(root, "s3", "us-east-1").add_auth(request)
    signed = request.prepare()
    try:
        with urllib.request.urlopen(urllib.request.Request(signed.url, data=data, method=method, headers=dict(signed.headers)), timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = ET.fromstring(error.read())
        raise RuntimeError("Storage admin failure: " + str(error.code) + " " + str(body.findtext("Code"))) from None

client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1", config=Config(signature_version="s3v4",s3={"addressing_style":"path"}))
try:
    client.create_bucket(Bucket=bucket)
except ClientError as error:
    if error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
        raise
# Remove any anonymous bucket policy. No public ACL/policy is provisioned.
client.delete_bucket_policy(Bucket=bucket)
policy = {"Version":"2012-10-17","Statement":[
    {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::"+bucket]},
    {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":["arn:aws:s3:::"+bucket+"/*"]},
]}
admin("add-canned-policy", policy, name="rac-dev-profile-photos")
admin("add-user", {"secretKey":secret,"status":"enabled"}, accessKey=access)
admin("set-user-or-group-policy", policyName="rac-dev-profile-photos", userOrGroup=access, isGroup="false")
print("PASS private profile bucket and restricted application identity provisioned")

app = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1", aws_access_key_id=access, aws_secret_access_key=secret, config=Config(signature_version="s3v4",s3={"addressing_style":"path"}))
key = "iam-probe-"+uuid.uuid4().hex
other = "rac-iam-test-"+uuid.uuid4().hex
client.create_bucket(Bucket=other)
try:
    app.head_bucket(Bucket=bucket)
    app.put_object(Bucket=bucket,Key=key,Body=b"probe")
    assert app.get_object(Bucket=bucket,Key=key)["Body"].read() == b"probe"
    client.put_object(Bucket=other,Key=key,Body=b"private")
    def denied(call):
        try:
            call()
        except ClientError as error:
            assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 403
        else:
            raise AssertionError("Application identity exceeded its storage permissions")
    denied(lambda:app.get_object(Bucket=other,Key=key))
    denied(lambda:app.create_bucket(Bucket="rac-denied-"+uuid.uuid4().hex))
    denied(lambda:app.put_bucket_policy(Bucket=bucket,Policy=json.dumps({"Version":"2012-10-17","Statement":[]})))
    try:
        urllib.request.urlopen(endpoint+"/"+bucket+"/"+key,timeout=10)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("Profile bucket allows anonymous reads")
    print("PASS app CRUD allowed; anonymous, other bucket, bucket creation and policy changes denied")
finally:
    app.delete_object(Bucket=bucket,Key=key)
    client.delete_object(Bucket=other,Key=key)
    client.delete_bucket(Bucket=other)

backup_access = os.environ["BACKUP_S3_ACCESS_KEY"]
backup_secret = os.environ["BACKUP_S3_SECRET_KEY"]
backup_policy = {"Version":"2012-10-17","Statement":[
    {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":["arn:aws:s3:::"+bucket]},
    {"Effect":"Allow","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::"+bucket+"/*"]},
]}
admin("add-canned-policy",backup_policy,name="rac-dev-photo-backup")
admin("add-user",{"secretKey":backup_secret,"status":"enabled"},accessKey=backup_access)
admin("set-user-or-group-policy",policyName="rac-dev-photo-backup",userOrGroup=backup_access,isGroup="false")
backup_client = boto3.client("s3",endpoint_url=endpoint,region_name="us-east-1",aws_access_key_id=backup_access,aws_secret_access_key=backup_secret,config=Config(signature_version="s3v4",s3={"addressing_style":"path"}))
backup_client.head_bucket(Bucket=bucket)
denied(lambda:backup_client.put_object(Bucket=bucket,Key="backup-must-not-write",Body=b"denied"))
print("PASS dedicated backup identity is read-only")
