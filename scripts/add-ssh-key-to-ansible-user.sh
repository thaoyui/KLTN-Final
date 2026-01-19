#!/bin/bash
# Script đơn giản để add SSH key vào ansible-user đã có sẵn
# Sử dụng root password để add key (không dùng root SSH key vì quyền quá rộng)
#
# Usage:
#   ./scripts/add-ssh-key-to-ansible-user.sh

set -e

INVENTORY="ansible/inventory/my-cluster_hosts.yml"
TARGET_USER="ansible-user"

# Tìm SSH public key (ưu tiên id_ed25519, sau đó ansible_user_key)
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

echo -e "${GREEN}=== Add SSH Key to Ansible User ===${NC}"
echo ""

# Check if inventory exists
if [ ! -f "$INVENTORY" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY${NC}"
    exit 1
fi

# Check if SSH public key exists
if [ ! -f "$SSH_PUBLIC_KEY" ]; then
    echo -e "${YELLOW}SSH public key not found: $SSH_PUBLIC_KEY${NC}"
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
echo -e "${GREEN}Adding SSH key to user '$TARGET_USER' on all nodes...${NC}"
echo -e "${YELLOW}You will be prompted for root password${NC}"
echo ""

# Run playbook với password authentication
ansible-playbook \
    -i "$INVENTORY" \
    ansible/playbooks/add-ssh-key-to-user.yml \
    --user root \
    --ask-pass \
  -e "target_user=$TARGET_USER" \
  -e "public_key_path=$SSH_PUBLIC_KEY" \
  -e "ansible_user=root"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=== SSH Key Added Successfully! ===${NC}"
    echo ""
    echo "Testing connection with ansible-user..."
    
    # Test với ansible-user (tạm thời override inventory)
    ansible all -i "$INVENTORY" \
        -m ping \
        --user "$TARGET_USER" \
        --private-key "$SSH_PRIVATE_KEY" \
        -e "ansible_user=$TARGET_USER"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓ Connection test successful!${NC}"
        echo ""
        echo "You can now use ansible-user for Ansible operations."
        echo ""
        echo "Update inventory to use:"
        echo "  ansible_user: $TARGET_USER"
        echo "  ansible_ssh_private_key_file: $SSH_PRIVATE_KEY"
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

