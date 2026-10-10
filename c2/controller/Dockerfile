# syntax=docker/dockerfile:1
# Build context is c2/ (see compose.yaml) so this stage can reach web/.

# ---- stage 1: build the React UI ----
FROM node:20-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Vite builds to ../controller/static (base /static/) → /build/controller/static
RUN npm run build

# ---- stage 2: controller runtime ----
FROM python:3.12-alpine
RUN pip install --no-cache-dir "flask==3.1.*" "docker==7.1.*" "redis==5.2.*"
WORKDIR /app
COPY controller/app.py .
COPY controller/examples ./examples
COPY --from=web /build/controller/static ./static
EXPOSE 8080
CMD ["python", "-u", "app.py"]
