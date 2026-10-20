FROM python:3.13-alpine
RUN pip install --no-cache-dir boto3==1.40.59
WORKDIR /test
COPY scripts/test_storage.py scripts/configure_storage.py /test/
USER 10001:10001
ENTRYPOINT ["python", "test_storage.py"]
