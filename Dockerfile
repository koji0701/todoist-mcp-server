# Generated by https://smithery.ai. See: https://smithery.ai/docs/build/project-config
# Use a lightweight Python image
FROM python:3.12-alpine AS base

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apk add --no-cache build-base

# Copy project manifests
COPY pyproject.toml uv.lock ./

# Install project dependencies
RUN pip install --no-cache-dir .

# Copy source code
COPY . .

# Expose port for SSE transport
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Default command
ENTRYPOINT ["python", "server.py"]
