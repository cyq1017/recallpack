FROM python:3.12-slim

WORKDIR /app

ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken

COPY requirements-v4.txt /app/requirements-v4.txt
RUN pip install --no-cache-dir -r requirements-v4.txt
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

COPY src /app/src
COPY fixtures /app/fixtures
COPY specs/001-recallpack-v4/contracts /app/specs/001-recallpack-v4/contracts
COPY web /app/web
COPY docs/submission /app/docs/submission

ENV PYTHONPATH=/app/src
ENV RECALLPACK_SQLITE_PATH=/data/recallpack.sqlite3

EXPOSE 8789

CMD ["python", "-m", "recallpack.demo_server", "--host", "0.0.0.0", "--port", "8789", "--root", "/app"]
