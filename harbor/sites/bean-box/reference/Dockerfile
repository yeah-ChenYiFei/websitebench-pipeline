FROM python:3.12-slim
WORKDIR /srv/reference
COPY . .
ENV PORT=8080
HEALTHCHECK --interval=2s --timeout=3s --retries=30 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["python", "server.py"]
