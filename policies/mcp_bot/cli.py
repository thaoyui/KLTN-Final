#!/usr/bin/env python3
"""MCP Bot CLI: ./mcp \"<policy request>\" """
from __future__ import annotations

import os
import sys
from datetime import datetime
import json
from pathlib import Path
import yaml

# Add project root to path
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

# Check critical dependencies
try:
    from github import Github
except ImportError:
    print("⚠️  Warning: PyGithub not installed. Install with: pip3 install PyGithub", file=sys.stderr)
    print("   Or run: ./install_deps.sh", file=sys.stderr)

try:
    from mcp_bot.generator.templates import PolicyGenerator, LiteralString
    from mcp_bot.git.pr import GitRepo, create_pr
    from mcp_bot.router.intent import parse_request
    from mcp_bot.validator.static import StaticValidationResult, validate_policy
    from mcp_bot.validator.llm_validation import LLMValidator
    from mcp_bot.schemas.policyspec import PolicyIntent
except ImportError:
    # Fallback to relative imports if run as module
    from .generator.templates import PolicyGenerator, LiteralString
    from .git.pr import GitRepo, create_pr
    from .router.intent import parse_request
    from .validator.static import StaticValidationResult, validate_policy
    from .validator.llm_validation import LLMValidator
    from .schemas.policyspec import PolicyIntent


MIN_LLM_SCORE = int(os.getenv("LLM_MIN_SCORE", "80"))


def scan_existing_policies(base_path: Path) -> list[dict]:
    """Scan existing policies in the repo and return their metadata."""
    policies = []
    templates_dir = base_path / "templates"
    
    if not templates_dir.exists():
        return policies
    
    for template_file in templates_dir.glob("*-template.yaml"):
        try:
            with open(template_file, "r") as f:
                template_yaml = yaml.safe_load(f)
            
            policy_name = template_file.stem.replace("-template", "")
            rego = ""
            targets = template_yaml.get("spec", {}).get("targets", [])
            if targets:
                rego = targets[0].get("rego", "")
            
            # Extract key info for similarity check
            policies.append({
                "name": policy_name,
                "file": str(template_file.name),
                "rego_preview": rego[:1000] if rego else "",  # More context for AI
                "rego_full": rego,  # Full Rego for better analysis
                "crd_kind": template_yaml.get("spec", {}).get("crd", {}).get("spec", {}).get("names", {}).get("kind", ""),
                "metadata": template_yaml.get("metadata", {}),
            })
        except Exception:
            pass
    
    return policies


def find_similar_policy(request: str, existing_policies: list[dict], llm_client) -> dict | None:
    """Use LLM to check if request matches an existing policy based on Rego logic."""
    if not existing_policies or not llm_client:
        return None
    
    # Load prompt template
    prompt_file = Path(__file__).parent / "llm" / "prompts" / "similarity_check.txt"
    if not prompt_file.exists():
        print(f"[DEBUG] Similarity prompt not found: {prompt_file}")
        return None
    
    prompt_template = prompt_file.read_text()
    
    # Build policy list with Rego code and metadata
    policy_details = "\n\n".join([
        f"POLICY NAME: {p['name']}\n"
        f"KIND: {p.get('crd_kind', 'N/A')}\n"
        f"FILE: {p['file']}\n"
        f"REGO CODE:\n{p.get('rego_full', p.get('rego_preview', ''))}"
        for p in existing_policies
    ])
    
    prompt = prompt_template.format(
        user_request=request,
        existing_policies=policy_details
    )

    try:
        result = llm_client.generate_text(prompt)
        import re
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            if data.get("matches_existing"):
                return data
    except Exception as e:
        print(f"[DEBUG] Similarity check failed: {e}")
    
    return None


def discover_policy_base_path(work_dir: str) -> Path:
    """Detect the directory that should contain generated Gatekeeper policies."""

    repo_root = Path(work_dir).resolve()
    env_path = os.getenv("POLICY_BASE_PATH")
    if env_path:
        candidate = (repo_root / env_path).resolve()
        if candidate.is_relative_to(repo_root):
            return candidate
        raise ValueError(f"POLICY_BASE_PATH {env_path!r} escapes repository root")

    # Heuristics: existing directories we know about
    heuristics = [
        Path("policies"),
        Path("gatekeeper"),
    ]
    for rel in heuristics:
        candidate = (repo_root / rel).resolve()
        if candidate.exists():
            return candidate

    # Look for kustomization directories that already contain templates/constraints
    candidates: list[Path] = []
    for kust_file in repo_root.glob("**/kustomization.yaml"):
        base_dir = kust_file.parent
        templates = base_dir / "templates"
        constraints = base_dir / "constraints"
        if templates.exists() or constraints.exists():
            candidates.append(base_dir.resolve())
    if candidates:
        return candidates[0]

    # Fall back to repo_root / policies
    return (repo_root / "policies").resolve()


