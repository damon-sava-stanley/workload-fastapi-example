FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached across source-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as non-root.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

# Bind 0.0.0.0 — binding 127.0.0.1 makes the readiness probe unreachable and
# the workload never goes ready. root_path is set in app code (from the
# WORKLOAD_ID env var DataRobot injects), not via a uvicorn flag, so this
# command is identical whether run locally or as a DataRobot workload.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
