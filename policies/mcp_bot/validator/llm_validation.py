"""LLM-based Policy Validation"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

import yaml

from ..llm.client import LLMClient, LLMRouter


class LLMValidationResult:
    """Result of LLM validation"""
    def __init__(
        self,
        valid: bool,
        score: int,
        errors: list[str],
        warnings: list[str],
        suggestions: list[str],
        corrected_rego: Optional[str] = None,
        corrected_schema: Optional[Dict] = None,
        corrected_constraint_spec: Optional[Dict] = None,
    ):
        self.valid = valid
        self.score = score
        self.errors = errors
        self.warnings = warnings
        self.suggestions = suggestions
        self.corrected_rego = corrected_rego
        self.corrected_schema = corrected_schema
        self.corrected_constraint_spec = corrected_constraint_spec


class LLMValidator:
    """Validate policies using LLM"""
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.use_llm = os.getenv("LLM_ENABLED", "true").lower() == "true"
        if self.use_llm:
            try:
                self.llm_client = llm_client or LLMRouter.get_client()
            except Exception as e:
                print(f"Warning: LLM validation disabled: {e}")
                self.use_llm = False
                self.llm_client = None
        else:
            self.llm_client = None
    
    def validate(
        self,
        template_path: str,
        constraint_path: Optional[str],
        user_prompt: str,
        policy_spec: Dict,
        template_content: Optional[str] = None,
        constraint_content: Optional[str] = None,
    ) -> LLMValidationResult:
        """
        Validate generated policy using LLM
        
        Returns:
            LLMValidationResult with validation outcome and corrections
        """
        print(f"[DEBUG] LLM Validator status:")
        print(f"  - use_llm: {self.use_llm}")
        print(f"  - llm_client: {self.llm_client is not None}")
        if self.llm_client:
            print(f"  - client type: {type(self.llm_client).__name__}")
            if hasattr(self.llm_client, 'use_sdk'):
                print(f"  - use_sdk: {self.llm_client.use_sdk}")
            if hasattr(self.llm_client, 'model'):
                print(f"  - model: {self.llm_client.model}")
        
        if not self.use_llm or not self.llm_client:
            # Skip LLM validation if disabled
            print(f"[DEBUG] ⚠️ LLM validation SKIPPED (use_llm={self.use_llm}, client={self.llm_client is not None})")
            return LLMValidationResult(
                valid=True,
                score=100,
                errors=[],
                warnings=["LLM validation skipped - not enabled or client not initialized"],
                suggestions=[],
            )
        
        # Read generated artifacts if not provided
        if template_content is None:
            with open(template_path) as f:
                template_content = f.read()
        
        if constraint_content is None:
            if constraint_path and Path(constraint_path).exists():
                with open(constraint_path) as f:
                    constraint_content = f.read()
            else:
                constraint_content = ""
        
        # Extract Rego and schema from template
        template_yaml = yaml.safe_load(template_content)
        rego = ""
        schema = {}
        
        if template_yaml and "spec" in template_yaml:
            targets = template_yaml["spec"].get("targets", [])
            if targets:
                rego = targets[0].get("rego", "")
            
            crd = template_yaml["spec"].get("crd", {})
            if "spec" in crd and "validation" in crd["spec"]:
                schema = crd["spec"]["validation"].get("openAPIV3Schema", {})
        
        # Extract constraint spec
        constraint_spec = {}
        if constraint_content:
            constraint_yaml = yaml.safe_load(constraint_content)
            if constraint_yaml and "spec" in constraint_yaml:
                constraint_spec = constraint_yaml["spec"]
        
        # Build policy artifacts summary for LLM
        policy_artifacts = {
            "rego": rego,
            "schema": schema,
            "constraint_spec": constraint_spec,
        }
        
        # Call LLM for validation
        prompt_file = Path(__file__).parent.parent / "llm" / "prompts" / "policy_validation.txt"
        
        if prompt_file.exists():
            template_text = prompt_file.read_text(encoding="utf-8")
        else:
            # Fallback
            template_text = """Validate this Gatekeeper policy:

Policy Artifacts:
{policy_artifacts}

User Request: {user_prompt}

Original Spec: {policy_spec_json}

Respond with JSON: {{"valid": true/false}}

Return valid=true if policy is correct and ready to use.
Return valid=false if policy has critical errors.
"""
        
        full_prompt = template_text.format(
            policy_artifacts=json.dumps(policy_artifacts, indent=2),
            user_prompt=user_prompt,
            policy_spec_json=json.dumps(policy_spec, indent=2),
        )
        
        try:
            # Use LLM to validate
            print(f"[DEBUG] 📞 Calling LLM API for validation...")
            print(f"[DEBUG]   Prompt length: {len(full_prompt)} chars")
            print(f"[DEBUG]   Rego length: {len(rego)} chars")
            
            # Use centralized client
            result = self.llm_client.generate_text(full_prompt)
            
            print(f"[DEBUG] ✅ LLM API response received: {len(result)} chars")
            print(f"[DEBUG]   Response preview: {result[:200]}...")
            
            parsed = self._parse_validation_result(result)
            print(f"[DEBUG] ✅ Parsed validation result:")
            print(f"   - valid: {parsed.valid}")
            print(f"   - score: {parsed.score}")
            print(f"   - errors: {len(parsed.errors)}")
            print(f"   - warnings: {len(parsed.warnings)}")
            print(f"   - suggestions: {len(parsed.suggestions)}")
            
            return parsed
        except Exception as e:
            print(f"[DEBUG] ❌ LLM validation error: {e}")
            import traceback
            traceback.print_exc()
            return LLMValidationResult(
                valid=True,  # Don't block on LLM failure
                score=100,
                errors=[],
                warnings=[f"LLM validation unavailable: {e}"],
                suggestions=[],
            )
    
    def _parse_validation_result(self, text: str) -> LLMValidationResult:
        """Parse LLM validation response"""
        import re
        
        # Extract JSON from response
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)
        else:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
        
        try:
            data = json.loads(text)
            # Simplified: only use valid boolean for decision making
            valid = data.get("valid", False)
            return LLMValidationResult(
                valid=valid,
                score=100 if valid else 0,  # Score kept for compatibility but not used
                errors=data.get("errors", []),
                warnings=data.get("warnings", []),
                suggestions=data.get("suggestions", []),
                corrected_rego=data.get("corrected_rego"),
                corrected_schema=data.get("corrected_schema"),
                corrected_constraint_spec=data.get("corrected_constraint_spec"),
            )
        except json.JSONDecodeError:
            # Fallback: try to extract valid boolean
            valid = "valid" in text.lower() and "true" in text.lower()
            return LLMValidationResult(
                valid=valid,
                score=100 if valid else 0,
                errors=[f"Failed to parse LLM response: {text[:200]}"],
                warnings=[],
                suggestions=[],
            )


def validate_with_llm(
    template_path: str,
    constraint_path: Optional[str],
    user_prompt: str,
    policy_spec: Dict,
) -> LLMValidationResult:
    """Convenience function for LLM validation"""
    validator = LLMValidator()
    return validator.validate(template_path, constraint_path, user_prompt, policy_spec)

