"""Scan endpoints"""
from flask import Blueprint, request, jsonify, current_app
from uuid import uuid4
from datetime import datetime, timezone
import asyncio
import yaml
import os
from pathlib import Path
from services import kube_check
from services import ansible_service as ansible_svc

bp = Blueprint('scans', __name__)

def _get_kube_variable_substitutions() -> dict:
    """Get variable substitutions mapping for Kube-check"""
    return {
        '$apiserverconf': '/etc/kubernetes/manifests/kube-apiserver.yaml',
        '$controllermanagerconf': '/etc/kubernetes/manifests/kube-controller-manager.yaml',
        '$schedulerconf': '/etc/kubernetes/manifests/kube-scheduler.yaml',
        '$etcdconf': '/etc/kubernetes/manifests/etcd.yaml',
        '$apiserverbin': 'kube-apiserver',
        '$controllermanagerbin': 'kube-controller-manager',
        '$schedulerbin': 'kube-scheduler',
        '$etcdbin': 'etcd',
        '$kubeletbin': 'kubelet',
        '$etcddatadir': '/var/lib/etcd',
        '$schedulerkubeconfig': '/etc/kubernetes/scheduler.conf',
        '$controllermanagerkubeconfig': '/etc/kubernetes/controller-manager.conf',
        '$kubeletsvc': '/usr/lib/systemd/system/kubelet.service.d/10-kubeadm.conf',
        '$kubeletkubeconfig': '/etc/kubernetes/kubelet.conf',
        '$kubeletconf': '/var/lib/kubelet/config.yaml',
        '$kubeletcafile': '/etc/kubernetes/pki/ca.crt',
        '$proxybin': 'kube-proxy',
        '$proxykubeconfig': '/var/lib/kube-proxy/kubeconfig.conf',
        '$proxyconf': '/var/lib/kube-proxy/config.conf'
    }

def _apply_variable_substitutions(text: str) -> str:
    """Apply variable substitutions to shell command text"""
    if not text:
        return text
    
    substitutions = _get_kube_variable_substitutions()
    result = text
    for var, value in substitutions.items():
        result = result.replace(var, value)
    return result

def _extract_shell_commands_from_checks(check_ids: list) -> dict:
    """
    Extract actual shell commands (audit/audit_config) from Kube-check YAML config files
    Returns dict mapping check_id -> list of commands (with variables substituted)
    """
    commands_map = {}
    
    try:
        # Find Kube-check config directory
        kube_check_path = os.getenv('KUBE_CHECK_PATH', os.path.join(os.path.dirname(__file__), '..', '..', 'Kube-check'))
        config_dir = os.path.join(kube_check_path, 'config')
        
        if not os.path.exists(config_dir):
            current_app.logger.warning(f"Kube-check config directory not found: {config_dir}")
            return commands_map
        
        # Config file mapping (same as in kube_check.py)
        config_mapping = {
            '1.1': 'master.yaml',
            '1.2': 'master.yaml',
            '1.3': 'master.yaml',
            '1.4': 'master.yaml',
            '2.': 'etcd.yaml',
            '3.': 'controlplane.yaml',
            '4.': 'node.yaml',
            '5.': 'policies.yaml'
        }
        
        # Group check_ids by config file
        config_files = {}
        for check_id in check_ids:
            config_file = None
            for prefix, file_name in config_mapping.items():
                if check_id.startswith(prefix):
                    config_file = file_name
                    break
            
            if not config_file:
                continue
            
            if config_file not in config_files:
                config_files[config_file] = []
            config_files[config_file].append(check_id)
        
        # Parse each config file and extract commands
        for config_file, check_ids_in_file in config_files.items():
            config_path = os.path.join(config_dir, config_file)
            if not os.path.exists(config_path):
                continue
            
            try:
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
                
                # Navigate through config structure: groups -> checks
                if isinstance(config_data, dict) and 'groups' in config_data:
                    for group in config_data.get('groups', []):
                        if isinstance(group, dict) and 'checks' in group:
                            for check in group.get('checks', []):
                                check_id = check.get('id')
                                if check_id in check_ids_in_file:
                                    commands = []
                                    
                                    # Extract audit command and substitute variables
                                    audit_cmd = check.get('audit')
                                    if audit_cmd:
                                        commands.append(_apply_variable_substitutions(audit_cmd))
                                    
                                    # Extract audit_config command and substitute variables
                                    audit_config_cmd = check.get('audit_config')
                                    if audit_config_cmd:
                                        commands.append(_apply_variable_substitutions(audit_config_cmd))
                                    
                                    if commands:
                                        commands_map[check_id] = commands
            except Exception as e:
                current_app.logger.warning(f"Failed to parse config file {config_file}: {e}")
                continue
        
    except Exception as e:
        current_app.logger.warning(f"Error extracting shell commands from checks: {e}")
    
    return commands_map

