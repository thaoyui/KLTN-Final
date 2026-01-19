#!/bin/bash
# Script tự động add SSH key vào ansible-user trên tất cả nodes
# Sử dụng ssh-copy-id (đơn giản, nhanh, có thể nhập password khác nhau)
#
# Usage:
#   ./scripts/add-ssh-key-ssh-copy-id.sh

set -e

INVENTORY="ansible/inventory/my-cluster_hosts.yml"
TARGET_USER="ansible-user"

# Tìm SSH public key
if [ -f "${HOME}/.ssh/id_ed25519.pub" ]; then
    SSH_PUBLIC_KEY="${HOME}/.ssh/id_ed25519.pub"
    SSH_PRIVATE_KEY="${HOME}/.ssh/id_ed25519"
elif [ -f "${HOME}/.ssh/ansible_user_key.pub" ]; then
    SSH_PUBLIC_KEY="${HOME}/.ssh/ansible_user_key.pub"
    SSH_PRIVATE_KEY="${HOME}/.ssh/ansible_user_key"
else
    SSH_PUBLIC_KEY="${HOME}/.ssh/id_ed25519.pub"
    SSH_PRIVATE_KEY="${HOME}/.ssh/id_ed25519"
fi

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Add SSH Key using ssh-copy-id ===${NC}"
echo ""

# Check if inventory exists
if [ ! -f "$INVENTORY" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY${NC}"
    exit 1
fi

# Check if SSH public key exists
if [ ! -f "$SSH_PUBLIC_KEY" ]; then
    echo -e "${RED}Error: SSH public key not found: $SSH_PUBLIC_KEY${NC}"
    echo -e "${YELLOW}Do you want to generate a new SSH key pair? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        ssh-keygen -t ed25519 -f "$SSH_PRIVATE_KEY" -N ""
        echo -e "${GREEN}SSH key generated: $SSH_PRIVATE_KEY${NC}"
    else
        echo -e "${RED}Aborted. Please provide a valid SSH public key.${NC}"
        exit 1
    fi
fi

# Set correct permissions
chmod 600 "$SSH_PRIVATE_KEY" 2>/dev/null || true

echo -e "${GREEN}Using SSH key: $SSH_PUBLIC_KEY${NC}"
echo -e "${GREEN}Target user: $TARGET_USER${NC}"
echo ""

# Parse inventory to get nodes
# Extract IPs from inventory YAML file
echo -e "${BLUE}Reading nodes from inventory...${NC}"

NODES=$(grep -E "^\s+ansible_host:\s+" "$INVENTORY" 2>/dev/null | \
    sed 's/.*ansible_host:\s*\([0-9.]*\).*/\1/' | \
    sort -u | \
    tr '\n' ' ')

# Fallback to default if empty
if [ -z "$NODES" ]; then
    echo -e "${YELLOW}Could not parse inventory. Using default nodes...${NC}"
    NODES="192.168.1.111 192.168.1.112 192.168.1.113"
fi

echo -e "${BLUE}Nodes to process:${NC}"
for node in $NODES; do
    echo -e "  - ${GREEN}$node${NC}"
done
echo ""

# Process each node
SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_NODES=()

for node in $NODES; do
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Processing: ${GREEN}$node${NC}"
    echo -e "${YELLOW}You will be prompted for password of user '$TARGET_USER' on this node${NC}"
    echo ""
    
    if ssh-copy-id -i "$SSH_PUBLIC_KEY" "$TARGET_USER@$node" 2>&1; then
        echo -e "${GREEN}✓ SSH key added successfully to $node${NC}"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        
        # Test connection
        echo -e "${BLUE}Testing connection...${NC}"
        if ssh -i "$SSH_PRIVATE_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$TARGET_USER@$node" "echo 'Connection OK'" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Connection test successful${NC}"
        else
            echo -e "${YELLOW}⚠ Connection test failed (but key was added)${NC}"
        fi
    else
        echo -e "${RED}✗ Failed to add SSH key to $node${NC}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_NODES+=("$node")
    fi
    echo ""
done

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}=== Summary ===${NC}"
echo -e "${GREEN}Success: $SUCCESS_COUNT node(s)${NC}"
if [ $FAIL_COUNT -gt 0 ]; then
    echo -e "${RED}Failed: $FAIL_COUNT node(s)${NC}"
    echo -e "${RED}Failed nodes: ${FAILED_NODES[*]}${NC}"
    echo ""
    echo -e "${YELLOW}You can retry failed nodes manually:${NC}"
    for node in "${FAILED_NODES[@]}"; do
        echo -e "  ssh-copy-id -i $SSH_PUBLIC_KEY $TARGET_USER@$node"
    done
    exit 1
else
    echo -e "${GREEN}All nodes processed successfully!${NC}"
    echo ""
    echo -e "${GREEN}You can now use ansible-user for Ansible operations.${NC}"
    echo ""
    echo -e "${BLUE}Test with Ansible:${NC}"
    echo -e "  ansible all -i $INVENTORY -m ping --user $TARGET_USER --private-key $SSH_PRIVATE_KEY"
fi

