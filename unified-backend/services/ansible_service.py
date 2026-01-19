"""Ansible service integration"""
import os
import json
import logging
import subprocess
import base64
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Cache for bootstrap status checks (in-memory + file-based)
_bootstrap_status_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes cache TTL
CACHE_DIR = Path(os.path.join(os.path.dirname(__file__), '..', 'cache'))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Paths - Support both local and Docker environments
_default_ansible_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'ansible')
_default_logs_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')

ANSIBLE_DIR = Path(os.getenv('ANSIBLE_DIR', _default_ansible_dir)).resolve()
PLAYBOOKS_DIR = ANSIBLE_DIR / "playbooks"
INVENTORY_DIR = ANSIBLE_DIR / "inventory"
LOGS_DIR = Path(os.getenv('LOGS_DIR', _default_logs_dir))
# Kube-check path - Support both local and Docker environments
# Use KUBE_CHECK_PATH env var if available, otherwise fallback to relative path from project root
_default_kubecheck_path = os.path.join(os.path.dirname(__file__), '..', '..', 'Kube-check')
KUBECHECK_PATH_LOCAL = Path(os.getenv('KUBE_CHECK_PATH', _default_kubecheck_path)).resolve()

# Ensure directories exist
try:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)  # parents=True để tạo parent dirs
except (PermissionError, OSError) as e:
    # Fallback to current directory if can't create /app/logs
    LOGS_DIR = Path(os.path.join(os.path.dirname(__file__), '..', 'logs'))
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.warning(f"Could not create logs directory, using: {LOGS_DIR}")

INVENTORY_DIR.mkdir(parents=True, exist_ok=True)