@bp.route('/api/scan', methods=['POST'])
def start_scan():
    """Start benchmark scan"""
    try:
        data = request.json
        selection_id = data.get('selectionId')
        config = data.get('config', {})
        cluster_name = data.get('clusterName')
        node_name = data.get('nodeName')      
        if not selection_id:
            return jsonify({
                "success": False,
                "error": "Selection ID is required"
            }), 400       
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
                "error": "Selection not found"
            }), 404      
        # Determine scan mode
        k8s_mode = current_app.config.get('K8S_MODE', 'local')
        # If frontend sends nodeName, force remote mode so Ansible is used per-node
        if node_name:
            scan_mode = 'remote'
        else:
            scan_mode = 'remote' if (k8s_mode == 'remote' and cluster_name) else 'local'   
        # Enforce node_name for remote scans to avoid falling back to wrong host
        if scan_mode == 'remote' and not node_name:
            return jsonify({
                "success": False,
                "error": "nodeName is required for remote scans"
            }), 400
        effective_cluster_name = cluster_name or current_app.config.get('CLUSTER_NAME', 'default')
        # Create scan job
        now_utc = datetime.now(timezone.utc)
        scan_job = {
            "id": str(uuid4()),
            "selectionId": selection_id,
            "status": "running",
            "startTime": now_utc.isoformat(),
            "timestamp": now_utc.isoformat(),  # Add timestamp field for easy access
            "config": config,
            "progress": 0,
            "results": [],
            "mode": scan_mode,
            "clusterName": effective_cluster_name,
            "nodeName": node_name
        }
        # Save to storage
        storage_service = current_app.config.get('storage_service')
        if storage_service:
            storage_service.create_scan(scan_job)
        else:
            # Fallback to in-memory storage
            storage = current_app.config['storage']
            storage['scans'].append(scan_job)
        
        current_app.logger.info(f"Start scan: selection={selection_id}, mode={scan_mode}, cluster={effective_cluster_name}, node={node_name}")

        # Start scan in background
        if scan_mode == 'remote':
            # Use Ansible Service
            _start_remote_scan(scan_job, selection['selectedItems'], effective_cluster_name, node_name)
        else:
            # Use local Kube-check
            _start_local_scan(scan_job, selection['selectedItems'])
        
        return jsonify({
            "success": True,
            "message": "Benchmark scan started",
            "data": {
                "scanId": scan_job['id'],
                "selectionId": selection_id,
                "status": "running",
                "mode": scan_mode,
                "clusterName": effective_cluster_name,
                "estimatedDuration": f"{len(selection['selectedItems']) * 2} seconds"
            }
        }), 202
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to start scan",
            "message": str(e)
        }), 500

@bp.route('/api/scan/<scan_id>', methods=['GET'])
def get_scan(scan_id):
    """Get scan status and results"""
    from flask import g
    import time
    
    api_start_time = time.time()
    
    storage_service = current_app.config.get('storage_service')
    if storage_service:
        scan = storage_service.get_scan(scan_id)
    else:
        # Fallback to in-memory storage
        storage = current_app.config['storage']
        scan = next((s for s in storage['scans'] if s['id'] == scan_id), None)
    
    if not scan:
        return jsonify({
            "success": False,
            "error": "Scan not found"
        }), 404
    
    api_duration = time.time() - api_start_time
    
    response_data = {
        "success": True,
        "data": scan
    }
    
    # Thêm API timing vào response
    if hasattr(g, 'start_time'):
        response_data["api_timing"] = {
            "api_processing_seconds": round(api_duration, 3),
            "total_response_seconds": round(time.time() - g.start_time, 3)
        }
    
    return jsonify(response_data), 200

