FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLATFORMIO_CORE_DIR=/data/pio
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py flash_bundle.py flash_local.py flash_ui.html ./
RUN useradd --system --uid 10001 --create-home builder && mkdir -p /data /run/secrets && chown -R builder:builder /data /srv/app
USER builder
EXPOSE 8080
CMD ["python","app.py"]
