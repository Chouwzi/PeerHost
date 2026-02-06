#!/bin/bash
# PeerHost VPS Setup Script for Ubuntu/Debian
# Run as root: sudo bash setup_vps.sh

set -e

echo "=========================================="
echo "    PeerHost Coordinator VPS Setup"
echo "=========================================="

# Configuration
INSTALL_DIR="/opt/peerhost"
SERVICE_USER="peerhost"
PYTHON_VERSION="python3"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo bash setup_vps.sh)"
    exit 1
fi

# Step 1: Update system and install dependencies
echo "[1/7] Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-venv python3-pip git curl

# Step 2: Create service user
echo "[2/7] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /bin/false $SERVICE_USER
    echo "User '$SERVICE_USER' created."
else
    echo "User '$SERVICE_USER' already exists."
fi

# Step 3: Create installation directory
echo "[3/7] Setting up installation directory..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

# If code doesn't exist, clone it
if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
    echo "Cloning PeerHost repository..."
    git clone https://github.com/Chouwzi/PeerHost.git .
else
    echo "Code already exists. Pulling latest..."
    git pull origin main || true
fi

# Step 4: Create Python virtual environment
echo "[4/7] Setting up Python virtual environment..."
$PYTHON_VERSION -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Step 5: Set permissions
echo "[5/7] Setting file permissions..."
chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR

# Make cloudflared executable
if [ -f "$INSTALL_DIR/app/storage/server_tunnel/cloudflared-linux-amd64" ]; then
    chmod +x $INSTALL_DIR/app/storage/server_tunnel/cloudflared-linux-amd64
    echo "cloudflared-linux-amd64 is now executable."
fi

# Step 6: Install systemd service
echo "[6/7] Installing systemd service..."
cp $INSTALL_DIR/services/peerhost.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable peerhost.service

# Step 7: Enable service (but don't start - user needs to configure first)
echo "[7/7] Enabling PeerHost service..."
echo "Service enabled but NOT started - you need to configure it first."

echo ""
echo "=========================================="
echo "    Setup Complete!"
echo "=========================================="
echo ""
echo "NEXT STEPS (Required before starting):"
echo "  1. Edit /opt/peerhost/app/settings.json"
echo "     - Set secret_key to a secure random string"
echo "     - Set game_hostname to your domain"
echo ""
echo "  2. Set up Cloudflare Tunnel in /opt/peerhost/app/storage/server_tunnel/"
echo "     - Copy api_config.yaml and credentials file"
echo "     - Make sure cloudflared is executable:"
echo "       chmod +x /opt/peerhost/app/storage/server_tunnel/cloudflared-linux-amd64"
echo ""
echo "  3. Start the service:"
echo "     sudo systemctl start peerhost"
echo ""
echo "Useful commands:"
echo "  - Check status:  sudo systemctl status peerhost"
echo "  - View logs:     sudo journalctl -u peerhost -f"
echo "  - Restart:       sudo systemctl restart peerhost"
echo "  - Stop:          sudo systemctl stop peerhost"
echo ""
