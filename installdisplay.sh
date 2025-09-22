#!/bin/bash

# This script installs and sets up the display driver for AllStarLink3 on Raspberry Pi.
# Run as any user: bash install_display_driver_script.sh
# Assumptions: Raspberry Pi OS (Debian-based), AllStarLink installed with Asterisk.
# Downloads display_driver.py from https://g1lro.uk/display_driver.py automatically.

set -e  # Exit on error

# Detect current user and paths
USER_HOME="$HOME"
USER_NAME="$USER"
SCRIPT_NAME="display_driver.py"

# Define paths using user variables
VENV_PATH="$USER_HOME/myenv"
SCRIPT_PATH="$USER_HOME/$SCRIPT_NAME"
FAV_FILE="$USER_HOME/favourites.txt"
SERVICE_FILE="/etc/systemd/system/display_driver.service"
FONT_PATH="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DOWNLOAD_URL="https://g1lro.uk/display_driver.py"

# Display detected paths
echo "=== Display Driver Installation for User: $USER_NAME ==="
echo "Home directory: $USER_HOME"
echo "Script path: $SCRIPT_PATH"
echo "Virtual env: $VENV_PATH"
echo "Favourites file: $FAV_FILE"
echo "Download URL: $DOWNLOAD_URL"
echo "=========================================="

# Step 0: Download display_driver.py if not exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Step 0: Downloading display_driver.py from $DOWNLOAD_URL..."
    if wget -O "$SCRIPT_PATH" "$DOWNLOAD_URL"; then
        echo "✓ Successfully downloaded $SCRIPT_PATH"
        chmod +x "$SCRIPT_PATH"
        echo "✓ Made script executable"
    else
        echo "Error: Failed to download $SCRIPT_PATH"
        echo "Please check your internet connection and try again."
        echo "Alternatively, manually download from: $DOWNLOAD_URL"
        exit 1
    fi
else
    echo "Step 0: $SCRIPT_PATH already exists, skipping download."
    # Ensure it's executable
    chmod +x "$SCRIPT_PATH"
fi

# Check if script file exists (after download attempt)
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: $SCRIPT_PATH not found after download attempt."
    echo "Please manually download from: $DOWNLOAD_URL"
    exit 1
fi

# Step 1: Install fonts if needed
if [ ! -f "$FONT_PATH" ]; then
    echo "Step 1: Font file $FONT_PATH not found. Installing fonts-dejavu..."
    sudo apt install -y fonts-dejavu
else
    echo "Step 1: Font file $FONT_PATH found."
fi

# Step 2: Update and upgrade system
echo "Step 2: Updating system..."
sudo apt update && sudo apt upgrade -y

# Step 3: Install required packages
echo "Step 3: Installing Python, build tools, and dependencies..."
sudo apt install -y python3 python3-pip python3-venv git wget fonts-dejavu python3-numpy i2c-tools build-essential

# Step 4: Check and fix /tmp permissions
echo "Step 4: Checking /tmp permissions..."
if mount | grep /tmp | grep noexec > /dev/null; then
    echo "Warning: /tmp is mounted with noexec. Remounting /tmp to allow execution..."
    sudo mount -o remount,exec /tmp || {
        echo "Error: Failed to remount /tmp. You may need to modify /etc/fstab or system settings."
        exit 1
    }
else
    echo "/tmp permissions OK."
fi
sudo chmod 1777 /tmp

# Step 5: Enable SPI interface
echo "Step 5: Enabling SPI interface..."
sudo raspi-config nonint do_spi 0  # 0 enables SPI
if lsmod | grep -q spi_bcm2835; then
    echo "✓ SPI is enabled."
else
    echo "Warning: SPI module not detected. Ensure hardware is connected correctly."
    echo "You may need to run 'sudo raspi-config' and enable SPI manually."
fi

# Step 6: Verify GPIO access
echo "Step 6: Checking GPIO access..."
if groups | grep -q gpio; then
    echo "✓ User is in gpio group."
else
    echo "Adding user $USER_NAME to gpio group..."
    sudo usermod -a -G gpio "$USER_NAME"
    echo "✓ Added to gpio group. Please log out and back in for group changes to take effect."
fi

# Step 7: Verify Asterisk
echo "Step 7: Checking Asterisk installation..."
if command -v asterisk >/dev/null 2>&1; then
    echo "✓ Asterisk is installed."
    echo "Asterisk version: $(asterisk -rx "core show version" 2>/dev/null | head -1 || echo "Unknown")"
else
    echo "Error: Asterisk not found. Please ensure AllStarLink is installed."
    exit 1
fi