def _static_result_to_dict(result: StaticValidationResult) -> list[dict[str, object]]:
    return [
        {"tool": check.tool, "target": check.target, "passed": check.passed, "errors": check.errors}
        for check in result.checks
    ]


def _llm_result_to_dict(result) -> dict[str, object]:
    return {
        "valid": result.valid,
        "score": result.score,
        "errors": result.errors,
        "warnings": result.warnings,
        "suggestions": result.suggestions,
        "corrected_rego": result.corrected_rego,
        "corrected_schema": result.corrected_schema,
        "corrected_constraint_spec": result.corrected_constraint_spec,
    }


def write_validation_report(
    report_dir: Path,
    spec,
    static_result: StaticValidationResult,
    llm_result,
) -> None:
    """Persist validation outcomes for reviewer visibility."""

    report_dir.mkdir(parents=True, exist_ok=True)
    report_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "policy_spec": spec.to_dict(),
        "static_validation": _static_result_to_dict(static_result),
        "llm_validation": _llm_result_to_dict(llm_result),
    }
    (report_dir / "validation.json").write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    lines = [
        "# Validation Report",
        f"_Generated_: {report_data['generated_at']}",
        "",
        "## Static Validation",
    ]
    for check in static_result.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"- **{check.tool}** ({check.target}): {status}")
        if check.errors:
            lines.extend([f"    - {err}" for err in check.errors])

    lines.extend(
        [
            "",
            "## LLM Validation",
            f"- Status: {'PASS' if llm_result.valid else 'FAIL'}",
            f"- Score: {llm_result.score}",
        ]
    )
    if llm_result.errors:
        lines.append("- Errors:")
        lines.extend([f"    - {err}" for err in llm_result.errors])
    if llm_result.warnings:
        lines.append("- Warnings:")
        lines.extend([f"    - {warn}" for warn in llm_result.warnings])
    if llm_result.suggestions:
        lines.append("- Suggestions:")
        lines.extend([f"    - {s}" for s in llm_result.suggestions])
    else:
        lines.append("- Suggestions: None")

    (report_dir / "validation.md").write_text("\n".join(lines), encoding="utf-8")


def print_validation_summary(static_result: StaticValidationResult, llm_result) -> None:
    """Emit a console summary for quick inspection."""

    print("\nValidation Summary")
    for check in static_result.checks:
        status = "✓" if check.passed else "✗"
        print(f"  {status} {check.tool} ({check.target})")
        if check.errors:
            for err in check.errors:
                print(f"      - {err}")
    llm_status = "✓" if llm_result.valid else "✗"
    print(f"  {llm_status} LLM validation score={llm_result.score}")
    if llm_result.suggestions:
        print("    Suggestions:")
        for suggestion in llm_result.suggestions:
            print(f"      - {suggestion}")


