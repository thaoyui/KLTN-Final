#!/bin/bash
# Script để xem timing từ Ansible log files

LOG_DIR="${1:-/app/logs}"
CONTAINER_NAME="${2:-kube-check-unified-backend}"

echo "=== Viewing timing from Ansible logs ==="
echo ""

# Check if running in Docker or locally
if [ -d "/app/logs" ] || [ -d "$LOG_DIR" ]; then
    # In container or local
    if [ -d "/app/logs" ]; then
        LOG_DIR="/app/logs"
    fi
    echo "Log directory: $LOG_DIR"
    echo ""
    
    # Find latest scan log
    LATEST_LOG=$(ls -t ${LOG_DIR}/kube-check-scan_*.log 2>/dev/null | head -1)
    
    if [ -z "$LATEST_LOG" ]; then
        echo "No scan log files found in $LOG_DIR"
        exit 1
    fi
    
    echo "Latest log: $LATEST_LOG"
    echo ""
    echo "=== TIMING BREAKDOWN FROM LOG ==="
    echo ""
    
    # Extract timing section
    grep -A 20 "TIMING BREAKDOWN" "$LATEST_LOG" || \
    grep -A 20 "DETAILED TIMING" "$LATEST_LOG" || \
    grep -A 20 "Connection time" "$LATEST_LOG" || \
    echo "Timing section not found in log"
    
    echo ""
    echo "=== Full log file ==="
    echo "To view full log: cat $LATEST_LOG"
    
else
    # Try to access via Docker
    echo "Accessing logs from Docker container: $CONTAINER_NAME"
    echo ""
    
    docker exec "$CONTAINER_NAME" bash -c "
        LOG_DIR='${LOG_DIR}'
        if [ ! -d \"\$LOG_DIR\" ]; then
            LOG_DIR='/app/logs'
        fi
        
        LATEST_LOG=\$(ls -t \${LOG_DIR}/kube-check-scan_*.log 2>/dev/null | head -1)
        
        if [ -z \"\$LATEST_LOG\" ]; then
            echo 'No scan log files found'
            exit 1
        fi
        
        echo 'Latest log: '\$LATEST_LOG
        echo ''
        echo '=== TIMING BREAKDOWN FROM LOG ==='
        echo ''
        
        grep -A 20 'TIMING BREAKDOWN' \"\$LATEST_LOG\" || \
        grep -A 20 'DETAILED TIMING' \"\$LATEST_LOG\" || \
        grep -A 20 'Connection time' \"\$LATEST_LOG\" || \
        echo 'Timing section not found in log'
    "
fi

