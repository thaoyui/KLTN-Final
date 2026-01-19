#!/bin/bash
# Script test kết nối Ansible với ansible-user
#
# Usage:
#   ./scripts/test-ansible-user.sh

set -e

INVENTORY="ansible/inventory/my-cluster_hosts.yml"
SSH_KEY_PATH="${HOME}/.ssh/ansible_user_key"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Testing Ansible User Connection ===${NC}"
echo ""

# Check if inventory exists
if [ ! -f "$INVENTORY" ]; then
    echo -e "${RED}Error: Inventory file not found: $INVENTORY${NC}"
    exit 1
fi

# Check if SSH key exists
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo -e "${YELLOW}Warning: SSH key not found: $SSH_KEY_PATH${NC}"
    echo -e "${YELLOW}Please create SSH key pair first:${NC}"
    echo "  ssh-keygen -t ed25519 -f $SSH_KEY_PATH -N \"\""
    echo ""
    read -p "Do you want to generate SSH key now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N ""
        echo -e "${GREEN}SSH key generated: $SSH_KEY_PATH${NC}"
    else
        echo -e "${RED}Aborted. Please create SSH key first.${NC}"
        exit 1
    fi
fi

# Set correct permissions for SSH key
chmod 600 "$SSH_KEY_PATH"

echo -e "${GREEN}1. Testing Ansible ping...${NC}"
ansible all -i "$INVENTORY" -m ping

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Ping successful${NC}"
else
    echo -e "${RED}✗ Ping failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}2. Testing sudo access...${NC}"
ansible all -i "$INVENTORY" -m shell -a "whoami" --become

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Sudo access working${NC}"
else
    echo -e "${RED}✗ Sudo access failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}3. Testing file read (stat)...${NC}"
ansible all -i "$INVENTORY" -m shell -a "sudo stat /etc/kubernetes/manifests/kube-apiserver.yaml 2>/dev/null || echo 'File not found (OK for worker nodes)'" --become

echo ""
echo -e "${GREEN}4. Testing process check (ps)...${NC}"
ansible all -i "$INVENTORY" -m shell -a "sudo ps -fC kubelet 2>/dev/null | head -1 || echo 'kubelet not running (OK)'" --become

echo ""
echo -e "${GREEN}5. Testing file permissions (chmod - dry run)...${NC}"
ansible all -i "$INVENTORY" -m shell -a "sudo chmod --help > /dev/null && echo 'chmod available' || echo 'chmod not available'" --become

echo ""
echo -e "${GREEN}6. Testing systemctl...${NC}"
ansible all -i "$INVENTORY" -m shell -a "sudo systemctl --version > /dev/null && echo 'systemctl available' || echo 'systemctl not available'" --become

echo ""
echo -e "${GREEN}7. Testing kubectl (master nodes only)...${NC}"
ansible masters -i "$INVENTORY" -m shell -a "sudo kubectl version --client 2>/dev/null | head -1 || echo 'kubectl not available'" --become 2>/dev/null || echo "Skipping kubectl test (may not be available)"

echo ""
echo -e "${GREEN}=== All Tests Completed ===${NC}"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Test bootstrap:"
echo "   ansible-playbook -i $INVENTORY ansible/playbooks/kube-check-bootstrap.yml -e 'node_name=k8s-master-node01'"
echo ""
echo "2. Test scan:"
echo "   ansible-playbook -i $INVENTORY ansible/playbooks/kube-check-scan.yml -e 'check_ids=1.1.1,1.1.2' -e 'node_name=k8s-master-node01'"
echo ""

