#!/bin/bash
# Script helper để setup ansible-user trên tất cả K8s nodes
#
# Usage:
#   ./scripts/setup-ansible-user.sh [options]
#
# Options:
#   -u, --username USERNAME    Tên user cần tạo (default: ansible-user)
#   -k, --key-path PATH        Đường dẫn đến SSH public key (default: ~/.ssh/ansible_user_key.pub)
#   -i, --inventory PATH       Đường dẫn inventory file (default: ansible/inventory/my-cluster_hosts.yml)
#   -l, --limited              Sử dụng quyền sudo giới hạn thay vì full access
#   -h, --help                 Hiển thị help

set -e

# Default values
ANSIBLE_USERNAME="ansible-user"
SSH_KEY_PATH="${HOME}/.ssh/ansible_user_key.pub"
INVENTORY_PATH="ansible/inventory/my-cluster_hosts.yml"
SUDO_FULL_ACCESS="true"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--username)
            ANSIBLE_USERNAME="$2"
            shift 2
            ;;
        -k|--key-path)
            SSH_KEY_PATH="$2"
            shift 2
            ;;
        -i|--inventory)
            INVENTORY_PATH="$2"
            shift 2
            ;;
        -l|--limited)
            SUDO_FULL_ACCESS="false"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -u, --username USERNAME    Tên user cần tạo (default: ansible-user)"
            echo "  -k, --key-path PATH        Đường dẫn đến SSH public key (default: ~/.ssh/ansible_user_key.pub)"
            echo "  -i, --inventory PATH       Đường dẫn inventory file (default: ansible/inventory/my-cluster_hosts.yml)"
            echo "  -l, --limited              Sử dụng quyền sudo giới hạn thay vì full access"
            echo "  -h, --help                 Hiển thị help"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Expand tilde in paths
SSH_KEY_PATH="${SSH_KEY_PATH/#\~/$HOME}"
INVENTORY_PATH="${INVENTORY_PATH/#\~/$HOME}"

# Check if inventory file exists
if [ ! -f "$INVENTORY_PATH" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY_PATH${NC}"
    exit 1
fi

# Check if SSH key exists
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo -e "${YELLOW}Warning: SSH public key not found: $SSH_KEY_PATH${NC}"
    echo -e "${YELLOW}Do you want to generate a new SSH key pair? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        SSH_PRIVATE_KEY="${SSH_KEY_PATH%.pub}"
        echo "Generating SSH key pair..."
        ssh-keygen -t ed25519 -f "$SSH_PRIVATE_KEY" -N ""
        echo -e "${GREEN}SSH key pair generated: $SSH_PRIVATE_KEY${NC}"
    else
        echo -e "${RED}Aborted. Please provide a valid SSH public key.${NC}"
        exit 1
    fi
fi

# Display configuration
echo -e "${GREEN}=== Setup Ansible User Configuration ===${NC}"
echo "Username: $ANSIBLE_USERNAME"
echo "SSH Key: $SSH_KEY_PATH"
echo "Inventory: $INVENTORY_PATH"
echo "Sudo Access: $([ "$SUDO_FULL_ACCESS" = "true" ] && echo "Full" || echo "Limited")"
echo ""

# Confirm
echo -e "${YELLOW}This will setup user '$ANSIBLE_USERNAME' on all nodes in the inventory.${NC}"
echo -e "${YELLOW}Continue? (y/n)${NC}"
read -r response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo "Aborted."
    exit 0
fi

# Run playbook
echo -e "${GREEN}Running playbook...${NC}"
ansible-playbook \
    -i "$INVENTORY_PATH" \
    ansible/playbooks/setup-ansible-user.yml \
    --user root \
    --private-key "${SSH_KEY_PATH%.pub}" \
    -e "ansible_username=$ANSIBLE_USERNAME" \
    -e "ansible_public_key_path=$SSH_KEY_PATH" \
    -e "ansible_sudo_full_access=$SUDO_FULL_ACCESS"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=== Setup completed successfully! ===${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Update your inventory file to use the new user:"
    echo "   ansible_user: $ANSIBLE_USERNAME"
    echo "   ansible_ssh_private_key_file: ${SSH_KEY_PATH%.pub}"
    echo ""
    echo "2. Test connection:"
    echo "   ansible all -i $INVENTORY_PATH -m ping"
    echo ""
    echo "3. Test sudo access:"
    echo "   ansible all -i $INVENTORY_PATH -m shell -a 'whoami' --become"
else
    echo ""
    echo -e "${RED}=== Setup failed! ===${NC}"
    echo "Please check the error messages above."
    exit 1
fi

