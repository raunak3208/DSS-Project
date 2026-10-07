FROM python:3.11-slim
WORKDIR /app
COPY processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY processor/aiops_processor /app/aiops_processor
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
CMD ["python", "-m", "aiops_processor.main"]
