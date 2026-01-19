#!/usr/bin/env python3
"""
Check Executor for kube-bench-python
File-based approach supporting complex kube-bench patterns
"""

import subprocess
import re
import os
import json
import time
import yaml
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional, Union
from utils import Logger, PerformanceTimer, safe_file_read
from constants import SUBSTITUTIONS

class CheckExecutor:
    """Enhanced executor supporting all kube-bench patterns including dual audit and policies"""
    
    def __init__(self, config_data: Dict[str, Any]):
        self.config = config_data
        self.logger = Logger(__name__)
        self.cache = {}
        
    def get_component_config_from_files(self, component_type: str) -> Dict[str, str]:
        """Get component configuration from files"""
        cache_key = f"file_config_{component_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            with PerformanceTimer(f"read_{component_type}_config", self.logger):
                if component_type == "etcd":
                    config_data = self._get_etcd_config_from_files()
                elif component_type == "controlplane":
                    config_data = self._get_controlplane_config_from_files()
                elif component_type == "master":
                    config_data = self._get_master_config_from_files()
                elif component_type == "node":
                    config_data = self._get_node_config_from_files()
                elif component_type == "policies":
                    config_data = {}  # Policies use kubectl commands
                else:
                    self.logger.warning(f"Unknown component type: {component_type}")
                    config_data = {}
            
            self.cache[cache_key] = config_data
            return config_data
            
        except Exception as e:
            self.logger.error(f"Error reading {component_type} config from files: {e}")
            return {}
    
    def _load_config_from_paths(self, paths: List[str], component_name: str, prefix: str = "", is_manifest: bool = True) -> Dict[str, str]:
        """Generic method to load config from a list of paths"""
        config_dict = {}
        for path in paths:
            if Path(path).exists():
                try:
                    content = safe_file_read(path)
                    if not content:
                        continue
                        
                    if path.endswith(('.yaml', '.yml')):
                        data = yaml.safe_load(content)
                        if is_manifest:
                            extracted = self._extract_args_from_manifest(data, component_name)
                        else:
                            # Flatten simple dict if needed or just use as is if structure matches
                            # For kubelet/proxy, it's flat key-value mostly
                            extracted = {}
                            if isinstance(data, dict):
                                for k, v in data.items():
                                    extracted[k] = v
                    else:
                        extracted = self._parse_config_file(content)
                    
                    # Apply prefix if needed
                    for key, value in extracted.items():
                        final_key = f"{prefix}_{key}" if prefix else key
                        config_dict[final_key] = str(value)
                    
                    self.logger.info(f"Read {component_name} config from {path}")
                    return config_dict # Return on first successful read
                    
                except Exception as e:
                    self.logger.warning(f"Failed to read {path}: {e}")
                    continue
        return config_dict
    
    def _get_etcd_config_from_files(self) -> Dict[str, str]:
        """Read etcd config from manifest files"""
        etcd_paths = [
            '/etc/kubernetes/manifests/etcd.yaml',
            '/etc/kubernetes/manifests/etcd.yml',
            '/etc/kubernetes/manifests/etcd.manifest',
            '/var/lib/rancher/rke2/agent/pod-manifests/etcd.yaml',
            '/var/lib/rancher/k3s/server/db/etcd/config'
        ]
        return self._load_config_from_paths(etcd_paths, 'etcd')
    
    def _get_controlplane_config_from_files(self) -> Dict[str, str]:
        """Read API server config from manifest files"""
        api_server_paths = [
            '/etc/kubernetes/manifests/kube-apiserver.yaml',
            '/etc/kubernetes/manifests/kube-apiserver.yml',
            '/etc/kubernetes/manifests/kube-apiserver.manifest'
        ]
        return self._load_config_from_paths(api_server_paths, 'kube-apiserver', prefix='apiserver')
    
    def _get_master_config_from_files(self) -> Dict[str, str]:
        """Read master node config from all control plane component files"""
        config_dict = {}
        
        components = [
            ('kube-apiserver', 'apiserver'),
            ('kube-controller-manager', 'controller-manager'),
            ('kube-scheduler', 'scheduler')
        ]
        
        for component_name, prefix in components:
            manifest_paths = [
                f'/etc/kubernetes/manifests/{component_name}.yaml',
                f'/etc/kubernetes/manifests/{component_name}.yml'
            ]
            config_dict.update(self._load_config_from_paths(manifest_paths, component_name, prefix))
        
        return config_dict
    
    def _get_node_config_from_files(self) -> Dict[str, str]:
        """Read node config from kubelet and kube-proxy files"""
        config_dict = {}
        
        # Kubelet config paths
        kubelet_config_paths = [
            '/var/lib/kubelet/config.yaml',
            '/etc/kubernetes/kubelet/kubelet-config.yaml',
            '/etc/kubernetes/kubelet.yaml'
        ]
        config_dict.update(self._load_config_from_paths(kubelet_config_paths, 'kubelet', prefix='kubelet', is_manifest=False))
        
        # Kube-proxy config paths
        proxy_config_paths = [
            '/var/lib/kube-proxy/config.conf',
            '/etc/kubernetes/kube-proxy.yaml',
            '/var/lib/kube-proxy/kubeconfig.conf'
        ]
        config_dict.update(self._load_config_from_paths(proxy_config_paths, 'kube-proxy', prefix='proxy', is_manifest=False))
        
        return config_dict
    
    def _extract_args_from_manifest(self, manifest: Dict[str, Any], component_name: str) -> Dict[str, str]:
        """Extract command line arguments from Kubernetes manifest"""
        config_dict = {}
        
        try:
            containers = manifest.get('spec', {}).get('containers', [])
            
            for container in containers:
                if component_name in container.get('name', ''):
                    command = container.get('command', [])
                    args = container.get('args', [])
                    
                    for arg in command + args:
                        if isinstance(arg, str) and '=' in arg and arg.startswith('--'):
                            try:
                                key, value = arg.split('=', 1)
                                config_dict[key] = value
                            except ValueError:
                                continue
                    
                    env_vars = container.get('env', [])
                    for env_var in env_vars:
                        if isinstance(env_var, dict) and 'name' in env_var:
                            env_name = env_var['name']
                            env_value = env_var.get('value', '')
                            config_dict[f"env_{env_name}"] = env_value
                    
                    break
                    
        except Exception as e:
            self.logger.warning(f"Error extracting args from manifest: {e}")
        
        return config_dict
    
    def _parse_config_file(self, content: str) -> Dict[str, str]:
        """Parse configuration file content"""
        config_dict = {}
        
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                try:
                    key, value = line.split('=', 1)
                    config_dict[key.strip()] = value.strip().strip('"\'')
                except ValueError:
                    continue
        
        return config_dict
    
    def execute_audit_command(self, audit_cmd: str, component_type: str = "etcd") -> str:
        """Execute audit command with enhanced variable substitution"""
        if not audit_cmd:
            return ""
        try:
            # Handle multi-line audit commands (like in policies)
            if '\n' in audit_cmd:
                return self._execute_multiline_audit(audit_cmd, component_type)
            # Substitute variables
            substituted_cmd = self._substitute_variables(audit_cmd, component_type)
            self.logger.debug(f"Executing: {substituted_cmd}")
            # Execute command
            result = subprocess.run(
                substituted_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0 and result.returncode != 1:
                self.logger.debug(f"Command returned {result.returncode}: {result.stderr}")
            return result.stdout
        except subprocess.TimeoutExpired:
            self.logger.error("Audit command timed out")
            return ""
        except Exception as e:
            self.logger.error(f"Error executing audit command: {e}")
            return ""
    
    def _execute_multiline_audit(self, audit_cmd: str, component_type: str) -> str:
        """Execute multi-line audit commands (common in policies)"""
        try:
            # Substitute variables in the entire script
            substituted_cmd = self._substitute_variables(audit_cmd, component_type)
            
            # Execute as a shell script
            result = subprocess.run(
                substituted_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                executable='/bin/bash'
            )
            
            return result.stdout
            
        except subprocess.TimeoutExpired:
            self.logger.error("Multi-line audit command timed out")
            return ""
        except Exception as e:
            self.logger.error(f"Error executing multi-line audit: {e}")
            return ""
    
    def _substitute_variables(self, cmd: str, component_type: str) -> str:
        """Enhanced variable substitution using centralized constants"""
        # Get substitutions from constants
        component_subs = SUBSTITUTIONS.get(component_type, {})
        
        # Apply substitutions
        for var, value in component_subs.items():
            cmd = cmd.replace(var, value)
        
        return cmd
    
    def check_flag_in_output(self, output: str, flag: str, env_var: Optional[str] = None, component_type: Optional[str] = None) -> Tuple[bool, str]:
        """Enhanced flag checking with separate logic for policies vs other components"""
        if not output:
            return False, "No output from audit command"
        
        # Separate handling for policies (section 5) vs other components
        if component_type == 'policies':
            return self._check_policies_flag_output(output, flag)
        
        # Original logic for other components (sections 1, 2, 3, 4)
        if "permissions=" in output or "Access:" in output:
            return self._check_file_permissions(output, flag)
        elif "ownership=" in output or "Uid:" in output:
            return self._check_file_ownership(output, flag)
        elif "error:" in output.lower() or "no such file" in output.lower():
            return False, f"Error: {output.strip()}"
        
        # Special case for root:root exact match
        if flag == 'root:root' and flag in output:
            return True, flag
        
        # Special case for "File not found" message
        if flag == 'File not found' and flag in output:
            return True, flag
        
        # Standard flag checking (for ps output)
        return self._check_standard_flag(output, flag, env_var)

    def check_config_path(self, config_output: str, path: str) -> Tuple[bool, str]:
        """Check JSON path in config output"""
        try:
            if not config_output.strip():
                return False, "Empty config output"
            
            # Parse YAML/JSON config
            if config_output.strip().startswith('{'):
                config_data = json.loads(config_output)
            else:
                config_data = yaml.safe_load(config_output)
            
            if not config_data:
                return False, "Empty config data"
            
            # Extract value using path like "{.authentication.anonymous.enabled}"
            path_clean = path.strip('{}').strip('.')
            if not path_clean:
                return False, "Empty path"
            
            path_parts = path_clean.split('.')
            current = config_data
            
            for part in path_parts:
                if part and isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return False, f"Path not found: {part}"
            
            return True, str(current)
            
        except json.JSONDecodeError as e:
            self.logger.debug(f"JSON parse error: {e}")
            return False, f"JSON parse error: {e}"
        except yaml.YAMLError as e:
            self.logger.debug(f"YAML parse error: {e}")
            return False, f"YAML parse error: {e}"
        except Exception as e:
            self.logger.debug(f"Failed to parse config: {e}")
            return False, f"Parse error: {e}"
    
    def _check_policy_output(self, output: str, flag: str) -> Tuple[bool, str]:
        """Check policy output with ** format"""
        lines = output.strip().split('\n')
        for line in lines:
            if '**' in line and flag in line:
                # Extract value after flag
                parts = line.split()
                for part in parts:
                    if flag in part and ':' in part:
                        try:
                            value = part.split(':', 1)[1].strip()
                            return True, value
                        except IndexError:
                            continue
        return False, "Policy value not found"
    
    def _check_pod_security_output(self, output: str, flag: str) -> Tuple[bool, str]:
        """Check pod security output with *** format"""
        lines = output.strip().split('\n')
        for line in lines:
            if '***' in line and flag in line:
                parts = line.split()
                for part in parts:
                    if flag in part and ':' in part:
                        try:
                            value = part.split(':', 1)[1].strip()
                            return True, value
                        except IndexError:
                            continue
        return False, "Pod security value not found"
    
    def _check_boolean_output(self, output: str, flag: str) -> Tuple[bool, str]:
        """Check boolean output from kubectl commands"""
        lines = output.strip().split('\n')
        for line in lines:
            if flag in line and ':' in line:
                try:
                    value = line.split(':', 1)[1].strip()
                    return True, value
                except IndexError:
                    continue
        return False, "Boolean value not found"
    
    def _check_file_permissions(self, output: str, flag: str) -> Tuple[bool, str]:
        """Check file permissions in stat output"""
        # Format: Access: (0644/-rw-r--r--)
        access_match = re.search(r'Access:\s*\((\d+)/', output)
        if access_match:
            return True, access_match.group(1)
        
        # Format: permissions=644
        perm_match = re.search(r'permissions=(\d+)', output)
        if perm_match:
            return True, perm_match.group(1)
        
        return False, "Permissions not found"
    
    def _check_file_ownership(self, output: str, flag: str) -> Tuple[bool, str]:
        """Check file ownership in stat output"""
        # Format: ownership=root:root /path/to/file
        if "ownership=" in output:
            owner_match = re.search(r'ownership=([^\s]+)', output)
            if owner_match:
                ownership_value = owner_match.group(1)
                
                # If flag is 'ownership', return value
                if flag == 'ownership':
                    return True, ownership_value
                # If flag is 'root:root', compare with value
                elif flag == 'root:root':
                    return ownership_value == 'root:root', ownership_value
                # Otherwise, check contains
                else:
                    return flag in ownership_value, ownership_value
        
        # Check for exact match first (for output like "root:root")
        if flag in output:
            return True, flag
        
        # Format: Uid: (    0/    root)   Gid: (    0/    root)
        uid_match = re.search(r'Uid:\s*\(\s*\d+/\s*(\w+)\)', output)
        gid_match = re.search(r'Gid:\s*\(\s*\d+/\s*(\w+)\)', output)
        
        if uid_match and gid_match:
            return True, f"{uid_match.group(1)}:{gid_match.group(1)}"
        elif uid_match:
            return True, uid_match.group(1)
        
        return False, "Ownership not found"
        
        return False, "Flag not found"

    def _check_standard_flag(self, output: str, flag: str,
                            env_var: Optional[str] = None) -> Tuple[bool, str]:
        """
        Tìm flag trong command line, trả về (tồn tại, giá trị).
        Nếu chỉ có --flag không có value => trả 'true'.
        """
        for line in output.strip().splitlines():
            if flag not in line:
                continue

            # cắt riêng từng token
            tokens = line.strip().split()
            for tok in tokens:
                if tok.startswith(flag + "="):
                    value = tok.split("=", 1)[1]
                    return True, value
                if tok == flag:
                    return True, "true"

            # check biến môi trường nếu có
            if env_var:
                for tok in tokens:
                    if tok.startswith(env_var + "="):
                        value = tok.split("=", 1)[1]
                        return True, value

        return False, "Flag not found"

    def debug_flag_extraction(self, output: str, flag: str) -> None:
        """Debug function to test flag extraction"""
        print(f"=== Debug Flag Extraction ===")
        print(f"Looking for flag: {flag}")
        print(f"Output snippet: {output[:200]}...")
        
        # Test different patterns
        patterns = [
            rf'{re.escape(flag)}=([^\s]+)',  # --flag=value
            rf'{re.escape(flag)}\s+([^\s-]+)',  # --flag value
            rf'{re.escape(flag)}(?:=([^\s]+))?',  # Current pattern
        ]
        
        for i, pattern in enumerate(patterns):
            match = re.search(pattern, output)
            print(f"Pattern {i+1}: {pattern}")
            if match:
                print(f"  Match found: {match.group(0)}")
                print(f"  Value: {match.group(1) if match.group(1) else 'None'}")
            else:
                print(f"  No match")
        print("=" * 30)

    def evaluate_test(self, test_item: Dict[str, Any], audit_output: str) -> Dict[str, Any]:
        """Standard test evaluation for sections 1,2,3,4"""
        flag = test_item.get('flag', '')
        env_var = test_item.get('env')
        
        flag_exists, flag_value = self.check_flag_in_output(audit_output, flag, env_var)
        
        result = {
            'flag': flag,
            'exists': flag_exists,
            'value': flag_value,
            'passed': False,
            'message': ''
        }
        
        # Evaluate based on test type
        if 'set' in test_item:
            should_exist = test_item['set']
            if should_exist and flag_exists:
                result['passed'] = True
                result['message'] = f"Flag {flag} is set with value: {flag_value}"
            elif not should_exist and not flag_exists:
                result['passed'] = True
                result['message'] = f"Flag {flag} is not set (as required)"
            else:
                result['message'] = f"Flag {flag} existence check failed"
        
        elif 'compare' in test_item:
            compare = test_item['compare']
            op = compare.get('op', 'eq')
            expected_value = compare.get('value')
            
            if not flag_exists:
                result['message'] = f"Flag {flag} not found for comparison"
            else:
                result['passed'] = self._evaluate_comparison(flag_value, op, expected_value)
                if result['passed']:
                    result['message'] = f"Flag {flag} comparison passed: {flag_value} {op} {expected_value}"
                else:
                    result['message'] = f"Flag {flag} comparison failed: {flag_value} {op} {expected_value}"
        
        else:
            # Default: check if flag exists
            result['passed'] = flag_exists
            result['message'] = f"Flag {flag} {'found' if flag_exists else 'not found'}"
        
        return result

    def evaluate_policies_test(self, test_item: Dict[str, Any], audit_output: str) -> Dict[str, Any]:
        """Specialized test evaluation for policies section 5 with yes/no -> true/false mapping"""
        flag = test_item.get('flag', '')
        env_var = test_item.get('env')
        
        flag_exists, flag_value = self.check_flag_in_output(audit_output, flag, env_var, 'policies')
        
        result = {
            'flag': flag,
            'exists': flag_exists,
            'value': flag_value,
            'passed': False,
            'message': ''
        }
        
        # Evaluate based on test type
        if 'set' in test_item:
            should_exist = test_item['set']
            if should_exist and flag_exists:
                result['passed'] = True
                result['message'] = f"Flag {flag} is set with value: {flag_value}"
            elif not should_exist and not flag_exists:
                result['passed'] = True
                result['message'] = f"Flag {flag} is not set (as required)"
            else:
                result['message'] = f"Flag {flag} existence check failed"
        
        elif 'compare' in test_item:
            compare = test_item['compare']
            op = compare.get('op', 'eq')
            expected_value = compare.get('value')
            
            if not flag_exists:
                result['message'] = f"Flag {flag} not found for comparison"
            else:
                result['passed'] = self._evaluate_comparison(flag_value, op, expected_value, 'policies')
                if result['passed']:
                    result['message'] = f"Flag {flag} comparison passed: {flag_value} {op} {expected_value}"
                else:
                    result['message'] = f"Flag {flag} comparison failed: {flag_value} {op} {expected_value}"
        
        else:
            # Default: check if flag exists
            result['passed'] = flag_exists
            result['message'] = f"Flag {flag} {'found' if flag_exists else 'not found'}"
        
        return result

    def evaluate_dual_test(self, test_item: Dict[str, Any], audit_output: str, config_output: str, component_type: Optional[str] = None) -> Dict[str, Any]:
        """Evaluate test with both process and config outputs"""
        flag = test_item.get('flag', '')
        path = test_item.get('path', '')
        env_var = test_item.get('env')
        
        result = {
            'flag': flag,
            'path': path,
            'exists': False,
            'value': '',
            'passed': False,
            'message': '',
            'source': 'none'
        }
        
        # Try to find flag in process output first
        if flag and audit_output:
            flag_exists, flag_value = self.check_flag_in_output(audit_output, flag, env_var, component_type)
            if flag_exists:
                result['exists'] = True
                result['value'] = flag_value
                result['source'] = 'process'
        
        # Try to find path in config output if flag not found
        if not result['exists'] and path and config_output:
            config_exists, config_value = self.check_config_path(config_output, path)
            if config_exists:
                result['exists'] = True
                result['value'] = config_value
                result['source'] = 'config'
        
        # Evaluate based on test type
        if 'set' in test_item:
            should_exist = test_item['set']
            if should_exist and result['exists']:
                result['passed'] = True
                result['message'] = f"Value found: {result['value']} (from {result['source']})"
            elif not should_exist and not result['exists']:
                result['passed'] = True
                result['message'] = f"Value not found (as required)"
            else:
                result['message'] = f"Set check failed: expected {should_exist}, found {result['exists']}"
        
        elif 'compare' in test_item:
            compare = test_item['compare']
            op = compare.get('op', 'eq')
            expected_value = compare.get('value')
            
            if not result['exists']:
                result['message'] = f"Neither flag {flag} nor config path {path} found"
            else:
                result['passed'] = self._evaluate_comparison(result['value'], op, expected_value, component_type)
                if result['passed']:
                    result['message'] = f"Check passed: {result['value']} {op} {expected_value} (from {result['source']})"
                else:
                    result['message'] = f"Check failed: {result['value']} {op} {expected_value} (from {result['source']})"
        
        else:
            # Default: check if value exists
            result['passed'] = result['exists']
            result['message'] = f"Value {'found' if result['exists'] else 'not found'} (from {result['source']})"
        
        return result
    
    def _evaluate_comparison(self, actual_value: str, op: str, expected_value: Any, component_type: Optional[str] = None) -> bool:
        """Enhanced comparison operations with separate logic for policies"""
        try:
            actual_str = str(actual_value).strip()
            expected_str = str(expected_value).strip()
            
            # Special handling for policies - map no/yes to false/true for boolean comparisons
            if component_type == 'policies':
                if actual_str.lower() == 'no':
                    actual_str = 'false'
                elif actual_str.lower() == 'yes':
                    actual_str = 'true'
                
                # Handle boolean expected values
                if isinstance(expected_value, bool):
                    expected_str = 'true' if expected_value else 'false'
            
            if op == 'eq':
                # Special handling for boolean values
                if expected_str.lower() in ['true', 'false']:
                    return actual_str.lower() == expected_str.lower()
                return actual_str.lower() == expected_str.lower()
            elif op == 'noteq':
                return actual_str.lower() != expected_str.lower()
            elif op == 'has':
                return expected_str in actual_str
            elif op == 'nothave':
                return expected_str not in actual_str
            elif op in ['gte', 'lte', 'gt', 'lt']:
                try:
                    actual_num = float(actual_str)
                    expected_num = float(expected_str)
                    
                    if op == 'gte':
                        return actual_num >= expected_num
                    elif op == 'lte':
                        return actual_num <= expected_num
                    elif op == 'gt':
                        return actual_num > expected_num
                    elif op == 'lt':
                        return actual_num < expected_num
                except ValueError:
                    return False
            elif op == 'bitmask':
                return self._check_bitmask(actual_str, expected_str)
            elif op == 'valid_elements':
                allowed_values = [v.strip() for v in expected_str.split(',')]
                return actual_str in allowed_values
            else:
                self.logger.warning(f"Unknown comparison operator: {op}")
                return False
                
        except Exception as e:
            self.logger.error(f"Comparison error: {e}")
            return False

    
    def _check_bitmask(self, actual_value: str, expected_value: str) -> bool:
        """Check file permissions using bitmask"""
        try:
            actual_perm = int(actual_value, 8) if actual_value.isdigit() else int(actual_value)
            expected_perm = int(expected_value, 8) if expected_value.isdigit() else int(expected_value)
            return (actual_perm & 0o777) <= expected_perm
        except (ValueError, TypeError):
            return False
    
    def execute_check(self, check: Dict[str, Any], component_type: str = "etcd") -> Dict[str, Any]:
        """Execute a single security check with dual audit support"""
        check_id = check.get('id', 'unknown')
   
        audit_cmd = check.get('audit')
        audit_config_cmd = check.get('audit_config')  # Support for dual audit
        tests = check.get('tests', {})
        
        # Determine check type - trust YAML first, then check text for "(Manual)"
        check_text = check.get('text', 'No description')
        check_type = check.get('type')
        
        # If type is missing or defaulted to automated, check text for Manual override
        if not check_type or check_type == 'automated':
            if '(Manual)' in check_text:
                check_type = 'manual'
            elif not check_type:
                check_type = 'automated'
        
        # Debug logging (can be removed later)
        # with open("/tmp/debug_executor.txt", "a") as f:
        #     f.write(f"DEBUG: Check {check_id} - Text: '{check_text}'\n")
        #     f.write(f"DEBUG: Check {check_id} - Type from YAML: '{check.get('type')}'\n")
        #     f.write(f"DEBUG: Check {check_id} - Detected Type: '{check_type}'\n")
                
        use_multiple_values = check.get('use_multiple_values', False)
        scored = check.get('scored', True)
        
        start_time = time.time()
        
        self.logger.info(f"Executing check {check_id}: {check.get('text', 'No description')}")
        
        # Handle manual checks - ONLY skip if no audit command exists
        # If audit command exists, we run it even if marked Manual (user request)
        if not audit_cmd and not audit_config_cmd:
            return {
                'id': check_id,
                'text': check.get('text', 'No description'),
                'passed': None,
                'scored': scored,
                'test_results': [],
                'remediation': check.get('remediation', 'No remediation provided'),
                'type': 'manual',
                'execution_time': 0
            }
        
        try:
            # Execute both audit commands
            audit_output = ""
            config_output = ""
            
            if audit_cmd:
                audit_output = self.execute_audit_command(audit_cmd, component_type)
            
            if audit_config_cmd:
                config_output = self.execute_audit_command(audit_config_cmd, component_type)
            
            # Handle checks with multiple values
            if use_multiple_values:
                return self._execute_multiple_values_check(check, audit_output, component_type, start_time)
            
            # Process test items with dual output support
            test_items = tests.get('test_items', [])
            bin_op = tests.get('bin_op', 'and')
            
            test_results = []
            for test_item in test_items:
                # Use dual test evaluation if we have both outputs and a path
                if config_output and test_item.get('path'):
                    result = self.evaluate_dual_test(test_item, audit_output, config_output, component_type)
                else:
                    # Use specialized evaluation for policies
                    if component_type == 'policies':
                        result = self.evaluate_policies_test(test_item, audit_output)
                    else:
                        result = self.evaluate_test(test_item, audit_output)
                test_results.append(result)
            
            # Determine overall result
            if bin_op == 'and':
                overall_passed = all(r['passed'] for r in test_results)
            elif bin_op == 'or':
                overall_passed = any(r['passed'] for r in test_results)
            else:
                overall_passed = test_results[0]['passed'] if test_results else False
            
            execution_time = time.time() - start_time
            
            return {
                'id': check_id,
                'text': check.get('text', 'No description'),
                'passed': overall_passed,
                'scored': scored,
                'test_results': test_results,
                'remediation': check.get('remediation') if not overall_passed else None,
                'execution_time': round(execution_time, 3),
                'use_multiple_values': use_multiple_values,
                'has_dual_audit': bool(audit_config_cmd),
                'type': check_type
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"Error executing check {check_id}: {e}")
            
            return {
                'id': check_id,
                'text': check.get('text', 'No description'),
                'passed': False,
                'scored': scored,
                'test_results': [],
                'remediation': check.get('remediation'),
                'error': str(e),
                'execution_time': round(execution_time, 3)
            }
    
    def _execute_multiple_values_check(self, check: Dict[str, Any], audit_output: str, component_type: str, start_time: float) -> Dict[str, Any]:
        """Execute checks that handle multiple values with special logic for policies"""
        check_id = check.get('id', 'unknown')
        tests = check.get('tests', {})
        test_items = tests.get('test_items', [])
        bin_op = tests.get('bin_op', 'and')
        scored = check.get('scored', True)
        
        # Determine check type - trust YAML first, then check text for "(Manual)"
        check_text = check.get('text', 'No description')
        check_type = check.get('type')
        
        # If type is missing or defaulted to automated, check text for Manual override
        if not check_type or check_type == 'automated':
            if '(Manual)' in check_text:
                check_type = 'manual'
            elif not check_type:
                check_type = 'automated'
        
        # Split output into lines for multiple value processing
        lines = [line.strip() for line in audit_output.strip().split('\n') if line.strip()]
        all_results = []
        
        if not lines:
            execution_time = time.time() - start_time
            return {
                'id': check_id,
                'text': check.get('text', 'No description'),
                'passed': False,
                'scored': scored,
                'test_results': [],
                'remediation': check.get('remediation'),
                'execution_time': round(execution_time, 3),
                'lines_processed': 0,
                'message': 'No output to process',
                'type': check_type
            }
        
        # Process each line
        for line_idx, line in enumerate(lines):
            line_results = []
            for test_item in test_items:
                # Use specialized evaluation for policies
                if component_type == 'policies':
                    result = self.evaluate_policies_test(test_item, line)
                else:
                    result = self.evaluate_test(test_item, line)
                result['line_number'] = line_idx + 1
                result['line_content'] = line[:100] + '...' if len(line) > 100 else line
                line_results.append(result)
            
            all_results.extend(line_results)
        
        # ← SPECIAL LOGIC CHO POLICIES CHECKS
        if check_id in ['5.1.1', '5.1.5', '5.1.6', '5.2.2', '5.2.3', '5.2.4', '5.2.5', '5.2.6', '5.2.9']:
            # Đối với policies checks: TẤT CẢ phải compliant
            # Tìm tất cả results có flag "is_compliant"
            compliance_results = [r for r in all_results if r.get('flag') == 'is_compliant']
            
            if compliance_results:
                # TẤT CẢ compliance checks phải PASS
                overall_passed = all(r.get('passed', False) for r in compliance_results)
                
                # Debug info
                failed_count = sum(1 for r in compliance_results if not r.get('passed', False))
                self.logger.info(f"Check {check_id}: {len(compliance_results)} total items, {failed_count} failed")
            else:
                overall_passed = False
        
        elif check_id == '5.1.3':
            # ← SPECIAL CASE CHO 5.1.3: Wildcard check
            role_compliant_results = [r for r in all_results if r.get('flag') == 'role_is_compliant']
            clusterrole_compliant_results = [r for r in all_results if r.get('flag') == 'clusterrole_is_compliant']
            
            # TẤT CẢ roles phải compliant VÀ TẤT CẢ clusterroles phải compliant
            roles_all_compliant = all(r.get('passed', False) for r in role_compliant_results) if role_compliant_results else True
            clusterroles_all_compliant = all(r.get('passed', False) for r in clusterrole_compliant_results) if clusterrole_compliant_results else True
            
            overall_passed = roles_all_compliant and clusterroles_all_compliant
            
            # Debug info
            role_failed = sum(1 for r in role_compliant_results if not r.get('passed', False))
            clusterrole_failed = sum(1 for r in clusterrole_compliant_results if not r.get('passed', False))
            self.logger.info(f"Check 5.1.3: {len(role_compliant_results)} roles ({role_failed} failed), {len(clusterrole_compliant_results)} clusterroles ({clusterrole_failed} failed)")
        
        else:
            # Logic bình thường cho các checks khác
            if bin_op == 'and':
                overall_passed = all(r.get('passed', False) for r in all_results) if all_results else False
            elif bin_op == 'or':
                overall_passed = any(r.get('passed', False) for r in all_results) if all_results else False
            else:
                # For multiple values: all lines must match expected value
                matching_lines = sum(1 for r in all_results if r.get('passed', False))
                overall_passed = (matching_lines == len(lines)) if lines else False
        
        execution_time = time.time() - start_time
        
        return {
            'id': check_id,
            'text': check.get('text', 'No description'),
            'passed': overall_passed,
            'scored': scored,
            'test_results': all_results,
            'remediation': check.get('remediation') if not overall_passed else None,
            'execution_time': round(execution_time, 3),
            'lines_processed': len(lines),
            'multiple_values': True,
            'type': check_type
        }
    
    def execute_auto_remediation(self, check: Dict[str, Any], dry_run: bool = False, 
                                require_confirmation: bool = True) -> Dict[str, Any]:
        """Execute auto remediation for a check if available"""
        auto_remediation = check.get('auto_remediation')
        if not auto_remediation:
            return {
                'success': False,
                'error': 'No auto remediation available for this check',
                'executed': False
            }
        
        command = auto_remediation.get('command')
        description = auto_remediation.get('description', 'Auto remediation')
        requires_sudo = auto_remediation.get('requires_sudo', False)
        dry_run_safe = auto_remediation.get('dry_run_safe', True)
        
        # Apply variable substitutions to command
        command = self._apply_substitutions(command)
        
        # Check if command is safe for dry run
        if dry_run and not dry_run_safe:
            return {
                'success': False,
                'error': 'This remediation is not safe for dry run',
                'executed': False
            }
        
        # Prepare command for execution
        if requires_sudo:
            if dry_run:
                cmd = ['sudo', '-n', 'echo', f'DRY RUN: {command}']
            else:
                cmd = ['sudo', '-n', 'sh', '-c', command]
        else:
            if dry_run:
                cmd = ['sh', '-c', f'echo "DRY RUN: {command}"']
            else:
                cmd = ['sh', '-c', command]
        
        try:
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                check=False
            )
            
            return {
                'success': result.returncode == 0,
                'command': command,
                'description': description,
                'return_code': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'executed': not dry_run,
                'dry_run': dry_run
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Command execution timed out',
                'command': command,
                'description': description,
                'executed': False,
                'dry_run': dry_run
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Command execution failed: {str(e)}',
                'command': command,
                'description': description,
                'executed': False,
                'dry_run': dry_run
            }
    
    def _apply_substitutions(self, text: str) -> str:
        """Apply variable substitutions to text (same as in main.py)"""
        substitutions = {
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
        
        for var, value in substitutions.items():
            text = text.replace(var, value)
        return text

    def cleanup(self):
        """Cleanup resources"""
        self.cache.clear()
        self.logger.info("CheckExecutor cleanup completed")
    
    def _check_policies_flag_output(self, output: str, flag: str) -> Tuple[bool, str]:
        """Dedicated method for policies flag extraction (section 5 only)"""
        # Handle key: value format (common in kubectl output for policies)
        lines = output.strip().split('\n')
        for line in lines:
            if ':' in line and flag in line:
                # Extract value after colon
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if flag in key:
                        return True, value
        
        # Handle comma-separated format like "key: value, key2: value2, flag: target_value"
        for line in lines:
            if flag in line and ':' in line:
                # Use regex to find flag: value pattern anywhere in the line
                import re
                pattern = rf'{re.escape(flag)}:\s*([^,\s]+)'
                match = re.search(pattern, line)
                if match:
                    return True, match.group(1)
        
        # Handle ** format for some policy checks - improved parsing
        for line in lines:
            if '**' in line and flag in line:
                # Split by spaces but handle key: value pairs properly
                if f'{flag}:' in line:
                    # Find the flag: value pattern
                    import re
                    pattern = rf'{re.escape(flag)}:\s*(\S+)'
                    match = re.search(pattern, line)
                    if match:
                        return True, match.group(1)
        
        # Handle *** format for pod security checks - improved parsing  
        for line in lines:
            if '***' in line and flag in line:
                # Split by spaces but handle key: value pairs properly
                if f'{flag}:' in line:
                    # Find the flag: value pattern
                    import re
                    pattern = rf'{re.escape(flag)}:\s*(\S+)'
                    match = re.search(pattern, line)
                    if match:
                        return True, match.group(1)
        
        return False, "Policy flag not found"
