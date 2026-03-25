FROM python:3.12-slim

WORKDIR /app

# System deps for pymysql (pure-Python, no native libs needed) + gcc for cryptography
# Use Alibaba Cloud apt mirror for faster installs inside mainland China
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY . .

# Don't run as root
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# TCP terminal port + HTTP API port
EXPOSE 8808
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "main.py"]
