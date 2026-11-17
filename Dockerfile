FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && chmod -R a+rX /app && useradd --uid 10001 --create-home app
USER app
EXPOSE 8000
CMD ["sh", "scripts/start_api.sh"]
