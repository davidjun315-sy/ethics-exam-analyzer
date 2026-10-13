# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Optional build-only CA for corporate/proxy environments; TLS verification stays enabled.
RUN --mount=type=secret,id=build_ca,required=false,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; printf 'Acquire::https::CaInfo "/run/secrets/build_ca";\n' > /etc/apt/apt.conf.d/99-build-ca; fi && \
    apt-get update && apt-get install -y --no-install-recommends libstdc++6 fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99-build-ca
WORKDIR /app
COPY requirements.lock .
RUN --mount=type=secret,id=build_ca,required=false,mode=0444 \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi && \
    pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p storage && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