def run_scan(check_ids: List[str], cluster_name: str = 'default', node_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Run kube-check scan on K8s cluster via Ansible
    
    Args:
        check_ids: List of check IDs
        cluster_name: Cluster name
        node_name: Optional specific node name
    
    Returns:
        Dict with scan results
    """
    import time
    timing = {
        'start': time.time(),
        'inventory_lookup': None,
        'playbook_start': None,
        'playbook_end': None,
        'report_parsing': None,
        'end': None
    }
    
    try:
        logger.info(f"run_scan: cluster={cluster_name}, node_name={node_name}, check_ids={len(check_ids)}")
        # Try both YAML and INI formats
        inventory_path = _find_inventory_file(cluster_name)
        timing['inventory_lookup'] = time.time()
        
        if not inventory_path:
            return {
                "success": False,
                "error": f"Inventory file not found for cluster: {cluster_name}. Tried: {cluster_name}_hosts.yml and {cluster_name}_hosts.ini"
            }
        
        # Use pinned local Kube-check path
        kubecheck_path_local = str(KUBECHECK_PATH_LOCAL)
        
        # Remote path will use default: ansible_env.HOME + '/Kube-check' (from playbook)
        timing['playbook_start'] = time.time()
        result = run_ansible_playbook(
            "kube-check-scan.yml",
            inventory_path,
            extra_vars={
                "check_ids": check_ids,
                "node_name": node_name,
                "output_format": "json",
                "kubecheck_path_local": kubecheck_path_local
                # kubecheck_path and reports_path will use default: ansible_env.HOME + '/Kube-check'
            }
        )
        timing['playbook_end'] = time.time()
        
        # Parse timing từ Ansible output nếu có
        ansible_timing = {}
        
        # Thử đọc timing từ file trước (backup method - reliable)
        try:
            timing_files = list(Path("/tmp").glob("kube-check-timing-*.json"))
            logger.debug(f"Found {len(timing_files)} timing files in /tmp")
            if timing_files:
                # Lấy file mới nhất (sắp xếp theo mtime)
                latest_timing_file = max(timing_files, key=lambda p: p.stat().st_mtime)
                logger.info(f"Reading timing from file: {latest_timing_file}")
                with open(latest_timing_file, 'r') as f:
                    file_content = f.read()
                    logger.info(f"Raw timing file content: {file_content}")
                    file_timing = json.loads(file_content)
                    logger.debug(f"Parsed timing from file: {file_timing}")
                    ansible_timing = {
                        'connection_seconds': float(file_timing.get('connection_seconds', 0)),
                        'file_checks_seconds': float(file_timing.get('file_checks_seconds', 0)),
                        'execution_seconds': float(file_timing.get('execution_seconds', 0)),
                        'fetch_seconds': float(file_timing.get('fetch_seconds', 0)),
                        'total_playbook_seconds': float(file_timing.get('total_seconds', 0))
                    }
                    logger.info(f"Parsed Ansible timing from file {latest_timing_file}: {ansible_timing}")
                    # Cleanup file sau khi đọc
                    try:
                        latest_timing_file.unlink()
                        logger.debug(f"Cleaned up timing file: {latest_timing_file}")
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to cleanup timing file: {cleanup_error}")
            else:
                logger.warning("No timing files found in /tmp/kube-check-timing-*.json")
        except Exception as e:
            logger.warning(f"Could not read timing from file: {e}", exc_info=True)
        
        # Nếu chưa có timing từ file, thử parse từ output
        if not ansible_timing and result.get('output'):
            import re
            output_text = result.get('output', '')
            
            # Tìm timing breakdown từ Ansible debug output
            # Pattern có thể là:
            # - "Connection time: Xs" (trong debug msg)
            # - "Connection time: X" (không có 's')
            # - Multi-line format trong debug output
            
            # Thử nhiều patterns khác nhau
            patterns = [
                # Pattern 1: "Connection time: Xs" (có 's')
                (r'Connection time:\s*(\d+(?:\.\d+)?)\s*s', 'connection'),
                # Pattern 2: "Connection time: X" (không có 's')
                (r'Connection time:\s*(\d+(?:\.\d+)?)', 'connection'),
                # Pattern 3: Trong debug msg format
                (r'"Connection time:\s*(\d+(?:\.\d+)?)\s*s"', 'connection'),
            ]
            
            # Tìm từng giá trị
            conn_match = None
            exec_match = None
            fetch_match = None
            total_match = None
            
            for pattern, _ in patterns:
                if not conn_match:
                    conn_match = re.search(pattern.replace('Connection', 'Connection'), output_text, re.IGNORECASE | re.MULTILINE)
                if not exec_match:
                    exec_match = re.search(pattern.replace('Connection', 'Execution'), output_text, re.IGNORECASE | re.MULTILINE)
                if not fetch_match:
                    fetch_match = re.search(pattern.replace('Connection', 'Fetch'), output_text, re.IGNORECASE | re.MULTILINE)
                if not total_match:
                    total_match = re.search(pattern.replace('Connection', 'Total'), output_text, re.IGNORECASE | re.MULTILINE)
            
            # Fallback: tìm trong toàn bộ output với pattern đơn giản hơn
            if not conn_match:
                conn_match = re.search(r'Connection\s+time[:\s]+(\d+(?:\.\d+)?)', output_text, re.IGNORECASE)
            if not exec_match:
                exec_match = re.search(r'Execution\s+time[:\s]+(\d+(?:\.\d+)?)', output_text, re.IGNORECASE)
            if not fetch_match:
                fetch_match = re.search(r'Fetch\s+time[:\s]+(\d+(?:\.\d+)?)', output_text, re.IGNORECASE)
            if not total_match:
                total_match = re.search(r'Total\s+time[:\s]+(\d+(?:\.\d+)?)', output_text, re.IGNORECASE)
            
            # Tìm file checks time nếu có
            file_checks_match = re.search(r'File checks time[:\s]+(\d+(?:\.\d+)?)', output_text, re.IGNORECASE)
            
            # Thử parse từ scan_results timing JSON (ưu tiên nhất - từ fact)
            # Pattern 1: SCAN_TIMING_JSON_START...SCAN_TIMING_JSON_END (đúng format)
            scan_timing_match = re.search(r'SCAN_TIMING_JSON_START(.*?)SCAN_TIMING_JSON_END', output_text, re.DOTALL)
            if scan_timing_match:
                try:
                    json_str = scan_timing_match.group(1).strip()
                    # Clean up JSON string - handle escaped quotes from Ansible debug output
                    json_str = json_str.replace('\\"', '"')
                    # Remove surrounding quotes if any (after unescaping)
                    if json_str.startswith('"') and json_str.endswith('"'):
                        json_str = json_str[1:-1]
                    # Handle case where value is string "8" instead of number 8
                    # Pattern: "execution_seconds": "8" -> "execution_seconds": 8
                    json_str = re.sub(r':\s*"(\d+)"', r': \1', json_str)
                    scan_timing = json.loads(json_str)
                    ansible_timing = {
                        'connection_seconds': float(scan_timing.get('connection_seconds', 0)),
                        'file_checks_seconds': float(scan_timing.get('file_checks_seconds', 0)),
                        'execution_seconds': float(scan_timing.get('execution_seconds', 0)),
                        'fetch_seconds': float(scan_timing.get('fetch_seconds', 0)),
                        'total_playbook_seconds': float(scan_timing.get('total_seconds', 0))
                    }
                    logger.info(f"Parsed Ansible timing from scan_results fact: {ansible_timing}")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse scan_results timing JSON: {e}, content: {scan_timing_match.group(1)[:100]}")
                    scan_timing_match = None
            
            # Pattern 2: TIMING_JSON_START...SCAN_TIMING_JSON_END (mixed format - fix for compatibility)
            # Hoặc SCAN_TIMING_JSON_START nhưng có escaped quotes
            mixed_timing_match = None
            if not scan_timing_match:
                # Try mixed format: TIMING_JSON_START...SCAN_TIMING_JSON_END
                mixed_timing_match = re.search(r'TIMING_JSON_START(.*?)SCAN_TIMING_JSON_END', output_text, re.DOTALL)
                if not mixed_timing_match:
                    # Try SCAN_TIMING_JSON_START với escaped quotes
                    mixed_timing_match = re.search(r'SCAN_TIMING_JSON_START(.*?)SCAN_TIMING_JSON_END', output_text, re.DOTALL)
                
                if mixed_timing_match:
                    try:
                        json_str = mixed_timing_match.group(1).strip()
                        # Clean up JSON string - handle escaped quotes from Ansible debug output
                        # Ansible debug output: {\"execution_seconds\": \"8\"}
                        json_str = json_str.replace('\\"', '"')
                        # Remove surrounding quotes if any (after unescaping)
                        if json_str.startswith('"') and json_str.endswith('"'):
                            json_str = json_str[1:-1]
                        # Handle case where value is string "8" instead of number 8
                        # Pattern: "execution_seconds": "8" -> "execution_seconds": 8
                        json_str = re.sub(r':\s*"(\d+)"', r': \1', json_str)
                        json_timing = json.loads(json_str)
                        ansible_timing = {
                            'connection_seconds': float(json_timing.get('connection_seconds', json_timing.get('connection', 0))),
                            'file_checks_seconds': float(json_timing.get('file_checks_seconds', json_timing.get('file_checks', 0))),
                            'execution_seconds': float(json_timing.get('execution_seconds', json_timing.get('execution', 0))),
                            'fetch_seconds': float(json_timing.get('fetch_seconds', json_timing.get('fetch', 0))),
                            'total_playbook_seconds': float(json_timing.get('total_seconds', json_timing.get('total', 0)))
                        }
                        logger.info(f"Parsed Ansible timing from mixed format: {ansible_timing}")
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Failed to parse mixed timing JSON: {e}, content: {mixed_timing_match.group(1)[:100]}")
                        mixed_timing_match = None
            
            # Pattern 3: TIMING_JSON_START...TIMING_JSON_END (fallback)
            if not scan_timing_match and 'mixed_timing_match' not in locals():
                json_timing_match = re.search(r'TIMING_JSON_START\s+(.*?)\s+TIMING_JSON_END', output_text, re.DOTALL)
                if json_timing_match:
                    try:
                        json_str = json_timing_match.group(1).strip()
                        json_str = json_str.replace('\\"', '"')
                        json_str = re.sub(r'"(\d+)"', r'\1', json_str)  # "8" -> 8
                        json_timing = json.loads(json_str)
                        ansible_timing = {
                            'connection_seconds': float(json_timing.get('connection_seconds', json_timing.get('connection', 0))),
                            'file_checks_seconds': float(json_timing.get('file_checks_seconds', json_timing.get('file_checks', 0))),
                            'execution_seconds': float(json_timing.get('execution_seconds', json_timing.get('execution', 0))),
                            'fetch_seconds': float(json_timing.get('fetch_seconds', json_timing.get('fetch', 0))),
                            'total_playbook_seconds': float(json_timing.get('total_seconds', json_timing.get('total', 0)))
                        }
                        logger.info(f"Parsed Ansible timing from JSON debug: {ansible_timing}")
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(f"Failed to parse JSON timing: {e}")
                        json_timing_match = None  # Fallback to regex
            
            # Chỉ dùng regex nếu cả 2 JSON parsing đều không thành công
            if not scan_timing_match and not json_timing_match and (conn_match or exec_match or fetch_match or total_match):
                ansible_timing = {
                    'connection_seconds': float(conn_match.group(1)) if conn_match else 0,
                    'file_checks_seconds': float(file_checks_match.group(1)) if file_checks_match else 0,
                    'execution_seconds': float(exec_match.group(1)) if exec_match else 0,
                    'fetch_seconds': float(fetch_match.group(1)) if fetch_match else 0,
                    'total_playbook_seconds': float(total_match.group(1)) if total_match else 0
                }
                logger.info(f"Parsed Ansible timing: {ansible_timing}")
            else:
                # Debug: log một phần output để xem format thực tế
                # Tìm phần có chứa "TIMING" hoặc "time"
                timing_section = re.search(r'(?i)(TIMING|DETAILED|BREAKDOWN).{0,1000}', output_text)
                if timing_section:
                    logger.warning(f"Could not parse Ansible timing. Sample output:\n{timing_section.group(0)[:500]}")
                    # Log toàn bộ phần timing nếu có
                    full_timing = re.search(r'(?i)===.*?TIMING.*?BREAKDOWN.*?===.*?(?:\n.*?){0,20}', output_text, re.DOTALL)
                    if full_timing:
                        logger.warning(f"Full timing section:\n{full_timing.group(0)}")
                else:
                    logger.warning(f"Could not find timing section in Ansible output. Output length: {len(output_text)}")
                    # Log last 2000 chars để debug
                    logger.debug(f"Last 2000 chars of output:\n{output_text[-2000:]}")
        
        if result.get('success'):
            timing['report_parsing'] = time.time()
            # Try to find and parse report file
            reports_dir = Path("/tmp/kube-check-reports")
            results = []
            
            if reports_dir.exists():
                # Tối ưu: chỉ tìm file mới nhất, cleanup old files
                report_files = sorted(reports_dir.glob("scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                
                # Cleanup old files (keep only last 10)
                if len(report_files) > 10:
                    for old_file in report_files[10:]:
                        try:
                            old_file.unlink()
                            logger.debug(f"Cleaned up old report file: {old_file}")
                        except Exception as e:
                            logger.warning(f"Failed to cleanup old report {old_file}: {e}")
                
                if report_files:
                    try:
                        # Tối ưu: chỉ đọc file mới nhất
                        with open(report_files[0], 'r') as f:
                            report_data = json.load(f)
                            # Parse kube-check report format
                            results = _parse_kubecheck_report(report_data)
                            logger.info(f"Parsed {len(results)} results from report file: {report_files[0]}")
                    except Exception as e:
                        logger.warning(f"Failed to parse report file: {e}")
            
            # If no results from file, try parsing output
            if not results:
                output = result.get('output', '')
                results = _parse_ansible_output(output)
            
            timing['end'] = time.time()
            
            # Calculate timing breakdown
            playbook_duration = round(timing['playbook_end'] - timing['playbook_start'], 3) if timing['playbook_start'] and timing['playbook_end'] else 0
            execution_time = ansible_timing.get('execution_seconds', 0) if ansible_timing else 0
            
            # Nếu không parse được execution time từ playbook, estimate từ playbook_duration
            # Execution time thường chiếm 80-95% của playbook_duration (phần lớn nhất)
            if execution_time == 0 and playbook_duration > 0:
                # Estimate execution time = 90% của playbook_duration
                execution_time = round(playbook_duration * 0.90, 3)
                logger.warning(f"Could not parse execution time from playbook, estimating: {execution_time}s from playbook_duration: {playbook_duration}s")
            
            # Tính các timing từ Python level (không cần thêm task trong playbook)
            # Connection time: estimate từ playbook start (SSH overhead, rất nhỏ với ControlMaster)
            # Với gather_facts: no, connection time chỉ là SSH setup overhead
            connection_time = 0.1  # Default estimate (với ControlMaster reuse)
            if playbook_duration > 0 and execution_time > 0:
                # Estimate: connection + file checks + fetch = playbook_duration - execution_time
                # Connection thường rất nhỏ (< 0.5s với reuse), nên estimate nhỏ
                other_time = playbook_duration - execution_time
                if other_time > 0:
                    # Connection thường chiếm 10-20% của other_time
                    connection_time = round(other_time * 0.15, 3)
                    if connection_time > 2.0:  # Cap at 2s (nếu không reuse)
                        connection_time = 2.0
            
            # Fetch time: estimate từ thời gian còn lại sau execution
            fetch_time = 0.5  # Default estimate
            if playbook_duration > 0 and execution_time > 0:
                other_time = playbook_duration - execution_time
                if other_time > connection_time:
                    # Fetch thường chiếm 30-50% của other_time (sau khi trừ connection)
                    fetch_time = round((other_time - connection_time) * 0.4, 3)
                    if fetch_time > 3.0:  # Cap at 3s
                        fetch_time = 3.0
            
            # File checks time: rất nhỏ, estimate
            file_checks_time = 0.3  # Default estimate (stat check rất nhanh)
            
            timing_breakdown = {
                'inventory_lookup_seconds': round(timing['inventory_lookup'] - timing['start'], 3) if timing['inventory_lookup'] else 0,
                'playbook_execution_seconds': playbook_duration,
                'report_parsing_seconds': round(timing['end'] - timing['report_parsing'], 3) if timing['report_parsing'] else 0,
                'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
                # Timing từ playbook (chính xác)
                'task_execution_seconds': execution_time,
                # Timing estimate từ Python level (không cần thêm task)
                'connection_to_node_seconds': connection_time,
                'file_checks_seconds': file_checks_time,
                'result_fetch_seconds': fetch_time
            }
            
            # Merge với Ansible timing nếu có (để backward compatibility)
            if ansible_timing:
                timing_breakdown['ansible_breakdown'] = ansible_timing
                # Override với values từ playbook nếu có
                if ansible_timing.get('connection_seconds', 0) > 0:
                    timing_breakdown['connection_to_node_seconds'] = ansible_timing.get('connection_seconds', 0)
                if ansible_timing.get('file_checks_seconds', 0) > 0:
                    timing_breakdown['file_checks_seconds'] = ansible_timing.get('file_checks_seconds', 0)
                if ansible_timing.get('fetch_seconds', 0) > 0:
                    timing_breakdown['result_fetch_seconds'] = ansible_timing.get('fetch_seconds', 0)
            
            logger.info(f"Timing breakdown: {timing_breakdown}")
            
            return {
                "success": True,
                "results": results,
                "details": result,
                "timing": timing_breakdown
            }
        else:
            timing['end'] = time.time()
            timing_breakdown = {
                'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
                'failed_at': 'playbook_execution'
            }
            return {
                "success": False,
                "error": result.get('error', 'Ansible playbook failed'),
                "details": result,
                "timing": timing_breakdown
            }
            
    except Exception as e:
        timing['end'] = time.time()
        timing_breakdown = {
            'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
            'failed_at': 'exception'
        }
        logger.error(f"Error in run_scan: {e}")
        return {
            "success": False,
            "error": str(e),
            "timing": timing_breakdown
        }

def run_remediation(check_id: str, cluster_name: str = 'default', node_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Run remediation on K8s cluster via Ansible
    
    Args:
        check_id: Check ID to remediate
        cluster_name: Cluster name
        node_name: Optional specific node name
    
    Returns:
        Dict with remediation results and timing
    """
    import time
    timing = {
        'start': time.time(),
        'inventory_lookup': None,
        'playbook_start': None,
        'playbook_end': None,
        'end': None
    }
    
    try:
        inventory_path = _find_inventory_file(cluster_name)
        timing['inventory_lookup'] = time.time()
        
        if not inventory_path:
            return {
                "success": False,
                "error": f"Inventory file not found for cluster: {cluster_name}"
            }
        
        timing['playbook_start'] = time.time()
        result = run_ansible_playbook(
            "kube-check-remediate.yml",
            inventory_path,
            extra_vars={
                "check_id": check_id,
                "node_name": node_name,
                "auto_yes": True
            }
        )
        timing['playbook_end'] = time.time()
        
        # Parse timing từ Ansible output
        remediation_timing = {}
        if result.get('output'):
            import re
            output_text = result.get('output', '')
            
            # Parse từ REMEDIATION_TIMING_JSON_START (giống scan)
            remediation_timing_match = re.search(r'REMEDIATION_TIMING_JSON_START(.*?)REMEDIATION_TIMING_JSON_END', output_text, re.DOTALL)
            if remediation_timing_match:
                try:
                    json_str = remediation_timing_match.group(1).strip()
                    json_str = json_str.replace('\\"', '"')
                    json_str = re.sub(r'"(\d+)"', r'\1', json_str)  # "8" -> 8
                    timing_data = json.loads(json_str)
                    remediation_timing = {
                        'prescan_seconds': float(timing_data.get('prescan_seconds', 0)),
                        'remediation_seconds': float(timing_data.get('remediation_seconds', 0)),
                        'verification_seconds': float(timing_data.get('verification_seconds', 0))
                    }
                    logger.info(f"Parsed remediation timing from playbook: {remediation_timing}")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse remediation timing JSON: {e}")
        
        timing['end'] = time.time()
        
        # Calculate timing breakdown (giống scan)
        playbook_duration = round(timing['playbook_end'] - timing['playbook_start'], 3) if timing['playbook_start'] and timing['playbook_end'] else 0
        prescan_time = remediation_timing.get('prescan_seconds', 0) if remediation_timing else 0
        remediation_time = remediation_timing.get('remediation_seconds', 0) if remediation_timing else 0
        verification_time = remediation_timing.get('verification_seconds', 0) if remediation_timing else 0
        
        # Nếu không parse được, estimate từ playbook_duration
        if prescan_time == 0 and playbook_duration > 0:
            # Pre-scan thường tương đương với verification (cùng là scan)
            prescan_time = round(playbook_duration * 0.25, 3)
            logger.warning(f"Could not parse prescan time, estimating: {prescan_time}s")
        
        if remediation_time == 0 and playbook_duration > 0:
            # Remediation thường chiếm 30-40% của playbook_duration
            remediation_time = round(playbook_duration * 0.35, 3)
            logger.warning(f"Could not parse remediation time, estimating: {remediation_time}s")
        
        if verification_time == 0 and playbook_duration > 0 and remediation_time > 0:
            # Verification thường chiếm 25-30% của playbook_duration (tương đương prescan)
            if prescan_time > 0:
                verification_time = prescan_time  # Estimate bằng prescan
            else:
                remaining = playbook_duration - remediation_time
                verification_time = round(remaining * 0.45, 3)
            logger.warning(f"Could not parse verification time, estimating: {verification_time}s")
        
        # Estimate connection và fetch time (giống scan)
        connection_time = 0.1  # Default estimate
        fetch_time = 0.5  # Default estimate
        
        if playbook_duration > 0 and prescan_time > 0 and remediation_time > 0 and verification_time > 0:
            other_time = playbook_duration - prescan_time - remediation_time - verification_time
            if other_time > 0:
                connection_time = round(other_time * 0.15, 3)
                if connection_time > 2.0:
                    connection_time = 2.0
                fetch_time = round((other_time - connection_time) * 0.4, 3)
                if fetch_time > 3.0:
                    fetch_time = 3.0
        
        timing_breakdown = {
            'inventory_lookup_seconds': round(timing['inventory_lookup'] - timing['start'], 3) if timing['inventory_lookup'] else 0,
            'playbook_execution_seconds': playbook_duration,
            'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
            # Timing từ playbook (chính xác)
            'prescan_seconds': prescan_time,
            'remediation_seconds': remediation_time,
            'verification_seconds': verification_time,
            # Timing estimate từ Python level
            'connection_to_node_seconds': connection_time,
            'result_fetch_seconds': fetch_time
        }
        
        # Merge với remediation timing nếu có (để backward compatibility)
        if remediation_timing:
            timing_breakdown['ansible_breakdown'] = remediation_timing
        
        logger.info(f"Remediation timing breakdown: {timing_breakdown}")
        
        return {
            "success": result.get('success', False),
            "details": result,
            "timing": timing_breakdown
        }
        
    except Exception as e:
        timing['end'] = time.time()
        timing_breakdown = {
            'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
            'failed_at': 'exception'
        }
        logger.error(f"Error in run_remediation: {e}")
        return {
            "success": False,
            "error": str(e),
            "timing": timing_breakdown
        }

def bootstrap(cluster_name: str = 'default', node_names: Optional[Any] = None) -> Dict[str, Any]:
    """
    Bootstrap kube-check to nodes via Ansible.
    """
    import time
    timing = {
        'start': time.time(),
        'inventory_lookup': None,
        'playbook_start': None,
        'playbook_end': None,
        'end': None
    }
    
    try:
        logger.info(f"=== BOOTSTRAP START === cluster={cluster_name}, node_names={node_names}, type={type(node_names)}")
        logger.info(f"Bootstrap timing: start={timing['start']}")
        
        # Validate node_names
        if not node_names:
            return {
                "success": False,
                "error": "nodeNames is required and cannot be empty"
            }
        
        inventory_path = _find_inventory_file(cluster_name)
        timing['inventory_lookup'] = time.time()
        inventory_lookup_duration = round(timing['inventory_lookup'] - timing['start'], 3)
        logger.info(f"Bootstrap timing: inventory_lookup={inventory_lookup_duration}s")
        
        if not inventory_path:
            return {
                "success": False,
                "error": f"Inventory file not found for cluster: {cluster_name}"
            }

        # Convert node_names to pattern for Ansible
        node_name_pattern: Optional[str] = None
        if isinstance(node_names, list):
            if len(node_names) == 0:
                return {
                    "success": False,
                    "error": "nodeNames list cannot be empty"
                }
            node_name_pattern = ",".join(str(n) for n in node_names)
        elif isinstance(node_names, str):
            node_name_pattern = node_names
        else:
            return {
                "success": False,
                "error": f"nodeNames must be a list or string, got {type(node_names)}"
            }

        logger.info(f"Bootstrap pattern: {node_name_pattern}")

        # Use pinned local Kube-check path
        kubecheck_path_local = str(KUBECHECK_PATH_LOCAL)
        
        if not os.path.exists(kubecheck_path_local):
            return {
                "success": False,
                "error": f"Kube-check path not found: {kubecheck_path_local}"
            }

        logger.info(f"Running bootstrap playbook for nodes: {node_name_pattern}")
        timing['playbook_start'] = time.time()
        logger.info(f"Bootstrap timing: playbook_start={timing['playbook_start']}")
        result = run_ansible_playbook(
            "kube-check-bootstrap.yml",
            inventory_path,
            extra_vars={
                "node_name": node_name_pattern,
                "kubecheck_path_local": kubecheck_path_local
                # kubecheck_path and reports_path will use default: ansible_env.HOME + '/Kube-check'
            }
        )
        timing['playbook_end'] = time.time()
        playbook_duration = round(timing['playbook_end'] - timing['playbook_start'], 3)
        logger.info(f"Bootstrap timing: playbook_end={timing['playbook_end']}, playbook_duration={playbook_duration}s")
        
        # Parse timing từ Ansible output nếu có
        ansible_timing = {}
        if result.get('output'):
            import re
            output_text = result.get('output', '')
            
            # Tìm timing breakdown từ Ansible debug output
            copy_match = re.search(r'Copy time:\s*(\d+)s', output_text)
            install_match = re.search(r'Install dependencies time:\s*(\d+)s', output_text)
            total_match = re.search(r'Total bootstrap time:\s*(\d+)s', output_text)
            
            if copy_match or install_match or total_match:
                ansible_timing = {
                    'copy_seconds': int(copy_match.group(1)) if copy_match else 0,
                    'install_dependencies_seconds': int(install_match.group(1)) if install_match else 0,
                    'total_bootstrap_seconds': int(total_match.group(1)) if total_match else 0
                }
                logger.info(f"Bootstrap timing: Parsed Ansible timing - copy={ansible_timing.get('copy_seconds', 0)}s, install_deps={ansible_timing.get('install_dependencies_seconds', 0)}s, total_ansible={ansible_timing.get('total_bootstrap_seconds', 0)}s")

        logger.info(f"Bootstrap playbook result: success={result.get('success')}, error={result.get('error')}, ssh_error={result.get('ssh_error')}")

        # Calculate timing breakdown
        timing['end'] = time.time()
        timing_breakdown = {
            'inventory_lookup_seconds': round(timing['inventory_lookup'] - timing['start'], 3) if timing['inventory_lookup'] else 0,
            'playbook_execution_seconds': round(timing['playbook_end'] - timing['playbook_start'], 3) if timing['playbook_start'] and timing['playbook_end'] else 0,
            'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0
        }
        
        # Merge với Ansible timing nếu có
        if ansible_timing:
            timing_breakdown['ansible_breakdown'] = ansible_timing
            timing_breakdown['copy_kubecheck_seconds'] = ansible_timing.get('copy_seconds', 0)
            timing_breakdown['install_dependencies_seconds'] = ansible_timing.get('install_dependencies_seconds', 0)
            timing_breakdown['total_bootstrap_seconds'] = ansible_timing.get('total_bootstrap_seconds', 0)
        
        # Log timing breakdown chi tiết
        logger.info("=== BOOTSTRAP TIMING BREAKDOWN ===")
        logger.info(f"  Inventory lookup: {timing_breakdown.get('inventory_lookup_seconds', 0)}s")
        logger.info(f"  Playbook execution: {timing_breakdown.get('playbook_execution_seconds', 0)}s")
        if timing_breakdown.get('copy_kubecheck_seconds', 0) > 0:
            logger.info(f"  ├─ Copy Kube-check code: {timing_breakdown.get('copy_kubecheck_seconds', 0)}s")
        if timing_breakdown.get('install_dependencies_seconds', 0) > 0:
            logger.info(f"  ├─ Install dependencies: {timing_breakdown.get('install_dependencies_seconds', 0)}s")
        if timing_breakdown.get('total_bootstrap_seconds', 0) > 0:
            logger.info(f"  └─ Total (Ansible): {timing_breakdown.get('total_bootstrap_seconds', 0)}s")
        logger.info(f"  TOTAL (Python): {timing_breakdown.get('total_seconds', 0)}s")
        logger.info(f"=== END BOOTSTRAP TIMING ===")

        # Update bootstrap_status in inventory file if bootstrap succeeded
        status_map = None
        if result.get('success'):
            try:
                _update_bootstrap_status(inventory_path, node_names, 'ready')
                logger.info(f"Updated bootstrap_status in inventory for nodes: {node_names}")
            except Exception as e:
                logger.warning(f"Failed to update bootstrap_status in inventory: {e}")
            
            # Invalidate cache so next inventory check will get fresh status
            invalidate_bootstrap_cache(cluster_name)
            logger.info(f"Invalidated bootstrap cache for cluster: {cluster_name}")

            # Immediately refresh bootstrap status to return up-to-date states
            try:
                status_map = _check_bootstrap_status_real(cluster_name, inventory_path, force_refresh=True)
                logger.info(f"Refreshed bootstrap status after bootstrap: {status_map}")
            except Exception as e:
                logger.warning(f"Could not refresh bootstrap status post-bootstrap: {e}")

        # Build response with clear error message
        response = {
            "success": result.get('success', False),
            "details": result,
            "clusterName": cluster_name,
            "nodeNames": node_names,
            "timing": timing_breakdown
        }
        if status_map is not None:
            response["bootstrapStatus"] = status_map
        
        # Log success summary
        if result.get('success'):
            logger.info(f"=== BOOTSTRAP SUCCESS === Total time: {timing_breakdown.get('total_seconds', 0)}s, Nodes: {node_names}")
        
        # Always include error message when bootstrap fails
        if not result.get('success'):
            timing['end'] = time.time()
            timing_breakdown = {
                'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
                'failed_at': 'playbook_execution'
            }
            response['timing'] = timing_breakdown
            logger.error(f"=== BOOTSTRAP FAILED === Total time: {timing_breakdown.get('total_seconds', 0)}s, Failed at: {timing_breakdown.get('failed_at', 'unknown')}")
            
            # Priority: ssh_error > error > default message
            if result.get('ssh_error'):
                response["error"] = result.get('ssh_error')
            elif result.get('error'):
                response["error"] = result.get('error')
            else:
                # Extract error from output if no explicit error message
                output = result.get('output', '')
                if output:
                    # Look for last fatal or failed message
                    import re
                    fatal_match = re.search(r'fatal:\s*\[([^\]]+)\]\s*([^\n]+)', output)
                    if fatal_match:
                        response["error"] = f"Node {fatal_match.group(1)}: {fatal_match.group(2).strip()}"
                    else:
                        # Get last non-empty line from output
                        lines = [l.strip() for l in output.split('\n') if l.strip()]
                        if lines:
                            response["error"] = f"Bootstrap failed: {lines[-1]}"
                        else:
                            response["error"] = f"Bootstrap failed with return code {result.get('returncode', 'unknown')}"
                else:
                    response["error"] = "Bootstrap failed: No output available"
        
        return response
    except Exception as e:
        timing['end'] = time.time()
        timing_breakdown = {
            'total_seconds': round(timing['end'] - timing['start'], 3) if timing['end'] else 0,
            'failed_at': 'exception'
        }
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"=== BOOTSTRAP EXCEPTION === Error: {e}, Total time: {timing_breakdown.get('total_seconds', 0)}s")
        logger.error(f"Bootstrap exception traceback:\n{error_trace}")
        return {
            "success": False,
            "error": str(e),
            "traceback": error_trace,
            "timing": timing_breakdown
        }

