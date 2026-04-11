#!/bin/bash
# setup.sh — One-time server setup for discord-scrum-master on Oracle Cloud (Ubuntu 22.04 ARM)
# Run as: bash setup.sh

set -e

REPO_URL="https://github.com/YOUR_USERNAME/discord-scrum-master.git"  # ← change this
APP_DIR="/home/ubuntu/discord-scrum-master"
SERVICE_NAME="scrum-bot"

echo "=== [1/5] Updating system packages ==="
sudo apt-get update -y
sudo apt-get install -y python3.11 python3.11-venv python3-pip git

echo "=== [2/5] Cloning repository ==="
if [ -d "$APP_DIR" ]; then
    echo "Repo already exists — pulling latest..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

echo "=== [3/5] Setting up Python virtual environment ==="
cd "$APP_DIR"
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [4/5] Creating .env file ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" <<EOF
DISCORD_TOKEN=
DISCORD_GUILD_ID=

CHANNEL_SPRINT_DISCUSS=
CHANNEL_STANDUP=
CHANNEL_TASKS=
CHANNEL_BLOCKERS=
CHANNEL_AI_REPORT=
CHANNEL_CHANGELOG=

GROQ_API_KEY=

TIMEZONE=Asia/Kolkata
TEAM_LOG_REPO_PATH=$APP_DIR
EOF
    echo ""
    echo ">>> .env created at $APP_DIR/.env"
    echo ">>> Fill in your tokens before starting the bot:"
    echo "    nano $APP_DIR/.env"
    echo ""
else
    echo ".env already exists — skipping."
fi

echo "=== [5/5] Installing systemd service ==="
sudo cp "$APP_DIR/deploy/scrum-bot.service" /etc/systemd/system/${SERVICE_NAME}.service
sudo sed -i "s|APP_DIR|$APP_DIR|g" /etc/systemd/system/${SERVICE_NAME}.service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}

echo ""
echo "====================================================="
echo " Setup complete."
echo ""
echo " Next steps:"
echo "   1. Fill in your .env:  nano $APP_DIR/.env"
echo "   2. Start the bot:      sudo systemctl start scrum-bot"
echo "   3. Check logs:         sudo journalctl -u scrum-bot -f"
echo "====================================================="
