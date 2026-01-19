# Unified Flask Backend Dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    sshpass \
    git \
    build-essential \
    curl \
    ca-certificates \
    rsync \
    libpopt0 \
    && rm -rf /var/lib/apt/lists/*

# Install kubeconform
RUN KUBECONFORM_VERSION="v0.7.0" && \
    # Dynamically detect the architecture
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        KUBE_ARCH="amd64"; \
    elif [ "$ARCH" = "arm64" ]; then \
        KUBE_ARCH="arm64"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    echo "Installing kubeconform ${KUBECONFORM_VERSION} for ${KUBE_ARCH}..." && \
    curl -L "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-${KUBE_ARCH}.tar.gz" -o /tmp/kubeconform.tar.gz && \
    tar -xzf /tmp/kubeconform.tar.gz -C /tmp && \
    mv /tmp/kubeconform /usr/local/bin/kubeconform && \
    chmod +x /usr/local/bin/kubeconform && \
    rm -rf /tmp/kubeconform* && \
    # Verify installation
    kubeconform -v    
# Set working directory
WORKDIR /app

# Copy requirements
COPY unified-backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY unified-backend/ ./

# Copy Ansible configuration (playbooks will also be mounted as volume)
COPY ansible/ /app/ansible/

# Create necessary directories (logs, ssh keys, kubeconfig, SQLite data)
RUN mkdir -p /app/logs /app/ansible/ssh_keys /app/data /root/.ssh && \
    chmod 700 /root/.ssh

# Configure git (for MCP bot commits)
RUN git config --global user.email "trinhthao1@gmail.com" && \
    git config --global user.name "Trinh Thao"

# Set environment variables
ENV ANSIBLE_HOST_KEY_CHECKING=False
ENV ANSIBLE_SSH_ARGS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
ENV ANSIBLE_CONFIG=/app/ansible/ansible.cfg
ENV PYTHONUNBUFFERED=1
ENV K8S_MODE=local
ENV CLUSTER_NAME=default
ENV KUBE_CHECK_PATH=/app/Kube-check
ENV PORT=3001
ENV IP=0.0.0.0

# Expose port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:3001/health')" || exit 1

# Start service
CMD ["python", "app.py"]





