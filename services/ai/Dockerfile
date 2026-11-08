FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY common.py project.py project.json ./
COPY services/ai services/ai
USER 10001:10001
CMD ["python", "-m", "services.ai.app"]
