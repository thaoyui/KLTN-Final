"""Remediation endpoints"""
from flask import Blueprint, request, jsonify, current_app
from services import kube_check
from services import ansible_service as ansible_svc
from datetime import datetime
from typing import Optional
import time
import yaml
import os

bp = Blueprint('remediation', __name__)

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

def _extract_remediation_command_from_check(check_id: str) -> Optional[str]:
    """Extract remediation command from Kube-check config for a specific check (with variables substituted)"""
    try:
        # Find Kube-check config directory
        kube_check_path = os.getenv('KUBE_CHECK_PATH', os.path.join(os.path.dirname(__file__), '..', '..', 'Kube-check'))
        config_dir = os.path.join(kube_check_path, 'config')
        
        if not os.path.exists(config_dir):
            return None
        
        # Config file mapping
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
        
        # Find config file
        config_file = None
        for prefix, file_name in config_mapping.items():
            if check_id.startswith(prefix):
                config_file = file_name
                break
        
        if not config_file:
            return None
        
        config_path = os.path.join(config_dir, config_file)
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # Navigate through config structure
        if isinstance(config_data, dict) and 'groups' in config_data:
            for group in config_data.get('groups', []):
                if isinstance(group, dict) and 'checks' in group:
                    for check in group.get('checks', []):
                        if check.get('id') == check_id:
                            # Get auto_remediation command and substitute variables
                            auto_remediation = check.get('auto_remediation', {})
                            command = None
                            if isinstance(auto_remediation, dict):
                                command = auto_remediation.get('command')
                            elif isinstance(auto_remediation, str):
                                command = auto_remediation
                            
                            if command:
                                return _apply_variable_substitutions(command)
        
    except Exception as e:
        current_app.logger.warning(f"Error extracting remediation command for {check_id}: {e}")
    
    return None

