
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import shutil
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_bot.schemas.policyspec import PolicySpec, PolicyIntent, EnforcementMode, NamespaceSelector
from mcp_bot.generator.templates import PolicyGenerator

def test_create_policy():
    print("\n=== TEST 1: Automatic Policy Creation ===")
    
    # 1. Mock Policy Spec (Simulate LLM parsing "ban privileged containers")
    spec = PolicySpec(
        policy_id="ban-privileged",
        policy_type="ban-privileged",
        intent=PolicyIntent.CREATE,
        description="Banish privileged containers",
        target_kinds=["Pod"],
        namespaces=NamespaceSelector(exclude=["kube-system"]),
        enforcement=EnforcementMode.DENY,
        parameters={}
    )
    print(f"Input: User wants to '{spec.description}'")
    print(f"Parsed Intent: {spec.intent.value}")
    
    # 2. Setup temporary workspace
    work_dir = Path("temp_test_create")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()
    
    # 3. Run Generator
    print("Action: Generating artifacts...")
    generator = PolicyGenerator(
        base_path=str(work_dir),
        use_llm=False # Use templates/fallback for this test to avoid needing API key
    )
    
    # Mock internal template generation since we don't have a real template for "ban-privileged" in the fallback
    # We'll inject a dummy template for this test
    with patch.object(generator, '_get_rego', return_value="package banprivileged\nviolation[{'msg': 'msg'}] { true }"):
        with patch.object(generator, '_build_template_schema', return_value={"type": "object"}):
            artifacts = generator.generate(spec)
    
    # 4. Verify Output
    tmpl_path = Path(artifacts["template"])
    const_path = Path(artifacts["constraint"])
    
    if tmpl_path.exists() and const_path.exists():
        print("✅ SUCCESS: Artifacts created.")
        print(f"  - Template: {tmpl_path}")
        print(f"  - Constraint: {const_path}")
        
        # Check content
        with open(const_path) as f:
            const = yaml.safe_load(f)
            print(f"  - Enforcement: {const['spec']['enforcementAction']}")
            if const['spec']['enforcementAction'] == 'deny':
                print("✅ Verification: Enforcement is 'deny' as requested.")
            else:
                print("❌ Verification Failed: Enforcement mismatch.")
    else:
        print("❌ FAILED: Artifacts not created.")
    
    # Cleanup
    shutil.rmtree(work_dir)

def test_update_policy():
    print("\n=== TEST 2: Policy Update (Existing Policy) ===")
    
    # 1. Setup Workspace with EXISTING policy
    work_dir = Path("temp_test_update")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    
    # Create initial files
    templates_dir = work_dir / "templates"
    constraints_dir = work_dir / "constraints"
    templates_dir.mkdir(parents=True)
    constraints_dir.mkdir(parents=True)
    
    initial_tmpl = templates_dir / "ban-privileged-template.yaml"
    initial_const = constraints_dir / "ban-privileged-constraint.yaml"
    
    initial_tmpl.write_text("apiVersion: templates.gatekeeper.sh/v1\nkind: ConstraintTemplate\nmetadata:\n  name: ban-privileged\nspec:\n  targets:\n  - rego: | \n      package old\n")
    initial_const.write_text("apiVersion: constraints.gatekeeper.sh/v1beta1\nkind: BanPrivileged\nmetadata:\n  name: ban-privileged\nspec:\n  enforcementAction: dryrun\n  match:\n    excludedNamespaces: [kube-system]\n")
    
    print(f"Setup: Existing policy 'ban-privileged' (Enforcement: dryrun)")
    
    # 2. Mock Policy Spec (Simulate LLM parsing "update ban privileged to deny and exclude argocd")
    spec = PolicySpec(
        policy_id="ban-privileged",
        policy_type="ban-privileged",
        intent=PolicyIntent.MODIFY,
        description="Update to deny and exclude argocd",
        target_kinds=["Pod"],
        namespaces=NamespaceSelector(exclude=["kube-system", "argocd"]), # Added argocd
        enforcement=EnforcementMode.DENY, # Changed to deny
        parameters={}
    )
    print(f"Input: User wants to '{spec.description}'")
    print(f"Parsed Intent: {spec.intent.value}")
    
    # 3. Run Generator with MERGE enabled
    print("Action: Updating artifacts...")
    generator = PolicyGenerator(
        base_path=str(work_dir),
        use_llm=False,
        merge_existing=True # IMPORTANT: Enable merging
    )
    
    with patch.object(generator, '_get_rego', return_value="package banprivileged\nviolation[{'msg': 'msg'}] { true }"):
         with patch.object(generator, '_build_template_schema', return_value={"type": "object"}):
            generator.generate(spec)
            
    # 4. Verify Updates
    with open(initial_const) as f:
        const = yaml.safe_load(f)
        enforcement = const['spec']['enforcementAction']
        excluded = const['spec']['match']['excludedNamespaces']
        
        print(f"  - New Enforcement: {enforcement}")
        print(f"  - New Excluded Namespaces: {excluded}")
        
        if enforcement == 'deny' and 'argocd' in excluded and 'kube-system' in excluded:
            print("✅ SUCCESS: Policy updated correctly.")
            print("  - Enforcement changed from dryrun -> deny")
            print("  - 'argocd' added to excluded namespaces")
        else:
            print("❌ FAILED: Update did not apply correctly.")

    # Cleanup
    shutil.rmtree(work_dir)

if __name__ == "__main__":
    try:
        test_create_policy()
        test_update_policy()
    except Exception as e:
        print(f"Test Error: {e}")
        import traceback
        traceback.print_exc()
