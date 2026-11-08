FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY services/data/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common.py project.py project.json ./
COPY services/data services/data
USER 10001:10001
CMD ["python", "-m", "services.data.app"]