@bp.route('/api/scan/<scan_id>/timing', methods=['GET'])
def get_scan_timing(scan_id):
    """Get timing information for a scan"""
    from flask import g
    import time
    
    api_start_time = time.time()
    
    storage_service = current_app.config.get('storage_service')
    if storage_service:
        scan = storage_service.get_scan(scan_id)
    else:
        # Fallback to in-memory storage
        storage = current_app.config['storage']
        scan = next((s for s in storage['scans'] if s['id'] == scan_id), None)
    
    if not scan:
        return jsonify({
            "success": False,
            "error": "Scan not found"
        }), 404
    
    timing = scan.get('timing', {})
    if not timing:
        return jsonify({
            "success": False,
            "error": "Timing information not available for this scan"
        }), 404
    
    api_duration = time.time() - api_start_time
    
    # Tính toán breakdown chi tiết
    ansible_breakdown = timing.get('ansible_breakdown', {})
    
    response_data = {
        "success": True,
        "scanId": scan_id,
        "status": scan.get('status'),
        "timing": timing,
        "summary": {
            "connection_to_node_seconds": timing.get('connection_to_node_seconds', timing.get('connection_seconds', ansible_breakdown.get('connection_seconds', 0))),
            "file_checks_seconds": timing.get('file_checks_seconds', ansible_breakdown.get('file_checks_seconds', 0)),
            "task_execution_seconds": timing.get('task_execution_seconds', timing.get('execution_seconds', ansible_breakdown.get('execution_seconds', 0))),
            "result_fetch_seconds": timing.get('result_fetch_seconds', timing.get('fetch_seconds', ansible_breakdown.get('fetch_seconds', 0))),
            "total_seconds": timing.get('total_seconds', 0)
        },
        "detailed_breakdown": {
            # Python service timing
            "inventory_lookup_seconds": timing.get('inventory_lookup_seconds', 0),
            "playbook_execution_seconds": timing.get('playbook_execution_seconds', 0),
            "report_parsing_seconds": timing.get('report_parsing_seconds', 0),
            # Ansible playbook timing (từ trong playbook)
            "connection_to_node_seconds": timing.get('connection_to_node_seconds', timing.get('connection_seconds', ansible_breakdown.get('connection_seconds', 0))),
            "file_checks_seconds": timing.get('file_checks_seconds', ansible_breakdown.get('file_checks_seconds', 0)),
            "task_execution_seconds": timing.get('task_execution_seconds', timing.get('execution_seconds', ansible_breakdown.get('execution_seconds', 0))),
            "result_fetch_seconds": timing.get('result_fetch_seconds', timing.get('fetch_seconds', ansible_breakdown.get('fetch_seconds', 0))),
            # Total
            "total_seconds": timing.get('total_seconds', 0),
            "total_playbook_seconds": ansible_breakdown.get('total_playbook_seconds', timing.get('playbook_execution_seconds', 0))
        },
        "breakdown_explanation": {
            "inventory_lookup_seconds": "Thời gian tìm inventory file (Python)",
            "playbook_execution_seconds": "Tổng thời gian chạy playbook (Python)",
            "report_parsing_seconds": "Thời gian parse report file (Python)",
            "connection_to_node_seconds": "Thời gian connection + fact gathering + setup (trong playbook)",
            "file_checks_seconds": "Thời gian check files (kube-check src, venv) (trong playbook)",
            "task_execution_seconds": "Thời gian chạy kube-check scan (trong playbook)",
            "result_fetch_seconds": "Thời gian fetch report file (trong playbook)",
            "total_seconds": "Tổng thời gian từ Python service",
            "total_playbook_seconds": "Tổng thời gian trong playbook"
        }
    }
    
    # Thêm API timing vào response
    if hasattr(g, 'start_time'):
        response_data["api_timing"] = {
            "api_processing_seconds": round(api_duration, 3),
            "total_response_seconds": round(time.time() - g.start_time, 3)
        }
    
    return jsonify(response_data), 200

