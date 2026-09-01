FROM python:3.12-alpine

WORKDIR /app
COPY web/ /app/web/

EXPOSE 8787
CMD ["python3", "/app/web/relay_server.py", "--host", "0.0.0.0", "--port", "8787", "--state", "/data/state.json"]
