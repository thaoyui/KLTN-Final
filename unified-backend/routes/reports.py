"""Report endpoints"""
from flask import Blueprint, request, jsonify, send_file, current_app
from services import kube_check
from pathlib import Path
import os

bp = Blueprint('reports', __name__)

@bp.route('/api/generate-report', methods=['POST'])
def generate_report():
    """Generate HTML/PDF report"""
    try:
        data = request.json
        selected_items = data.get('selectedItems', [])
        format_type = data.get('format', 'html')
        filename = data.get('filename')
        
        if not selected_items or not isinstance(selected_items, list) or len(selected_items) == 0:
            return jsonify({
                "success": False,
                "error": "Invalid request",
                "message": "selectedItems must be a non-empty array"
            }), 400
        
        if format_type not in ['html', 'pdf']:
            return jsonify({
                "success": False,
                "error": "Invalid format",
                "message": 'Format must be either "html" or "pdf"'
            }), 400
        
        check_ids = [item['id'] for item in selected_items]
        reports_path = current_app.config['REPORTS_PATH']
        
        # Generate filename
        from datetime import datetime
        timestamp = datetime.now().isoformat().replace(':', '-').replace('.', '-')
        if not filename:
            filename = f"kube-check-report-{timestamp}.{format_type}"
        
        output_path = os.path.join(reports_path, filename)
        
        # Run scan and generate report
        # Note: This is simplified - actual implementation would use kube-check's report generation
        result = kube_check.run_scan(check_ids, output_format=format_type)
        
        if result.get('success'):
            # For now, just save results as JSON
            # Full report generation would use kube-check's report templates
            import json
            with open(output_path, 'w') as f:
                json.dump(result.get('results', []), f, indent=2)
            
            file_size = os.path.getsize(output_path)
            
            return jsonify({
                "success": True,
                "message": "Report generated successfully",
                "data": {
                    "filename": filename,
                    "format": format_type,
                    "downloadUrl": f"/api/download-report/{filename}",
                    "checksExecuted": len(check_ids),
                    "timestamp": datetime.now().isoformat(),
                    "size": file_size
                }
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": "Report generation failed",
                "message": result.get('error', 'Unknown error')
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to generate report",
            "message": str(e)
        }), 500

@bp.route('/api/download-report/<filename>', methods=['GET'])
def download_report(filename):
    """Download report file"""
    # Security: prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({
            "success": False,
            "error": "Invalid filename"
        }), 400
    
    reports_path = current_app.config['REPORTS_PATH']
    file_path = os.path.join(reports_path, filename)
    
    if not os.path.exists(file_path):
        return jsonify({
            "success": False,
            "error": "File not found"
        }), 404
    
    return send_file(file_path, as_attachment=True)

@bp.route('/api/reports', methods=['GET'])
def list_reports():
    """List available reports"""
    try:
        reports_path = current_app.config['REPORTS_PATH']
        
        if not os.path.exists(reports_path):
            return jsonify({
                "success": True,
                "data": [],
                "total": 0
            }), 200
        
        files = []
        for filename in os.listdir(reports_path):
            file_path = os.path.join(reports_path, filename)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                files.append({
                    "filename": filename,
                    "size": stat.st_size,
                    "created": stat.st_ctime,
                    "modified": stat.st_mtime,
                    "downloadUrl": f"/api/download-report/{filename}"
                })
        
        # Sort by created time (newest first)
        files.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({
            "success": True,
            "data": files,
            "total": len(files)
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to list reports",
            "message": str(e)
        }), 500