def test_connection(cluster_name: str, kubeconfig: Optional[str] = None, nodes: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    Test connection to K8s cluster
    
    Args:
        cluster_name: Cluster name
        kubeconfig: Optional base64 encoded kubeconfig
        nodes: Optional list of nodes
    
    Returns:
        Dict with connection test results
    """
    try:
        # Save kubeconfig if provided
        kubeconfig_path = None
        if kubeconfig:
            kubeconfig_path = save_kubeconfig(kubeconfig, cluster_name)
        else:
            kubeconfig_path = os.path.expanduser("~/.kube/config")
        
        # Create/update inventory
        if nodes:
            # Check if user wants INI format (if any node has format specified)
            format_type = nodes[0].get('inventory_format', 'yaml') if nodes else 'yaml'
            inventory_path = create_inventory(nodes, cluster_name, format=format_type)
        else:
            # Try both formats
            yaml_path = INVENTORY_DIR / "hosts.yml"
            ini_path = INVENTORY_DIR / "hosts.ini"
            inventory_path = yaml_path if yaml_path.exists() else (ini_path if ini_path.exists() else yaml_path)
        
        # Test connection
        result = run_ansible_playbook(
            "test-connection.yml",
            inventory_path,
            extra_vars={
                "kubeconfig_path": kubeconfig_path
            }
        )
        
        return {
            "success": result.get('success', False),
            "message": "Connection test completed",
            "details": result
        }
        
    except Exception as e:
        logger.error(f"Error in test_connection: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def _extract_ssh_error(output: str) -> Optional[str]:
    """Extract SSH connection errors from Ansible output"""
    import re
    
    # Pattern for SSH connection failures
    patterns = [
        r'Failed to connect to the host via ssh:.*?(?:\n|$)',
        r'Permission denied.*?\(publickey,password\)',
        r'UNREACHABLE!.*?"msg":\s*"([^"]+)"',
        r'SSH Error:.*?(?:\n|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, output, re.MULTILINE | re.IGNORECASE)
        if match:
            error_msg = match.group(0).strip()
            # Clean up the message
            if 'UNREACHABLE' in output:
                # Try to extract JSON message
                json_match = re.search(r'"msg":\s*"([^"]+)"', output)
                if json_match:
                    error_msg = json_match.group(1)
            return error_msg
    
    # Check for common SSH errors
    if 'Permission denied' in output:
        return "SSH Permission denied: The SSH key is not authorized on the remote node. Please add the public key to ~/.ssh/authorized_keys on the target node."
    if 'Connection refused' in output:
        return "SSH Connection refused: Cannot connect to the remote node. Check if SSH service is running and firewall rules."
    if 'Host key verification failed' in output:
        return "SSH Host key verification failed: The host key has changed or is not trusted."
    
    return None

def run_ansible_playbook(playbook_name: str, inventory_path: Path, extra_vars: Optional[Dict] = None) -> Dict[str, Any]:
    """Run Ansible playbook and return results"""
    playbook_path = PLAYBOOKS_DIR / playbook_name
    
    if not playbook_path.exists():
        return {
            "success": False,
            "error": f"Playbook not found: {playbook_path}"
        }
    
    # Validate inventory file and check SSH keys
    if inventory_path.exists():
        try:
            import yaml
            with open(inventory_path, 'r') as f:
                inventory_data = yaml.safe_load(f)
            
            # Check SSH keys for all hosts
            all_hosts = inventory_data.get('all', {}).get('hosts', {})
            for hostname, host_vars in all_hosts.items():
                if isinstance(host_vars, dict):
                    ssh_key = host_vars.get('ansible_ssh_private_key_file')
                    ansible_user = host_vars.get('ansible_user', 'root')
                    ansible_host = host_vars.get('ansible_host', hostname)
                    
                    if ssh_key:
                        # Check if key file exists
                        if os.path.exists(ssh_key):
                            # Check permissions (should be 600)
                            key_stat = os.stat(ssh_key)
                            key_mode = oct(key_stat.st_mode)[-3:]
                            if key_mode != '600':
                                logger.warning(f"SSH key {ssh_key} has wrong permissions: {key_mode} (should be 600)")
                            else:
                                logger.info(f"SSH key validated: {ssh_key} (permissions: {key_mode})")
                        else:
                            logger.error(f"SSH key not found for {hostname}: {ssh_key}")
                    else:
                        logger.warning(f"No SSH key specified for {hostname} (user: {ansible_user}, host: {ansible_host})")
        except Exception as e:
            logger.warning(f"Could not validate SSH keys from inventory: {e}")
    
    # Build ansible-playbook command với các flags tối ưu
    cmd = [
        "ansible-playbook",
        "-i", str(inventory_path),
        str(playbook_path)
        # Note: Không thêm -v để giảm output và tăng tốc
        # Verbose output làm chậm execution
    ]
    
    if extra_vars:
        cmd.extend(["-e", json.dumps(extra_vars)])
    
    # Set ANSIBLE_CONFIG environment variable
    ansible_config_path = ANSIBLE_DIR / "ansible.cfg"
    env = os.environ.copy()
    if ansible_config_path.exists():
        env['ANSIBLE_CONFIG'] = str(ansible_config_path)
        logger.info(f"Using ANSIBLE_CONFIG: {ansible_config_path}")
    
    # Ensure SSH key is used from inventory, not asking for password
    env['ANSIBLE_HOST_KEY_CHECKING'] = 'False'
    env['ANSIBLE_SSH_ARGS'] = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no -o LogLevel=ERROR'
    # Clear any cached SSH connections that might have host key issues
    env['ANSIBLE_SSH_CONTROL_PATH'] = '/tmp/ansible-ssh-%%h-%%p-%%r'
    # Force disable ControlMaster to avoid caching issues
    env['ANSIBLE_SSH_CONTROL_PATH_DIR'] = '/tmp'
    # Clear known_hosts before running to avoid host key verification issues
    import subprocess
    try:
        subprocess.run('rm -f /root/.ssh/known_hosts ~/.ssh/known_hosts /tmp/ansible-ssh-* 2>/dev/null', 
                      shell=True, stderr=subprocess.DEVNULL, timeout=2)
    except:
        pass
    
    # Run playbook
    try:
        log_file = LOGS_DIR / f"{playbook_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        with open(log_file, 'w') as f:
            result = subprocess.run(
                cmd,
                text=True,
                timeout=1800,  # 30 minutes
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env
            )
        
        # Tối ưu: chỉ đọc phần cuối của log file nếu file quá lớn (last 5000 lines)
        try:
            # Check file size first
            file_size = log_file.stat().st_size
            if file_size > 1024 * 1024:  # > 1MB
                # Read only last 5000 lines
                with open(log_file, 'rb') as f:
                    # Seek to end and read backwards
                    f.seek(0, 2)  # Seek to end
                    size = f.tell()
                    # Read last 100KB
                    read_size = min(100 * 1024, size)
                    f.seek(max(0, size - read_size))
                    tail_content = f.read().decode('utf-8', errors='ignore')
                    # Get last 5000 lines
                    lines = tail_content.split('\n')
                    output = '\n'.join(lines[-5000:])
                    logger.info(f"Log file too large ({file_size} bytes), reading only last 5000 lines")
            else:
                output = log_file.read_text()
        except Exception as e:
            logger.warning(f"Error reading log file, reading full content: {e}")
            output = log_file.read_text()
        
        # Extract SSH connection errors for better error messages
        ssh_error = None
        error_message = None
        if result.returncode != 0:
            ssh_error = _extract_ssh_error(output)
            
            # Extract error from Ansible output if no SSH error
            if not ssh_error:
                # Look for "fatal:" or "FAILED!" in output
                import re
                fatal_pattern = r'fatal:\s*\[([^\]]+)\]\s*([^\n]+)'
                failed_pattern = r'FAILED!\s*=>\s*\{[^}]*"msg":\s*"([^"]+)"'
                
                fatal_match = re.search(fatal_pattern, output)
                failed_match = re.search(failed_pattern, output)
                
                if fatal_match:
                    error_message = f"Node {fatal_match.group(1)}: {fatal_match.group(2).strip()}"
                elif failed_match:
                    error_message = failed_match.group(1).strip()
                else:
                    # Extract last few lines of output as error
                    lines = output.split('\n')
                    error_lines = [line for line in lines[-10:] if line.strip() and not line.startswith('PLAY') and not line.startswith('TASK')]
                    if error_lines:
                        error_message = error_lines[-1].strip()
                    else:
                        error_message = f"Playbook failed with return code {result.returncode}"
        
        result_dict = {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "output": output,
            "log_file": str(log_file)
        }
        
        if ssh_error:
            result_dict["ssh_error"] = ssh_error
            result_dict["error"] = ssh_error
        elif error_message:
            result_dict["error"] = error_message
        
        return result_dict
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Playbook execution timeout"
        }
    except Exception as e:
        logger.error(f"Error running playbook: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def save_kubeconfig(kubeconfig_base64: str, cluster_name: str) -> str:
    """Save kubeconfig to file"""
    # Support both Docker and local environments
    kubeconfig_dir = Path(os.getenv('KUBECONFIG_DIR', os.path.expanduser("~/.kube")))
    kubeconfig_dir.mkdir(parents=True, exist_ok=True)
    
    kubeconfig_path = kubeconfig_dir / f"config_{cluster_name}"
    
    try:
        kubeconfig_content = base64.b64decode(kubeconfig_base64).decode('utf-8')
        kubeconfig_path.write_text(kubeconfig_content)
        kubeconfig_path.chmod(0o600)
        logger.info(f"Saved kubeconfig to {kubeconfig_path}")
        return str(kubeconfig_path)
    except Exception as e:
        logger.error(f"Error saving kubeconfig: {e}")
        raise

def create_inventory(nodes: List[Dict], cluster_name: str, format: str = 'yaml') -> Path:
    """
    Create Ansible inventory file from nodes list
    
    Args:
        nodes: List of node dictionaries
        cluster_name: Cluster name
        format: 'yaml' or 'ini'
    
    Returns:
        Path to inventory file
    """
    if format == 'ini':
        inventory_path = INVENTORY_DIR / f"{cluster_name}_hosts.ini"
        return _create_ini_inventory(nodes, cluster_name, inventory_path)
    else:
        inventory_path = INVENTORY_DIR / f"{cluster_name}_hosts.yml"
        return _create_yaml_inventory(nodes, cluster_name, inventory_path)

def _create_yaml_inventory(nodes: List[Dict], cluster_name: str, inventory_path: Path) -> Path:
    """Create YAML format inventory"""
    inventory = {
        "all": {
            "hosts": {},
            "vars": {
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
            }
        }
    }
    
    # Group nodes by role if provided
    masters = []
    workers = []
    others = []
    
    for node in nodes:
        role = node.get('role', '').lower()
        if 'master' in role:
            masters.append(node)
        elif 'worker' in role:
            workers.append(node)
        else:
            others.append(node)
    
    # Add groups if we have them
    if masters:
        inventory["masters"] = {"hosts": {}}
    if workers:
        inventory["workers"] = {"hosts": {}}
    
    # Helper function to resolve SSH key path
    def resolve_ssh_key_path(ssh_key):
        if not ssh_key:
            return None
        if os.path.isabs(ssh_key):
            if os.path.exists(ssh_key):
                return ssh_key
            else:
                logger.warning(f"SSH key not found (absolute path): {ssh_key}")
                return ssh_key  # Return anyway
        
        # Try common locations
        possible_paths = [
            os.path.join(str(ANSIBLE_DIR), 'ssh_keys', ssh_key),
            os.path.join('/app/ansible/ssh_keys', ssh_key),
            os.path.expanduser(f"~/{ssh_key}"),
            os.path.join(os.path.dirname(__file__), '..', '..', 'ansible', 'ssh_keys', ssh_key)
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                logger.info(f"Found SSH key at: {abs_path}")
                return abs_path
        
        # If not found, return absolute path anyway
        final_path = os.path.abspath(os.path.join(str(ANSIBLE_DIR), 'ssh_keys', ssh_key))
        logger.warning(f"SSH key not found, using expected path: {final_path}")
        return final_path
    
    for node in nodes:
        host_vars = {
            "ansible_host": node.get('ip'),
            "ansible_user": node.get('user', 'root'),
        }
        
        if node.get('ssh_key'):
            ssh_key = resolve_ssh_key_path(node['ssh_key'])
            if ssh_key:
                host_vars["ansible_ssh_private_key_file"] = ssh_key
        
        if node.get('ssh_password'):
            host_vars["ansible_ssh_pass"] = node['ssh_password']
        
        node_name = node.get('name', node.get('ip'))
        inventory["all"]["hosts"][node_name] = host_vars
        
        # Add to groups
        role = node.get('role', '').lower()
        if 'master' in role and masters:
            inventory["masters"]["hosts"][node_name] = host_vars
        elif 'worker' in role and workers:
            inventory["workers"]["hosts"][node_name] = host_vars
    
    inventory_path.write_text(yaml.dump(inventory, default_flow_style=False))
    logger.info(f"Created YAML inventory: {inventory_path}")
    
    return inventory_path

def _create_ini_inventory(nodes: List[Dict], cluster_name: str, inventory_path: Path) -> Path:
    """Create INI format inventory (like your format)"""
    lines = []
    
    # Group nodes by role
    masters = []
    workers = []
    others = []
    
    for node in nodes:
        role = node.get('role', '').lower()
        if 'master' in role:
            masters.append(node)
        elif 'worker' in role:
            workers.append(node)
        else:
            others.append(node)
    
    # Helper function to resolve SSH key path
    def resolve_ssh_key(ssh_key):
        if not ssh_key:
            return None
        if os.path.isabs(ssh_key):
            if os.path.exists(ssh_key):
                return ssh_key
            else:
                logger.warning(f"SSH key not found (absolute path): {ssh_key}")
                return ssh_key  # Return anyway, let Ansible handle error
        
        # Try common locations
        possible_paths = [
            os.path.join(str(ANSIBLE_DIR), 'ssh_keys', ssh_key),
            os.path.join('/app/ansible/ssh_keys', ssh_key),
            os.path.expanduser(f"~/{ssh_key}"),
            os.path.join(os.path.dirname(__file__), '..', '..', 'ansible', 'ssh_keys', ssh_key)
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                logger.info(f"Found SSH key at: {abs_path}")
                return abs_path
        
        # If not found, return absolute path anyway (Ansible will show better error)
        final_path = os.path.join(str(ANSIBLE_DIR), 'ssh_keys', ssh_key)
        logger.warning(f"SSH key not found, using: {final_path}")
        return final_path
    
    # Write masters group
    if masters:
        lines.append("[masters]")
        for node in masters:
            node_name = node.get('name', node.get('ip'))
            line = f"{node_name} ansible_host={node.get('ip')} ansible_user={node.get('user', 'root')}"
            ssh_key = resolve_ssh_key(node.get('ssh_key'))
            if ssh_key:
                line += f" ansible_ssh_private_key_file={ssh_key}"
            lines.append(line)
        lines.append("")
    
    # Write workers group
    if workers:
        lines.append("[workers]")
        for node in workers:
            node_name = node.get('name', node.get('ip'))
            line = f"{node_name} ansible_host={node.get('ip')} ansible_user={node.get('user', 'root')}"
            ssh_key = resolve_ssh_key(node.get('ssh_key'))
            if ssh_key:
                line += f" ansible_ssh_private_key_file={ssh_key}"
            lines.append(line)
        lines.append("")
    
    # Write other nodes to [all] if no role
    if others:
        lines.append("[all]")
        for node in others:
            node_name = node.get('name', node.get('ip'))
            line = f"{node_name} ansible_host={node.get('ip')} ansible_user={node.get('user', 'root')}"
            if node.get('ssh_key'):
                line += f" ansible_ssh_private_key_file={node['ssh_key']}"
            lines.append(line)
        lines.append("")
    
    # Write [all:vars]
    lines.append("[all:vars]")
    lines.append("ansible_ssh_common_args='-o StrictHostKeyChecking=no'")
    lines.append("ansible_python_interpreter=/usr/bin/python3")
    
    inventory_path.write_text("\n".join(lines))
    logger.info(f"Created INI inventory: {inventory_path}")
    
    return inventory_path

def _find_inventory_file(cluster_name: str) -> Optional[Path]:
    """
    Find inventory file (try both YAML and INI formats)
    Priority: cluster-specific > default > create new
    """
    # Priority 1: Cluster-specific files
    yaml_path = INVENTORY_DIR / f"{cluster_name}_hosts.yml"
    ini_path = INVENTORY_DIR / f"{cluster_name}_hosts.ini"
    
    if yaml_path.exists():
        logger.info(f"Found inventory file: {yaml_path}")
        return yaml_path
    elif ini_path.exists():
        logger.info(f"Found inventory file: {ini_path}")
        return ini_path
    
    # Priority 2: Default files
    default_yaml = INVENTORY_DIR / "hosts.yml"
    default_ini = INVENTORY_DIR / "hosts.ini"
    
    if default_yaml.exists():
        logger.info(f"Found default inventory file: {default_yaml}")
        return default_yaml
    elif default_ini.exists():
        logger.info(f"Found default inventory file: {default_ini}")
        return default_ini
    
    # Priority 3: Try any .ini or .yml files in inventory directory
    for file in INVENTORY_DIR.glob("*.ini"):
        if file.name != "hosts.yml.example":
            logger.info(f"Found inventory file: {file}")
            return file
    
    for file in INVENTORY_DIR.glob("*.yml"):
        if file.name != "hosts.yml.example":
            logger.info(f"Found inventory file: {file}")
            return file
    
    logger.warning(f"No inventory file found for cluster: {cluster_name}")
    return None


def _load_bootstrap_cache_from_file(cluster_name: str, inventory_path: Path) -> Optional[Dict[str, Any]]:
    """Load bootstrap status cache from file"""
    cache_file = CACHE_DIR / f"bootstrap_{cluster_name}_{inventory_path.stem}.json"
    if cache_file.exists():
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
                # Convert timestamp string back to datetime
                if 'timestamp' in data:
                    data['timestamp'] = datetime.fromisoformat(data['timestamp'])
                return data
        except Exception as e:
            logger.warning(f"Failed to load cache file {cache_file}: {e}")
    return None

def _save_bootstrap_cache_to_file(cluster_name: str, inventory_path: Path, status_map: Dict[str, str], timestamp: datetime):
    """Save bootstrap status cache to file"""
    cache_file = CACHE_DIR / f"bootstrap_{cluster_name}_{inventory_path.stem}.json"
    try:
        data = {
            'status_map': status_map,
            'timestamp': timestamp.isoformat(),
            'cluster_name': cluster_name,
            'inventory_path': str(inventory_path)
        }
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved bootstrap cache to {cache_file}")
    except Exception as e:
        logger.warning(f"Failed to save cache file {cache_file}: {e}")

def _check_bootstrap_status_real(cluster_name: str, inventory_path: Path, force_refresh: bool = False) -> Dict[str, str]:
    """
    Check bootstrap status on actual nodes by running playbook
    Uses 2-layer cache: in-memory (hot) + file (persistent)
    
    Args:
        cluster_name: Cluster name (used as cache key)
        inventory_path: Path to inventory file
        force_refresh: If True, bypass cache and check again
    
    Returns:
        Dict mapping hostname -> bootstrap_status ('ready', 'venv_missing', 'not_bootstrapped')
    """
    cache_key = f"{cluster_name}:{str(inventory_path)}"
    now = datetime.now()
    
    # Layer 1: Check in-memory cache (hot cache)
    if not force_refresh and cache_key in _bootstrap_status_cache:
        cached_data = _bootstrap_status_cache[cache_key]
        cache_time = cached_data.get('timestamp')
        if cache_time and (now - cache_time) < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.info(f"Using hot cache for bootstrap status: {cluster_name}")
            return cached_data.get('status_map', {})
        else:
            # Hot cache expired, remove it
            del _bootstrap_status_cache[cache_key]
    
    # Layer 2: Check file cache (persistent cache)
    if not force_refresh:
        file_cache = _load_bootstrap_cache_from_file(cluster_name, inventory_path)
        if file_cache:
            cache_time = file_cache.get('timestamp')
            if cache_time and isinstance(cache_time, datetime):
                if (now - cache_time) < timedelta(seconds=CACHE_TTL_SECONDS):
                    # Load into hot cache and return
                    status_map = file_cache.get('status_map', {})
                    _bootstrap_status_cache[cache_key] = {
                        'status_map': status_map,
                        'timestamp': cache_time
                    }
                    logger.info(f"Using file cache for bootstrap status: {cluster_name}")
                    return status_map
                else:
                    logger.info(f"File cache expired for {cluster_name}, checking nodes...")
    
    # Layer 3: Run playbook to check actual status on nodes
    try:
        logger.info(f"Checking bootstrap status on actual nodes for cluster {cluster_name}...")
        result = run_ansible_playbook(
            "check-bootstrap-status.yml",
            inventory_path
            # kubecheck_path will use default: ansible_env.HOME + '/Kube-check'
        )
        
        status_map = {}
        # Always try to parse output, even if playbook partially failed
        # (some nodes might be unreachable, but others succeeded)
        output = result.get('output', '')
        if output:
            import re
            
            # PRIORITY 1: Parse JSON from BOOTSTRAP_TIMING_JSON_START (playbook output format)
            bootstrap_json_pattern = r'BOOTSTRAP_TIMING_JSON_START\s+(.*?)\s+BOOTSTRAP_TIMING_JSON_END'
            bootstrap_json_matches = re.findall(bootstrap_json_pattern, output, re.DOTALL)
            for json_str in bootstrap_json_matches:
                try:
                    # Clean up JSON string (Ansible debug output often escapes quotes)
                    clean_json_str = json_str.strip()
                    if r'\"' in clean_json_str:
                        clean_json_str = clean_json_str.replace(r'\"', '"')
                    
                    # Remove surrounding quotes if they exist after unescaping
                    if clean_json_str.startswith('"') and clean_json_str.endswith('"'):
                         clean_json_str = clean_json_str[1:-1]

                    json_data = json.loads(clean_json_str)
                    host = json_data.get('host')
                    bootstrap_status = json_data.get('bootstrap_status')
                    if host and bootstrap_status:
                        status_map[host] = bootstrap_status.strip()
                        logger.info(f"Parsed bootstrap status from JSON: {host} = {bootstrap_status}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse bootstrap JSON: {e}, content: {json_str[:100]}")
            
            # PRIORITY 2: Look for pattern: "NODE=hostname STATUS=status" (legacy format)
            if not status_map:
                pattern = r'NODE=(\S+)\s+STATUS=\s*([^\s\n"]+)'
                matches = re.findall(pattern, output)
                for node_name, status in matches:
                    status_map[node_name] = status.strip()
            
            # PRIORITY 3: Try alternative pattern if first one didn't match
            if not status_map:
                # Try matching entire line with debug msg format
                pattern2 = r'"msg":\s*"NODE=(\S+)\s+STATUS=\s*([^\s"]+)"'
                matches2 = re.findall(pattern2, output)
                for node_name, status in matches2:
                    status_map[node_name] = status.strip()
            
            # PRIORITY 4: Parse UNREACHABLE nodes from Ansible output (fallback)
            # Pattern: "hostname : UNREACHABLE! => {...}" or "hostname | UNREACHABLE! => {...}"
            # Also check PLAY RECAP section: "hostname : ok=X changed=Y unreachable=1 failed=Z"
            unreachable_patterns = [
                r'(\S+)\s*[|:]\s*UNREACHABLE!',  # Standard format
                r'(\S+)\s*:\s*ok=\d+\s+changed=\d+\s+unreachable=1',  # PLAY RECAP format
                r'(\S+)\s*:\s*ok=\d+\s+changed=\d+\s+unreachable=\d+\s+failed=\d+',  # Full PLAY RECAP
            ]
            for pattern in unreachable_patterns:
                unreachable_matches = re.findall(pattern, output, re.MULTILINE)
                for node_name in unreachable_matches:
                    # Only set if not already in status_map (to avoid overwriting successful checks)
                    if node_name not in status_map:
                        status_map[node_name] = 'unreachable'
                        logger.info(f"Detected unreachable node: {node_name}")
        
        if not status_map:
            if not result.get('success'):
                logger.warning(f"Bootstrap status check playbook failed: {result.get('error')}")
            # If no status found, try to use file cache as fallback
            file_cache = _load_bootstrap_cache_from_file(cluster_name, inventory_path)
            if file_cache:
                status_map = file_cache.get('status_map', {})
                logger.info(f"Using stale file cache as fallback for {cluster_name}")
        else:
            logger.info(f"Successfully parsed bootstrap status for {len(status_map)} node(s): {list(status_map.keys())}")
        
        # Update both caches
        _bootstrap_status_cache[cache_key] = {
            'status_map': status_map,
            'timestamp': now
        }
        _save_bootstrap_cache_to_file(cluster_name, inventory_path, status_map, now)
        
        logger.info(f"Bootstrap status check completed: {status_map}")
        return status_map
    except Exception as e:
        logger.error(f"Failed to check bootstrap status on nodes: {e}")
        # Try to use file cache as fallback
        file_cache = _load_bootstrap_cache_from_file(cluster_name, inventory_path)
        if file_cache:
            return file_cache.get('status_map', {})
        return {}

def invalidate_bootstrap_cache(cluster_name: str = None):
    """
    Invalidate bootstrap status cache (both in-memory and file)
    
    Args:
        cluster_name: If provided, only invalidate cache for this cluster.
                     If None, invalidate all caches.
    """
    # Invalidate in-memory cache
    if cluster_name:
        # Remove all cache entries for this cluster
        keys_to_remove = [k for k in _bootstrap_status_cache.keys() if k.startswith(f"{cluster_name}:")]
        for key in keys_to_remove:
            del _bootstrap_status_cache[key]
        logger.info(f"Invalidated in-memory bootstrap cache for cluster: {cluster_name}")
    else:
        _bootstrap_status_cache.clear()
        logger.info("Invalidated all in-memory bootstrap caches")
    
    # Invalidate file cache
    try:
        if cluster_name:
            # Find and delete cache files for this cluster
            pattern = f"bootstrap_{cluster_name}_*.json"
            for cache_file in CACHE_DIR.glob(pattern):
                cache_file.unlink()
                logger.info(f"Deleted cache file: {cache_file}")
        else:
            # Delete all bootstrap cache files
            for cache_file in CACHE_DIR.glob("bootstrap_*.json"):
                cache_file.unlink()
            logger.info("Deleted all bootstrap cache files")
    except Exception as e:
        logger.warning(f"Failed to delete cache files: {e}")

def get_inventory_nodes(cluster_name: str = 'default', force_refresh: bool = False) -> Dict[str, Any]:
    """
    Return inventory hosts with basic metadata and inferred roles.
    Checks actual bootstrap status on nodes instead of reading from inventory file.
    Uses cache to avoid running playbook on every request.
    
    Args:
        cluster_name: Cluster name
        force_refresh: If True, bypass cache and check bootstrap status again
    """
    inventory_path = _find_inventory_file(cluster_name)
    if not inventory_path:
        # Fallback mock data so UI can render even without inventory
        sample_nodes = [
            {"name": "master-1", "ip": "192.168.1.10", "user": "root", "role": "master", "status": "not_bootstrapped"},
            {"name": "worker-1", "ip": "192.168.1.20", "user": "root", "role": "worker", "status": "venv_missing"},
            {"name": "worker-2", "ip": "192.168.1.21", "user": "root", "role": "worker", "status": "ready"},
        ]
        return {
            "success": True,
            "clusterName": cluster_name,
            "nodes": sample_nodes,
            "mock": True,
            "message": "Inventory not found, returning sample nodes."
        }

    try:
        ansible_config_path = ANSIBLE_DIR / "ansible.cfg"
        env = os.environ.copy()
        if ansible_config_path.exists():
            env['ANSIBLE_CONFIG'] = str(ansible_config_path)

        cmd = [
            "ansible-inventory",
            "-i", str(inventory_path),
            "--list"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        if result.returncode != 0:
            return {
                "success": False,
                "error": "Failed to parse inventory",
                "details": result.stderr or result.stdout
            }

        data = json.loads(result.stdout)
        hostvars = data.get('_meta', {}).get('hostvars', {}) or {}

        def extract_hosts(group_obj: Any) -> set:
            if isinstance(group_obj, dict):
                hosts = group_obj.get('hosts', {})
                if isinstance(hosts, dict):
                    return set(hosts.keys())
                if isinstance(hosts, list):
                    return set(hosts)
            if isinstance(group_obj, list):
                return set(group_obj)
            return set()

        masters = extract_hosts(data.get('masters'))
        workers = extract_hosts(data.get('workers'))

        # Check actual bootstrap status on nodes (with cache)
        actual_status_map = _check_bootstrap_status_real(cluster_name, inventory_path, force_refresh=force_refresh)
        
        nodes: List[Dict[str, Any]] = []
        # Get all hostnames from inventory to ensure we check all nodes
        all_inventory_hosts = set(hostvars.keys())
        checked_hosts = set(actual_status_map.keys())
        
        # If force_refresh and some hosts are missing from status_map, they might be unreachable
        # But we already parse UNREACHABLE from output, so missing hosts are likely truly unreachable
        if force_refresh:
            missing_hosts = all_inventory_hosts - checked_hosts
            if missing_hosts:
                logger.warning(f"Some hosts not found in status check: {missing_hosts}. They may be unreachable.")
        
        for hostname, vars in hostvars.items():
            role = 'master' if hostname in masters else ('worker' if hostname in workers else None)
            # Use actual status from nodes, fallback to inventory file, then default
            # If node not in status_map after force refresh, assume unreachable
            bootstrap_status = (
                actual_status_map.get(hostname) or 
                vars.get('bootstrap_status') or 
                ('unreachable' if force_refresh and hostname not in actual_status_map else 'not_bootstrapped')
            )
            
            nodes.append({
                "name": hostname,
                "ip": vars.get('ansible_host'),
                "user": vars.get('ansible_user'),
                "role": role,
                "status": bootstrap_status,
                "note": vars.get('note')
            })

        return {
            "success": True,
            "clusterName": cluster_name,
            "nodes": nodes
        }
    except Exception as e:
        logger.error(f"Error loading inventory: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def _parse_kubecheck_report(report_data: Dict) -> List[Dict]:
    """Parse kube-check report JSON format"""
    results = []
    
    try:
        # Kube-check report format: list of groups, each with checks
        if isinstance(report_data, list):
            for group in report_data:
                if isinstance(group, dict) and 'checks' in group:
                    results.extend(group['checks'])
                elif isinstance(group, dict):
                    results.append(group)
        elif isinstance(report_data, dict):
            if 'checks' in report_data:
                results = report_data['checks']
            else:
                results = [report_data]
    except Exception as e:
        logger.warning(f"Failed to parse kube-check report: {e}")
    
    return results

def _update_bootstrap_status(inventory_path: Path, node_names: Optional[Any], status: str = 'ready'):
    """
    Update bootstrap_status in inventory file after successful bootstrap
    
    Args:
        inventory_path: Path to inventory file
        node_names: Node name(s) to update (can be list, string, or None for all)
        status: Status to set (default: 'ready')
    """
    if not inventory_path.exists():
        logger.warning(f"Inventory file not found: {inventory_path}")
        return
    
    try:
        # Parse node names
        nodes_to_update = []
        if node_names:
            if isinstance(node_names, list):
                nodes_to_update = node_names
            else:
                nodes_to_update = [str(node_names)]
        
        # Read inventory file
        if inventory_path.suffix == '.yml' or inventory_path.suffix == '.yaml':
            with open(inventory_path, 'r') as f:
                inventory = yaml.safe_load(f) or {}
            
            # Update bootstrap_status for specified nodes
            if nodes_to_update:
                for node_name in nodes_to_update:
                    # Update in all.hosts
                    if 'all' in inventory and 'hosts' in inventory['all']:
                        if node_name in inventory['all']['hosts']:
                            if not isinstance(inventory['all']['hosts'][node_name], dict):
                                inventory['all']['hosts'][node_name] = {}
                            inventory['all']['hosts'][node_name]['bootstrap_status'] = status
                    
                    # Update in masters/workers if exists
                    for group in ['masters', 'workers']:
                        if group in inventory and 'hosts' in inventory[group]:
                            if node_name in inventory[group]['hosts']:
                                if not isinstance(inventory[group]['hosts'][node_name], dict):
                                    inventory[group]['hosts'][node_name] = {}
                                inventory[group]['hosts'][node_name]['bootstrap_status'] = status
            else:
                # Update all nodes if no specific nodes provided
                for group_key in ['all', 'masters', 'workers']:
                    if group_key in inventory and 'hosts' in inventory[group_key]:
                        for node_name in inventory[group_key]['hosts']:
                            if not isinstance(inventory[group_key]['hosts'][node_name], dict):
                                inventory[group_key]['hosts'][node_name] = {}
                            inventory[group_key]['hosts'][node_name]['bootstrap_status'] = status
            
            # Write back to file
            with open(inventory_path, 'w') as f:
                yaml.dump(inventory, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Updated bootstrap_status to '{status}' for nodes: {nodes_to_update or 'all'}")
        else:
            # INI format - more complex, skip for now or implement if needed
            logger.warning(f"INI format inventory update not implemented yet: {inventory_path}")
            
    except Exception as e:
        logger.error(f"Error updating bootstrap_status: {e}")
        raise

def _parse_ansible_output(output: str) -> List[Dict]:
    """Parse results from Ansible output"""
    results = []
    
    # Try to find JSON in output
    try:
        json_match = output.find('[')
        if json_match >= 0:
            json_str = output[json_match:]
            # Find the end of JSON array
            bracket_count = 0
            end_pos = -1
            for i, char in enumerate(json_str):
                if char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_pos = i + 1
                        break
            
            if end_pos > 0:
                json_data = json.loads(json_str[:end_pos])
                if isinstance(json_data, list):
                    results = json_data
    except Exception as e:
        logger.warning(f"Failed to parse JSON from output: {e}")
    
    return results

