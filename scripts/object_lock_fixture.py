"""Synthetic provider capability proof, not legal certification or production setup."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid

import boto3
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials
from botocore.exceptions import ClientError


def main():
    endpoint=os.environ['S3_ENDPOINT']
    if endpoint!='http://evidence-storage-fixture:9000':
        raise RuntimeError('Only the disposable capability fixture is accepted')
    client=boto3.client('s3',endpoint_url=endpoint,region_name='us-east-1',config=Config(signature_version='s3v4',s3={'addressing_style':'path'}))
    if len(sys.argv)>1:
        state=json.loads(Path(sys.argv[1]).read_text())
        stored=client.get_object(Bucket=state['bucket'],Key=state['key'],VersionId=state['version'])['Body'].read()
        assert hashlib.sha256(stored).hexdigest()==state['digest']
        retention=client.get_object_retention(Bucket=state['bucket'],Key=state['key'],VersionId=state['version'])['Retention']
        assert retention['Mode']=='COMPLIANCE' and retention['RetainUntilDate']>datetime.now(timezone.utc)
        print('PASS: version-specific bytes and COMPLIANCE retention survive storage process restart',flush=True)
        return
    def denied(call):
        try:
            call()
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode']==403:
                return
            raise
        raise AssertionError('Object Lock capability gate failed: protected operation succeeded')
    bucket='rac-evidence-fixture-'+uuid.uuid4().hex[:16]
    key='synthetic-evidence.bin'
    raw=b'RAC synthetic evidence capability fixture; no personal data'
    until=datetime.now(timezone.utc)+timedelta(minutes=5)
    client.create_bucket(Bucket=bucket,ObjectLockEnabledForBucket=True)
    assert client.get_bucket_versioning(Bucket=bucket)['Status']=='Enabled'
    assert client.get_object_lock_configuration(Bucket=bucket)['ObjectLockConfiguration']['ObjectLockEnabled']=='Enabled'
    result=client.put_object(Bucket=bucket,Key=key,Body=raw,ObjectLockMode='COMPLIANCE',ObjectLockRetainUntilDate=until)
    version=result.get('VersionId')
    assert version and version!='null','Version ID is mandatory for evidence references'
    denied(lambda:client.delete_object(Bucket=bucket,Key=key,VersionId=version))
    denied(lambda:client.delete_object(Bucket=bucket,Key=key,VersionId=version,BypassGovernanceRetention=True))
    denied(lambda:client.put_object_retention(Bucket=bucket,Key=key,VersionId=version,Retention={'Mode':'COMPLIANCE','RetainUntilDate':until-timedelta(minutes=1)},BypassGovernanceRetention=True))
    denied(lambda:client.put_object_retention(Bucket=bucket,Key=key,VersionId=version,Retention={'Mode':'GOVERNANCE','RetainUntilDate':until},BypassGovernanceRetention=True))
    # A new version/delete marker must not destroy the retained version. Never
    # confuse protection of a version with protection of the latest key view.
    replacement=client.put_object(Bucket=bucket,Key=key,Body=b'synthetic replacement')
    assert replacement.get('VersionId') and replacement['VersionId']!=version
    client.delete_object(Bucket=bucket,Key=key)
    assert client.get_object(Bucket=bucket,Key=key,VersionId=version)['Body'].read()==raw
    # Regression GHSA-28w4-rp2p-636w: only target our newly created disposable
    # bucket. A force-delete must not bypass protected retained versions.
    url=endpoint+'/'+bucket
    request=AWSRequest(method='DELETE',url=url,headers={'x-rustfs-force-delete':'true'})
    S3SigV4Auth(Credentials(os.environ['AWS_ACCESS_KEY_ID'],os.environ['AWS_SECRET_ACCESS_KEY']),'s3','us-east-1').add_auth(request)
    signed=request.prepare()
    try:
        with urllib.request.urlopen(urllib.request.Request(signed.url,method='DELETE',headers=dict(signed.headers)),timeout=15):
            pass
    except urllib.error.HTTPError as error:
        if error.code not in (400,403,409):
            raise
    else:
        raise AssertionError('Object Lock gate failed: force-delete accepted retained bucket')
    assert client.get_object(Bucket=bucket,Key=key,VersionId=version)['Body'].read()==raw
    held=client.put_object(Bucket=bucket,Key='synthetic-hold.bin',Body=b'synthetic hold',ObjectLockLegalHoldStatus='ON')['VersionId']
    denied(lambda:client.delete_object(Bucket=bucket,Key='synthetic-hold.bin',VersionId=held))
    client.put_object_legal_hold(Bucket=bucket,Key='synthetic-hold.bin',VersionId=held,LegalHold={'Status':'OFF'})
    client.delete_object(Bucket=bucket,Key='synthetic-hold.bin',VersionId=held)
    print(json.dumps({'bucket':bucket,'key':key,'version':version,'digest':hashlib.sha256(raw).hexdigest()}),flush=True)


if __name__=='__main__':
    main()
