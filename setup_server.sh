#!/bin/bash
# setup_server.sh — One-command setup for Restaurant-IQ Bot on Ubuntu
#
# Run this on your Oracle Cloud (or any Ubuntu) server with:
#   bash setup_server.sh
#
# It will: install Python, download your code, install packages,
# and set up the bot to start automatically on boot.

set -e  # Stop if anything goes wrong

echo ""
echo "======================================="
echo "  Restaurant-IQ Bot — Server Setup"
echo "======================================="
echo ""

# ── Step 1: Update system ─────────────────────────────────────────────────────
echo "Step 1/6: Updating system packages (takes ~1 minute)..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git
echo "         Done ✓"

# ── Step 2: Download the bot code ─────────────────────────────────────────────
echo "Step 2/6: Downloading the bot code..."
BOT_DIR="$HOME/restaurant-iq-bot"

if [ -d "$BOT_DIR/.git" ]; then
    echo "         Existing install found — updating..."
    cd "$BOT_DIR"
    git fetch origin
    git checkout claude/complete-app-release-UWnTF
    git pull origin claude/complete-app-release-UWnTF
else
    git clone https://github.com/kfrem/restaurant-iq-bot.git "$BOT_DIR"
    cd "$BOT_DIR"
    git checkout claude/complete-app-release-UWnTF
fi
echo "         Done ✓"

# ── Step 3: Create isolated Python environment ────────────────────────────────
echo "Step 3/6: Creating Python environment..."
cd "$BOT_DIR"
python3 -m venv venv
echo "         Done ✓"

# ── Step 4: Install Python packages ──────────────────────────────────────────
echo "Step 4/6: Installing packages (takes 2-4 minutes)..."
"$BOT_DIR/venv/bin/pip" install -q --upgrade pip
"$BOT_DIR/venv/bin/pip" install -q -r "$BOT_DIR/requirements.txt"
echo "         Done ✓"

# ── Step 5: Check for .env file ───────────────────────────────────────────────
echo "Step 5/6: Checking configuration..."
if [ ! -f "$BOT_DIR/.env" ]; then
    echo ""
    echo "  ⚠️  No .env file found — you must add it before starting the bot."
    echo "  See instructions below for how to upload it from your Windows PC."
    echo ""
else
    echo "         .env file found ✓"
fi

# ── Step 6: Create systemd service (auto-start on boot) ──────────────────────
echo "Step 6/6: Setting up auto-start service..."
VENV_PYTHON="$BOT_DIR/venv/bin/python"
USERNAME=$(whoami)

sudo tee /etc/systemd/system/restaurant-iq.service > /dev/null <<EOF
[Unit]
Description=Restaurant-IQ Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USERNAME
WorkingDirectory=$BOT_DIR
ExecStart=$VENV_PYTHON bot.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable restaurant-iq
echo "         Done ✓"

# ── Open firewall port for Stripe webhooks ────────────────────────────────────
sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || true

echo ""
echo "======================================="
echo "  Setup complete!"
echo "======================================="
echo ""

if [ ! -f "$BOT_DIR/.env" ]; then
    echo "NEXT: Upload your .env file, then start the bot:"
    echo ""
    echo "  1. Upload .env (from your Windows PC — see guide)"
    echo "  2. sudo systemctl start restaurant-iq"
    echo "  3. sudo systemctl status restaurant-iq"
else
    echo "NEXT: Start the bot:"
    echo ""
    echo "  sudo systemctl start restaurant-iq"
    echo ""
    echo "Then check it is running:"
    echo "  sudo systemctl status restaurant-iq"
fi

echo ""
echo "To see live logs at any time:"
echo "  sudo journalctl -u restaurant-iq -f"
echo ""
echo "To restart the bot (e.g. after updating .env):"
echo "  sudo systemctl restart restaurant-iq"
echo ""
