# Multi-stage: build frontend, then runtime image.
#
# NOTE (v1): This Dockerfile requires `observatory/web-src/` scaffolding
# which lands in Task 9 (frontend bootstrap). Building this image in v1
# will fail at the `COPY observatory/web-src/package.json ...` step
# because the directory doesn't exist yet. The Dockerfile is checked in
# now as a shape-for-v2 so the deploy story is visible end-to-end.
FROM node:20-alpine AS frontend
WORKDIR /src
COPY observatory/web-src/package.json observatory/web-src/package-lock.json* ./
RUN npm ci
COPY observatory/web-src/ ./
RUN npm run build
# outputs to /src/../web — bring it into the runtime stage via COPY below.

FROM python:3.11-slim AS runtime
WORKDIR /app
COPY observatory/pyproject.toml ./observatory/
RUN pip install --no-cache-dir flit_core && pip install --no-cache-dir ./observatory
COPY observatory/ ./observatory/
COPY --from=frontend /src/../web ./observatory/web
ENV OBSERVATORY_BIND_HOST=0.0.0.0
ENV OBSERVATORY_BIND_PORT=8765
EXPOSE 8765
CMD ["python", "-m", "observatory"]
