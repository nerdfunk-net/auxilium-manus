FROM python:3.12-slim

# pyATS/Unicon need a real ssh client (device connections) and a build
# toolchain for the couple of C extensions pulled in transitively.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        openssh-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8100

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PYATS_SHIM_PORT:-8100}"]
