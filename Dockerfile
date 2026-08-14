FROM python:3.12-slim
WORKDIR /app
COPY server.py index.html README.md ./
ENV PORT=8787 PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "server.py"]
