FROM python:3.11-slim
WORKDIR /app
COPY services/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY services/svc /app/svc
COPY loadgen/loadgen.py /app/loadgen.py
ENV PYTHONPATH=/app/common:/app PYTHONUNBUFFERED=1
CMD ["uvicorn", "svc.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
