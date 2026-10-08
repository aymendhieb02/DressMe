FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/ml-service
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY bundle ./bundle
RUN python bundle/selftest.py > /tmp/bundle-selftest.json \
    && python -c "import json; r=json.load(open('/tmp/bundle-selftest.json')); assert r.get('passed') is True, r"

COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
