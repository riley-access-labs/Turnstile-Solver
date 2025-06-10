#!/bin/bash

start_xrdp_services() {
    rm -rf /var/run/xrdp-sesman.pid
    rm -rf /var/run/xrdp.pid
    rm -rf /var/run/xrdp/xrdp-sesman.pid
    rm -rf /var/run/xrdp/xrdp.pid

    xrdp-sesman &
    xrdp -n &

    echo "Waiting for X server to be ready..."
    for i in {1..20}; do
        if pgrep Xorg >/dev/null; then
            echo "Xorg is running."
            return
        fi
        sleep 1
    done

    echo "Xorg not detected after timeout."
}

stop_xrdp_services() {
    xrdp --kill
    xrdp-sesman --kill
    exit 0
}

# Update repository if needed
cd /root/Desktop/Turnstile-Solver || {
    echo "Failed to change directory to Turnstile-Solver"
    exit 1
}

echo "Checking for repository updates..."
git pull origin main || {
    echo "Failed to pull latest changes, continuing with existing code..."
}

python3 -m camoufox fetch

trap "stop_xrdp_services" SIGKILL SIGTERM SIGHUP SIGINT EXIT
start_xrdp_services

if [ "$RUN_API_SOLVER" = "true" ]; then
    echo "Starting API solver in headful mode..."
    xvfb-run -a python3 /root/Desktop/Turnstile-Solver/api_solver.py --browser_type=camoufox --host=0.0.0.0 --debug=$DEBUG
fi
