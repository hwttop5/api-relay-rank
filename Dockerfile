FROM node:20-bookworm-slim

ARG SUPERCRONIC_VERSION=v0.2.29
ARG NEXT_PUBLIC_SITE_URL=
ARG NEXT_PUBLIC_BAIDU_TONGJI_ID=

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TZ=Asia/Shanghai \
    PORT=3000 \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    NEXT_PUBLIC_BAIDU_TONGJI_ID=${NEXT_PUBLIC_BAIDU_TONGJI_ID} \
    PATH=/app/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip curl ca-certificates tini tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
      amd64) supercronic_arch="amd64" ;; \
      arm64) supercronic_arch="arm64" ;; \
      *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/supercronic "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${supercronic_arch}" \
    && chmod +x /usr/local/bin/supercronic

COPY package.json package-lock.json requirements.txt ./

RUN npm ci --include=dev --ignore-scripts \
    && python -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

RUN npm run build

ENTRYPOINT ["tini", "--"]
CMD ["sh", "deploy/start-app.sh"]