# Step 8: Configure sudo permissions for Asterisk
echo "Step 8: Configuring sudo permissions for Asterisk..."
SUDOERS_D="/etc/sudoers.d/asl-display"
if [ ! -f "$SUDOERS_D" ]; then
    echo "Creating sudoers file for $USER_NAME to run asterisk commands..."
    echo "$USER_NAME ALL=(ALL) NOPASSWD: /usr/sbin/asterisk" | sudo tee "$SUDOERS_D" > /dev/null
    sudo chmod 440 "$SUDOERS_D"
    echo "✓ Sudo permissions configured."
else
    echo "✓ Sudo permissions already configured."
fi

# Step 9: Create virtual environment
echo "Step 9: Creating virtual environment at $VENV_PATH..."
if [ -d "$VENV_PATH" ]; then
    echo "Removing existing virtual environment..."
    rm -rf "$VENV_PATH"
fi
python3 -m venv "$VENV_PATH"

# Activate venv
source "$VENV_PATH/bin/activate"

# Step 10: Install Adafruit Blinka and dependencies
echo "Step 10: Installing Adafruit Blinka and dependencies..."
pip install --upgrade pip
pip install --upgrade setuptools
# Attempt to install sysv_ipc, but continue if it fails (optional for Blinka)
echo "Installing sysv_ipc (optional for Blinka)..."
pip install sysv_ipc --no-build-isolation || {
    echo "Warning: sysv_ipc installation failed. Continuing without it, as it's optional for Adafruit Blinka."
}
pip install --upgrade adafruit-python-shell adafruit-blinka

# Step 11: Install specific libraries
echo "Step 11: Installing Adafruit RGB Display and Pillow..."
pip install adafruit-circuitpython-rgb-display pillow

# Step 12: Test Asterisk connectivity from virtual environment
echo "Step 12: Testing Asterisk connectivity..."
TEST_AST_RESULT=""
if sudo -u "$USER_NAME" "$VENV_PATH"/bin/python -c "
import subprocess
try:
    result = subprocess.check_output('sudo asterisk -rx \"rpt lstats 58175\"', shell=True, stderr=subprocess.STDOUT).decode('utf-8')
    print('✓ Asterisk test successful')
except Exception as e:
    print('✗ Asterisk test failed:', str(e))
" 2>/dev/null; then
    echo "✓ Asterisk connectivity test passed."
else
    echo "Warning: Asterisk test failed. Check sudo permissions and Asterisk status."
fi

# Deactivate venv
deactivate

# Step 13: Test run the script
echo "Step 13: Testing $SCRIPT_NAME..."
TEST_PID=""
if sudo -u "$USER_NAME" "$VENV_PATH"/bin/python "$SCRIPT_PATH" >/tmp/display_driver_test.log 2>&1 & then
    TEST_PID=$!
    echo "✓ Test run started successfully (PID: $TEST_PID). Check the display for 10 seconds..."
    sleep 10
    if kill "$TEST_PID" 2>/dev/null; then
        echo "✓ Test run stopped successfully."
    else
        echo "Warning: Could not stop test process. It may still be running."
    fi
else
    echo "✗ Test run failed. Check /tmp/display_driver_test.log for errors:"
    cat /tmp/display_driver_test.log
    echo "You may need to check hardware connections or node number configuration."
fi

# Step 14: Create sample favourites.txt if not exists
if [ ! -f "$FAV_FILE" ]; then
    echo "Step 14: Creating sample favourites.txt..."
    cat > "$FAV_FILE" << EOF
99999
#^^^ Your node number here
# AllStarLink Favourites - Format: Name,NodeNumber
# Up to 6 favourites supported
Hubnet,41223
Parrot,40894
EOF
    chmod 644 "$FAV_FILE"
    echo "✓ Sample favourites.txt created at $FAV_FILE"
    echo "Edit with: nano $FAV_FILE"
else
    echo "Step 14: $FAV_FILE already exists, skipping creation."
    chmod 644 "$FAV_FILE"
fi

# Step 15: Set up systemd service to run the script on boot
echo "Step 15: Setting up systemd service..."
sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Display Driver for AllStarLink - User: $USER_NAME
After=network-online.target asterisk.service
Requires=asterisk.service
Wants=asterisk.service

[Service]
Type=simple
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$USER_HOME
Environment=PATH=$VENV_PATH/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=HOME=$USER_HOME
ExecStart=$VENV_PATH/bin/python $SCRIPT_PATH
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
# Security settings - FIXED for sudo/asterisk compatibility
NoNewPrivileges=no
PrivateTmp=false
ProtectSystem=full
ReadWritePaths=$USER_HOME $VENV_PATH /tmp /run

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd, enable and start service
sudo systemctl daemon-reload
sudo systemctl enable display_driver.service
sudo systemctl restart display_driver.service

