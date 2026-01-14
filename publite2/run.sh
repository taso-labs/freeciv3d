#!/bin/bash

# Use tee to send logs to BOTH file AND stdout (for GCP Cloud Logging capture)
# Note: Removed nohup since container runs in foreground; use -u for unbuffered output
python3 -u publite2.py 2>&1 | tee ../logs/publite2.log &
PUBLITE2_PID=$!
sleep 5

# Check if publite2 started successfully
if kill -0 $PUBLITE2_PID 2>/dev/null; then
    echo "✓ publite2 started (PID: $PUBLITE2_PID)"
else
    echo "✗ publite2 failed to start, last 5 lines:"
    tail -5 ../logs/publite2.log
fi
