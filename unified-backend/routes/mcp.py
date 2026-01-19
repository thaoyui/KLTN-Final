"""MCP Bot endpoints"""
import os
import sys
import re
import subprocess
import time
from pathlib import Path
from flask import Blueprint, request, jsonify
from datetime import datetime

bp = Blueprint('mcp', __name__)

# Get project root - policies directory should be at the same level as unified-backend
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_policies_dir = os.path.join(_base_dir, 'policies')

def summarize_output(text):
    """Summarize CLI output using Local Qwen, Cloud Qwen, or Gemini"""
    import urllib.request
    import json
    import ssl
    import certifi
    
    # 1. Try Local Qwen (Ollama/vLLM)
    local_url = os.getenv("QWEN_LOCAL_URL", "http://localhost:11434/v1/chat/completions")
    local_model = os.getenv("QWEN_LOCAL_MODEL", "qwen2.5-coder")
    
    if os.getenv("USE_LOCAL_QWEN", "false").lower() == "true":
        try:
            prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}

Summary:"""
            
            data = json.dumps({
                "model": local_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 500
            }).encode('utf-8')
            
            req = urllib.request.Request(local_url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"Local Qwen summarization failed: {e}")
    
    # 2. Try Cloud Qwen
    qwen_api_key = os.getenv("QWEN_API_KEY")
    if qwen_api_key:
        try:
            prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}

Summary:"""
            
            data = json.dumps({
                "model": "qwen-plus",
                "input": {"messages": [{"role": "user", "content": prompt}]},
                "parameters": {"temperature": 0.7, "max_tokens": 500}
            }).encode('utf-8')
            
            req = urllib.request.Request(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {qwen_api_key}'
                }
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                if 'output' in result and 'text' in result['output']:
                    return result['output']['text'].strip()
        except Exception as e:
            print(f"Cloud Qwen summarization failed: {e}")
    
    # 3. Try Gemini
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if gemini_api_key:
        try:
            prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}

