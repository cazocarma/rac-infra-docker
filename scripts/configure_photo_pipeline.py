"""Opt-in DEV quarantine/staging IAM; no profile/public bucket or WORM claims."""
import json
import os
import uuid
from functools import partial

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.credentials import Credentials
from botocore.exceptions import ClientError
from storage_admin import admin as signed_admin


def main():
    if os.environ.get('RAC_ENV') != 'dev':
        raise RuntimeError('Photo pipeline provisioning requires explicit dev environment')
    endpoint = os.environ['S3_ENDPOINT']
    root = Credentials(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'])
    quarantine, staging = os.environ['PHOTO_QUARANTINE_BUCKET'], os.environ['PHOTO_STAGING_BUCKET']
    if quarantine == staging or os.environ.get('PROFILE_S3_BUCKET') in (quarantine, staging):
        raise RuntimeError('Photo pipeline buckets must be separate from each other and profiles')
    names = ('INGEST', 'READER', 'STAGING')
    identities = {name: (os.environ['PHOTO_'+name+'_ACCESS_KEY'], os.environ['PHOTO_'+name+'_SECRET_KEY']) for name in names}
    if len({value[0] for value in identities.values()} | {root.access_key}) != 4 or any(value[1] == root.secret_key for value in identities.values()):
        raise RuntimeError('Photo pipeline requires three separate non-root identities')
    config = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
    def client(access, secret):
        return boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1', aws_access_key_id=access, aws_secret_access_key=secret, config=config)
    owner = client(root.access_key, root.secret_key)
    admin = partial(signed_admin, endpoint, root)
    for bucket in (quarantine, staging):
        try:
            owner.create_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response['Error']['Code'] != 'BucketAlreadyOwnedByYou':
                raise
        owner.delete_bucket_policy(Bucket=bucket)
    clients = {}
    for name in names:
        access, secret = identities[name]
        bucket = staging if name == 'STAGING' else quarantine
        suffix = '.jpg' if name == 'STAGING' else '.raw'
        actions = ['s3:GetObject'] if name == 'READER' else ['s3:GetObject', 's3:PutObject']
        policy = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': actions, 'Resource': ['arn:aws:s3:::'+bucket+'/*'+suffix]}]}
        policy_name = 'rac-dev-photo-'+name.lower()
        admin('add-canned-policy', policy, name=policy_name)
        admin('add-user', {'secretKey': secret, 'status': 'enabled'}, accessKey=access)
        admin('set-user-or-group-policy', policyName=policy_name, userOrGroup=access, isGroup='false')
        clients[name] = client(access, secret)
    def denied(call):
        try:
            call()
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode'] == 403:
                return
            raise
        raise AssertionError('Photo pipeline IAM boundary exceeded')
    raw, jpg = uuid.uuid4().hex+'.raw', uuid.uuid4().hex+'.jpg'
    try:
        clients['INGEST'].put_object(Bucket=quarantine, Key=raw, Body=b'private-source', IfNoneMatch='*')
        assert clients['READER'].get_object(Bucket=quarantine, Key=raw)['Body'].read() == b'private-source'
        clients['STAGING'].put_object(Bucket=staging, Key=jpg, Body=b'private-derived', IfNoneMatch='*')
        assert clients['STAGING'].get_object(Bucket=staging, Key=jpg)['Body'].read() == b'private-derived'
        for name, app in clients.items():
            allowed_bucket, allowed_key = (staging, jpg) if name == 'STAGING' else (quarantine, raw)
            other_bucket, other_key = (quarantine, raw) if name == 'STAGING' else (staging, jpg)
            denied(lambda: app.get_object(Bucket=other_bucket, Key=other_key))
            denied(lambda: app.put_object(Bucket=other_bucket, Key=other_key, Body=b'denied'))
            denied(lambda: app.delete_object(Bucket=allowed_bucket, Key=allowed_key))
            denied(lambda: app.list_objects_v2(Bucket=allowed_bucket))
            denied(lambda: app.put_bucket_policy(Bucket=allowed_bucket, Policy=json.dumps({'Version':'2012-10-17','Statement':[]})))
            denied(lambda: app.put_object_acl(Bucket=allowed_bucket, Key=allowed_key, ACL='public-read'))
        denied(lambda: clients['READER'].put_object(Bucket=quarantine, Key=raw, Body=b'denied'))
        anonymous = boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1', config=Config(signature_version=UNSIGNED))
        denied(lambda: anonymous.get_object(Bucket=quarantine, Key=raw))
        denied(lambda: anonymous.get_object(Bucket=staging, Key=jpg))
        print('PASS: separate ingest/read-only quarantine/staging IAM; cross-bucket, write by reader, delete, list, ACL, policy and anonymous access denied', flush=True)
    finally:
        owner.delete_object(Bucket=quarantine, Key=raw)
        owner.delete_object(Bucket=staging, Key=jpg)


if __name__ == '__main__':
    main()
