import sys
import os
import subprocess
import venv
from pathlib import Path

def in_virtualenv():
    return sys.prefix != sys.base_prefix

def get_venv_python(venv_path):
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"

def ensure_venv(project_root):
    venv_dir = project_root / ".venv"
    if not venv_dir.exists():
        print(f"Creating virtual environment in {venv_dir}...")
        try:
            venv.create(venv_dir, with_pip=True)
        except Exception as e:
            print(f"Error creating virtual environment: {e}")
            # Fallback: try running without venv if creation fails (unlikely but possible)
            return None
    return get_venv_python(venv_dir)

def install_dependencies(python_executable, requirements_path):
    print("Checking dependencies...")
    try:
        subprocess.check_call([str(python_executable), "-m", "pip", "install", "-r", str(requirements_path)])
    except subprocess.CalledProcessError:
        print("Failed to install dependencies.")
        sys.exit(1)

if __name__ == "__main__":
    # Determine project root (parent of the directory containing this script)
    current_dir = Path(__file__).parent.resolve() # .../server
    project_root = current_dir.parent # .../

    # Add project root to sys.path
    sys.path.insert(0, str(project_root))
    
    # Change to project root
    os.chdir(project_root)

    if not in_virtualenv():
        print("Not in a virtual environment. Setting one up...")
        venv_python = ensure_venv(project_root)
        
        if venv_python and venv_python.exists():
            print(f"Re-launching with virtual environment: {venv_python}")
            # Re-run this script using the venv python
            try:
                subprocess.check_call([str(venv_python), __file__] + sys.argv[1:])
            except subprocess.CalledProcessError as e:
                sys.exit(e.returncode)
            sys.exit(0)
        else:
            print("Warning: Could not setup virtual environment. Trying to proceed with system python (might fail)...")

    # If we are here, we are likely in the venv (or fallback)
    install_dependencies(sys.executable, current_dir / "requirements.txt")

    # Load environment variables from .env
    env_path = project_root / ".env"
    if env_path.exists():
        print(f"Loading environment variables from {env_path}")
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Handle both KEY=value and KEY="value" formats
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        # Only set if not already in environment (env vars take precedence)
                        if key.strip() not in os.environ:
                            os.environ[key.strip()] = value
    else:
        print("Warning: .env file not found. Using environment variables from shell.")
    
    # Print loaded environment variables (mask sensitive ones)
    print("\n📋 Environment Configuration:")
    env_vars_to_check = [
        "GIT_REPO", "GIT_USER", "GIT_PAT", 
        "LLM_PROVIDER", "USE_LOCAL_QWEN",
        "QWEN_LOCAL_URL", "QWEN_LOCAL_MODEL", "QWEN_LOCAL_TOKEN",
        "GOOGLE_GEMINI_API_KEY", "QWEN_API_KEY"
    ]
    for var in env_vars_to_check:
        value = os.getenv(var)
        if value:
            if "PAT" in var or "TOKEN" in var or "KEY" in var:
                masked = value[:10] + "..." if len(value) > 10 else "***"
                print(f"  ✅ {var}={masked}")
            else:
                print(f"  ✅ {var}={value}")
        else:
            print(f"  ⚠️  {var}=not set")
    print()

    print(f"Starting Flask Backend Server from {project_root}...")
    try:
        from server.main import app
        app.run(host="127.0.0.1", port=8000, debug=True)
    except ImportError as e:
        print(f"Error importing app: {e}")
    except Exception as e:
        print(f"Failed to start server: {e}")