Summary:"""
            
            data = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}]
            }).encode('utf-8')
            
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={gemini_api_key}",
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                if 'candidates' in result and len(result['candidates']) > 0:
                    return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            print(f"Gemini summarization failed: {e}")
    
    # Fallback: return original text
    return text

@bp.route('/api/mcp/chat', methods=['POST'])
def chat():
    """
    Executes the mcp_bot CLI via subprocess and returns the output.
    """
    start_time = time.time()
    
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"detail": "Message is required"}), 400
    
    user_message = data["message"]
    
    try:
        # Call CLI: python3 -m mcp_bot.cli "message"
        # The mcp_bot module should be in the policies directory
        cmd = [sys.executable, "-m", "mcp_bot.cli", user_message]
        
        # Inherit environment variables from current process
        env = os.environ.copy()
        
        # Ensure all required env vars are set
        required_vars = ["GIT_REPO", "GIT_USER", "GIT_PAT", "LLM_PROVIDER"]
        missing_vars = [var for var in required_vars if not env.get(var)]
        if missing_vars:
            return jsonify({
                "detail": f"Missing required environment variables: {', '.join(missing_vars)}",
                "error": "configuration_error"
            }), 500
        
        # Change working directory to policies directory
        cwd = _policies_dir if os.path.exists(_policies_dir) else os.getcwd()
        
        print(f"Running CLI: {' '.join(cmd)}")
        print(f"Working directory: {cwd}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=cwd
        )
        
        output = result.stdout
        error = result.stderr
        
        # Log output to terminal for debugging
        print("=== CLI STDOUT ===")
        print(output)
        if error:
            print("=== CLI STDERR ===")
            print(error)
        print("==================")
        
        # Strip ANSI codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_output = ansi_escape.sub('', output)
        clean_error = ansi_escape.sub('', error) if error else ""
        
        # Parse PR URL from stdout - handle both "PR created:" and "✓ PR created:"
        pr_match = re.search(r"(?:✓\s*)?PR created:\s*(https://[^\s]+)", clean_output)
        pr_url = pr_match.group(1) if pr_match else None
        
        # Parse policy information from output
        policy_info = {}
        policy_match = re.search(r"Policy:\s*([^\s(]+)", clean_output)
        if policy_match:
            policy_info["policy_name"] = policy_match.group(1)
        
        intent_match = re.search(r"Intent:\s*(\w+)", clean_output)
        if intent_match:
            policy_info["intent"] = intent_match.group(1)
        
        enforcement_match = re.search(r"Enforcement:\s*(\w+)", clean_output)
        if enforcement_match:
            policy_info["enforcement"] = enforcement_match.group(1)
        
        target_kinds_match = re.search(r"Target Kinds:\s*(.+?)(?:\n|$)", clean_output)
        if target_kinds_match:
            kinds_str = target_kinds_match.group(1).strip()
            policy_info["target_kinds"] = [k.strip() for k in kinds_str.split(',') if k.strip()]
        
        # Parse excluded namespaces from NamespaceSelector format
        namespaces_match = re.search(r"Namespaces:\s*NamespaceSelector\([^)]*exclude=\[([^\]]+)\]", clean_output)
        if namespaces_match:
            excluded_str = namespaces_match.group(1)
            # Extract quoted strings
            excluded_namespaces = re.findall(r"'([^']+)'", excluded_str)
            # Only add if there are namespaces (and filter out empty strings)
            if excluded_namespaces:
                filtered_namespaces = [ns for ns in excluded_namespaces if ns.strip()]
                if filtered_namespaces:
                    policy_info["excluded_namespaces"] = filtered_namespaces
        
        # Determine status
        status = "success" if result.returncode == 0 else "failure"
        
        # Extract error message if there is an error
        error_message = None
        if result.returncode != 0:
            # Try to extract error from stderr first
            if clean_error:
                error_message = clean_error.strip()
            else:
                # Try to extract error from stdout
                error_patterns = [
                    r"Error:\s*(.+?)(?:\n|$)",
                    r"✗\s*(.+?)(?:\n|$)",
                    r"FAILED[:\s]*(.+?)(?:\n|$)",
                    r"fatal:\s*(.+?)(?:\n|$)",
                ]
                for pattern in error_patterns:
                    match = re.search(pattern, clean_output, re.IGNORECASE | re.MULTILINE)
                    if match:
                        error_message = match.group(1).strip()
                        break
                
                # If no pattern matched, use last meaningful line
                if not error_message:
                    lines = [l.strip() for l in clean_output.split('\n') if l.strip() and not l.startswith('[')]
                    if lines:
                        error_message = lines[-1]
        
        # Calculate execution time
        execution_time = time.time() - start_time
        
        # Build response - include: error (if any), status, pr_url, policy info, and timing
        response_data = {}
        
        if error_message:
            response_data["error"] = error_message
        
        response_data["status"] = status
        
        if pr_url:
            response_data["pr_url"] = pr_url
        
        # Add policy information if available (exclude enforcement)
        policy_response = {}
        if policy_info:
            if "policy_name" in policy_info:
                policy_response["policy_name"] = policy_info["policy_name"]
            if "intent" in policy_info:
                policy_response["intent"] = policy_info["intent"]
            if "target_kinds" in policy_info:
                policy_response["target_kinds"] = policy_info["target_kinds"]
            if "excluded_namespaces" in policy_info:
                policy_response["excluded_namespaces"] = policy_info["excluded_namespaces"]
            if policy_response:
                response_data["policy"] = policy_response
        
        # Add timing information
        response_data["execution_time"] = round(execution_time, 2)
        
        # Log audit event
        try:
            from flask import current_app
            storage_service = current_app.config.get('storage_service')
            if storage_service:
                import json as json_lib
                from datetime import datetime, timezone
                
                # Build action description
                action_desc = f"Policy request: {user_message[:100]}"
                if policy_info.get("policy_name"):
                    action_desc = f"Policy: {policy_info['policy_name']} ({policy_info.get('intent', 'unknown')})"
                
                # Build details
                details = {
                    "request": user_message,
                    "execution_time": round(execution_time, 2),
                }
                if policy_response:
                    details["policy"] = policy_response
                if pr_url:
                    details["pr_url"] = pr_url
                if error_message:
                    details["error"] = error_message
                
                audit_event = {
                    "type": "policy_generation",
                    "action": action_desc,
                    "command": f"python3 -m mcp_bot.cli \"{user_message}\"",
                    "source": "mcp_bot",
                    "status": "SUCCESS" if status == "success" else "FAILED",
                    "user": None,  # Could be extracted from request headers if available
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": details
                }
                
                storage_service.log_audit_event(audit_event)
        except Exception as e:
            # Don't fail the request if audit logging fails
            print(f"Failed to log audit event: {e}")
        
        # If CLI failed, return 500
        if result.returncode != 0:
            return jsonify(response_data), 500
            
        return jsonify(response_data)

    except Exception as e:
        print(f"Error in /api/mcp/chat: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"detail": str(e)}), 500

