"""Policy Generator: DSL → ConstraintTemplate/Constraint YAML"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional
import yaml


class LiteralString(str):
    """Force literal block scalar style in YAML."""
    pass

def literal_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

yaml.add_representer(LiteralString, literal_representer)
yaml.add_representer(LiteralString, literal_representer, Dumper=yaml.SafeDumper)


from ..llm.client import LLMClient, LLMRouter
from ..schemas.policyspec import PolicySpec
from ..validator.llm_validation import LLMValidator


class PolicyGenerator:
    """Generate Gatekeeper artifacts from PolicySpec using LLM"""
    
    TEMPLATES_DIR = Path(__file__).parent / "rego_templates"
    
    def __init__(
        self,
        base_path: str = "policies",
        llm_client: Optional[LLMClient] = None,
        use_llm: bool = True,
        overwrite_existing: Optional[bool] = None,
        merge_existing: Optional[bool] = None,
    ):
        self.base_path = Path(base_path)
        self.templates_dir = self.base_path / "templates"
        self.constraints_dir = self.base_path / "constraints"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.constraints_dir.mkdir(parents=True, exist_ok=True)
        self.overwrite_existing = (
            overwrite_existing
            if overwrite_existing is not None
            else os.getenv("MCP_OVERWRITE_POLICIES", "false").lower() == "true"
        )
        self.merge_existing = (
            merge_existing
            if merge_existing is not None
            else os.getenv("MCP_MERGE_POLICIES", "false").lower() == "true"
        )
        
        # LLM setup
        self.use_llm = use_llm and os.getenv("LLM_ENABLED", "true").lower() == "true"
        if self.use_llm:
            try:
                self.llm_client = llm_client or LLMRouter.get_client()
            except Exception as e:
                print(f"Warning: LLM initialization failed, falling back to templates: {e}")
                self.use_llm = False
                self.llm_client = None
        else:
            self.llm_client = None
    
    def generate(self, spec: PolicySpec, user_prompt: str = "") -> Dict[str, str]:
        """
        Generate CT and Constraint files
        
        Args:
            spec: PolicySpec DSL
            user_prompt: Original user request (for LLM context)
        
        Returns:
            Dict with "template" and "constraint" file paths
        """
        ct_file = self.templates_dir / f"{spec.policy_type}-template.yaml"
        constraint_file = self.constraints_dir / f"{spec.policy_type}-constraint.yaml"

        overwrite_existing = self.overwrite_existing
        merge_existing = self.merge_existing

        policy_exists = ct_file.exists() and constraint_file.exists()
        
        if policy_exists:
            if not (overwrite_existing or merge_existing):
                print(
                    f"[INFO] Policy '{spec.policy_type}' already exists at "
                    f"{ct_file if ct_file.exists() else constraint_file}. Skipping generation "
                    "(set MCP_OVERWRITE_POLICIES=true to overwrite or MCP_MERGE_POLICIES=true to merge)."
                )
                return {
                    "template": str(ct_file),
                    "constraint": str(constraint_file),
                }
            if overwrite_existing:
                print(
                    f"[INFO] Policy '{spec.policy_type}' already exists but MCP_OVERWRITE_POLICIES=true; "
                    "regenerating artifacts."
                )
            elif merge_existing:
                print(
                    f"[INFO] Policy '{spec.policy_type}' already exists; will UPDATE existing files (not regenerate)."
                )

        # LOGIC: 
        # - Policy NOT exists → Generate new with LLM
        # - Policy EXISTS + merge_existing → Only patch existing files, NO regenerate
        # - Policy EXISTS + overwrite_existing → Regenerate with LLM
        
        if policy_exists and merge_existing and not overwrite_existing:
            # UPDATE MODE: Policy exists, only patch/update existing files
            # DO NOT regenerate Rego code - preserve existing logic
            # Double-check files exist before patching
            if not ct_file.exists() or not constraint_file.exists():
                missing_files = []
                if not ct_file.exists():
                    missing_files.append(str(ct_file))
                if not constraint_file.exists():
                    missing_files.append(str(constraint_file))
                
                print(f"[DEBUG] ⚠️ Files not found for UPDATE mode:")
                for f in missing_files:
                    print(f"[DEBUG]   - {f}")
                print(f"[DEBUG] 🔄 Falling back to CREATE MODE")
                policy_exists = False
        
        if policy_exists and merge_existing and not overwrite_existing:
            # UPDATE MODE: Policy exists, only patch/update existing files
            # DO NOT regenerate Rego code - preserve existing logic
            print(f"[DEBUG] 📝 UPDATE MODE: Patching existing policy '{spec.policy_type}'")
            
            try:
                ct_content = self._patch_existing_template(ct_file, spec, user_prompt)
                constraint_content = self._patch_existing_constraint(constraint_file, spec, user_prompt)
            except FileNotFoundError as e:
                print(f"[DEBUG] ⚠️ {e}")
                print(f"[DEBUG] 🔄 Falling back to CREATE MODE")
                policy_exists = False
                # Fall through to CREATE mode below
        
        if not (policy_exists and merge_existing and not overwrite_existing):
            # CREATE/OVERWRITE MODE: Generate new policy with LLM
            print(f"[DEBUG] 🆕 CREATE MODE: Generating new policy '{spec.policy_type}'")
            
        llm_result = {}
        validator = LLMValidator(self.llm_client)
        max_retries = 3
        attempt = 0
        current_prompt = user_prompt or spec.description
        
        if self.use_llm and self.llm_client:
            while attempt < max_retries:
                attempt += 1
                print(f"[DEBUG] 🤖 Calling LLM (Attempt {attempt}/{max_retries}) for: {spec.policy_type}")
                try:
                    llm_result = self.llm_client.generate_policy(current_prompt, spec.to_dict())
                    
                    # Render content for validation
                    ct_content_temp = self._render_template(spec, llm_result)
                    constraint_content_temp = self._render_constraint(spec, llm_result)
                    
                    # Validate
                    print(f"[DEBUG] 🔍 Validating attempt {attempt}...")
                    validation_result = validator.validate(
                        template_path="dummy", 
                        constraint_path="dummy",
                        user_prompt=user_prompt,
                        policy_spec=spec.to_dict(),
                        template_content=ct_content_temp,
                        constraint_content=constraint_content_temp
                    )
                    
                    # Accept if valid and score >= 70 (lowered from 80 for more flexibility)
                    # Or if score >= 60 and no critical errors (schema/rego syntax errors)
                    critical_errors = [e for e in validation_result.errors if any(keyword in e.lower() for keyword in ["schema", "syntax", "compile", "invalid", "nested"])]
                    
                    if validation_result.valid and validation_result.score >= 70:
                        print(f"[DEBUG] ✅ Validation passed (Score: {validation_result.score})")
                        break
                    elif validation_result.score >= 60 and not critical_errors:
                        print(f"[DEBUG] ✅ Validation passed (Score: {validation_result.score}, no critical errors)")
                        break
                    
                    print(f"[DEBUG] ⚠️ Validation failed (Score: {validation_result.score})")
                    print(f"[DEBUG]   Errors: {validation_result.errors}")
                    print(f"[DEBUG]   Warnings: {validation_result.warnings}")
                    
                    # Prepare for retry with detailed feedback
                    error_msg = "\n".join(validation_result.errors[:5])  # Limit to first 5 errors
                    warning_msg = "\n".join(validation_result.warnings[:3])  # Limit to first 3 warnings
                    feedback = f"Errors:\n{error_msg}"
                    if warning_msg:
                        feedback += f"\n\nWarnings:\n{warning_msg}"
                    
                    current_prompt = f"{user_prompt}\n\nPREVIOUS ATTEMPT FAILED (Score: {validation_result.score}):\n{feedback}\n\nPlease fix ALL errors. Follow the prompt rules exactly. Return ONLY valid JSON."
                    
                except Exception as e:
                    print(f"[DEBUG] ⚠️ LLM generation failed: {e}")
                    if attempt == max_retries:
                        break

            ct_content = self._render_template(spec, llm_result)
            constraint_content = self._render_constraint(spec, llm_result)
        
        # Write files
        ct_file.write_text(ct_content)
        constraint_file.write_text(constraint_content)
        
        return {
            "template": str(ct_file),
            "constraint": str(constraint_file),
        }
    
    def _render_template(self, spec: PolicySpec, llm_result: Dict) -> str:
        """Render ConstraintTemplate YAML"""
        kind = self._to_pascal(spec.policy_type)
        
        # Generate template name: lowercase of Kind with NO hyphens (Gatekeeper requirement)
        template_name = kind.lower()
        
        # Get Rego code
        rego = llm_result.get("rego", "")
        if rego:
            rego = self._normalize_rego_text(rego)
            # Fix package name to match metadata.name (lowercase, no hyphens)
            expected_package = template_name  # template_name is already lowercase, no hyphens
            # Extract current package name from Rego
            import re
            package_match = re.search(r'^package\s+(\S+)', rego, re.MULTILINE)
            if package_match:
                current_package = package_match.group(1)
                if current_package != expected_package:
                    print(f"[DEBUG] 🔧 Fixing package name: {current_package} → {expected_package}")
                    rego = re.sub(r'^package\s+\S+', f'package {expected_package}', rego, flags=re.MULTILINE)
            else:
                # No package declaration found, add it
                print(f"[DEBUG] 🔧 Adding missing package declaration: {expected_package}")
                rego = f"package {expected_package}\n\n{rego}"
            print(f"[DEBUG] ✅ Using LLM-generated Rego ({len(rego)} chars)")
        else:
            print("[DEBUG] ⚠️ LLM returned empty rego, using generic fallback")
            rego = f"package {template_name}\n\nviolation[{{\"msg\": msg}}] {{\n  msg := \"Policy logic not implemented\"\n}}"

        # Get Schema
        schema_json = llm_result.get("schema", {})
        schema = {}
        
        if schema_json:
            try:
                schema_data = json.loads(schema_json) if isinstance(schema_json, str) else schema_json
                if isinstance(schema_data, dict):
                    # Fix nested openAPIV3Schema issue (common LLM mistake)
                    if "openAPIV3Schema" in schema_data:
                        inner_schema = schema_data["openAPIV3Schema"]
                        # Check if it's nested again (double nested)
                        if isinstance(inner_schema, dict) and "openAPIV3Schema" in inner_schema:
                            print("[DEBUG] 🔧 Fixing double-nested openAPIV3Schema")
                            schema = inner_schema["openAPIV3Schema"]
                        else:
                            schema = inner_schema
                    elif "type" in schema_data and "properties" in schema_data:
                        schema = schema_data
                    elif "parameters" in schema_data:
                        schema = {"type": "object", "properties": {"parameters": schema_data["parameters"]}}
                    elif schema_data.get("properties", {}).get("parameters"):
                        schema = schema_data
                    else:
                        schema = schema_data # Best effort
                
                # Validate and fix schema structure
                schema = self._fix_schema_structure(schema)
                print(f"[DEBUG] ✅ Using LLM-generated schema (fixed)")
            except Exception as e:
                print(f"[DEBUG] ⚠️ Schema parsing failed: {e}")
                import traceback
                traceback.print_exc()
        
        if not schema:
            print("[DEBUG] ⚠️ Using generic fallback schema")
            schema = {"type": "object", "properties": {}}

        # Generate template name: lowercase of Kind with NO hyphens (Gatekeeper requirement)
        template_name = kind.lower()

        ct = {
            "apiVersion": "templates.gatekeeper.sh/v1",
            "kind": "ConstraintTemplate",
            "metadata": {
                "name": template_name,
                "annotations": {
                    "argocd.argoproj.io/sync-wave": "-1",
                },
            },
            "spec": {
                "crd": {
                    "spec": {
                        "names": {
                            "kind": kind,
                        },
                        "validation": {
                            "legacySchema": False,
                            "openAPIV3Schema": schema,
                        },
                    },
                },
                "targets": [
                    {
                        "target": "admission.k8s.gatekeeper.sh",
                        "rego": LiteralString(rego),
                    }
                ],
            },
        }
        
        return yaml.dump(ct, sort_keys=False, default_flow_style=False)
    
    def _render_constraint(self, spec: PolicySpec, llm_result: Dict) -> str:
        """Render Constraint YAML"""
        kind = self._to_pascal(spec.policy_type)
        
        excluded = spec.namespaces.exclude or ["kube-system", "gatekeeper-system"]
        
        # Get Constraint Spec
        constraint_spec = None
        spec_json = llm_result.get("constraint_spec", {})
        
        if spec_json:
            try:
                constraint_spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
                print(f"[DEBUG] ✅ Using LLM-generated constraint spec")
                
                # Normalize match section: fix invalid fields BEFORE merging parameters
                match_section = constraint_spec.get("match", {})
                if match_section:
                    # Remove invalid 'namespaces' field (Gatekeeper uses excludedNamespaces, not namespaces)
                    if "namespaces" in match_section:
                        namespaces_val = match_section.pop("namespaces")
                        # If it was an object with exclude/include, convert to excludedNamespaces
                        if isinstance(namespaces_val, dict):
                            if "exclude" in namespaces_val:
                                excluded_list = namespaces_val["exclude"]
                                if isinstance(excluded_list, list):
                                    existing_excluded = match_section.get("excludedNamespaces", [])
                                    if isinstance(existing_excluded, list):
                                        match_section["excludedNamespaces"] = list(set(existing_excluded + excluded_list))
                                    else:
                                        match_section["excludedNamespaces"] = excluded_list
                                else:
                                    match_section["excludedNamespaces"] = excluded
                            else:
                                match_section["excludedNamespaces"] = excluded
                        print(f"[DEBUG] ⚠️ Removed invalid 'namespaces' field from match section")
                    
                    # Ensure excludedNamespaces is an array (not object or string)
                    if "excludedNamespaces" in match_section:
                        excluded_ns = match_section["excludedNamespaces"]
                        if not isinstance(excluded_ns, list):
                            if isinstance(excluded_ns, str):
                                match_section["excludedNamespaces"] = [excluded_ns]
                            elif isinstance(excluded_ns, dict):
                                # If it's an object, try to extract exclude array
                                if "exclude" in excluded_ns and isinstance(excluded_ns["exclude"], list):
                                    match_section["excludedNamespaces"] = excluded_ns["exclude"]
                                else:
                                    match_section["excludedNamespaces"] = excluded
                            else:
                                match_section["excludedNamespaces"] = excluded
                            print(f"[DEBUG] ⚠️ Fixed excludedNamespaces to be an array")
                    
                    # Normalize kinds: convert strings to proper objects with apiGroups
                    if "kinds" in match_section:
                        kinds = match_section["kinds"]
                        if isinstance(kinds, list):
                            normalized_kinds = []
                            for kind_item in kinds:
                                if isinstance(kind_item, str):
                                    # Convert string to proper structure
                                    if kind_item == "Pod":
                                        normalized_kinds.append({"apiGroups": [""], "kinds": [kind_item]})
                                    elif kind_item in ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"]:
                                        normalized_kinds.append({"apiGroups": ["apps"], "kinds": [kind_item]})
                                    else:
                                        # Default to apps group for other workload resources
                                        normalized_kinds.append({"apiGroups": ["apps"], "kinds": [kind_item]})
                                elif isinstance(kind_item, dict):
                                    # Already structured, but ensure apiGroups is a list
                                    if "apiGroups" in kind_item:
                                        if not isinstance(kind_item["apiGroups"], list):
                                            kind_item["apiGroups"] = [kind_item["apiGroups"]]
                                    elif "kinds" in kind_item:
                                        # Has kinds but no apiGroups, infer from kind
                                        kind_names = kind_item["kinds"] if isinstance(kind_item["kinds"], list) else [kind_item["kinds"]]
                                        if "Pod" in kind_names:
                                            kind_item["apiGroups"] = [""]
                                        else:
                                            kind_item["apiGroups"] = ["apps"]
                                    normalized_kinds.append(kind_item)
                            match_section["kinds"] = normalized_kinds
                            print(f"[DEBUG] ⚠️ Normalized kinds to proper object format")
                    
                    constraint_spec["match"] = match_section
                else:
                    # LLM didn't provide match section, create default
                    print("[DEBUG] ⚠️ LLM constraint spec missing match section, creating default")
                    match_section = {}
                
                # Ensure enforcementAction exists
                if "enforcementAction" not in constraint_spec:
                    constraint_spec["enforcementAction"] = spec.enforcement.value
                    print(f"[DEBUG] ⚠️ Added missing enforcementAction: {spec.enforcement.value}")
                
                # Ensure match section exists with proper structure
                if not match_section or "kinds" not in match_section:
                    print("[DEBUG] ⚠️ Creating default match section")
                    # Build proper match.kinds structure with apiGroups
                    kinds_list = []
                    core_kinds = []
                    apps_kinds = []
                    batch_kinds = []
                    
                    for target_kind in spec.target_kinds:
                        if target_kind == "Pod":
                            core_kinds.append(target_kind)
                        elif target_kind in ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"]:
                            apps_kinds.append(target_kind)
                        elif target_kind in ["Job", "CronJob"]:
                            batch_kinds.append(target_kind)
                        else:
                            apps_kinds.append(target_kind)
                    
                    if core_kinds:
                        kinds_list.append({"apiGroups": [""], "kinds": core_kinds})
                    if apps_kinds:
                        kinds_list.append({"apiGroups": ["apps"], "kinds": apps_kinds})
                    if batch_kinds:
                        kinds_list.append({"apiGroups": ["batch"], "kinds": batch_kinds})
                    
                    match_section = {
                        "kinds": kinds_list,
                        "excludedNamespaces": excluded,
                    }
                    constraint_spec["match"] = match_section
                
                # IMPORTANT: Merge user-requested parameters into LLM-generated spec
                # The LLM may not include parameters from the user's update request
                if spec.parameters:
                    llm_params = constraint_spec.get("parameters", {})
                    if isinstance(llm_params, dict):
                        # Merge spec.parameters into LLM-generated parameters
                        for key, value in spec.parameters.items():
                            if key not in llm_params:
                                llm_params[key] = value
                            elif isinstance(llm_params[key], list) and isinstance(value, list):
                                # Merge lists without duplicates
                                for item in value:
                                    if item not in llm_params[key]:
                                        llm_params[key].append(item)
                        constraint_spec["parameters"] = llm_params
                    else:
                        constraint_spec["parameters"] = spec.parameters
                    print(f"[DEBUG] ✅ Merged user parameters: {spec.parameters}")
                elif "parameters" not in constraint_spec:
                    constraint_spec["parameters"] = spec.parameters or {}
            except Exception as e:
                print(f"[DEBUG] ⚠️ Constraint spec parsing failed: {e}")
                import traceback
                traceback.print_exc()

        if not constraint_spec:
            print("[DEBUG] ⚠️ Using generic fallback constraint spec")
            # Build proper match.kinds structure with apiGroups
            kinds_list = []
            # Group kinds by apiGroup
            core_kinds = []
            apps_kinds = []
            batch_kinds = []
            
            for target_kind in spec.target_kinds:
                if target_kind == "Pod":
                    core_kinds.append(target_kind)
                elif target_kind in ["Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"]:
                    apps_kinds.append(target_kind)
                elif target_kind in ["Job", "CronJob"]:
                    batch_kinds.append(target_kind)
                else:
                    # Default to apps group for other workload resources
                    apps_kinds.append(target_kind)
            
            # Add grouped kinds to kinds_list
            if core_kinds:
                kinds_list.append({
                    "apiGroups": [""],
                    "kinds": core_kinds
                })
            if apps_kinds:
                kinds_list.append({
                    "apiGroups": ["apps"],
                    "kinds": apps_kinds
                })
            if batch_kinds:
                kinds_list.append({
                    "apiGroups": ["batch"],
                    "kinds": batch_kinds
                })
            
            constraint_spec = {
                "enforcementAction": spec.enforcement.value,
                "match": {
                    "kinds": kinds_list,
                    "excludedNamespaces": excluded,
                },
                "parameters": spec.parameters,
            }
        
        # Generate constraint name: lowercase of Kind with NO hyphens (Gatekeeper requirement)
        constraint_name = kind.lower()
        
        constraint = {
            "apiVersion": "constraints.gatekeeper.sh/v1beta1",
            "kind": kind,
            "metadata": {
                "name": constraint_name,
                "annotations": {
                    "argocd.argoproj.io/sync-wave": "0",
                    "argocd.argoproj.io/sync-options": "SkipDryRunOnMissingResource=true",
                },
            },
            "spec": constraint_spec,
        }
        
        return yaml.dump(constraint, sort_keys=False, default_flow_style=False)

    def _normalize_rego_text(self, text: str) -> str:
        """Normalize Rego text: handle escapes and strip trailing whitespace."""
        if not isinstance(text, str):
            return ""
        
        # 1. Handle literal escapes (LLM sometimes double-escapes)
        text = text.replace("\\r\\n", "\n").replace("\\r", "\n").replace("\\n", "\n").replace("\\t", "\t")
        
        # 2. Handle actual carriage returns
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        
        # 3. Strip trailing whitespace from each line (Crucial for YAML block style)
        lines = [line.rstrip() for line in text.split("\n")]
        text = "\n".join(lines)
        
        # 4. Ensure it ends with a newline
        if text and not text.endswith("\n"):
            text += "\n"
            
        return text

    def _ensure_literal_rego_block(self, yaml_content: str) -> str:
        """
        Ensure the rego field uses YAML literal block style so formatting matches the base files.
        """
        try:
            data = yaml.safe_load(yaml_content) or {}
        except yaml.YAMLError:
            return yaml_content

        spec = data.get("spec", {})
        targets = spec.get("targets", [])
        if targets:
            rego_val = targets[0].get("rego")
            if isinstance(rego_val, str) and not isinstance(rego_val, LiteralString):
                targets[0]["rego"] = LiteralString(self._normalize_rego_text(rego_val))

        return yaml.dump(data, sort_keys=False, default_flow_style=False)

    def _recursive_update(self, d: dict, u: dict) -> dict:
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._recursive_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def _patch_existing_template(self, template_path: Path, spec: 'PolicySpec', user_prompt: str) -> str:
        """
        UPDATE MODE: Patch existing ConstraintTemplate.
        - If new parameters are added, update both schema AND Rego code to use them
        - For CONFIG updates (namespace exemption, etc.) - only update constraint, not template
        """
        if not template_path.exists():
            raise FileNotFoundError(
                f"Cannot update policy because existing artifacts were not found:\n"
                f"  - {template_path}"
            )
        
        print(f"[DEBUG] 📝 Patching existing template: {template_path.name}")
        
        existing_content = template_path.read_text()
        existing_yaml = yaml.safe_load(existing_content) or {}
        
        # Get existing Rego code
        targets = existing_yaml.get("spec", {}).get("targets", [])
        existing_rego = ""
        if targets and "rego" in targets[0]:
            existing_rego = targets[0]["rego"]
        
        # Get existing schema properties
        existing_schema = (
            existing_yaml.get("spec", {})
            .get("crd", {})
            .get("spec", {})
            .get("validation", {})
            .get("openAPIV3Schema", {})
        )
        existing_properties = existing_schema.get("properties", {})
        
        # Check if we have new parameters that need Rego code updates
        new_parameters = {}
        if spec.parameters:
            for param_name, param_value in spec.parameters.items():
                if param_name not in existing_properties:
                    new_parameters[param_name] = param_value
        
        # If we have new parameters, we MUST update Rego code to use them
        if new_parameters:
            print(f"[DEBUG] 🔄 New parameters detected: {list(new_parameters.keys())}")
            print(f"[DEBUG] 📝 Updating Rego code to use new parameters...")
            
            # Use LLM to update Rego code with new parameters
            if self.use_llm and self.llm_client:
                try:
                    # Create a prompt to update Rego code
                    update_prompt = (
                        f"Update the following Rego code to use the new parameter(s): {list(new_parameters.keys())}\n\n"
                        f"Existing Rego code:\n```rego\n{existing_rego}\n```\n\n"
                        f"New parameters to add:\n{json.dumps(new_parameters, indent=2)}\n\n"
                        f"User request: {user_prompt}\n\n"
                        f"IMPORTANT: Add logic to check and use the new parameter(s) in the Rego code. "
                        f"For example, if 'exemptImages' is added, add logic to exempt containers with images matching the exemptImages list."
                    )
                    
                    # Try AI patching first - this should update Rego code
                    patch_ops = self._generate_patch_with_llm(existing_content, update_prompt)
                    if patch_ops:
                        print(f"[DEBUG] 🔍 Generated Patch Ops: {json.dumps(patch_ops, indent=2)}")
                        patched_content = self._apply_patch(existing_content, patch_ops)
                        if patched_content != existing_content:
                            try:
                                patched_yaml = yaml.safe_load(patched_content)
                                # Verify Rego was updated
                                patched_targets = patched_yaml.get("spec", {}).get("targets", [])
                                if patched_targets and "rego" in patched_targets[0]:
                                    patched_rego = patched_targets[0]["rego"]
                                    # Check if Rego mentions new parameters
                                    params_mentioned = all(
                                        param_name.lower() in patched_rego.lower() 
                                        for param_name in new_parameters.keys()
                                    )
                                    if params_mentioned or len(patched_rego) > len(existing_rego):
                                        print(f"[DEBUG] ✅ Rego code updated with new parameters")
                                        yaml.safe_load(patched_content)  # Validate YAML
                                        return patched_content
                                    else:
                                        print(f"[DEBUG] ⚠️ Rego code may not have been updated properly")
                            except yaml.YAMLError as ye:
                                print(f"[DEBUG] ⚠️ AI Patch resulted in invalid YAML: {ye}")
                    
                    # If AI patching didn't work, try to update Rego manually using LLM
                    print(f"[DEBUG] 🔄 Attempting to update Rego code directly...")
                    from mcp_bot.llm.client import LLMRouter
                    llm_client = LLMRouter.get_client()
                    if llm_client:
                        # Generate updated Rego code
                        rego_prompt = (
                            f"Update this Rego code to add support for new parameters: {list(new_parameters.keys())}\n\n"
                            f"Existing Rego:\n```rego\n{existing_rego}\n```\n\n"
                            f"New parameters: {json.dumps(new_parameters, indent=2)}\n\n"
                            f"User request: {user_prompt}\n\n"
                            f"Return ONLY the updated Rego code, no explanations."
                        )
                        try:
                            updated_rego = llm_client.generate_text(rego_prompt)
                            # Clean up response (remove markdown code blocks if any)
                            import re
                            rego_match = re.search(r'```(?:rego)?\s*(.*?)\s*```', updated_rego, re.DOTALL)
                            if rego_match:
                                updated_rego = rego_match.group(1)
                            updated_rego = updated_rego.strip()
                            
                            if updated_rego and len(updated_rego) > len(existing_rego):
                                # Update Rego in YAML
                                if targets:
                                    targets[0]["rego"] = LiteralString(self._normalize_rego_text(updated_rego))
                                    print(f"[DEBUG] ✅ Rego code updated directly")
                                else:
                                    print(f"[DEBUG] ⚠️ No targets found in template")
                        except Exception as e:
                            print(f"[DEBUG] ⚠️ Failed to update Rego directly: {e}")
                            
                except Exception as e:
                    print(f"[DEBUG] ⚠️ AI Patching failed: {e}")
        
        # Try AI patching for other updates (non-parameter changes)
        if self.use_llm and self.llm_client:
            try:
                patch_ops = self._generate_patch_with_llm(existing_content, user_prompt)
                if patch_ops:
                    print(f"[DEBUG] 🔍 Generated Patch Ops: {json.dumps(patch_ops, indent=2)}")
                    patched_content = self._apply_patch(existing_content, patch_ops)
                    if patched_content != existing_content:
                        try:
                            yaml.safe_load(patched_content)
                            print(f"[DEBUG] ✅ AI Patch applied successfully")
                            return patched_content
                        except yaml.YAMLError as ye:
                            print(f"[DEBUG] ⚠️ AI Patch resulted in invalid YAML: {ye}")
                else:
                    print(f"[DEBUG] ℹ️ No patch generated by AI.")
            except Exception as e:
                print(f"[DEBUG] ⚠️ AI Patching failed: {e}")
        
        # Fallback: Only update schema if spec has new parameters
        if not spec.parameters:
            print(f"[DEBUG] ℹ️ No parameters to add, keeping template unchanged")
            return existing_content
        
        # Only if we need to add schema properties
        print(f"[DEBUG] 📝 Adding new parameters to schema: {list(spec.parameters.keys())}")
        
        # Preserve Rego as LiteralString
        if targets and "rego" in targets[0]:
            rego_text = targets[0]["rego"]
            if isinstance(rego_text, str):
                targets[0]["rego"] = LiteralString(self._normalize_rego_text(rego_text))
        
        schema = (
            existing_yaml.setdefault("spec", {})
            .setdefault("crd", {})
            .setdefault("spec", {})
            .setdefault("validation", {})
            .setdefault("openAPIV3Schema", {})
        )
        properties = schema.setdefault("properties", {})
        
        # Add schema properties for new parameters
        for param_name, param_value in spec.parameters.items():
            if param_name not in properties:
                if isinstance(param_value, list):
                    properties[param_name] = {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": f"Parameter {param_name} for policy."
                    }
                elif isinstance(param_value, bool):
                    properties[param_name] = {"type": "boolean"}
                elif isinstance(param_value, int):
                    properties[param_name] = {"type": "integer"}
                elif isinstance(param_value, str):
                    properties[param_name] = {"type": "string"}
                else:
                    properties[param_name] = {"type": "object"}
                print(f"[DEBUG] ✅ Added schema property: {param_name}")
        
        return yaml.dump(existing_yaml, sort_keys=False, default_flow_style=False, allow_unicode=True)

    def _patch_existing_constraint(self, constraint_path: Path, spec: 'PolicySpec', user_prompt: str) -> str:
        """
        UPDATE MODE: Patch existing Constraint file.
        Only updates parameters, namespaces, enforcement - NOT structure.
        """
        if not constraint_path.exists():
            raise FileNotFoundError(
                f"Cannot update policy because existing artifacts were not found:\n"
                f"  - {constraint_path}"
            )
        
        print(f"[DEBUG] 📝 Patching existing constraint: {constraint_path.name}")
        
        existing_content = constraint_path.read_text()
        existing_yaml = yaml.safe_load(existing_content) or {}
        
        # Try AI patching first
        if self.use_llm and self.llm_client:
            try:
                patch_ops = self._generate_patch_with_llm(existing_content, user_prompt)
                if patch_ops:
                    print(f"[DEBUG] 🔍 Generated Patch Ops: {json.dumps(patch_ops, indent=2)}")
                    patched_content = self._apply_patch(existing_content, patch_ops)
                    if patched_content != existing_content:
                        try:
                            yaml.safe_load(patched_content)
                            print(f"[DEBUG] ✅ AI Patch applied successfully")
                            return patched_content
                        except yaml.YAMLError as ye:
                            print(f"[DEBUG] ⚠️ AI Patch resulted in invalid YAML: {ye}")
                else:
                    print(f"[DEBUG] ℹ️ No patch generated by AI.")
            except Exception as e:
                print(f"[DEBUG] ⚠️ AI Patching failed: {e}")

        # Fallback: Manually update specific fields
        existing_spec = existing_yaml.setdefault("spec", {})
        
        # Update parameters - MERGE not replace
        if spec.parameters:
            print(f"[DEBUG] 📝 Merging parameters: {spec.parameters}")
            existing_params = existing_spec.setdefault("parameters", {})
            for key, value in spec.parameters.items():
                if key in existing_params:
                    existing_value = existing_params[key]
                    # Merge lists without duplicates
                    if isinstance(existing_value, list) and isinstance(value, list):
                        merged = list(existing_value)
                        for item in value:
                            if item not in merged:
                                merged.append(item)
                        existing_params[key] = merged
                        print(f"[DEBUG] ✅ Merged list parameter: {key}")
                    else:
                        existing_params[key] = value
                        print(f"[DEBUG] ✅ Updated parameter: {key}")
                else:
                    existing_params[key] = value
                    print(f"[DEBUG] ✅ Added new parameter: {key}")
        
        # Update excluded namespaces - MERGE not replace
        if spec.namespaces.exclude:
            existing_match = existing_spec.setdefault("match", {})
            existing_excluded = existing_match.get("excludedNamespaces", [])
            if not isinstance(existing_excluded, list):
                existing_excluded = []
            existing_excluded_set = set(existing_excluded)
            new_excluded = set(spec.namespaces.exclude)
            merged_excluded = existing_excluded_set | new_excluded
            if merged_excluded != existing_excluded_set:
                existing_match["excludedNamespaces"] = sorted(list(merged_excluded))
                print(f"[DEBUG] ✅ Merged excludedNamespaces: {sorted(merged_excluded)}")

        return yaml.dump(existing_yaml, sort_keys=False, default_flow_style=False, allow_unicode=True)

    def _generate_patch_with_llm(self, content: str, request: str) -> list:
        """Generate patch operations using LLM"""
        if not self.use_llm or not self.llm_client:
            return []
        
        prompt_file = Path(__file__).parent.parent / "llm" / "prompts" / "file_patch.txt"
        if prompt_file.exists():
            template = prompt_file.read_text(encoding="utf-8")
        else:
            return []
            
        full_prompt = template.format(file_content=content, user_request=request)
        
        try:
            # Use the centralized client method
            text = self.llm_client.generate_text(full_prompt)

            # Parse JSON
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
            else:
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    text = json_match.group(0)
            
            data = json.loads(text)
            return data.get("edits", [])
        except Exception as e:
            print(f"[DEBUG] Patch generation error: {e}")
            return []

    def _apply_patch(self, content: str, edits: list) -> str:
        """
        Apply list of edits to content.
        For YAML files, prefer YAML manipulation over string replacement to preserve formatting.
        """
        # Try to parse as YAML first - if successful, use YAML manipulation
        try:
            yaml_data = yaml.safe_load(content)
            if yaml_data is not None:
                # Use YAML manipulation for better formatting
                return self._apply_patch_yaml(content, yaml_data, edits)
        except yaml.YAMLError:
            pass
        
        # Fallback to string replacement for non-YAML or if YAML parsing fails
        current_content = content
        
        for edit in edits:
            action = edit.get("action")
            target = edit.get("target")
            replacement = edit.get("content", "")
            
            if not target:
                continue
                
            if action == "replace":
                if target in current_content:
                    current_content = current_content.replace(target, replacement, 1)
                else:
                    print(f"[DEBUG] ⚠️ Target not found for replace: {target[:20]}...")
            
            elif action == "insert_after":
                if target in current_content:
                    # Normalize replacement indentation
                    replacement = replacement.strip()
                    # Find indentation of target line
                    lines = current_content.split('\n')
                    for i, line in enumerate(lines):
                        if target in line:
                            # Get indentation of target line
                            indent = len(line) - len(line.lstrip())
                            # Apply same indentation to replacement
                            replacement_indented = ' ' * indent + replacement
                            # Insert after target line
                            lines.insert(i + 1, replacement_indented)
                            current_content = '\n'.join(lines)
                            break
                else:
                    print(f"[DEBUG] ⚠️ Target not found for insert_after: {target[:20]}...")
            
            elif action == "delete":
                if target in current_content:
                    current_content = current_content.replace(target, "", 1)
        
        return current_content
    
    def _apply_patch_yaml(self, original_content: str, yaml_data: dict, edits: list) -> str:
        """
        Apply patches using YAML manipulation for better formatting.
        This preserves YAML structure and indentation.
        """
        # For now, if we have YAML data, we'll still use string replacement
        # but with better indentation handling
        # TODO: Implement proper YAML tree manipulation
        current_content = original_content
        
        for edit in edits:
            action = edit.get("action")
            target = edit.get("target")
            replacement = edit.get("content", "")
            
            if not target:
                continue
            
            if action == "insert_after":
                if target in current_content:
                    # Find the line with target
                    lines = current_content.split('\n')
                    for i, line in enumerate(lines):
                        if target in line:
                            # Get indentation of target line
                            indent = len(line) - len(line.lstrip())
                            # Normalize replacement (remove leading/trailing whitespace)
                            replacement_clean = replacement.strip()
                            # Apply same indentation
                            replacement_indented = ' ' * indent + replacement_clean
                            # Insert after target line
                            lines.insert(i + 1, replacement_indented)
                            current_content = '\n'.join(lines)
                            break
        
        return current_content
    
    def _to_pascal(self, text: str) -> str:
        """Convert kebab-case to PascalCase"""
        return "".join(word.capitalize() for word in text.split("-"))
    
    def _fix_schema_structure(self, schema: Dict) -> Dict:
        """Fix common schema structure issues from LLM generation
        
        Fixes:
        1. Removes nested openAPIV3Schema (double nesting)
        2. Ensures type: object is present
        3. Ensures properties exist
        4. Removes nested spec.parameters wrappers
        """
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        
        # Fix nested openAPIV3Schema (double nesting)
        if "openAPIV3Schema" in schema:
            inner = schema["openAPIV3Schema"]
            if isinstance(inner, dict) and "openAPIV3Schema" in inner:
                print("[DEBUG] 🔧 Fixing double-nested openAPIV3Schema")
                schema = inner["openAPIV3Schema"]
            else:
                schema = inner
        
        # Ensure type and properties exist
        if "type" not in schema:
            schema["type"] = "object"
        
        if "properties" not in schema:
            schema["properties"] = {}
        
        # Remove any nested "spec" or "parameters" wrappers (wrong structure)
        if "properties" in schema:
            props = schema["properties"]
            # Fix: spec.parameters structure (WRONG - should be direct)
            if "spec" in props and isinstance(props["spec"], dict):
                if "properties" in props["spec"] and "parameters" in props["spec"]["properties"]:
                    print("[DEBUG] 🔧 Fixing nested spec.parameters structure")
                    schema["properties"] = props["spec"]["properties"]["parameters"].get("properties", {})
            elif "parameters" in props and isinstance(props["parameters"], dict):
                if "properties" in props["parameters"]:
                    print("[DEBUG] 🔧 Fixing nested parameters structure")
                    schema["properties"] = props["parameters"]["properties"]
        
        # Ensure properties is a dict
        if not isinstance(schema.get("properties"), dict):
            schema["properties"] = {}
        
        return schema
    
    def update_kustomization(self):
        """Update kustomization.yaml to include all generated files
        
        CRITICAL: Templates MUST be listed before constraints so ConstraintTemplates
        are applied first to create CRDs before Constraints reference them.
        """
        kustomization_file = self.base_path / "kustomization.yaml"
        
        resources = []
        if kustomization_file.exists():
            with open(kustomization_file) as f:
                kust = yaml.safe_load(f) or {}
                resources = kust.get("resources") or []
                if not isinstance(resources, list):
                    resources = []
        
        # Separate existing resources into templates and constraints
        existing_templates = []
        existing_constraints = []
        existing_other = []
        
        for res in resources:
            if res.startswith("templates/"):
                existing_templates.append(res)
            elif res.startswith("constraints/"):
                existing_constraints.append(res)
            else:
                existing_other.append(res)
        
        # Add template files (sorted)
        template_paths = []
        for tmpl in sorted(self.templates_dir.glob("*.yaml")):
            rel_path = f"templates/{tmpl.name}"
            if rel_path not in existing_templates:
                template_paths.append(rel_path)
        
        # Add constraint files (sorted)
        constraint_paths = []
        for constraint in sorted(self.constraints_dir.glob("*.yaml")):
            rel_path = f"constraints/{constraint.name}"
            if rel_path not in existing_constraints:
                constraint_paths.append(rel_path)
        
        # Combine: other resources, then templates (sorted), then constraints (sorted)
        # This ensures templates are applied BEFORE constraints
        all_resources = (
            existing_other +
            sorted(existing_templates + template_paths) +
            sorted(existing_constraints + constraint_paths)
        )
        
        # Write back
        kustomization = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": all_resources,
        }
        
        kustomization_file.write_text(yaml.dump(kustomization, sort_keys=False))
