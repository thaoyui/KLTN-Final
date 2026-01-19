#!/bin/bash
# Script để xem timing chi tiết từ scan

SCAN_ID="${1}"
API_URL="${2:-http://localhost:3001}"

if [ -z "$SCAN_ID" ]; then
    echo "Usage: $0 <scan_id> [api_url]"
    echo ""
    echo "Example:"
    echo "  $0 87fd97b7-41a3-44ce-bff9-bde55a2b194a"
    echo "  $0 87fd97b7-41a3-44ce-bff9-bde55a2b194a http://localhost:3001"
    exit 1
fi

echo "=== Fetching timing for scan: $SCAN_ID ==="
echo ""

# Get timing from API
TIMING_JSON=$(curl -s "${API_URL}/api/scan/${SCAN_ID}/timing")

if [ $? -ne 0 ]; then
    echo "Error: Failed to fetch timing from API"
    exit 1
fi

# Check if successful
SUCCESS=$(echo "$TIMING_JSON" | grep -o '"success":true' || echo "")
if [ -z "$SUCCESS" ]; then
    echo "Error: Scan not found or timing not available"
    echo "$TIMING_JSON" | python3 -m json.tool 2>/dev/null || echo "$TIMING_JSON"
    exit 1
fi

# Display formatted timing
echo "$TIMING_JSON" | python3 -c "
import json
import sys

data = json.load(sys.stdin)

print('📊 TIMING SUMMARY')
print('=' * 60)
summary = data.get('summary', {})
print(f\"Connection to Node:     {summary.get('connection_to_node_seconds', 0):.3f}s\")
print(f\"File Checks:            {summary.get('file_checks_seconds', 0):.3f}s\")
print(f\"Task Execution:         {summary.get('task_execution_seconds', 0):.3f}s\")
print(f\"Result Fetch:           {summary.get('result_fetch_seconds', 0):.3f}s\")
print(f\"Total Time:             {summary.get('total_seconds', 0):.3f}s\")
print()

print('📈 DETAILED BREAKDOWN')
print('=' * 60)
breakdown = data.get('detailed_breakdown', {})
explanation = data.get('breakdown_explanation', {})

for key, value in breakdown.items():
    if isinstance(value, (int, float)) and value > 0:
        desc = explanation.get(key, key)
        print(f\"{key:30s}: {value:8.3f}s - {desc}\")

print()
print('🔧 API TIMING')
print('=' * 60)
api_timing = data.get('api_timing', {})
print(f\"API Processing:         {api_timing.get('api_processing_seconds', 0):.3f}s\")
print(f\"Total Response:         {api_timing.get('total_response_seconds', 0):.3f}s\")
print()

# Show Ansible breakdown if available
ansible_breakdown = data.get('timing', {}).get('ansible_breakdown', {})
if ansible_breakdown and any(v > 0 for v in ansible_breakdown.values()):
    print('⚙️  ANSIBLE BREAKDOWN (from playbook)')
    print('=' * 60)
    for key, value in ansible_breakdown.items():
        if isinstance(value, (int, float)):
            print(f\"{key:30s}: {value:8.3f}s\")
    print()
"

echo ""
echo "💡 To view raw JSON:"
echo "   curl ${API_URL}/api/scan/${SCAN_ID}/timing | python3 -m json.tool"

