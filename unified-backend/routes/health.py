"""Health check endpoints"""
from flask import Blueprint, jsonify
from datetime import datetime

bp = Blueprint('health', __name__)

@bp.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "OK",
        "timestamp": datetime.now().isoformat(),
        "service": "Kubernetes CIS Benchmark API (Unified Flask Backend)"
    }), 200





