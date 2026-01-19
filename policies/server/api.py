import os
import sys
import re
import subprocess
import json
from pathlib import Path
from flask import Blueprint, request, jsonify, Response, stream_with_context
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

api_bp = Blueprint("api", __name__)

# In-memory storage for history (in production, use database)
request_history = []

@api_bp.route("/chat", methods=["POST"])
def chat():
    """
    Executes the mcp_bot CLI via subprocess and returns the output.
    """
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"detail": "Message is required"}), 400
    
    user_message = data["message"]
    
    try:
        # Call CLI: python3 -m mcp_bot.cli "message"
        cmd = [sys.executable, "-m", "mcp_bot.cli", user_message]
        
        # Inherit environment variables from current process
        # This includes variables from .env file loaded by server/run.py
        env = os.environ.copy()
        
        # Ensure all required env vars are set
        required_vars = ["GIT_REPO", "GIT_USER", "GIT_PAT", "LLM_PROVIDER"]
        missing_vars = [var for var in required_vars if not env.get(var)]
        if missing_vars:
            return jsonify({
                "detail": f"Missing required environment variables: {', '.join(missing_vars)}",
                "error": "configuration_error"
            }), 500
        
        print(f"Running CLI: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(project_root)
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

        # Write to debug log file
        with open("server_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n\n=== Request: {user_message} ===\n")
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"STDOUT:\n{output}\n")
            f.write(f"STDERR:\n{error}\n")
            f.write("==================\n")
        
        # Parse PR URL from stdout
        # Looking for: "✓ PR created: https://..."
        pr_match = re.search(r"PR created:\s*(https://[^\s]+)", output)
        pr_url = pr_match.group(1) if pr_match else None
        
        # Strip ANSI codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        clean_output = ansi_escape.sub('', output)
        clean_error = ansi_escape.sub('', error) if error else ""
        
        # Combine output and error for display
        full_output = clean_output
        if clean_error:
            full_output += "\n\n=== STDERR ===\n" + clean_error
            
        if not full_output or not full_output.strip():
            full_output = "[System] Command executed but returned no output."
            
        response_data = {
            "output": full_output,
            "pr_url": pr_url,
            "status": "success" if result.returncode == 0 else "failure"
        }
        
        # Clean the output for the user
        # Remove ANSI codes first (already done above)
        
        # Filter out debug and verbose lines
        lines = full_output.split('\n')
        cleaned_lines = []
        for line in lines:
            # Strip whitespace for checking start, but keep original indentation
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line) # Keep empty lines for spacing
                continue
                
            # Skip debug and verbose progress messages
            if (stripped.startswith("[DEBUG]") or
                stripped.startswith("Cloning") or
                stripped.startswith("Generating") or
                stripped.startswith("Validating") or
                stripped.startswith("Creating branch") or
                stripped.startswith("Pushing branch") or
                stripped.startswith("Switched to") or
                stripped.startswith("Command:") or 
                stripped.startswith("Parsing request")):
                continue
                
            cleaned_lines.append(line)
            
        clean_output_text = "\n".join(cleaned_lines).strip()

        if not clean_output_text:
            clean_output_text = "[System] Command executed successfully."

        # AI Summarization
        try:
            print("Summarizing output with AI...")
            summary = summarize_output(clean_output_text)
            final_output = summary
        except Exception as e:
            print(f"Summarization failed: {e}")
            final_output = clean_output_text # Fallback to cleaned text

        response_data = {
            "output": final_output,
            "pr_url": pr_url,
            "status": "success" if result.returncode == 0 else "failure",
            "timestamp": datetime.now().isoformat(),
            "request": user_message
        }
        
        # Save to history
        history_item = {
            "id": len(request_history),
            "request": user_message,
            "response": response_data,
            "timestamp": datetime.now().isoformat()
        }
        request_history.append(history_item)
        
        # If CLI failed, return 500 but still include output so user can see why
        if result.returncode != 0:
            with open("server_debug.log", "a", encoding="utf-8") as f:
                f.write("Returning 500 error\n")
            return jsonify(response_data), 500
            
        with open("server_debug.log", "a", encoding="utf-8") as f:
            f.write("Returning success response\n")
        return jsonify(response_data)

    except Exception as e:
        print(f"Error in /chat: {e}")
        with open("server_debug.log", "a", encoding="utf-8") as f:
            f.write(f"EXCEPTION: {e}\n")
        return jsonify({"detail": str(e)}), 500

