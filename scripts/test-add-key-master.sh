#!/bin/bash
# Test add SSH key vào ansible-user trên master node01
#
# Usage:
#   ./scripts/test-add-key-master.sh

set -e

INVENTORY="ansible/inventory/my-cluster_hosts.yml"
TARGET_USER="ansible-user"
TARGET_NODE="k8s-master-node01"

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
NC='\033[0m' # No Color

echo -e "${GREEN}=== Test Add SSH Key to Ansible User (Master Node01) ===${NC}"
echo ""

# Check if inventory exists
if [ ! -f "$INVENTORY" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY${NC}"
    exit 1
fi

# Check if SSH public key exists
if [ ! -f "$SSH_PUBLIC_KEY" ]; then
    echo -e "${RED}Error: SSH public key not found: $SSH_PUBLIC_KEY${NC}"
    exit 1
fi

# Set correct permissions
chmod 600 "$SSH_PRIVATE_KEY" 2>/dev/null || true

echo -e "${GREEN}Target node: $TARGET_NODE${NC}"
echo -e "${GREEN}Using SSH key: $SSH_PUBLIC_KEY${NC}"
echo -e "${GREEN}Adding SSH key to user '$TARGET_USER'...${NC}"
echo -e "${YELLOW}You will be prompted for root password${NC}"
echo ""

# Run playbook chỉ trên master node01
ansible-playbook \
    -i "$INVENTORY" \
    ansible/playbooks/add-ssh-key-to-user.yml \
    --limit "$TARGET_NODE" \
    --user root \
    --ask-pass \
    -e "target_user=$TARGET_USER" \
    -e "public_key_path=$SSH_PUBLIC_KEY" \
    -e "ansible_user=root"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=== SSH Key Added Successfully! ===${NC}"
    echo ""
    echo "Testing connection with ansible-user on $TARGET_NODE..."
    
    # Test với ansible-user
    ansible "$TARGET_NODE" -i "$INVENTORY" \
        -m ping \
        --user "$TARGET_USER" \
        --private-key "$SSH_PRIVATE_KEY" \
        -e "ansible_user=$TARGET_USER"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓ Connection test successful!${NC}"
        echo ""
        echo "You can now use ansible-user on $TARGET_NODE."
        echo ""
        echo "Test SSH manually:"
        echo "  ssh -i $SSH_PRIVATE_KEY ansible-user@192.168.1.111"
    else
        echo ""
        echo -e "${YELLOW}⚠ Connection test failed. Please check:${NC}"
        echo "1. SSH key was added correctly"
        echo "2. User has proper permissions"
        echo "3. Sudoers is configured (if needed)"
    fi
else
    echo ""
    echo -e "${RED}=== Failed to add SSH key ===${NC}"
    exit 1
fi

