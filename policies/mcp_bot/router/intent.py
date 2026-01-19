"""Intent Router: NL → Intent + PolicySpec (Pure AI, no hardcode)"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

from ..schemas.policyspec import PolicyIntent, PolicySpec, EnforcementMode, NamespaceSelector

# Try to import LLM client
try:
    from ..llm.client import LLMRouter, GeminiClient
    HAS_LLM = True
except ImportError:
    HAS_LLM = False
    GeminiClient = None


class IntentRouter:
    """AI-powered intent router - Pure LLM inference, NO hardcode patterns"""
    
    DEFAULT_EXCLUDED_NS = ["kube-system", "gatekeeper-system", "argocd"]
    
    def __init__(self, use_llm: bool = True):
        """Initialize intent router - LLM is REQUIRED (no fallback)"""
        if not HAS_LLM:
            raise RuntimeError("LLM client not available. Install google-genai or set QWEN_API_KEY")
        
        self.use_llm = use_llm
        self.llm_client = None
        if self.use_llm:
            try:
                self.llm_client = LLMRouter().get_client()
                if not self.llm_client:
                    raise RuntimeError("Failed to initialize LLM client")
            except Exception as e:
                raise RuntimeError(f"LLM client initialization failed: {e}") from e
    
    def parse(self, request: str) -> Tuple[PolicyIntent, PolicySpec]:
        """
        Parse natural language request into PolicySpec using AI ONLY
        NO hardcode patterns - Pure LLM inference based on prompts
        
        Returns:
            (intent, spec)
        
        Raises:
            RuntimeError: If LLM is not available or parsing fails
        """
        if not self.llm_client:
            raise RuntimeError("LLM client not initialized. Cannot parse request without AI.")
        
        print(f"[DEBUG] 🤖 AI Parsing request (no hardcode): {request[:80]}...")
        try:
            spec = self._parse_with_llm(request)
            if not spec:
                raise RuntimeError("LLM returned None - failed to parse request")
            
            intent = spec.intent
            print(f"[DEBUG] ✅ AI parsed successfully:")
            print(f"  - Policy Type: {spec.policy_type}")
            print(f"  - Target Kinds: {spec.target_kinds}")
            print(f"  - Enforcement: {spec.enforcement.value}")
            print(f"  - Namespaces: {spec.namespaces}")
            print(f"  - Parameters: {spec.parameters}")
            print(f"  - Update Type: {spec.update_type}")
            return intent, spec
        except Exception as e:
            print(f"[DEBUG] ❌ AI parsing failed: {e}")
            raise RuntimeError(f"Failed to parse request with AI: {e}") from e
    
    def _parse_with_llm(self, request: str) -> Optional[PolicySpec]:
        """Parse request using LLM inference - NO pattern matching"""
        # Load prompt template
        prompt_file = Path(__file__).parent.parent / "llm" / "prompts" / "intent_parsing.txt"
        if prompt_file.exists():
            template = prompt_file.read_text(encoding="utf-8")
        else:
            # Fallback template (but still AI-based)
            template = """Parse this Kubernetes Gatekeeper policy request into PolicySpec JSON using AI inference:

User Request: {user_request}

Understand the intent, infer the policy type, target kinds, and parameters.
Return ONLY valid JSON:
{{
  "policy_id": "<type>",
  "policy_type": "<infer type>",
  "intent": "create",
  "description": "<original request>",
  "target_kinds": ["<infer from request>"],
  "namespaces": {{"exclude": ["kube-system", "gatekeeper-system", "argocd"]}},
  "enforcement": "<infer: dryrun/deny/warn>",
  "parameters": {{}}
}}"""
        
        full_prompt = template.format(user_request=request)
        
        # Call LLM generic text generation
        try:
            text = self.llm_client.generate_text(full_prompt)
            json_str = self._extract_json_from_text(text)
        except Exception as e:
            print(f"[DEBUG] ❌ LLM API call failed: {e}")
            return None
        
        if not json_str:
            print(f"[DEBUG] ❌ Could not extract JSON from LLM response")
            print(f"[DEBUG]   Full response: {text[:500] if 'text' in locals() else 'N/A'}")
            return None
        
        try:
            # Clean up JSON string (remove trailing commas, fix quotes if needed)
            json_str = json_str.strip()
            # Try to fix common JSON issues
            json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing comma before }
            json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing comma before ]
            
            data = json.loads(json_str)
            # Convert to PolicySpec
            return PolicySpec.from_dict(data)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] ❌ JSON decode error: {e}")
            print(f"[DEBUG]   Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            print(f"[DEBUG]   JSON string (first 500 chars): {json_str[:500]}")
            print(f"[DEBUG]   Full JSON string length: {len(json_str)}")
            # Try to extract and show the problematic part
            if hasattr(e, 'pos') and e.pos > 0:
                start = max(0, e.pos - 50)
                end = min(len(json_str), e.pos + 50)
                print(f"[DEBUG]   Context around error: ...{json_str[start:end]}...")
            return None
        except (KeyError, ValueError) as e:
            print(f"[DEBUG] ❌ Failed to convert to PolicySpec: {e}")
            print(f"[DEBUG]   Parsed data: {data if 'data' in locals() else 'N/A'}")
            print(f"[DEBUG]   JSON string: {json_str[:200]}")
            return None
    
    def _extract_json_from_text(self, text: str) -> Optional[str]:
        """Extract JSON from LLM response (may be in code blocks)"""
        print(f"[DEBUG] 📝 Extracting JSON from response ({len(text)} chars)")
        
        # Try to find JSON in code blocks first (most common)
        json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
            print(f"[DEBUG] ✅ Found JSON in code block ({len(json_str)} chars)")
            return json_str
        
        # Try to find JSON object (match from first { to matching })
        # Use a more robust matching that handles nested braces
        depth = 0
        start = -1
        for i, char in enumerate(text):
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    json_str = text[start:i+1]
                    print(f"[DEBUG] ✅ Found JSON object ({len(json_str)} chars)")
                    return json_str
        
        # Fallback: try simple regex (less reliable but might work)
        json_match = re.search(r'(\{[\s\S]{20,}\})', text)  # At least 20 chars
        if json_match:
            json_str = json_match.group(1).strip()
            print(f"[DEBUG] ⚠️ Found JSON via fallback regex ({len(json_str)} chars)")
            return json_str
        
        print(f"[DEBUG] ❌ No JSON found in response")
        print(f"[DEBUG]   Response preview: {text[:300]}")
        return None


def parse_request(request: str) -> PolicySpec:
    """Convenience function to parse request into PolicySpec (AI-only)"""
    router = IntentRouter()
    _, spec = router.parse(request)
    return spec
