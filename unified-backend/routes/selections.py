"""Benchmark selections endpoints"""
from flask import Blueprint, request, jsonify, current_app
from uuid import uuid4
from datetime import datetime

bp = Blueprint('selections', __name__)

@bp.route('/api/selections', methods=['GET'])
def get_selections():
    """Get all benchmark selections"""
    storage_service = current_app.config.get('storage_service')
    if storage_service:
        selections = storage_service.get_all_selections()
        total = len(selections)
    else:
        # Fallback to in-memory storage
        storage = current_app.config['storage']
        selections = storage['selections']
        total = len(selections)
    
    return jsonify({
        "success": True,
        "data": selections,
        "total": total
    }), 200

@bp.route('/api/selections', methods=['POST'])
def create_selection():
    """Submit new benchmark selection"""
    try:
        data = request.json
        selected_items = data.get('selectedItems', [])
        metadata = data.get('metadata', {})
        
        if not selected_items or not isinstance(selected_items, list):
            return jsonify({
                "success": False,
                "error": "Invalid request",
                "message": "selectedItems must be a non-empty array"
            }), 400
        
        # Validate items
        for item in selected_items:
            if not item.get('id') or not item.get('title'):
                return jsonify({
                    "success": False,
                    "error": "Invalid item format",
                    "message": "Each item must have id and title"
                }), 400
        
        # Create selection record
        selection = {
            "id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "selectedItems": selected_items,
            "totalSelected": len(selected_items),
            "metadata": {
                "userAgent": request.headers.get('User-Agent'),
                "ipAddress": request.remote_addr,
                **metadata
            },
            "status": "submitted"
        }
        
        # Save to storage
        storage_service = current_app.config.get('storage_service')
        if storage_service:
            storage_service.create_selection({
                'id': selection['id'],
                'name': metadata.get('name'),
                'description': metadata.get('description'),
                'selectedItems': selected_items,
                'timestamp': selection['timestamp']
            })
        else:
            # Fallback to in-memory storage
            storage = current_app.config['storage']
            storage['selections'].append(selection)
        
        return jsonify({
            "success": True,
            "message": "Benchmark selection submitted successfully",
            "data": {
                "selectionId": selection['id'],
                "totalSelected": len(selected_items),
                "timestamp": selection['timestamp']
            }
        }), 201
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to process selection",
            "message": str(e)
        }), 500

@bp.route('/api/selections/<selection_id>', methods=['GET'])
def get_selection(selection_id):
    """Get specific selection by ID"""
    storage_service = current_app.config.get('storage_service')
    if storage_service:
        selection = storage_service.get_selection(selection_id)
    else:
        # Fallback to in-memory storage
        storage = current_app.config['storage']
        selection = next((s for s in storage['selections'] if s['id'] == selection_id), None)
    
    if not selection:
        return jsonify({
            "success": False,
            "error": "Selection not found",
            "message": f"No selection found with ID: {selection_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": selection
    }), 200





