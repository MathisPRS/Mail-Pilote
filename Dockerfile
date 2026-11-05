# syntax=docker/dockerfile:1
FROM --platform=linux/amd64 node:22-slim AS front
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM --platform=linux/amd64 python:3.12-slim
# Node 22 : requis par le CLI Claude Code (copié depuis l'image node)
COPY --from=front /usr/local/bin/node /usr/local/bin/node
COPY --from=front /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && npm i -g @anthropic-ai/claude-code@2.1.318 \
 && npm cache clean --force

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin mailpilot \
 && mkdir /data && chown 1000:1000 /data

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY --from=front /build/dist /app/frontend/dist

ENV DATA_DIR=/data \
    MP_FRONTEND_DIST=/app/frontend/dist \
    PYTHONUNBUFFERED=1
VOLUME /data
USER 1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000","--no-proxy-headers"]
