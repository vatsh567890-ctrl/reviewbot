FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install git, ca-certificates, Node.js, and npm
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install ESLint globally for JavaScript/TypeScript analysis
RUN npm install -g eslint

# Copy package source and manifests
COPY pyproject.toml README.md /app/
COPY reviewbot/ /app/reviewbot/

# Install reviewbot and pinned dependencies (ruff version matches pyproject.toml)
RUN pip install ruff==0.17.2 && pip install .

ENTRYPOINT ["python", "-m", "reviewbot.cli"]
