# Ansible Service Dockerfile
FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    sshpass \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Ansible and Python dependencies
RUN pip install --no-cache-dir \
    ansible==7.7.0 \
    ansible-core==2.14.5 \
    kubernetes==27.2.0 \
    flask==2.3.3 \
    flask-cors==4.0.0 \
    requests==2.31.0 \
    pyyaml==6.0.1

# Set working directory
WORKDIR /app

# Copy requirements
COPY ansible-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ansible-service/ ./

# Copy Ansible configuration
COPY ansible/ /app/ansible/

# Create necessary directories
RUN mkdir -p /app/logs /app/ansible/ssh_keys /root/.ssh && \
    chmod 700 /root/.ssh

# Set Ansible configuration
ENV ANSIBLE_HOST_KEY_CHECKING=False
ENV ANSIBLE_SSH_ARGS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
ENV ANSIBLE_CONFIG=/app/ansible/ansible.cfg

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

# Start service
CMD ["python", "app.py"]