def _ensure_dict(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def apply_llm_corrections(template_path: str, constraint_path: str | None, llm_result) -> bool:
    """Apply LLM-provided corrections directly to the generated files."""

    template_changed = False
    schema = _ensure_dict(llm_result.corrected_schema)
    if llm_result.corrected_rego or schema:
        with open(template_path, encoding="utf-8") as f:
            template_yaml = yaml.safe_load(f) or {}
        spec = template_yaml.setdefault("spec", {})
        targets = spec.setdefault("targets", [])
        if targets:
            if llm_result.corrected_rego:
                # Clean and wrap in LiteralString
                rego_clean = llm_result.corrected_rego.replace("\r", "")
                lines = [line.rstrip() for line in rego_clean.split("\n")]
                rego_clean = "\n".join(lines)
                if rego_clean and not rego_clean.endswith("\n"):
                    rego_clean += "\n"
                
                targets[0]["rego"] = LiteralString(rego_clean)
                template_changed = True
        crd = spec.setdefault("crd", {}).setdefault("spec", {}).setdefault("validation", {})
        if schema:
            crd["openAPIV3Schema"] = schema
            template_changed = True
        if template_changed:
            with open(template_path, "w", encoding="utf-8") as f:
                yaml.dump(template_yaml, f, sort_keys=False, default_flow_style=False)

    constraint_changed = False
    corrected_constraint = _ensure_dict(llm_result.corrected_constraint_spec)
    if constraint_path and corrected_constraint:
        with open(constraint_path, encoding="utf-8") as f:
            constraint_yaml = yaml.safe_load(f) or {}
        constraint_yaml["spec"] = corrected_constraint
        with open(constraint_path, "w", encoding="utf-8") as f:
            yaml.dump(constraint_yaml, f, sort_keys=False, default_flow_style=False)
        constraint_changed = True

    return template_changed or constraint_changed


def main():
    """Main CLI entrypoint"""
    if len(sys.argv) < 2:
        print("Usage: ./mcp \"<policy request>\"", file=sys.stderr)
        print("\nExample: ./mcp \"banish pod run root\"", file=sys.stderr)
        sys.exit(1)

    request = sys.argv[1].strip()
    if not request:
        print("Error: Empty policy request.", file=sys.stderr)
        sys.exit(1)

    # Load .env file if it exists
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        # print(f"Loading environment from {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        key, value = line.split("=", 1)
                        if key.strip() not in os.environ:
                            os.environ[key.strip()] = value.strip()
                    except ValueError:
                        pass

    # Get environment variables
    repo_url = os.getenv("GIT_REPO")
    auth_user = os.getenv("GIT_USER", os.getenv("GITHUB_USERNAME"))
    auth_pat = os.getenv("GIT_PAT", os.getenv("GITHUB_TOKEN"))
    
    if not repo_url or not auth_user or not auth_pat:
        print("Error: Set GIT_REPO, GIT_USER, GIT_PAT", file=sys.stderr)
        sys.exit(1)
    
    print(f"Parsing request: {request}")
    
    # Parse request → PolicySpec
    try:
        spec = parse_request(request)
    except Exception as e:
        print(f"Error parsing request: {e}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Policy: {spec.policy_id} ({spec.policy_type})")
    print(f"Intent: {spec.intent.value}")
    print(f"Enforcement: {spec.enforcement.value}")
    print(f"Target Kinds: {', '.join(spec.target_kinds)}")
    is_modify = spec.intent == PolicyIntent.MODIFY
    if is_modify:
        print("Mode: update existing policy artifacts")
    
    # Setup workspace
    import tempfile
    work_dir = tempfile.mkdtemp(prefix="mcp-")
    repo = GitRepo(repo_url, auth_user, auth_pat, work_dir)
    
    try:
        # Clone repo
        print(f"Cloning {repo_url} ...")
        repo.clone()
        
        # Discover base path first
        base_policy_path = discover_policy_base_path(work_dir)
        
        # Scan existing policies
        existing_policies = scan_existing_policies(base_policy_path)
        if existing_policies:
            print(f"[DEBUG] Found {len(existing_policies)} existing policies")
        
        # Check if the requested policy file exists (for MODIFY intent)
        temp_template = base_policy_path / "templates" / f"{spec.policy_type}-template.yaml"
        policy_exists = temp_template.exists()
        
        # ALWAYS run similarity check to let AI analyze all existing policies
        # and determine if user's request matches any existing policy
        if existing_policies:
            from mcp_bot.llm.client import LLMRouter
            llm_client = LLMRouter.get_client()
            
            print(f"[DEBUG] 🤖 AI analyzing all existing policies to find match...")
            print(f"[DEBUG] Found {len(existing_policies)} existing policies")
            similar = find_similar_policy(request, existing_policies, llm_client)
            print(f"[DEBUG] Similarity result: {similar}")
            
            if similar:
                existing_name = similar.get("existing_policy_name")
                reason = similar.get("reason", "")
                
                print(f"\n✅ MATCHED EXISTING POLICY: '{existing_name}'")
                print(f"   Reason: {reason}")
                
                # Update spec to use the matched policy name
                spec.policy_id = existing_name
                spec.policy_type = existing_name
                spec.intent = PolicyIntent.MODIFY
                is_modify = True
                print(f"\n→ Will UPDATE existing policy '{existing_name}'")
            else:
                print(f"[DEBUG] No matching policy found. Will CREATE new policy.")
        
        # Generate policy
        print("Generating policy artifacts ...")
        base_policy_path = discover_policy_base_path(work_dir)
        report_dir = base_policy_path / "reports" / spec.policy_id
        merge_override = True if is_modify else None
        overwrite_override = False if is_modify else None
        generator = PolicyGenerator(
            base_path=str(base_policy_path),
            overwrite_existing=overwrite_override,
            merge_existing=merge_override,
        )
        
        # Check if policy exists (after similarity check may have updated spec.policy_type)
        template_path = generator.templates_dir / f"{spec.policy_type}-template.yaml"
        constraint_path = generator.constraints_dir / f"{spec.policy_type}-constraint.yaml"
        policy_exists = template_path.exists() and constraint_path.exists()
        
        if policy_exists:
            if is_modify:
                # Policy exists and user wants to update → UPDATE mode
                print(f"[INFO] Policy '{spec.policy_type}' exists. Updating existing policy...")
            else:
                # Policy exists but user wants to create → warn and ask
                print(
                    f"[WARNING] Policy '{spec.policy_type}' already exists at:\n"
                    f"  - {template_path}\n"
                    f"  - {constraint_path}\n"
                    f"Use 'update' command to modify existing policy, or set MCP_OVERWRITE_POLICIES=true to overwrite.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            if is_modify:
                # Policy doesn't exist but user wants to update → fallback to CREATE
                print(f"[INFO] Policy '{spec.policy_type}' not found. Creating new policy instead...")
                # Change to CREATE mode
                merge_override = None
                overwrite_override = None
                generator = PolicyGenerator(
                    base_path=str(base_policy_path),
                    overwrite_existing=overwrite_override,
                    merge_existing=merge_override,
                )
            else:
                # Policy doesn't exist and user wants to create → CREATE mode
                print(f"[INFO] Creating new policy '{spec.policy_type}'...")
        
        artifacts = generator.generate(spec, user_prompt=request)
        generator.update_kustomization()
        
        # Validate with static tools
        llm_validator = LLMValidator()
        auto_fix_applied = False
        while True:
            print("Validating generated policies (static) ...")
            static_result = validate_policy(artifacts["template"], artifacts.get("constraint"))
            if static_result.passed:
                print("✓ Static validation passed")
            else:
                print("✗ Static validation reported issues")

            print("Validating generated policies (LLM) ...")
            print(f"[DEBUG] Initializing LLM validator...")
            print(f"[DEBUG] LLM Validator initialized:")
            print(f"  - use_llm: {llm_validator.use_llm}")
            print(f"  - llm_client: {llm_validator.llm_client is not None}")
            if llm_validator.llm_client:
                print(f"  - client class: {type(llm_validator.llm_client).__name__}")
                if hasattr(llm_validator.llm_client, 'use_sdk'):
                    print(f"  - SDK enabled: {llm_validator.llm_client.use_sdk}")

            llm_result = llm_validator.validate(
                artifacts["template"],
                artifacts.get("constraint"),
                request,
                spec.to_dict(),
            )

            if not llm_result.valid:
                print(f"✗ LLM validation failed (valid = false)")
                if llm_result.errors:
                    print(f"  Errors: {', '.join(llm_result.errors)}")
                if llm_result.warnings:
                    print(f"  Warnings: {', '.join(llm_result.warnings)}")
            else:
                print(f"✓ LLM validation passed (valid = true)")
                if llm_result.suggestions:
                    print(f"  Suggestions: {', '.join(llm_result.suggestions)}")

            print_validation_summary(static_result, llm_result)
            write_validation_report(report_dir, spec, static_result, llm_result)

            if not static_result.passed:
                print(f"\n✗ Static validation failed. Review {report_dir} before proceeding.")
                sys.exit(1)

            if llm_validator.use_llm and not llm_result.valid:
                corrections_available = (
                    llm_result.corrected_rego
                    or llm_result.corrected_schema
                    or llm_result.corrected_constraint_spec
                )
                if corrections_available and not auto_fix_applied:
                    print("Applying LLM-provided corrections automatically ...")
                    if apply_llm_corrections(
                        artifacts["template"],
                        artifacts.get("constraint"),
                        llm_result,
                    ):
                        auto_fix_applied = True
                        print("✓ Corrections applied. Re-running validation.")
                        continue
                    print("⚠ Unable to apply corrections automatically.")

                print(
                    "\n✗ LLM validation failed (valid = false). Review "
                    f"{report_dir / 'validation.md'} for details."
                )
                sys.exit(1)
            break
    
        # Create branch and commit
        import secrets

        branch_suffix = secrets.token_hex(3)
        branch_prefix = "policy-update" if is_modify else "policy"
        branch = f"{branch_prefix}/{spec.policy_type}-{branch_suffix}"
        print(f"Creating branch: {branch}")
        repo.checkout_branch(branch)
        
        # Determine files to commit by inspecting git status
        repo_root = Path(work_dir).resolve()
        try:
            rel_prefix = base_policy_path.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            rel_prefix = ""
        prefix = f"{rel_prefix.rstrip('/')}/" if rel_prefix else None
        changed_files = repo.get_changed_files(prefix=prefix)
        if not changed_files:
            print("No changes detected after generation; skipping commit.")
            sys.exit(0)

        # Show changes
        print("\n" + "="*60)
        print("📝 PREVIEW OF CHANGES")
        print("="*60)
        for rel_path in changed_files:
            print(f"\n📄 File: {rel_path}")
            print("-" * 40)
            try:
                diff = repo.get_diff(rel_path)
                print(diff)
            except Exception as e:
                print(f"Error getting diff: {e}")
            print("-" * 40)
        print("="*60 + "\n")

        if is_modify:
            commit_msg = f"chore(policy): update {spec.policy_id}"
        else:
            commit_msg = f"feat(policy): add {spec.policy_id} ({spec.enforcement.value})"
        repo.commit(commit_msg, changed_files)
        
        print("Pushing branch ...")
        push_succeeded = False
        try:
            repo.push(branch)
            push_succeeded = True
            print("✓ Branch pushed successfully")
        except Exception as e:
            print(f"⚠ Git push failed: {e}")
            print("  This might be due to:")
            print("  1. Fine-grained PAT needs 'Contents: write' permission")
            print("  2. Token missing 'repo' scope (Classic PAT)")
            print("  3. Branch already exists on remote")
            print("  4. Network issues")
            print("\n  💡 Fix: Create Classic PAT with 'repo' scope")
            print("     See: FIX_TOKEN.md for detailed instructions")
            print("\n  Files are committed locally. You can manually push:")
            print(f"    cd {work_dir}")
            print(f"    git push -u origin {branch}")
            
            # Check if branch exists on remote before trying PR
            if not push_succeeded:
                print("\n  ⚠️  Cannot create PR - branch doesn't exist on remote")
                print("     Fix token and push branch first, then create PR manually")
                sys.exit(1)
        
        # Create PR
        if is_modify:
            pr_title = f"chore(policy): update {spec.policy_id}"
            target_kinds = ", ".join(spec.target_kinds) or "None"
            excluded_namespaces = ", ".join(spec.namespaces.exclude) or "None"
            pr_body = f"""## Policy Update: {spec.policy_id}

**Description**: {spec.description or request}

### Summary
- Enforcement: {spec.enforcement.value}
- Target Kinds: {target_kinds}
- Excluded namespaces (after merge): {excluded_namespaces}

### Artifacts
- ConstraintTemplate: `{Path(artifacts['template']).name}`
- Constraint: `{Path(artifacts['constraint']).name}`

### Validation
- ✓ kubeconform passed
- ✓ gator validation passed
"""
        else:
            pr_title = f"feat(policy): add {spec.policy_id}"
            pr_body = f"""## Policy: {spec.policy_id}

**Description**: {spec.description}

### Artifacts
- ConstraintTemplate: `{Path(artifacts['template']).name}`
- Constraint: `{Path(artifacts['constraint']).name}` ({spec.enforcement.value})
- Match: {', '.join(spec.target_kinds)}
- Excluded namespaces: {', '.join(spec.namespaces.exclude)}

### Sync Waves
- CT: -1 (created before constraints)
- Constraint: 0 (applied after CT)

### Rollout Plan
1. Merge PR → Argo CD syncs to cluster
2. Observe audit results in {spec.enforcement.value} mode
3. Promote to `deny` in follow-up PR after validation

### Validation
- ✓ kubeconform passed
- ✓ gator validation passed
"""
        
        print("Creating PR ...")
        try:
            pr_url = create_pr(repo_url, auth_user, auth_pat, branch, pr_title, pr_body)
            
            if pr_url:
                print(f"✓ PR created: {pr_url}")
            else:
                print("⚠ PR creation failed")
                print(f"  You can create manually at:")
                repo_parts = repo_url.replace("https://github.com/", "").replace(".git", "").split("/")
                if len(repo_parts) == 2:
                    print(f"  https://github.com/{repo_parts[0]}/{repo_parts[1]}/compare/main...{branch}")
        except Exception as e:
            print(f"⚠ PR creation error: {e}")
            print("  You can create the PR manually on GitHub")
        
        print("Done!")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
