#!/bin/bash
set -e # Stop the script immediately if any command fails

# Restore standard Linux PATH because systemd limits it to just the python python venv
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH

# Load Node Version Manager (NVM) so 'nvm' and 'yarn' commands become available
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"


# Log all output to a deployment log file
exec > /home/arslan/86NOCConnectorCenter/deploy.log 2>&1

echo "========================================"
echo "Deployment started at $(date)"
echo "========================================"

# 1. Go to project directory
cd /home/arslan/86NOCConnectorCenter

# 2. Pull latest changes (hard reset to match remote)
echo "Pulling latest code from main branch..."
git fetch origin main
git reset --hard origin/main

# 3. Build Frontend
echo "Building frontend..."
cd frontend
nvm use v20
yarn install
yarn run build
cd ..

# 4. Update Backend
echo "Installing backend dependencies..."
cd backend
# Use the existing virtual environment pip
venv/bin/pip install -r requirements.txt
cd ..

# 5. Restart Backend Server
# IMPORTANT: This script is a CHILD of noc-backend (spawned by the webhook).
# We CANNOT call systemctl restart directly — systemd kills entire cgroup (including us).
# Instead, we touch a trigger file. A separate systemd path unit (noc-restart.path)
# watches for this file and restarts noc-backend from OUTSIDE the cgroup.
rm -f /tmp/noc-restart-trigger
touch /tmp/noc-restart-trigger

echo "========================================"
echo "Deployment Complete at $(date)!"
echo "========================================"
