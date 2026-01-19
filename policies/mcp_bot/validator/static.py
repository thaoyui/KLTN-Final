"""Static Validation: kubeconform checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
import subprocess
from pathlib import Path
from typing import List, Optional


@dataclass
class ToolCheckResult:
    """Represents the outcome of a single tool/target validation."""

    tool: str
    target: str
    errors: list[str]

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass
class StaticValidationResult:
    """Aggregate result of all static validations."""

    checks: list[ToolCheckResult]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


DEFAULT_K8S_VERSION = os.getenv("KUBECONFORM_VERSION", "1.28.0")


def _normalize_kube_version(version: str) -> str:
    """Ensure kubeconform version is either master or full x.y.z."""

    if not version:
        return DEFAULT_K8S_VERSION
    version = version.strip()
    if version.lower() == "master":
        return "master"
    parts = [p for p in version.split(".") if p]
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:3])


def validate_kubeconform(file_path: str, k8s_version: str = DEFAULT_K8S_VERSION) -> List[str]:
    """
    Validate YAML with kubeconform
    
    Returns:
        List of errors (empty if valid)
    """
    if not Path(file_path).exists():
        return [f"File not found: {file_path}"]
    
    try:
        version = _normalize_kube_version(k8s_version)
        result = subprocess.run(
            ["kubeconform", "-strict", "-kubernetes-version", version, file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return result.stderr.splitlines()
        return []
    except FileNotFoundError:
        return ["kubeconform not installed. Install: brew install yannh/kubeconform/kubeconform"]
    except subprocess.TimeoutExpired:
        return ["kubeconform validation timed out"]


def validate_policy(template_path: str, constraint_path: Optional[str] = None) -> StaticValidationResult:
    """Validate a policy (CT + optional Constraint) and return detailed results."""

    checks: list[ToolCheckResult] = []

    kubeconform_errors = validate_kubeconform(template_path)
    checks.append(ToolCheckResult("kubeconform", template_path, kubeconform_errors))

    if constraint_path:
        kubeconform_errors = validate_kubeconform(constraint_path)
        checks.append(ToolCheckResult("kubeconform", constraint_path, kubeconform_errors))

    return StaticValidationResult(checks=checks)
