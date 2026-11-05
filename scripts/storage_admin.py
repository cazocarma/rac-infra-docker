"""Shared signed RustFS administration transport; no environment side effects."""
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest


def admin(endpoint, credentials, path, body=None, method='PUT', **query):
    url = endpoint + '/rustfs/admin/v3/' + path
    if query:
        url += '?' + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else b''
    request = AWSRequest(method=method, url=url, data=data, headers={'Content-Type': 'application/json'})
    S3SigV4Auth(credentials, 's3', 'us-east-1').add_auth(request)
    signed = request.prepare()
    try:
        with urllib.request.urlopen(urllib.request.Request(signed.url, data=data, method=method, headers=dict(signed.headers)), timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as error:
        # Never expose a signed URL, credentials or response payload.
        try:
            code = ET.fromstring(error.read()).findtext('Code')
        except ET.ParseError:
            code = 'unparseable-response'
        raise RuntimeError('Storage admin failure: '+str(error.code)+' '+str(code)) from None
