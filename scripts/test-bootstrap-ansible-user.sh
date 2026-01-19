#!/bin/bash
# Test Bootstrap với ansible-user
#
# Usage:
#   ./scripts/test-bootstrap-ansible-user.sh [node_name]

set -e

INVENTORY="ansible/inventory/my-cluster_hosts.yml"
NODE_NAME="${1:-k8s-master-node01}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Test Bootstrap with ansible-user ===${NC}"
echo ""

# Check if inventory exists
if [ ! -f "$INVENTORY" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY${NC}"
    exit 1
fi

# Check if ansible-user can connect
echo -e "${BLUE}1. Testing ansible-user connection...${NC}"
if ansible "$NODE_NAME" -i "$INVENTORY" -m ping >/dev/null 2>&1; then
    echo -e "${GREEN}✓ ansible-user can connect${NC}"
else
    echo -e "${RED}✗ ansible-user cannot connect${NC}"
    echo -e "${YELLOW}Please run: ./scripts/add-ssh-key-ssh-copy-id.sh${NC}"
    exit 1
fi

# Check if ansible-user can use sudo
echo -e "${BLUE}2. Testing sudo access...${NC}"
if ansible "$NODE_NAME" -i "$INVENTORY" -m shell -a "whoami" --become >/dev/null 2>&1; then
    echo -e "${GREEN}✓ ansible-user can use sudo${NC}"
else
    echo -e "${RED}✗ ansible-user cannot use sudo${NC}"
    echo -e "${YELLOW}Please check sudoers configuration${NC}"
    exit 1
fi

# Test bootstrap playbook
echo -e "${BLUE}3. Testing bootstrap playbook...${NC}"
echo -e "${YELLOW}Running bootstrap for node: $NODE_NAME${NC}"
echo ""

ansible-playbook \
    -i "$INVENTORY" \
    ansible/playbooks/kube-check-bootstrap.yml \
    --limit "$NODE_NAME" \
    -e "node_name=$NODE_NAME" \
    -e "kubecheck_path_local=/home/thaopieh/Final/DACN/Kube-check"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=== Bootstrap Test Successful! ===${NC}"
    echo ""
    echo -e "${BLUE}4. Verifying bootstrap...${NC}"
    
    # Check if /home/ansible-user/Kube-check exists
    if ansible "$NODE_NAME" -i "$INVENTORY" -m stat -a "path=/home/ansible-user/Kube-check" | grep -q '"exists": true'; then
        echo -e "${GREEN}✓ /home/ansible-user/Kube-check directory exists${NC}"
    else
        echo -e "${YELLOW}⚠ /home/ansible-user/Kube-check directory not found${NC}"
    fi
    
    # Check if venv exists
    if ansible "$NODE_NAME" -i "$INVENTORY" -m stat -a "path=/home/ansible-user/Kube-check/venv" | grep -q '"exists": true'; then
        echo -e "${GREEN}✓ venv exists${NC}"
    else
        echo -e "${YELLOW}⚠ venv not found${NC}"
    fi
    
    # Check if src exists
    if ansible "$NODE_NAME" -i "$INVENTORY" -m stat -a "path=/home/ansible-user/Kube-check/src" | grep -q '"exists": true'; then
        echo -e "${GREEN}✓ src directory exists${NC}"
    else
        echo -e "${YELLOW}⚠ src directory not found${NC}"
    fi
    
    echo ""
    echo -e "${GREEN}You can now test bootstrap from frontend!${NC}"
else
    echo ""
    echo -e "${RED}=== Bootstrap Test Failed ===${NC}"
    echo -e "${YELLOW}Check the error messages above${NC}"
    exit 1
fi

