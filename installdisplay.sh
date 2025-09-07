#!/bin/bash

# This script installs and sets up the display_driver.py for AllStarLink3 on Raspberry Pi.
# Run as admin user: bash install_display_driver_script.sh
# Assumptions: Raspberry Pi OS (Debian-based), AllStarLink installed with Asterisk.
# The display_driver.py file should be downloaded from https://g1lro.uk/display_driver.py and placed in /home/admin before running this script.
# If the file is named differently, adjust the SCRIPT_PATH variable below.

set -e  # Exit on error

# Define paths
VENV_PATH="/home/admin/myenv"
SCRIPT_PATH="/home/admin/display_driver.py"
FAV_FILE="/home/admin/favourites.txt"
SERVICE_FILE="/etc/systemd/system/display_driver.service"
FONT_PATH="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Check if script file exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: $SCRIPT_PATH not found. Please download it from https://g1lro.uk/display_driver.py and place it in /home/admin."
    exit 1
fi

# Check if font file exists
if [ ! -f "$FONT_PATH" ]; then
    echo "Error: Font file $FONT_PATH not found. Installing fonts-dejavu..."
    sudo apt install -y fonts-dejavu
fi

# Step 1: Update and upgrade system
echo "Updating system..."
sudo apt update && sudo apt upgrade -y

# Step 2: Install required packages
echo "Installing Python, build tools, and dependencies..."
sudo apt install -y python3 python3-pip python3-venv git wget fonts-dejavu python3-numpy i2c-tools build-essential

# Step 3: Check and fix /tmp permissions
echo "Checking /tmp permissions..."
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

# Step 4: Enable SPI interface
echo "Enabling SPI interface..."
sudo raspi-config nonint do_spi 0  # 0 enables SPI
if lsmod | grep -q spi_bcm2835; then
    echo "SPI is enabled."
else
    echo "Warning: SPI module not detected. Ensure hardware is connected correctly."
fi

# Step 5: Verify GPIO access
echo "Checking GPIO access..."
if groups | grep -q gpio; then
    echo "User is in gpio group."
else
    echo "Adding user to gpio group..."
    sudo usermod -a -G gpio admin
fi

# Step 6: Verify Asterisk
echo "Checking Asterisk installation..."
if command -v asterisk >/dev/null 2>&1; then
    echo "Asterisk is installed."
else
    echo "Error: Asterisk not found. Please ensure AllStarLink is installed."
    exit 1
fi

# Step 7: Create virtual environment
echo "Creating virtual environment..."
rm -rf "$VENV_PATH"  # Remove if exists (careful!)
python3 -m venv "$VENV_PATH"

# Activate venv
source "$VENV_PATH/bin/activate"

# Step 8: Install Adafruit Blinka and dependencies
echo "Installing Adafruit Blinka and dependencies..."
pip install --upgrade pip
pip install --upgrade setuptools
# Attempt to install sysv_ipc, but continue if it fails (optional for Blinka)
pip install sysv_ipc --no-build-isolation || {
    echo "Warning: sysv_ipc installation failed. Continuing without it, as it's optional for Adafruit Blinka."
}
pip install --upgrade adafruit-python-shell adafruit-blinka

# Step 9: Install specific libraries
echo "Installing Adafruit RGB Display and Pillow..."
pip install adafruit-circuitpython-rgb-display pillow

# Step 10: Test run the script
echo "Testing display_driver.py..."
if sudo $VENV_PATH/bin/python "$SCRIPT_PATH" >/tmp/display_driver_test.log 2>&1 & sleep 5; then
    echo "Test run started successfully. Check the display."
    kill $! 2>/dev/null || true
else
    echo "Test run failed. Check /tmp/display_driver_test.log for errors."
    cat /tmp/display_driver_test.log
fi

# Deactivate venv
deactivate

# Step 11: Create sample favourites.txt if not exists
if [ ! -f "$FAV_FILE" ]; then
    echo "Creating sample favourites.txt..."
    echo "Hubnet,41223" > "$FAV_FILE"
    echo "# Add your favorites in format: Name,NodeNumber (one per line)" >> "$FAV_FILE"
fi

# Step 12: Set up systemd service to run the script on boot
echo "Setting up systemd service..."
sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Display Driver for AllStarLink
After=multi-user.target

[Service]
User=admin
WorkingDirectory=/home/admin
ExecStart=$VENV_PATH/bin/python $SCRIPT_PATH
Restart=always
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd, enable and start service
sudo systemctl daemon-reload
sudo systemctl enable display_driver.service
sudo systemctl restart display_driver.service

# Step 13: Verify
echo "Installation complete!"
echo "Check service status with: sudo systemctl status display_driver.service"
echo "View logs with: journalctl -u display_driver.service -b"
echo "If the display is blank, verify:"
echo "- SPI is enabled (check with 'lsmod | grep spi_bcm2835')."
echo "- Hardware connections: ST7789 display (CS on CE0, DC on D25, backlight on D22), buttons (GPIO 23, 24)."
echo "- $SCRIPT_PATH exists and has correct node number (default: 58175)."
echo "- Font file exists at $FONT_PATH."
echo "- Asterisk is running (check with 'sudo asterisk -rx \"core show version\"')."
echo "- Check test run logs at /tmp/display_driver_test.log if the test failed."
echo "- If sysv_ipc issues persist, check /tmp permissions or system security settings."
echo "Reboot if necessary: sudo reboot"