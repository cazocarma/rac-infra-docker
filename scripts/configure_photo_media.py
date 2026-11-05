"""Explicit DEV private versioned destination and minimal promotion IAM.

No legal-evidence retention or WORM. Never enables the application/promotion flag.
"""
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
        raise RuntimeError('Photo media provisioning requires explicit DEV')
    endpoint = os.environ['S3_ENDPOINT']
    root = Credentials(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'])
    media, staging = os.environ['PHOTO_MEDIA_BUCKET'], os.environ['PHOTO_STAGING_BUCKET']
    buckets = (media, staging, os.environ['PHOTO_QUARANTINE_BUCKET'], os.environ['PROFILE_S3_BUCKET'])
    if not all(buckets) or len(set(buckets)) != 4:
        raise RuntimeError('Approved media must use a separate private bucket')
    access, secret = os.environ['PHOTO_PROMOTER_ACCESS_KEY'], os.environ['PHOTO_PROMOTER_SECRET_KEY']
    other_access = {root.access_key, os.environ['PROFILE_S3_ACCESS_KEY']}
    other_secrets = {root.secret_key, os.environ['PROFILE_S3_SECRET_KEY']}
    for name in ('INGEST', 'READER', 'STAGING', 'PREVIEW'):
        other_access.add(os.environ['PHOTO_'+name+'_ACCESS_KEY'])
        other_secrets.add(os.environ['PHOTO_'+name+'_SECRET_KEY'])
    if not access or not secret or access in other_access or secret in other_secrets:
        raise RuntimeError('Independent promotion identity required')
    config = Config(signature_version='s3v4', s3={'addressing_style': 'path'})

    def client(key, password):
        return boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1',
                            aws_access_key_id=key, aws_secret_access_key=password, config=config)

    owner = client(root.access_key, root.secret_key)
    try:
        owner.create_bucket(Bucket=media)
    except ClientError as error:
        if error.response['Error']['Code'] != 'BucketAlreadyOwnedByYou':
            raise
    try:
        owner.get_bucket_policy(Bucket=media)
    except ClientError as error:
        if error.response['Error']['Code'] not in ('NoSuchBucketPolicy', 'NoSuchPolicy'):
            raise
    else:
        raise RuntimeError('Photo media bucket must have no public/shared bucket policy')
    owner.put_bucket_versioning(Bucket=media, VersioningConfiguration={'Status': 'Enabled'})
    if owner.get_bucket_versioning(Bucket=media).get('Status') != 'Enabled':
        raise RuntimeError('Photo media versioning not enabled')
    policy = {'Version': '2012-10-17', 'Statement': [
        {'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': ['arn:aws:s3:::'+staging+'/*.jpg']},
        {'Effect': 'Allow', 'Action': ['s3:PutObject', 's3:GetObject', 's3:GetObjectVersion'],
         'Resource': ['arn:aws:s3:::'+media+'/*.jpg']},
    ]}
    admin = partial(signed_admin, endpoint, root)
    admin('add-canned-policy', policy, name='rac-dev-photo-promoter')
    admin('add-user', {'secretKey': secret, 'status': 'enabled'}, accessKey=access)
    admin('set-user-or-group-policy', policyName='rac-dev-photo-promoter', userOrGroup=access, isGroup='false')
    app = client(access, secret)

    def denied(call):
        try:
            call()
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode'] == 403:
                return
            raise
        raise AssertionError('Promotion IAM boundary exceeded')

    key, raw = uuid.uuid4().hex+'.jpg', uuid.uuid4().hex+'.raw'
    versions = []
    try:
        owner.put_object(Bucket=staging, Key=key, Body=b'private-staging')
        owner.put_object(Bucket=staging, Key=raw, Body=b'not-a-jpeg')
        assert app.get_object(Bucket=staging, Key=key)['Body'].read() == b'private-staging'
        created = app.put_object(Bucket=media, Key=key, Body=b'approved-fixture', IfNoneMatch='*')
        first = created.get('VersionId')
        assert first and first != 'null', 'Missing provider version'
        versions.append(first)
        try:
            app.put_object(Bucket=media, Key=key, Body=b'replacement', IfNoneMatch='*')
        except ClientError as error:
            assert error.response['ResponseMetadata']['HTTPStatusCode'] == 412
        else:
            raise AssertionError('Conditional media creation replaced an object')
        second = owner.put_object(Bucket=media, Key=key, Body=b'privileged-later-version')['VersionId']
        versions.append(second)
        assert first != second
        exact = app.get_object(Bucket=media, Key=key, VersionId=first)
        assert exact['VersionId'] == first and exact['Body'].read() == b'approved-fixture'
        assert app.get_object(Bucket=media, Key=key)['VersionId'] == second
        denied(lambda: app.get_object(Bucket=staging, Key=raw))
        denied(lambda: app.get_object(Bucket=os.environ['PHOTO_QUARANTINE_BUCKET'], Key=raw))
        denied(lambda: app.put_object(Bucket=staging, Key=key, Body=b'denied'))
        denied(lambda: app.put_object(Bucket=media, Key=raw, Body=b'denied'))
        denied(lambda: app.delete_object(Bucket=media, Key=key))
        denied(lambda: app.delete_object(Bucket=media, Key=key, VersionId=first))
        denied(lambda: app.list_objects_v2(Bucket=media))
        denied(lambda: app.list_object_versions(Bucket=media))
        denied(lambda: app.get_bucket_versioning(Bucket=media))
        denied(lambda: app.put_bucket_versioning(Bucket=media, VersioningConfiguration={'Status': 'Suspended'}))
        denied(lambda: app.put_object_acl(Bucket=media, Key=key, ACL='public-read'))
        denied(lambda: app.put_bucket_policy(Bucket=media, Policy=json.dumps({'Version': '2012-10-17', 'Statement': []})))
        anonymous = boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1', config=Config(signature_version=UNSIGNED))
        denied(lambda: anonymous.get_object(Bucket=media, Key=key))
        print('PASS: private versioned media, exact older-version readback, conditional creation and isolated promotion IAM; no originals, mutation of staging, delete, list, ACL, bucket policy/versioning or anonymous access', flush=True)
    finally:
        owner.delete_object(Bucket=staging, Key=key)
        owner.delete_object(Bucket=staging, Key=raw)
        for version in versions:
            owner.delete_object(Bucket=media, Key=key, VersionId=version)


if __name__ == '__main__':
    main()
