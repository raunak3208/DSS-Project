FROM python:3.11-slim
WORKDIR /app
COPY controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY controller/aiops_controller /app/aiops_controller
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "aiops_controller.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