@bp.route('/api/remediate', methods=['POST'])
def remediate():
    """Run remediation for checks"""
    try:
        data = request.json
        check_ids = data.get('checkIds', [])
        cluster_name = data.get('clusterName')
        node_name = data.get('nodeName')
        if not check_ids or not isinstance(check_ids, list) or len(check_ids) == 0:
            return jsonify({
                "success": False,
                "error": "checkIds array is required"
            }), 400    
        # Determine remediation mode
        k8s_mode = current_app.config.get('K8S_MODE', 'local')
        remediation_mode = 'remote' if (k8s_mode == 'remote' and cluster_name) else 'local'
        effective_cluster_name = cluster_name or current_app.config.get('CLUSTER_NAME', 'default')
        results = []
        storage_service = current_app.config.get('storage_service')
        for check_id in check_ids:
            try:
                if remediation_mode == 'remote':
                    # Use Ansible Service
                    remediation_result = ansible_svc.run_remediation(
                        check_id,
                        effective_cluster_name,
                        node_name
                    )
                    # Verify after remediation
                    verify_result = _verify_remediation_remote(check_id, effective_cluster_name, node_name)
                    result_entry = {
                        "checkId": check_id,
                        "action": "remediate",
                        "success": remediation_result.get('success', False),
                        "status": "PASS" if (remediation_result.get('success') and verify_result.get('status') == 'PASS') else "FAIL",
                        "message": "Fixed and verified successfully" if verify_result.get('status') == 'PASS' else "Remediation failed or verification failed",
                        "details": remediation_result,
                        "verifyDetails": verify_result
                    }
                    results.append(result_entry)
                    # Audit log
                    if storage_service:
                        try:
                            # Build actual command executed on node (from playbook)
                            kubecheck_path_remote = f"/home/ansible-user/Kube-check"
                            reports_path_remote = f"/home/ansible-user/Kube-check/reports"
                            # Actual command from playbook: python venv/bin/python src/main.py remediate --check ... --yes --output-format json --output-file ...
                            actual_node_command = f"{kubecheck_path_remote}/venv/bin/python {kubecheck_path_remote}/src/main.py remediate --check {check_id} --yes --output-format json --output-file {reports_path_remote}/remediate_{check_id}_<hostname>_<epoch>.json"                            
                            # Extract actual shell remediation command from config
                            remediation_shell_command = _extract_remediation_command_from_check(check_id)                            
                            storage_service.log_audit_event({
                                "type": "remediation",
                                "check_id": check_id,
                                "node_name": node_name,
                                "cluster_name": effective_cluster_name,
                                "action": "Run remote remediation",
                                "command": "ansible-playbook kube-check-remediate.yml",
                                "source": "ansible",
                                "status": "SUCCESS" if result_entry["success"] else "FAILED",
                                "user": "ui",
                                "details": {
                                    "mode": remediation_mode,
                                    "nodeCommand": actual_node_command,
                                    "remediationShellCommand": remediation_shell_command,
                                    "remediationResult": remediation_result,
                                    "verifyResult": verify_result,
                                },
                            })
                        except Exception:
                            current_app.logger.warning("Failed to log remediation audit event", exc_info=True)
                else:
                    remediation_result = kube_check.run_remediation(check_id, auto_yes=True)
                    if not remediation_result.get('success'):
                        result_entry = {
                            "checkId": check_id,
                            "action": "remediate",
                            "success": False,
                            "status": "FAIL",
                            "message": "Remediation script failed",
                            "details": remediation_result
                        }
                        results.append(result_entry)

                        # Audit log
                        if storage_service:
                            try:
                                # Build actual command for local remediation
                                actual_node_command = f"kube-check remediate --check {check_id} --yes"
                                
                                # Extract actual shell remediation command from config
                                remediation_shell_command = _extract_remediation_command_from_check(check_id)
                                
                                storage_service.log_audit_event({
                                    "type": "remediation",
                                    "check_id": check_id,
                                    "node_name": node_name,
                                    "cluster_name": effective_cluster_name,
                                    "action": "Run local remediation",
                                    "command": "kube-check auto-remediation",
                                    "source": "kube_check",
                                    "status": "FAILED",
                                    "user": "ui",
                                    "details": {
                                        "mode": remediation_mode,
                                        "nodeCommand": actual_node_command,
                                        "remediationShellCommand": remediation_shell_command,
                                        "remediationResult": remediation_result,
                                    },
                                })
                            except Exception:
                                current_app.logger.warning("Failed to log remediation audit event", exc_info=True)
                        continue
                    
                    # Verify after remediation
                    verify_result = _verify_remediation_local(check_id)
                    
                    result_entry = {
                        "checkId": check_id,
                        "action": "verify",
                        "success": verify_result.get('status') == 'PASS',
                        "status": verify_result.get('status', 'FAIL'),
                        "message": "Fixed and verified successfully" if verify_result.get('status') == 'PASS' else f"Fix applied but verification failed",
                        "details": remediation_result,
                        "verifyDetails": verify_result
                    }
                    results.append(result_entry)

                    # Audit log
                    if storage_service:
                        try:
                            # Build actual command for local remediation
                            actual_node_command = f"kube-check remediate --check {check_id} --yes"
                            
                            # Extract actual shell remediation command from config
                            remediation_shell_command = _extract_remediation_command_from_check(check_id)
                            
                            storage_service.log_audit_event({
                                "type": "remediation",
                                "check_id": check_id,
                                "node_name": node_name,
                                "cluster_name": effective_cluster_name,
                                "action": "Run local remediation",
                                "command": "kube-check auto-remediation",
                                "source": "kube_check",
                                "status": "SUCCESS" if result_entry["success"] else "FAILED",
                                "user": "ui",
                                "details": {
                                    "mode": remediation_mode,
                                    "nodeCommand": actual_node_command,
                                    "remediationShellCommand": remediation_shell_command,
                                    "remediationResult": remediation_result,
                                    "verifyResult": verify_result,
                                },
                            })
                        except Exception:
                            current_app.logger.warning("Failed to log remediation audit event", exc_info=True)
                    
            except Exception as e:
                results.append({
                    "checkId": check_id,
                    "success": False,
                    "status": "ERROR",
                    "error": str(e)
                })
        
        return jsonify({
            "success": True,
            "mode": remediation_mode,
            "results": results
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Failed to execute remediation",
            "details": str(e)
        }), 500

def _verify_remediation_local(check_id: str, max_retries: int = 3) -> dict:
    """Verify remediation locally with retries"""
    delays = [3, 10, 15]  # seconds
    
    for i in range(max_retries):
        if i > 0:
            time.sleep(delays[i-1])
        
        result = kube_check.run_scan([check_id])
        if result.get('success'):
            results = result.get('results', [])
            if results and len(results) > 0:
                check_result = results[0]
                if check_result.get('passed') or check_result.get('status') == 'PASS':
                    return {"status": "PASS", "details": check_result}
        
        if i < max_retries - 1:
            continue
    
    return {"status": "FAIL", "message": "Verification failed after retries"}

def _verify_remediation_remote(check_id: str, cluster_name: str, node_name: str = None, max_retries: int = 3) -> dict:
    """Verify remediation remotely with retries"""
    delays = [3, 10, 15]  # seconds
    
    for i in range(max_retries):
        if i > 0:
            time.sleep(delays[i-1])
        
        result = ansible_svc.run_scan([check_id], cluster_name, node_name)
        if result.get('success'):
            results = result.get('results', [])
            if results and len(results) > 0:
                check_result = results[0]
                if check_result.get('passed') or check_result.get('status') == 'PASS':
                    return {"status": "PASS", "details": check_result}
        
        if i < max_retries - 1:
            continue
    
    return {"status": "FAIL", "message": "Verification failed after retries"}