# Step 16: Verify service with Asterisk test
echo "Step 16: Verifying service with Asterisk test..."
sleep 5  # Give service time to start
if sudo systemctl is-active --quiet display_driver.service; then
    echo "✓ Service is active and running."
    echo "Testing Asterisk integration..."
    sleep 3  # Wait for script to initialize
    
    # Test asterisk command through service context
    if sudo -u "$USER_NAME" "$VENV_PATH"/bin/python -c "
import subprocess
import time
time.sleep(2)  # Wait for script to fully start
try:
    cmd = 'sudo asterisk -rx \"rpt lstats 58175\"'
    result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=10).decode('utf-8')
    print('✓ Service Asterisk test: SUCCESS')
    print('Output preview:', result[:100] + '...' if len(result) > 100 else result)
except Exception as e:
    print('✗ Service Asterisk test: FAILED -', str(e))
" 2>&1 | grep -q "SUCCESS"; then
        echo "✓ Asterisk integration test passed!"
    else
        echo "Warning: Asterisk integration test failed. Check logs for details."
    fi
    
    echo "Service status:"
    sudo systemctl status display_driver.service --no-pager -l
else
    echo "✗ Service failed to start. Check status:"
    sudo systemctl status display_driver.service --no-pager -l
    echo "Check logs with: journalctl -u display_driver.service -f"
    echo ""
    echo "Common troubleshooting steps:"
    echo "1. Check if display_driver.py runs manually:"
    echo "   $VENV_PATH/bin/python $SCRIPT_PATH"
    echo "2. Verify node number (58175) in $SCRIPT_PATH"
    echo "3. Check hardware connections (SPI, display, buttons)"
    echo "4. Ensure SPI is enabled: lsmod | grep spi_bcm2835"
    echo "5. Check sudo permissions: sudo cat /etc/sudoers.d/asl-display"
fi

# Step 17: Display completion message
echo ""
echo "=== Installation Complete! ==="
echo "User: $USER_NAME"
echo "Script: $SCRIPT_PATH"
echo "Virtual Environment: $VENV_PATH"
echo "Favourites File: $FAV_FILE"
echo "Service: display_driver.service"
echo ""
echo "Service Status: $(sudo systemctl is-active display_driver.service)"
echo ""
echo "🚀 QUICK START GUIDE:"
echo "1. Check service status: sudo systemctl status display_driver.service"
echo "2. View live logs: journalctl -u display_driver.service -f"
echo "3. View boot logs: journalctl -u display_driver.service -b"
echo "4. Restart service: sudo systemctl restart display_driver.service"
echo "5. Edit favourites: nano $FAV_FILE"
echo "6. Test manually: $VENV_PATH/bin/python $SCRIPT_PATH"
echo ""
echo "📱 HARDWARE CHECKLIST:"
echo "- ✓ SPI enabled (check with 'lsmod | grep spi_bcm2835')"
echo "- ✓ Hardware connected: ST7789 display (CS on CE0, DC on D25, backlight on D22)"
echo "- ✓ Buttons: GPIO 23 (Button A), GPIO 24 (Button B)"
echo "- ✓ Font: $FONT_PATH"
echo "- ✓ Asterisk running: sudo asterisk -rx \"core show version\""
echo ""
echo "🎛️ BUTTON CONTROLS:"
echo "Main Screen:"
echo "  Button A: Cycle through options (Favourites → Nodes)"
echo "  Button B: Select/Connect (Favourites menu or Disconnect nodes)"
echo ""
echo "Favourites Menu:"
echo "  Button A: Cycle through favourites"
echo "  Button B: Connect to selected favourite or Exit"
echo ""
echo "💾 FAVOURITES SETUP:"
echo "Edit $FAV_FILE with format: Name,NodeNumber"
echo "Example:"
echo "  Hubnet,41223"
echo "  Club,57699"
echo "  Weather,41235"
echo ""
echo "🔧 TROUBLESHOOTING:"
echo "If display is blank:"
echo "  1. Check connections and power"
echo "  2. Verify SPI: sudo raspi-config (Interfacing Options > SPI)"
echo "  3. Check test logs: cat /tmp/display_driver_test.log"
echo ""
echo "If buttons don't work:"
echo "  1. Check GPIO connections (23=A, 24=B)"
echo "  2. Verify gpio group: groups | grep gpio"
echo ""
echo "If Asterisk commands fail:"
echo "  1. Check sudo permissions: sudo cat /etc/sudoers.d/asl-display"
echo "  2. Test manually: sudo -u $USER_NAME sudo asterisk -rx 'core show version'"
echo "  3. Check Asterisk status: sudo systemctl status asterisk"
echo ""
echo "Reboot recommended to ensure all changes take effect: sudo reboot"
echo "========================"