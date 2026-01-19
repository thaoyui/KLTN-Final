"""LLM Client Interface for Gemini and Qwen"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

import certifi

# Try to import Google Gemini SDK
try:
    from google import genai
    HAS_GEMINI_SDK = True
except ImportError:
    HAS_GEMINI_SDK = False


class LLMClientError(Exception):
    """LLM client error"""
    pass


class LLMClient(ABC):
    """Abstract LLM client interface"""
    
    @abstractmethod
    def generate_policy(self, prompt: str, spec: Dict) -> Dict[str, str]:
        """
        Generate ConstraintTemplate and Constraint from prompt + spec
        
        Returns:
            Dict with "rego", "schema", "constraint" keys
        """
        pass

    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        """
        Generate raw text from prompt
        """
        pass


class GeminiClient(LLMClient):
    """Google Gemini LLM client using official SDK"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash-exp"):
        self.api_key = api_key or os.getenv("GOOGLE_GEMINI_API_KEY")
        # Use gemini-2.0-flash-exp (latest) or gemini-1.5-flash, gemini-1.5-pro
        self.model = model or os.getenv("GOOGLE_GEMINI_MODEL", "gemini-2.0-flash-exp")
        self.timeout = 30
        
        if not self.api_key:
            raise ValueError("GOOGLE_GEMINI_API_KEY not set")
        
        # Initialize SDK client if available
        if HAS_GEMINI_SDK:
            try:
                self.client = genai.Client(api_key=self.api_key)
                self.use_sdk = True
            except Exception as e:
                print(f"Warning: Failed to initialize Gemini SDK, falling back to HTTP: {e}")
                self.use_sdk = False
                self.client = None
        else:
            self.use_sdk = False
            self.client = None
    
    def generate_policy(self, prompt: str, spec: Dict) -> Dict[str, str]:
        """Generate policy using Gemini (SDK or HTTP fallback)"""
        full_prompt = self._build_prompt(prompt, spec)
        text = self.generate_text(full_prompt)
        return self._parse_response(text)

    def generate_text(self, prompt: str) -> str:
        """Generate raw text using Gemini"""
        # Try SDK first if available
        if self.use_sdk and self.client:
            print(f"[DEBUG] 🤖 Gemini SDK: Generating text with model {self.model}")
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                text = response.text
                print(f"[DEBUG] ✅ SDK response: {len(text)} chars")
                return text
            except Exception as e:
                print(f"[DEBUG] ⚠️ Gemini SDK failed: {e}, falling back to HTTP")
                # Fall through to HTTP method
        
        # Fallback to HTTP method
        return self._generate_text_http(prompt)
    
    def _generate_text_http(self, prompt: str) -> str:
        """Generate text using HTTP API (fallback)"""
        print(f"[DEBUG] 🔧 Gemini HTTP: Generating text with model {self.model}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        
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
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=ctx) as resp:
                body = json.load(resp)
                return body["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"Gemini API request failed: {exc.code} {exc.reason}. {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"Gemini API request failed: {exc}") from exc
    

    
    def _build_prompt(self, user_prompt: str, spec: Dict) -> str:
        """Build full prompt for Gemini from template"""
        prompt_file = Path(__file__).parent / "prompts" / "policy_generation.txt"
        
        if prompt_file.exists():
            template = prompt_file.read_text(encoding="utf-8")
        else:
            # Fallback to inline prompt
            template = """You are a Gatekeeper policy expert. Generate a complete Gatekeeper policy based on this request:

User Request: {user_prompt}

Policy Specification:
{policy_spec_json}

Generate:
1. Rego code for the ConstraintTemplate (package name should match policy type)
2. OpenAPI schema for parameters (JSON schema format)
3. Constraint YAML snippet (spec section only)

Format your response as JSON:
{{
  "rego": "<rego code here>",
  "schema": {{"parameters schema here"}},
  "constraint_spec": {{"constraint spec here"}}
}}

Important:
- Rego must use object.get() for safe access
- Use violation[{{"msg": msg}}] format
- Schema must match parameter types
- Constraint spec should include enforcementAction, match, parameters
"""
        
        return (
            template.replace("{user_prompt}", user_prompt)
            .replace("{policy_spec_json}", json.dumps(spec, indent=2))
        )

    def _parse_response(self, text: str) -> Dict[str, str]:
        """Parse LLM response with better error handling"""
        import re
        print(f"[DEBUG] Parsing LLM response ({len(text)} chars)")
        
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
            print(f"[DEBUG] Found JSON in code block")
        else:
            # Try to find JSON object directly (greedy match)
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                text = json_match.group(0)
                print(f"[DEBUG] Found JSON object in text")
        
        try:
            data = json.loads(text)
            print(f"[DEBUG] ✅ Parsed JSON successfully")
            print(f"[DEBUG]   Keys: {list(data.keys())}")
            
            # Extract fields
            rego = data.get("rego", "")
            schema_raw = data.get("schema", {})
            constraint_spec_raw = data.get("constraint_spec", {})
            
            # Normalize schema (ensure it's JSON string)
            if isinstance(schema_raw, dict):
                schema_json = json.dumps(schema_raw)
            elif isinstance(schema_raw, str):
                try:
                    # Validate it's valid JSON
                    json.loads(schema_raw)
                    schema_json = schema_raw
                except:
                    schema_json = json.dumps({})
            else:
                schema_json = json.dumps({})
            
            # Normalize constraint_spec
            if isinstance(constraint_spec_raw, dict):
                constraint_json = json.dumps(constraint_spec_raw)
            elif isinstance(constraint_spec_raw, str):
                try:
                    json.loads(constraint_spec_raw)
                    constraint_json = constraint_spec_raw
                except:
                    constraint_json = json.dumps({})
            else:
                constraint_json = json.dumps({})
            
            return {
                "rego": rego,
                "schema": schema_json,
                "constraint_spec": constraint_json,
            }
        except json.JSONDecodeError as e:
            print(f"[DEBUG] ⚠️ JSON parse error: {e}")
            print(f"[DEBUG]   Text preview: {text[:500]}")
            # Fallback: try to extract fields manually
            rego_match = re.search(r'"rego"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, re.DOTALL)
            if not rego_match:
                rego_match = re.search(r'"rego"\s*:\s*"([^"]+)"', text)
            
            return {
                "rego": rego_match.group(1) if rego_match else "",
                "schema": "{}",
                "constraint_spec": "{}",
            }


class QwenClient(LLMClient):
    """Alibaba Qwen LLM client (Local or Cloud)"""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.use_local = os.getenv("USE_LOCAL_QWEN", "false").lower() == "true"
        
        if self.use_local:
            # Check for bearer token in environment
            local_token = os.getenv("QWEN_LOCAL_TOKEN")
            self.api_key = local_token if local_token else None
            self.base_url = os.getenv("QWEN_LOCAL_URL", "http://localhost:11434/v1/chat/completions")
            self.model = os.getenv("QWEN_LOCAL_MODEL", "qwen2.5-coder")
        else:
            self.api_key = api_key or os.getenv("QWEN_API_KEY")
            self.base_url = base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation")
            self.model = "qwen-turbo"
            
            if not self.api_key:
                raise ValueError("QWEN_API_KEY not set (and USE_LOCAL_QWEN is false)")
                
        self.timeout = 300 # Increased timeout for local models

    def generate_policy(self, prompt: str, spec: Dict) -> Dict[str, str]:
        """Generate policy using Qwen"""
        full_prompt = self._build_prompt(prompt, spec)
        text = self.generate_text(full_prompt)
        return self._parse_response(text)

    def generate_text(self, prompt: str) -> str:
        """Generate raw text using Qwen"""
        headers = {
            "Content-Type": "application/json",
        }
        
        # Add Authorization header if token is available (for local endpoints that require auth)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        if self.use_local:
            # OpenAI Compatible Format (Ollama/vLLM)
            payload = {
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }],
                "temperature": 0.1,
                "max_tokens": 2000,
            }
        else:
            # DashScope Native Format
            headers["Authorization"] = f"Bearer {self.api_key}"
            payload = {
                "model": self.model,
                "input": {
                    "messages": [{
                        "role": "user",
                        "content": prompt
                    }]
                },
                "parameters": {
                    "temperature": 0.1,
                    "max_tokens": 2000,
                }
            }
        
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        
        ctx = ssl.create_default_context(cafile=certifi.where())
        if self.use_local:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=ctx) as resp:
                body = json.load(resp)
                
                if self.use_local:
                    # OpenAI format response
                    return body["choices"][0]["message"]["content"]
                else:
                    # DashScope format response
                    return body["output"]["choices"][0]["message"]["content"]
                    
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"Qwen API request failed: {exc.code} {exc.reason}. {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"Qwen API request failed: {exc}") from exc
    
    def _build_prompt(self, user_prompt: str, spec: Dict) -> str:
        """Build full prompt for Qwen from template"""
        prompt_file = Path(__file__).parent / "prompts" / "policy_generation.txt"
        
        if prompt_file.exists():
            template = prompt_file.read_text(encoding="utf-8")
        else:
            # Fallback to inline prompt
            template = """你是Gatekeeper策略专家。根据以下要求生成完整的Gatekeeper策略：

用户请求: {user_prompt}

策略规格:
{policy_spec_json}

生成：
1. ConstraintTemplate的Rego代码（package名称应与策略类型匹配）
2. 参数的OpenAPI schema（JSON schema格式）
3. Constraint YAML片段（仅spec部分）

以JSON格式回复：
{{
  "rego": "<rego代码>",
  "schema": {{"参数schema"}},
  "constraint_spec": {{"constraint spec"}}
}}

重要：
- Rego必须使用object.get()进行安全访问
- 使用violation[{{"msg": msg}}]格式
- Schema必须匹配参数类型
- Constraint spec应包含enforcementAction、match、parameters
"""
        
        return (
            template.replace("{user_prompt}", user_prompt)
            .replace("{policy_spec_json}", json.dumps(spec, indent=2, ensure_ascii=False))
        )

    def _parse_response(self, text: str) -> Dict[str, str]:
        """Parse LLM response (same as Gemini)"""
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
        
        try:
            data = json.loads(text)
            return {
                "rego": data.get("rego", ""),
                "schema": json.dumps(data.get("schema", {})),
                "constraint_spec": json.dumps(data.get("constraint_spec", {})),
            }
        except json.JSONDecodeError:
            rego_match = re.search(r'"rego":\s*"(.*?)"', text, re.DOTALL)
            return {
                "rego": rego_match.group(1) if rego_match else "",
                "schema": "{}",
                "constraint_spec": "{}",
            }


class LLMRouter:
    """Route to appropriate LLM client based on environment"""
    
    @staticmethod
    def get_client() -> LLMClient:
        """Get LLM client based on environment variables"""
        llm_provider = os.getenv("LLM_PROVIDER", "").lower()
        use_local_qwen = os.getenv("USE_LOCAL_QWEN", "false").lower() == "true"
        
        if llm_provider == "qwen" or use_local_qwen:
            return QwenClient()
        else:
            return GeminiClient()