@bp.route('/api/scans', methods=['GET'])
def get_scans():
    """Get all scans"""
    storage_service = current_app.config.get('storage_service')
    if storage_service:
        limit = request.args.get('limit', type=int)
        scans = storage_service.get_all_scans(limit=limit)
        total = len(scans)
    else:
        # Fallback to in-memory storage
        storage = current_app.config['storage']
        scans = storage['scans']
        total = len(scans)
    
    return jsonify({
        "success": True,
        "data": scans,
        "total": total
    }), 200

@bp.route('/api/kube-check/status', methods=['GET'])
def kube_check_status():
    """Get Kube-check system status"""
    status = kube_check.get_status()
    return jsonify({
        "success": True,
        "data": status,
        "ready": status.get('kube_check_available', False) and status.get('path_exists', False)
    }), 200

@bp.route('/api/kube-check/test', methods=['POST'])
def test_kube_check():
    """Test single Kube-check"""
    try:
        data = request.json
        check_id = data.get('checkId')
        
        if not check_id:
            return jsonify({
                "success": False,
                "error": "Check ID is required"
            }), 400
        
        result = kube_check.run_scan([check_id])
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "message": "Kube-check test completed",
                "data": result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": "Kube-check test failed",
                "message": result.get('error', 'Unknown error'),
                "checkId": check_id
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Kube-check test failed",
            "message": str(e)
        }), 500

def _start_local_scan(scan_job, selected_items):
    """Start local scan using Kube-check"""
    try:
        check_ids = [item['id'] for item in selected_items]
        result = kube_check.run_scan(check_ids)
        
        if result.get('success'):
            # Map results
            results = result.get('results', [])
            scan_job['results'] = _map_results(results, selected_items)
        else:
            scan_job['results'] = _create_failed_results(selected_items, result.get('error', 'Unknown error'))
        
        scan_job['status'] = 'completed'
        now_utc = datetime.now(timezone.utc)
        scan_job['endTime'] = now_utc.isoformat()
        scan_job['timestamp'] = now_utc.isoformat()  # Update timestamp when completed
        scan_job['progress'] = 100

        storage_service = current_app.config.get('storage_service')
        if storage_service:
            # Update in storage
            storage_service.update_scan(scan_job['id'], {
                'status': 'completed',
                'endTime': scan_job['endTime'],
                'timestamp': scan_job['timestamp'],
                'progress': 100,
                'results': scan_job['results']
            })

            # Audit: local scan
            try:
                # Build actual command for local scan (kube-check CLI)
                check_ids_str = ','.join(check_ids)
                actual_node_command = f"kube-check run --check {check_ids_str}"
                
                # Extract actual shell commands from Kube-check config
                shell_commands = _extract_shell_commands_from_checks(check_ids)
                
                storage_service.log_audit_event({
                    "type": "scan",
                    "check_id": None,
                    "node_name": scan_job.get("nodeName") or scan_job.get("node_name"),
                    "cluster_name": scan_job.get("clusterName") or scan_job.get("cluster_name"),
                    "action": "Run local kube-check scan",
                    "command": "kube-check scan",
                    "source": "kube_check",
                    "status": "SUCCESS",
                    "user": "ui",
                    "details": {
                        "scanId": scan_job.get("id"),
                        "checkIds": check_ids,
                        "nodeCommand": actual_node_command,
                        "shellCommands": shell_commands,
                        "resultSummary": {
                            "totalResults": len(scan_job.get("results", [])),
                        },
                    },
                })
            except Exception:
                current_app.logger.warning("Failed to log local scan audit event", exc_info=True)
        
    except Exception as e:
        scan_job['results'] = _create_failed_results(selected_items, str(e))
        scan_job['status'] = 'failed'
        now_utc = datetime.now(timezone.utc)
        scan_job['endTime'] = now_utc.isoformat()
        scan_job['timestamp'] = now_utc.isoformat()  # Update timestamp when failed
        scan_job['progress'] = 100

        storage_service = current_app.config.get('storage_service')
        if storage_service:
            # Update in storage
            storage_service.update_scan(scan_job['id'], {
                'status': 'failed',
                'endTime': scan_job['endTime'],
                'timestamp': scan_job['timestamp'],
                'progress': 100,
                'results': scan_job['results']
            })

            # Audit: local scan failed
            try:
                # Extract actual shell commands from Kube-check config
                shell_commands = _extract_shell_commands_from_checks(check_ids)
                
                storage_service.log_audit_event({
                    "type": "scan",
                    "check_id": None,
                    "node_name": scan_job.get("nodeName") or scan_job.get("node_name"),
                    "cluster_name": scan_job.get("clusterName") or scan_job.get("cluster_name"),
                    "action": "Run local kube-check scan",
                    "command": "kube-check scan",
                    "source": "kube_check",
                    "status": "FAILED",
                    "user": "ui",
                    "details": {
                        "scanId": scan_job.get("id"),
                        "checkIds": check_ids,
                        "nodeCommand": f"kube-check run --check {','.join(check_ids)}",
                        "shellCommands": shell_commands,
                        "error": str(e),
                    },
                })
            except Exception:
                current_app.logger.warning("Failed to log local scan audit event", exc_info=True)