def summarize_output(text):
    """Summarize CLI output using Local Qwen, Cloud Qwen, or Gemini"""
    import urllib.request
    import json
    import ssl
    import certifi
    
    # 1. Try Local Qwen (Ollama/vLLM)
    # Default to Ollama's OpenAI-compatible endpoint
    local_url = os.getenv("QWEN_LOCAL_URL", "http://localhost:11434/v1/chat/completions")
    local_model = os.getenv("QWEN_LOCAL_MODEL", "qwen2.5-coder")
    
    # Only try local if explicitly enabled or if we want to try it by default
    # Let's check if the user wants it via env var or just try it if configured
    if os.getenv("USE_LOCAL_QWEN", "false").lower() == "true":
        print(f"Using Local Qwen ({local_model}) at {local_url}...")
        
        prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}
"""
        payload = {
            "model": local_model,
            "messages": [{
                "role": "user",
                "content": prompt
            }],
            "temperature": 0.1,
            "max_tokens": 1000
        }
        
        headers = {
            "Content-Type": "application/json",
        }
        
        request = urllib.request.Request(
            local_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        
        # Localhost usually doesn't need SSL context, but good to have just in case
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(request, timeout=10, context=ctx) as resp:
                body = json.load(resp)
                return body["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Local Qwen summary failed: {e}")
            # Fall through to Cloud Qwen/Gemini
            pass

    # 2. Try Cloud Qwen (User Preference)
    qwen_api_key = os.getenv("QWEN_API_KEY")
    if qwen_api_key:
        print("Using Cloud Qwen for summarization...")
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        
        prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}
"""
        payload = {
            "model": "qwen-turbo",
            "input": {
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            },
            "parameters": {
                "temperature": 0.1,
                "max_tokens": 1000,
            }
        }
        
        headers = {
            "Authorization": f"Bearer {qwen_api_key}",
            "Content-Type": "application/json",
        }
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        
        ctx = ssl.create_default_context(cafile=certifi.where())
        
        try:
            with urllib.request.urlopen(request, timeout=30, context=ctx) as resp:
                body = json.load(resp)
                return body["output"]["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Qwen summary failed: {e}")
            # Fall through to Gemini if Qwen fails
            pass

    # Fallback to Gemini
    api_key = os.getenv("GOOGLE_GEMINI_API_KEY")
    if not api_key:
        return text
        
    print("Using Gemini for summarization...")
    model = "gemini-2.0-flash-exp"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    prompt = f"""You are a helpful assistant for a Kubernetes policy tool. 
Summarize the following CLI output for the user. 
Extract the key actions taken (e.g., "Created PR", "Validated policy").
Format it nicely with emojis.
If there is a PR link, make sure to mention it clearly.
Keep it concise but informative.

CLI Output:
{text}
"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    
    ctx = ssl.create_default_context(cafile=certifi.where())
    
    with urllib.request.urlopen(request, timeout=30, context=ctx) as resp:
        body = json.load(resp)
        return body["candidates"][0]["content"]["parts"][0]["text"]

@api_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })

@api_bp.route("/history", methods=["GET"])
def get_history():
    """Get request history"""
    limit = request.args.get("limit", 50, type=int)
    return jsonify({
        "history": request_history[-limit:],
        "total": len(request_history)
    })

@api_bp.route("/history/<int:history_id>", methods=["GET"])
def get_history_item(history_id):
    """Get specific history item"""
    if 0 <= history_id < len(request_history):
        return jsonify(request_history[history_id])
    return jsonify({"error": "History item not found"}), 404

@api_bp.route("/history", methods=["DELETE"])
def clear_history():
    """Clear request history"""
    request_history.clear()
    return jsonify({"message": "History cleared"})

@api_bp.route("/status", methods=["GET"])
def get_status():
    """Get system status and configuration"""
    return jsonify({
        "status": "running",
        "llm_provider": os.getenv("LLM_PROVIDER", "not_set"),
        "git_repo": os.getenv("GIT_REPO", "not_set"),
        "has_gemini": bool(os.getenv("GOOGLE_GEMINI_API_KEY")),
        "has_qwen": bool(os.getenv("QWEN_API_KEY")),
        "use_local_qwen": os.getenv("USE_LOCAL_QWEN", "false").lower() == "true",
        "timestamp": datetime.now().isoformat()
    })

@api_bp.route("/apply", methods=["POST"])
def apply():
    return jsonify({"detail": "Endpoint deprecated. Use /chat."}), 410
