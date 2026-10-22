FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manus_agent ./manus_agent
# The shipped example handlers; mount your own directory over /app/handlers (see README.md).
COPY handlers ./handlers

# Run unprivileged: the agent holds the shared secret and sees the data it is sent.
RUN useradd --system --create-home agent
USER agent

ENV PYTHONUNBUFFERED=1 \
    MANUS_AGENT_HTTP_HOST=0.0.0.0 \
    MANUS_AGENT_HANDLERS_DIR=/app/handlers
EXPOSE 8080

# MANUS_AGENT_ID, MANUS_AGENT_SECRET and MANUS_AGENT_HTTP_PORT and/or MANUS_AGENT_REDIS_URL
# are required at run time (see .env.example).
CMD ["python", "-m", "manus_agent"]
