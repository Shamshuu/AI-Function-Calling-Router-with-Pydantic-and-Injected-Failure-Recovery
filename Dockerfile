FROM python:3.11-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# One-shot evaluation job: runs the harness and writes ./output/metrics.json
CMD ["python", "evaluate_router.py"]