def _start_remote_scan(scan_job, selected_items, cluster_name, node_name):
    """Start remote scan using Ansible Service"""
    try:
        check_ids = [item['id'] for item in selected_items]
        result = ansible_svc.run_scan(check_ids, cluster_name, node_name)
        
        if result.get('success'):
            results = result.get('results', [])
            scan_job['results'] = _map_results(results, selected_items)
            # Lưu timing information
            if 'timing' in result:
                scan_job['timing'] = result['timing']
                current_app.logger.info(f"Scan timing: {result['timing']}")
        else:
            scan_job['results'] = _create_failed_results(selected_items, result.get('error', 'Unknown error'))
            # Lưu timing ngay cả khi failed
            if 'timing' in result:
                scan_job['timing'] = result['timing']
        
        scan_job['status'] = 'completed'
        now_utc = datetime.now(timezone.utc)
        scan_job['endTime'] = now_utc.isoformat()
        scan_job['timestamp'] = now_utc.isoformat()  # Update timestamp when completed
        scan_job['progress'] = 100

        storage_service = current_app.config.get('storage_service')
        if storage_service:
            # Update in storage
            update_data = {
                'status': 'completed',
                'endTime': scan_job['endTime'],
                'timestamp': scan_job['timestamp'],
                'progress': 100,
                'results': scan_job['results']
            }
            # Thêm timing nếu có
            if 'timing' in scan_job:
                update_data['timing'] = scan_job['timing']
            storage_service.update_scan(scan_job['id'], update_data)

            # Audit: remote scan via Ansible
            try:
                # Build actual command executed on node (from playbook)
                kubecheck_path_remote = f"/home/ansible-user/Kube-check"
                reports_path_remote = f"/home/ansible-user/Kube-check/reports"
                check_ids_str = ','.join(check_ids)
                # Actual command from playbook: python venv/bin/python src/main.py run --check ... --output-format json --output-file ...
                actual_node_command = f"{kubecheck_path_remote}/venv/bin/python {kubecheck_path_remote}/src/main.py run --check {check_ids_str} --output-format json --output-file {reports_path_remote}/scan_<hostname>_<epoch>.json"
                
                # Extract actual shell commands from Kube-check config
                shell_commands = _extract_shell_commands_from_checks(check_ids)
                
                storage_service.log_audit_event({
                    "type": "scan",
                    "check_id": None,
                    "node_name": node_name or scan_job.get("nodeName") or scan_job.get("node_name"),
                    "cluster_name": cluster_name or scan_job.get("clusterName") or scan_job.get("cluster_name"),
                    "action": "Run remote scan",
                    "command": "ansible-playbook kube-check-scan.yml",
                    "source": "ansible",
                    "status": "SUCCESS",
                    "user": "ui",
                    "details": {
                        "scanId": scan_job.get("id"),
                        "checkIds": check_ids,
                        "nodeCommand": actual_node_command,
                        "shellCommands": shell_commands,  # Actual shell commands like ps, cat, stat, etc.
                        "resultSummary": {
                            "totalResults": len(scan_job.get("results", [])),
                        },
                    },
                })
            except Exception:
                current_app.logger.warning("Failed to log remote scan audit event", exc_info=True)
        
    except Exception as e:
        scan_job['results'] = _create_failed_results(selected_items, str(e))
        scan_job['status'] = 'failed'
        now_utc = datetime.now(timezone.utc)
        scan_job['endTime'] = now_utc.isoformat()
        scan_job['timestamp'] = now_utc.isoformat()  # Update timestamp when failed
        scan_job['progress'] = 100

        storage_service = current_app.config.get('storage_service')
        if storage_service:
            # Update in storage
            storage_service.update_scan(scan_job['id'], {
                'status': 'failed',
                'endTime': scan_job['endTime'],
                'timestamp': scan_job['timestamp'],
                'progress': 100,
                'results': scan_job['results']
            })

            # Audit: remote scan failed
            try:
                # Build actual command executed on node (from playbook)
                kubecheck_path_remote = f"/home/ansible-user/Kube-check"
                reports_path_remote = f"/home/ansible-user/Kube-check/reports"
                check_ids_str = ','.join(check_ids)
                actual_node_command = f"{kubecheck_path_remote}/venv/bin/python {kubecheck_path_remote}/src/main.py run --check {check_ids_str} --output-format json --output-file {reports_path_remote}/scan_<hostname>_<epoch>.json"
                
                # Extract actual shell commands from Kube-check config
                shell_commands = _extract_shell_commands_from_checks(check_ids)
                
                storage_service.log_audit_event({
                    "type": "scan",
                    "check_id": None,
                    "node_name": node_name or scan_job.get("nodeName") or scan_job.get("node_name"),
                    "cluster_name": cluster_name or scan_job.get("clusterName") or scan_job.get("cluster_name"),
                    "action": "Run remote scan",
                    "command": "ansible-playbook kube-check-scan.yml",
                    "source": "ansible",
                    "status": "FAILED",
                    "user": "ui",
                    "details": {
                        "scanId": scan_job.get("id"),
                        "checkIds": check_ids,
                        "nodeCommand": actual_node_command,
                        "shellCommands": shell_commands,
                        "error": str(e),
                    },
                })
            except Exception:
                current_app.logger.warning("Failed to log remote scan audit event", exc_info=True)

def _map_results(results, selected_items):
    """Map kube-check results to scan job format"""
    mapped = []
    for item in selected_items:
        result = next((r for r in results if r.get('id') == item['id']), None)
        
        if result:
            status = "FAIL"
            if result.get('passed') or result.get('status') == 'PASS':
                status = "PASS"
            elif result.get('type') == 'manual' or result.get('status') == 'WARN':
                status = "WARN"
            
            mapped.append({
                "itemId": item['id'],
                "title": result.get('text') or result.get('title') or item.get('title'),
                "status": status,
                "score": result.get('scored', False) and (10 if status == "PASS" else 0),
                "details": result.get('error') or (status == "PASS" and "Check passed" or "Check failed"),
                "remediation": result.get('remediation'),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        else:
            mapped.append({
                "itemId": item['id'],
                "title": item.get('title'),
                "status": "FAIL",
                "score": 0,
                "details": "Check not executed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
    
    return mapped

def _create_failed_results(selected_items, error_message):
    """Create failed results for all items"""
    return [{
        "itemId": item['id'],
        "title": item.get('title'),
        "status": "FAIL",
        "score": 0,
        "details": f"Scan failed: {error_message}",
        "timestamp": datetime.now().isoformat()
    } for item in selected_items]

