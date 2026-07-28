# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

# Install system dependencies required by the runner:
# - openssh-client: for SSH key-based auth (asyncssh needs ssh-keygen)
# - docker-cli: for Docker container management on the host
# - kubectl: for applying manifests
# - helm: for installing Helm charts (EBS CSI driver)
# - curl: for fetching install scripts
# - git: for cloning VPA autoscaler repo during install
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    gnupg \
    apt-transport-https \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian bookworm stable" \
    > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | gpg --dearmor -o /usr/share/keyrings/kubernetes-apt-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /" \
    > /etc/apt/sources.list.d/kubernetes.list \
    && apt-get update && apt-get install -y --no-install-recommends kubectl \
    && rm -rf /var/lib/apt/lists/*

# Install Helm
RUN curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies only (no dev deps)
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY src/ ./src/
COPY main.py ./
COPY README.md ./

# Install the project itself
RUN uv sync --frozen --no-dev

# Create .kube directory for kubeconfig
RUN mkdir -p /root/.kube

# Expose the Runner API port
EXPOSE 8080

# Run the application
CMD ["uv", "run", "python", "main.py"]
