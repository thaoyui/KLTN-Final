#!/usr/bin/env python3
"""
Ansible Service - REST API để gọi Ansible playbooks
Kết nối với K8s cluster và execute kube-check
"""
import os
import json
import logging
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
ANSIBLE_DIR = Path("/app/ansible")
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"
INVENTORY_DIR = ANSIBLE_DIR / "inventory"
LOGS_DIR = Path("/app/logs")

# Ensure directories exist
LOGS_DIR.mkdir(exist_ok=True)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "ansible-service",
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/api/k8s/connect', methods=['POST'])
def connect_k8s():
    """
    Connect to K8s cluster và verify connection
    Body: {
        "kubeconfig": "base64_encoded_kubeconfig",
        "cluster_name": "my-cluster",
        "nodes": [
            {"name": "node1", "ip": "192.168.1.10", "user": "root", "ssh_key": "path/to/key"}
        ]
    }
    """
    try:
        data = request.json
        logger.info(f"Connect request: {data.get('cluster_name', 'unknown')}")
        
        # Save kubeconfig if provided
        if data.get('kubeconfig'):
            kubeconfig_path = save_kubeconfig(data['kubeconfig'], data.get('cluster_name', 'default'))
        else:
            kubeconfig_path = os.path.expanduser("~/.kube/config")
        
        # Update inventory with nodes
        if data.get('nodes'):
            inventory_path = create_inventory(data['nodes'], data.get('cluster_name', 'default'))
        else:
            inventory_path = INVENTORY_DIR / "hosts.yml"
        
        # Test connection
        result = run_ansible_playbook(
            "test-connection.yml",
            inventory_path,
            extra_vars={
                "kubeconfig_path": kubeconfig_path
            }
        )
        
        return jsonify({
            "success": result['success'],
            "message": "Connection test completed",
            "details": result
        }), 200 if result['success'] else 500
        
    except Exception as e:
        logger.error(f"Error in connect_k8s: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/k8s/scan', methods=['POST'])
def scan_k8s():
    """
    Execute kube-check scan trên K8s cluster
    Body: {
        "check_ids": ["1.1.1", "1.2.9", "2.1"],
        "cluster_name": "my-cluster",
        "node_name": "node1" (optional - scan specific node)
    }
    """
    try:
        data = request.json
        check_ids = data.get('check_ids', [])
        cluster_name = data.get('cluster_name', 'default')
        node_name = data.get('node_name')
        
        logger.info(f"Scan request: {len(check_ids)} checks on {cluster_name}")
        
        # Run scan playbook
        result = run_ansible_playbook(
            "kube-check-scan.yml",
            INVENTORY_DIR / f"{cluster_name}_hosts.yml",
            extra_vars={
                "check_ids": check_ids,
                "node_name": node_name,
                "output_format": "json"
            }
        )
        
        return jsonify({
            "success": result['success'],
            "results": result.get('results', []),
            "details": result
        }), 200 if result['success'] else 500
        
    except Exception as e:
        logger.error(f"Error in scan_k8s: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/k8s/remediate', methods=['POST'])
def remediate_k8s():
    """
    Execute remediation trên K8s cluster
    Body: {
        "check_id": "1.1.1",
        "cluster_name": "my-cluster",
        "node_name": "node1"
    }
    """
    try:
        data = request.json
        check_id = data.get('check_id')
        cluster_name = data.get('cluster_name', 'default')
        node_name = data.get('node_name')
        
        if not check_id:
            return jsonify({
                "success": False,
                "error": "check_id is required"
            }), 400
        
        logger.info(f"Remediate request: {check_id} on {cluster_name}")
        
        # Run remediation playbook
        result = run_ansible_playbook(
            "kube-check-remediate.yml",
            INVENTORY_DIR / f"{cluster_name}_hosts.yml",
            extra_vars={
                "check_id": check_id,
                "node_name": node_name,
                "auto_yes": True
            }
        )
        
        return jsonify({
            "success": result['success'],
            "details": result
        }), 200 if result['success'] else 500
        
    except Exception as e:
        logger.error(f"Error in remediate_k8s: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/k8s/copy-files', methods=['POST'])
def copy_files():
    """
    Copy files từ K8s nodes về local
    Body: {
        "cluster_name": "my-cluster",
        "node_name": "node1",
        "remote_paths": ["/etc/kubernetes/admin.conf", "/var/lib/etcd"],
        "local_path": "/tmp/k8s-files"
    }
    """
    try:
        data = request.json
        cluster_name = data.get('cluster_name', 'default')
        node_name = data.get('node_name')
        remote_paths = data.get('remote_paths', [])
        local_path = data.get('local_path', '/tmp/k8s-files')
        
        logger.info(f"Copy files request: {len(remote_paths)} files from {node_name}")
        
        result = run_ansible_playbook(
            "copy-files.yml",
            INVENTORY_DIR / f"{cluster_name}_hosts.yml",
            extra_vars={
                "node_name": node_name,
                "remote_paths": remote_paths,
                "local_path": local_path
            }
        )
        
        return jsonify({
            "success": result['success'],
            "copied_files": result.get('copied_files', []),
            "details": result
        }), 200 if result['success'] else 500
        
    except Exception as e:
        logger.error(f"Error in copy_files: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def save_kubeconfig(kubeconfig_base64, cluster_name):
    """Save kubeconfig to file"""
    import base64
    
    kubeconfig_dir = Path("/root/.kube")
    kubeconfig_dir.mkdir(parents=True, exist_ok=True)
    
    kubeconfig_path = kubeconfig_dir / f"config_{cluster_name}"
    
    try:
        kubeconfig_content = base64.b64decode(kubeconfig_base64).decode('utf-8')
        kubeconfig_path.write_text(kubeconfig_content)
        kubeconfig_path.chmod(0o600)
        logger.info(f"Saved kubeconfig to {kubeconfig_path}")
        return str(kubeconfig_path)
    except Exception as e:
        logger.error(f"Error saving kubeconfig: {str(e)}")
        raise


def create_inventory(nodes, cluster_name):
    """Create Ansible inventory file from nodes list"""
    inventory_path = INVENTORY_DIR / f"{cluster_name}_hosts.yml"
    
    inventory = {
        "all": {
            "hosts": {},
            "vars": {
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
            }
        }
    }
    
    for node in nodes:
        host_vars = {
            "ansible_host": node.get('ip'),
            "ansible_user": node.get('user', 'root'),
        }
        
        if node.get('ssh_key'):
            host_vars["ansible_ssh_private_key_file"] = node['ssh_key']
        
        if node.get('ssh_password'):
            host_vars["ansible_ssh_pass"] = node['ssh_password']
        
        inventory["all"]["hosts"][node['name']] = host_vars
    
    import yaml
    inventory_path.write_text(yaml.dump(inventory))
    logger.info(f"Created inventory: {inventory_path}")
    
    return inventory_path


def run_ansible_playbook(playbook_name, inventory_path, extra_vars=None):
    """Run Ansible playbook and return results"""
    playbook_path = PLAYBOOKS_DIR / playbook_name
    
    if not playbook_path.exists():
        return {
            "success": False,
            "error": f"Playbook not found: {playbook_path}"
        }
    
    # Build ansible-playbook command
    cmd = [
        "ansible-playbook",
        "-i", str(inventory_path),
        str(playbook_path),
        "--json"
    ]
    
    if extra_vars:
        import json
        cmd.extend(["-e", json.dumps(extra_vars)])
    
    # Run playbook
    try:
        log_file = LOGS_DIR / f"{playbook_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        with open(log_file, 'w') as f:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes
                stdout=f,
                stderr=subprocess.STDOUT
            )
        
        # Parse JSON output if available
        output = log_file.read_text()
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "output": output,
            "log_file": str(log_file)
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Playbook execution timeout"
        }
    except Exception as e:
        logger.error(f"Error running playbook: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

