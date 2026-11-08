FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY common.py project.py project.json ./
COPY services/reviews services/reviews
USER 10001:10001
CMD ["python", "-m", "services.reviews.app"]
