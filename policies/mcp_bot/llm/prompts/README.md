# LLM Prompts

Common prompts used by both Gemini and Qwen LLM providers.

## Files

| Prompt | Purpose | When Used |
|--------|---------|-----------|
| `intent_parsing.txt` | Parse natural language → PolicySpec | First step: understand user request |
| `similarity_check.txt` | Check if policy already exists | Before CREATE: avoid duplicates |
| `policy_generation.txt` | Generate Rego + Schema + Constraint | CREATE mode: new policy |
| `file_patch.txt` | Generate patch for existing files | MODIFY mode: update policy |
| `policy_validation.txt` | Validate generated artifacts | After generation: check quality |

## Key Rules (All Prompts)

### NO HARDCODED VALUES IN REGO

**WRONG:**
```rego
exemptImages := ["nginx:latest"]  # Hardcoded in Rego!
```

**CORRECT:**
```rego
exemptImages := object.get(input.parameters, "exemptImages", [])  # From parameters
```

- Rego code = LOGIC (template/frame)
- Constraint file = DATA (actual values)
- Parameters MUST come from `input.parameters`
