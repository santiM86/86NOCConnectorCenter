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
pip install -r requirements.txt
cd ..

# 5. Restart Backend Server
echo "Restarting backend service..."
# Important: ensure arslan has visudo NOPASSWD for this exact command
sudo systemctl restart noc-backend

sudo systemctl status noc-backend

echo "========================================"
echo "Deployment Complete at $(date)!"
echo "========================================"
# To see logs

# tail -f /home/arslan/86NOCConnectorCenter/deploy.log
