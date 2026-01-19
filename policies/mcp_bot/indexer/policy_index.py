"""Policy Indexer: Index existing templates and retrieve candidates"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class PolicyMetadata:
    """Metadata for a ConstraintTemplate/Constraint"""
    def __init__(
        self,
        kind: str,
        template_path: str,
        constraint_path: Optional[str] = None,
        parameters: Optional[Dict] = None,
        enforcement: str = "dryrun",
        target_kinds: Optional[List[str]] = None,
    ):
        self.kind = kind
        self.template_path = template_path
        self.constraint_path = constraint_path
        self.parameters = parameters or {}
        self.enforcement = enforcement
        self.target_kinds = target_kinds or []
    
    def to_dict(self) -> Dict:
        return {
            "kind": self.kind,
            "template_path": self.template_path,
            "constraint_path": self.constraint_path,
            "parameters": self.parameters,
            "enforcement": self.enforcement,
            "target_kinds": self.target_kinds,
        }


class PolicyIndex:
    """Index and retrieve existing Gatekeeper policies"""
    
    def __init__(self, base_path: str = "policies"):
        self.base_path = Path(base_path)
        self.index: Dict[str, PolicyMetadata] = {}
        self._scan_policies()
    
    def _scan_policies(self):
        """Scan repository for existing policies"""
        templates_dir = self.base_path / "templates"
        constraints_dir = self.base_path / "constraints"
        
        if not templates_dir.exists():
            return
        
        # Scan templates
        for tmpl_file in templates_dir.glob("*.yaml"):
            try:
                with open(tmpl_file) as f:
                    tmpl = yaml.safe_load(f)
                    if not tmpl or tmpl.get("kind") != "ConstraintTemplate":
                        continue
                    
                    kind = tmpl["spec"]["crd"]["spec"]["names"]["kind"]
                    
                    # Find matching constraint
                    constraint_path = None
                    constraint_file = constraints_dir / tmpl_file.name.replace("-template", "-constraint")
                    if constraint_file.exists():
                        with open(constraint_file) as cf:
                            constraint = yaml.safe_load(cf)
                            if constraint and constraint.get("kind") == kind:
                                constraint_path = str(constraint_file)
                                enforcement = constraint.get("spec", {}).get("enforcementAction", "dryrun")
                                
                                # Extract target kinds
                                match = constraint.get("spec", {}).get("match", {})
                                kinds = match.get("kinds", [])
                                target_kinds = []
                                for k in kinds:
                                    target_kinds.extend(k.get("kinds", []))
                            else:
                                enforcement = "dryrun"
                                target_kinds = []
                    else:
                        enforcement = "dryrun"
                        target_kinds = []
                    
                    # Extract parameters schema
                    params_schema = tmpl.get("spec", {}).get("crd", {}).get("spec", {}).get("validation", {}).get("openAPIV3Schema", {})
                    params = params_schema.get("properties", {}).get("parameters", {}).get("properties", {})
                    
                    self.index[kind] = PolicyMetadata(
                        kind=kind,
                        template_path=str(tmpl_file),
                        constraint_path=constraint_path,
                        parameters=params,
                        enforcement=enforcement,
                        target_kinds=target_kinds,
                    )
            except Exception as e:
                print(f"Warning: Failed to index {tmpl_file}: {e}")
    
    def retrieve(self, policy_type: str) -> Optional[PolicyMetadata]:
        """Retrieve policy by type (simple keyword matching)"""
        # Map policy_type to kind
        type_to_kind = {
            "nonroot": "CisNonRoot",
            "nolatest": "CisNoLatest",
            "requiredlabels": "K8sRequiredLabels",
            "noprivileged": "CisNoPrivileged",
        }
        
        kind = type_to_kind.get(policy_type)
        if kind and kind in self.index:
            return self.index[kind]
        
        # Fallback: search by similarity
        for k, meta in self.index.items():
            if policy_type.lower() in k.lower() or k.lower() in policy_type.lower():
                return meta
        
        return None
    
    def list_all(self) -> List[PolicyMetadata]:
        """List all indexed policies"""
        return list(self.index.values())
    
    def export_index(self, output_path: str):
        """Export index to JSON for RAG/ML"""
        data = {k: v.to_dict() for k, v in self.index.items()}
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

