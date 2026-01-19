import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print(f"Project root: {project_root}")
print(f"Sys path: {sys.path}")

try:
    print("Attempting imports...")
    from mcp_bot.router.intent import parse_request
    from mcp_bot.generator.templates import PolicyGenerator
    from mcp_bot.validator.static import validate_policy
    from mcp_bot.validator.llm_validation import LLMValidator
    print("Imports successful!")
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)
except Exception as e:
    print(f"An error occurred during import: {e}")
    sys.exit(1)

try:
    print("Testing parse_request...")
    spec = parse_request("banish pod run root")
    print(f"Parsed spec: {spec}")
except Exception as e:
    print(f"Error during parse_request: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("Test complete.")
