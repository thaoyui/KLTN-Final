"""K8s/Ansible endpoints"""
from flask import Blueprint, request, jsonify, current_app
from services import ansible_service as ansible_svc

bp = Blueprint('k8s', __name__)

@bp.route('/api/k8s/connect', methods=['POST'])
def connect_k8s():
    """Test connection to K8s cluster"""
    try:
        data = request.json
        kubeconfig = data.get('kubeconfig')
        cluster_name = data.get('clusterName') or current_app.config.get('CLUSTER_NAME', 'default')
        nodes = data.get('nodes', [])
        
        if not cluster_name:
            return jsonify({
                "success": False,
                "error": "clusterName is required"
            }), 400
        
        result = ansible_svc.test_connection(cluster_name, kubeconfig, nodes)
        
        return jsonify({
            "success": result.get('success', False),
            "message": result.get('message', 'Connection test completed'),
            "details": result.get('details', result)
        }), 200 if result.get('success') else 500
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to test connection",
            "details": str(e)
        }), 500

# New: fetch inventory nodes
@bp.route('/api/k8s/inventory', methods=['GET'])
def get_inventory():
    """Return nodes from Ansible inventory"""
    cluster_name = request.args.get('clusterName') or current_app.config.get('CLUSTER_NAME', 'default')
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    try:
        result = ansible_svc.get_inventory_nodes(cluster_name, force_refresh=force_refresh)
        status_code = 200 if result.get('success') else 404
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to load inventory",
            "details": str(e)
        }), 500


@bp.route('/api/k8s/bootstrap', methods=['POST'])
def bootstrap_nodes():
    """Run bootstrap playbook on selected nodes"""
    try:
        data = request.json or {}
        cluster_name = data.get('clusterName') or current_app.config.get('CLUSTER_NAME', 'default')
        node_names = data.get('nodeNames') or data.get('nodeName')
        
        # Validate input
        if not node_names:
            return jsonify({
                "success": False,
                "error": "nodeNames is required"
            }), 400
        
        if not isinstance(node_names, list) and not isinstance(node_names, str):
            return jsonify({
                "success": False,
                "error": "nodeNames must be a list or string"
            }), 400

        result = ansible_svc.bootstrap(cluster_name, node_names)

        # Audit bootstrap action
        storage_service = current_app.config.get('storage_service')
        if storage_service:
            try:
                # Normalize node names to string for logging
                if isinstance(node_names, list):
                    node_name_str = ",".join(str(n) for n in node_names)
                else:
                    node_name_str = str(node_names)

                storage_service.log_audit_event({
                    "type": "bootstrap",
                    "check_id": None,
                    "node_name": node_name_str,
                    "cluster_name": cluster_name,
                    "action": "Run bootstrap playbook",
                    "command": "ansible-playbook kube-check-bootstrap.yml",
                    "source": "ansible",
                    "status": "SUCCESS" if result.get("success") else "FAILED",
                    "user": "ui",
                    "details": {
                        "request": {
                            "clusterName": cluster_name,
                            "nodeNames": node_names,
                        },
                        "response": result,
                    },
                })
            except Exception:
                current_app.logger.warning("Failed to log bootstrap audit event", exc_info=True)

        # Thêm API timing vào response
        from flask import g
        import time
        if hasattr(g, 'start_time'):
            api_duration = time.time() - g.start_time
            result["api_timing"] = {
                "api_processing_seconds": round(api_duration, 3),
                "total_response_seconds": round(api_duration, 3)
            }
        
        status_code = 200 if result.get('success') else 500
        return jsonify(result), status_code
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        current_app.logger.error(f"Bootstrap error: {e}\n{error_details}")
        return jsonify({
            "success": False,
            "error": "Failed to bootstrap nodes",
            "details": str(e),
            "traceback": error_details if current_app.debug else None
        }), 500
