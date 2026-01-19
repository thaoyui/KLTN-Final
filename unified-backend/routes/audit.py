"""Audit log endpoints"""
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint('audit', __name__)


@bp.route('/api/audit', methods=['GET'])
def get_audit_events():
    """Return recent audit events (remediations, scans, manual actions)"""
    try:
        storage_service = current_app.config.get('storage_service')
        if not storage_service:
            return jsonify({
                "success": False,
                "error": "Storage service not available"
            }), 500

        limit = request.args.get('limit', default=50, type=int)
        event_type = request.args.get('type')  # e.g. remediation, scan

        events = storage_service.get_audit_events(limit=limit, event_type=event_type)

        return jsonify({
            "success": True,
            "data": events,
            "total": len(events)
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to load audit events",
            "details": str(e)
        }), 500


