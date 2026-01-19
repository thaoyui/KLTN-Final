#!/usr/bin/env python3
"""
Unified Flask Backend - Gộp Backend + Kube-check + Ansible
Thay thế Node.js backend bằng Flask server duy nhất
"""
import os
import logging
import time
from flask import Flask, request, g
from flask_cors import CORS
from datetime import datetime

# Import routes
from routes import selections, scans, remediation, k8s, health, audit, mcp
from services.storage import StorageService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Allow all origins for now

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
app.config['JSON_SORT_KEYS'] = False

# Environment variables
K8S_MODE = os.getenv('K8S_MODE', 'local')
CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'default')

# Resolve paths - Support both local and Docker
_base_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_base_dir)

# KUBE_CHECK_PATH:
# - In container: provided via env (e.g. /app/Kube-check, see docker-compose.unified.yml)
# - Local dev: fallback to project path /home/thaopieh/Final/DACN/Kube-check
KUBE_CHECK_PATH = os.getenv('KUBE_CHECK_PATH', "/home/thaopieh/Final/DACN/Kube-check")
KUBE_CHECK_PATH = os.path.abspath(KUBE_CHECK_PATH)
REPORTS_PATH = os.path.join(KUBE_CHECK_PATH, 'reports')
LOGS_DIR = os.getenv('LOGS_DIR', os.path.join(_project_dir, 'logs'))

# Ensure directories exist
try:
    os.makedirs(REPORTS_PATH, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
except (PermissionError, OSError) as e:
    logger.warning(f"Could not create directories: {e}")
    # Use current directory as fallback
    REPORTS_PATH = os.path.join(_base_dir, 'reports')
    LOGS_DIR = os.path.join(_base_dir, 'logs')
    os.makedirs(REPORTS_PATH, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

# Add timing middleware để đo thời gian response
@app.before_request
def before_request():
    """Đo thời gian bắt đầu request"""
    g.start_time = time.time()

@app.after_request
def after_request(response):
    """Thêm timing vào response headers và log"""
    if hasattr(g, 'start_time'):
        duration = time.time() - g.start_time
        # Thêm vào response headers
        response.headers['X-Response-Time'] = f"{duration:.3f}s"
        response.headers['X-Response-Time-Ms'] = f"{int(duration * 1000)}ms"
        
        # Log timing cho các endpoint quan trọng
        if request.path.startswith('/api/scan') or request.path.startswith('/api/k8s'):
            logger.info(f"API {request.method} {request.path} - Response time: {duration:.3f}s")
    
    return response

# Register blueprints
app.register_blueprint(health.bp)
app.register_blueprint(selections.bp)
app.register_blueprint(scans.bp)
app.register_blueprint(remediation.bp)
app.register_blueprint(k8s.bp)
app.register_blueprint(audit.bp)
app.register_blueprint(mcp.bp)

# Store configuration in app context
app.config['K8S_MODE'] = K8S_MODE
app.config['CLUSTER_NAME'] = CLUSTER_NAME
app.config['KUBE_CHECK_PATH'] = KUBE_CHECK_PATH
app.config['REPORTS_PATH'] = REPORTS_PATH
app.config['LOGS_DIR'] = LOGS_DIR

# Initialize SQLite storage service
# Database path: /app/data/scans.db in container, ./data/scans.db locally
storage_service = StorageService()
app.config['storage_service'] = storage_service

# Keep backward compatibility with in-memory storage dict
# (for gradual migration, can be removed later)
app.config['storage'] = {
    'selections': [],
    'scans': []
}

logger.info(f"🚀 Unified Flask Backend started")
logger.info(f"   K8S_MODE: {K8S_MODE}")
logger.info(f"   CLUSTER_NAME: {CLUSTER_NAME}")
logger.info(f"   KUBE_CHECK_PATH: {KUBE_CHECK_PATH}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3001))
    host = os.getenv('IP', '0.0.0.0')
    app.run(host=host, port=port, debug=False)

