FROM restic/restic:0.19.1 AS restic
FROM postgres:16-alpine
RUN apk add --no-cache python3 py3-pip && python3 -m venv /opt/backup && /opt/backup/bin/pip install --no-cache-dir "psycopg[binary]==3.3.6" boto3==1.40.59
COPY --from=restic /usr/bin/restic /usr/bin/restic
WORKDIR /tools
COPY scripts/backup.py /tools/backup.py
ENV PATH="/opt/backup/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 RESTIC_REPOSITORY=/backups/repository RESTIC_CACHE_DIR=/work/cache HOME=/work
USER 10001:10001
ENTRYPOINT ["python", "/tools/backup.py"]
CMD ["schedule"]
