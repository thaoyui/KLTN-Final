#!/bin/bash
# Script copy SSH public key lên remote node
# Usage: ./scripts/copy-ssh-key-to-node.sh <node-ip> <user> [ssh-key-path]

set -e

NODE_IP="${1:-192.168.1.111}"
NODE_USER="${2:-ansible-user}"
SSH_KEY_PATH="${3:-${HOME}/.ssh/id_ed25519}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Copy SSH Public Key to Remote Node ===${NC}"
echo "Node IP: $NODE_IP"
echo "User: $NODE_USER"
echo "SSH Key: $SSH_KEY_PATH"
echo ""

# Check if private key exists
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo -e "${RED}Error: SSH private key not found: $SSH_KEY_PATH${NC}"
    exit 1
fi

# Check if public key exists
SSH_PUBLIC_KEY="${SSH_KEY_PATH}.pub"
if [ ! -f "$SSH_PUBLIC_KEY" ]; then
    echo -e "${YELLOW}Warning: Public key not found: $SSH_PUBLIC_KEY${NC}"
    echo -e "${YELLOW}Generating public key from private key...${NC}"
    ssh-keygen -y -f "$SSH_KEY_PATH" > "$SSH_PUBLIC_KEY"
    echo -e "${GREEN}Public key generated: $SSH_PUBLIC_KEY${NC}"
fi

echo -e "${GREEN}Copying public key to $NODE_USER@$NODE_IP...${NC}"
echo -e "${YELLOW}You may be prompted for password${NC}"
echo ""

# Method 1: Try ssh-copy-id
if command -v ssh-copy-id &> /dev/null; then
    echo -e "${GREEN}Using ssh-copy-id...${NC}"
    ssh-copy-id -i "$SSH_PUBLIC_KEY" "$NODE_USER@$NODE_IP" || {
        echo -e "${YELLOW}ssh-copy-id failed, trying manual method...${NC}"
        # Method 2: Manual copy
        cat "$SSH_PUBLIC_KEY" | ssh "$NODE_USER@$NODE_IP" \
            "mkdir -p ~/.ssh && \
             chmod 700 ~/.ssh && \
             cat >> ~/.ssh/authorized_keys && \
             chmod 600 ~/.ssh/authorized_keys && \
             echo 'SSH key added successfully'"
    }
else
    # Method 2: Manual copy
    echo -e "${GREEN}Using manual method...${NC}"
    cat "$SSH_PUBLIC_KEY" | ssh "$NODE_USER@$NODE_IP" \
        "mkdir -p ~/.ssh && \
         chmod 700 ~/.ssh && \
         cat >> ~/.ssh/authorized_keys && \
         chmod 600 ~/.ssh/authorized_keys && \
         echo 'SSH key added successfully'"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ SSH key copied successfully!${NC}"
    echo ""
    echo -e "${GREEN}Testing connection...${NC}"
    ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$NODE_USER@$NODE_IP" "echo 'Connection test successful!'"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}=== Success! SSH key is working ===${NC}"
    else
        echo ""
        echo -e "${RED}Connection test failed. Please check:${NC}"
        echo "  1. Public key was added to ~/.ssh/authorized_keys"
        echo "  2. File permissions: ~/.ssh (700), ~/.ssh/authorized_keys (600)"
        echo "  3. User has correct ownership"
    fi
else
    echo ""
    echo -e "${RED}Failed to copy SSH key${NC}"
    exit 1
fi


