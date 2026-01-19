"""PolicySpec DSL Schema for MCP Bot"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PolicyIntent(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    EXPLAIN = "explain"
    AUDIT = "audit"
    WHAT_IF = "what-if"


class EnforcementMode(str, Enum):
    DRYRUN = "dryrun"
    DENY = "deny"
    WARN = "warn"


@dataclass
class NamespaceSelector:
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=lambda: ["kube-system", "gatekeeper-system"])


@dataclass
class PolicySpec:
    """DSL representation of a Gatekeeper policy request"""
    policy_id: str
    policy_type: str  # e.g., "nonroot", "nolatest", "requiredlabels", "noprivileged"
    intent: PolicyIntent = PolicyIntent.CREATE
    description: str = ""
    
    # Scope
    target_kinds: List[str] = field(default_factory=lambda: ["Pod", "Deployment", "StatefulSet"])
    namespaces: NamespaceSelector = field(default_factory=NamespaceSelector)
    
    # Enforcement
    enforcement: EnforcementMode = EnforcementMode.DRYRUN
    
    # Parameters (policy-specific)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    references: List[str] = field(default_factory=list)
    locale: Optional[str] = None
    update_type: str = "HYBRID" # CONFIG, LOGIC, HYBRID
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON/YAML"""
        return {
            "policy_id": self.policy_id,
            "policy_type": self.policy_type,
            "intent": self.intent.value,
            "description": self.description,
            "target_kinds": self.target_kinds,
            "namespaces": {
                "include": self.namespaces.include,
                "exclude": self.namespaces.exclude,
            },
            "enforcement": self.enforcement.value,
            "parameters": self.parameters,
            "references": self.references,
            "locale": self.locale,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PolicySpec:
        """Deserialize from dict"""
        ns = data.get("namespaces", {})
        intent_raw = str(data.get("intent", "create")).lower()
        try:
            intent = PolicyIntent(intent_raw)
        except ValueError:
            intent = INTENT_SYNONYMS.get(intent_raw, PolicyIntent.CREATE)

        return cls(
            policy_id=data["policy_id"],
            policy_type=data["policy_type"],
            intent=intent,
            description=data.get("description", ""),
            target_kinds=data.get("target_kinds", []),
            namespaces=NamespaceSelector(
                include=ns.get("include", []),
                exclude=ns.get("exclude", ["kube-system", "gatekeeper-system"]),
            ),
            enforcement=EnforcementMode(data.get("enforcement", "dryrun")),
            parameters=data.get("parameters", {}),
            references=data.get("references", []),
            locale=data.get("locale"),
            update_type=data.get("update_type", "HYBRID"),
        )


INTENT_SYNONYMS = {
    "deny": PolicyIntent.CREATE,
    "prevent": PolicyIntent.CREATE,
    "block": PolicyIntent.CREATE,
    "forbid": PolicyIntent.CREATE,
    "ban": PolicyIntent.CREATE,
    "stop": PolicyIntent.CREATE,
}
