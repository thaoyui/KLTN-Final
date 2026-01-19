"""Kube-check integration service"""
import sys
import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Add Kube-check to path - Support both local and Docker
_default_kube_check = os.path.join(os.path.dirname(__file__), '..', '..', 'Kube-check')
KUBE_CHECK_PATH = os.getenv('KUBE_CHECK_PATH', _default_kube_check)
KUBE_CHECK_PATH = os.path.abspath(KUBE_CHECK_PATH)  # Resolve to absolute path

if KUBE_CHECK_PATH not in sys.path:
    sys.path.insert(0, KUBE_CHECK_PATH)

try:
    # Import Kube-check modules
    kube_check_src = os.path.join(KUBE_CHECK_PATH, 'src')
    if os.path.exists(kube_check_src):
        sys.path.insert(0, kube_check_src)
        from main import KubeBenchPython
        from executor import CheckExecutor
        from parser import YAMLParser
        KUBE_CHECK_AVAILABLE = True
        logger.info("Kube-check modules loaded successfully")
    else:
        logger.warning(f"Kube-check source directory not found: {kube_check_src}")
        KUBE_CHECK_AVAILABLE = False
except ImportError as e:
    logger.warning(f"Kube-check not available: {e}. This is OK if running in remote mode only.")
    KUBE_CHECK_AVAILABLE = False
except Exception as e:
    logger.warning(f"Kube-check initialization error: {e}. This is OK if running in remote mode only.")
    KUBE_CHECK_AVAILABLE = False

# Config file mapping
CONFIG_MAPPING = {
    '1.1': 'master.yaml',
    '1.2': 'master.yaml',
    '1.3': 'master.yaml',
    '1.4': 'master.yaml',
    '2.': 'etcd.yaml',
    '3.': 'controlplane.yaml',
    '4.': 'node.yaml',
    '5.': 'policies.yaml'
}

def get_config_file(check_id: str) -> Optional[str]:
    """Determine config file based on check ID"""
    for prefix, config_file in CONFIG_MAPPING.items():
        if check_id.startswith(prefix):
            return config_file
    return None

def run_scan(check_ids: List[str], output_format: str = 'json') -> Dict[str, Any]:
    """
    Run kube-check scan for given check IDs
    
    Args:
        check_ids: List of check IDs (e.g., ['1.1.1', '1.2.9'])
        output_format: Output format ('json', 'text', 'html', 'pdf')
    
    Returns:
        Dict with results
    """
    if not KUBE_CHECK_AVAILABLE:
        return {
            "success": False,
            "error": "Kube-check not available"
        }
    
    try:
        # Use a default config file (master.yaml) for initialization
        # The run_multiple_configs_with_report will auto-map checks to correct configs
        default_config = os.path.join(KUBE_CHECK_PATH, 'config', 'master.yaml')
        
        if not os.path.exists(default_config):
            # Try etcd.yaml as fallback
            default_config = os.path.join(KUBE_CHECK_PATH, 'config', 'etcd.yaml')
        
        if not os.path.exists(default_config):
            return {
                "success": False,
                "error": "No config file found"
            }
        
        logger.info(f"Running scan for {len(check_ids)} checks: {check_ids}")
        
        # Initialize KubeBenchPython
        kube_bench = KubeBenchPython(
            default_config,
            log_level='INFO',
            no_color=True,
            enable_file_logging=False
        )
        
        # Use run_multiple_configs_with_report which auto-maps checks to configs
        success = kube_bench.run_multiple_configs_with_report(
            check_ids,
            output_format='json',  # Always use JSON for API
            output_file=None,  # Don't save to file, return results
            progress=False,
            targets=None,
            include_passed=True,
            include_manual=True,
            show_remediation=True
        )
        
        if not success:
            return {
                "success": False,
                "error": "Failed to run checks"
            }
        
        # Get results from kube_bench.results
        results = kube_bench.results if hasattr(kube_bench, 'results') else []
        
        # Flatten results if they're grouped
        all_results = []
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    if 'checks' in item:
                        all_results.extend(item['checks'])
                    else:
                        all_results.append(item)
        
        return {
            "success": True,
            "results": all_results,
            "total_checks": len(check_ids),
            "executed_checks": len(all_results)
        }
        
    except Exception as e:
        logger.error(f"Error in run_scan: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }

def run_remediation(check_id: str, auto_yes: bool = True) -> Dict[str, Any]:
    """
    Run remediation for a check ID
    
    Args:
        check_id: Check ID to remediate
        auto_yes: Skip confirmation
    
    Returns:
        Dict with remediation results
    """
    if not KUBE_CHECK_AVAILABLE:
        return {
            "success": False,
            "error": "Kube-check not available"
        }
    
    try:
        config_file = get_config_file(check_id)
        if not config_file:
            return {
                "success": False,
                "error": f"Unknown check ID format: {check_id}"
            }
        
        config_path = os.path.join(KUBE_CHECK_PATH, 'config', config_file)
        if not os.path.exists(config_path):
            return {
                "success": False,
                "error": f"Config file not found: {config_path}"
            }
        
        # Initialize KubeBenchPython
        kube_bench = KubeBenchPython(
            config_path,
            log_level='INFO',
            no_color=True
        )
        
        # Run remediation
        result = kube_bench.execute_auto_remediation_for_failed_checks(
            dry_run=False,
            auto_yes=auto_yes,
            check_filter=check_id
        )
        
        return {
            "success": True,
            "check_id": check_id,
            "remediation_successful": result.get('remediation_successful', 0),
            "details": result
        }
        
    except Exception as e:
        logger.error(f"Error in run_remediation: {e}")
        return {
            "success": False,
            "error": str(e),
            "check_id": check_id
        }

def get_status() -> Dict[str, Any]:
    """Get kube-check status"""
    status = {
        "kube_check_available": KUBE_CHECK_AVAILABLE,
        "kube_check_path": KUBE_CHECK_PATH,
        "path_exists": os.path.exists(KUBE_CHECK_PATH),
        "config_files": {}
    }
    
    if KUBE_CHECK_AVAILABLE:
        config_dir = os.path.join(KUBE_CHECK_PATH, 'config')
        for prefix, config_file in CONFIG_MAPPING.items():
            config_path = os.path.join(config_dir, config_file)
            status['config_files'][config_file] = os.path.exists(config_path)
    
    return status

