FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend ./frontend
ENV VITE_API_URL=""
RUN npm --prefix frontend run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NEXUS_SERVE_FRONTEND=true \
    NEXUS_FRONTEND_DIST_PATH=frontend/dist
WORKDIR /app
COPY requirements.txt requirements-online.txt ./
RUN pip install --no-cache-dir -r requirements-online.txt
COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/data
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
