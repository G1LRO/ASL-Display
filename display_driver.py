#!/usr/bin/env python3
# Version at https://github.com/G1LRO/ASL-Display
# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-FileCopyrightText: 2025 GU1LRO
# SPDX-License-Identifier: MIT
# SPDX-License-Identifier: CC-BY-NC-4.0
#
# This work is licensed under the Creative Commons Attribution-NonCommercial 4.0
# International License. To view a copy of this license, visit
# http://creativecommons.org/licenses/by-nc/4.0/ or send a letter to Creative
# Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# This software is free to use and modify for noncommercial purposes. The original
# copyright notices (including those of Adafruit Industries and GU1LRO) must be
# retained in all copies or substantial portions of the software.
# -*- coding: utf-8 -*-
import time
import subprocess
import digitalio
import board
import os
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import st7789

# Configuration for CS and DC pins
cs_pin = digitalio.DigitalInOut(board.CE0)
dc_pin = digitalio.DigitalInOut(board.D25)
reset_pin = None
BAUDRATE = 24000000

# Setup SPI bus
spi = board.SPI()

# Configure buttons (Adafruit Mini PiTFT: Button A on GPIO 23, Button B on GPIO 24)
button_a = digitalio.DigitalInOut(board.D23)
button_a.direction = digitalio.Direction.INPUT
button_a.pull = digitalio.Pull.UP
button_b = digitalio.DigitalInOut(board.D24)
button_b.direction = digitalio.Direction.INPUT
button_b.pull = digitalio.Pull.UP

# Create the ST7789 display
try:
    disp = st7789.ST7789(
        spi,
        cs=cs_pin,
        dc=dc_pin,
        rst=reset_pin,
        baudrate=BAUDRATE,
        width=240,
        height=240,
        x_offset=0,
        y_offset=80,
    )
except Exception as e:
    print(f"Display init error: {e}")
    exit(1)

# Create blank image for drawing
height = disp.width
width = disp.height
image = Image.new("RGB", (width, height))
rotation = 180

# Get drawing object
draw = ImageDraw.Draw(image)
draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
disp.image(image, rotation)

# Define constants
padding = -2
top = padding
x = 0

# Load font
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
except Exception as e:
    print(f"Font error: {e}")
    exit(1)

# Turn on backlight
backlight = digitalio.DigitalInOut(board.D22)
backlight.switch_to_output()
backlight.value = True

# Read node number and favorites from file
def read_config():
    favorites_file = os.path.expanduser("~/favourites.txt")
    try:
        with open(favorites_file, "r") as f:
            lines = f.readlines()
        
        # First line should be the node number
        if not lines:
            print("Error: favourites.txt is empty")
            return None, {}
        
        node_number_line = lines[0].strip()
        if not node_number_line or not node_number_line.isdigit():
            print(f"Error: First line '{node_number_line}' is not a valid node number")
            return None, {}
        
        node_number = node_number_line
        print(f"Using node number: {node_number}")
        
        # Read favorites from remaining lines
        favorites = {}
        for line in lines[1:7]:  # Lines 2-7 (up to 6 favorites)
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1].isdigit():
                favorites[parts[1]] = parts[0]
        
        print(f"Loaded favorites: {favorites}")
        return node_number, favorites
        
    except Exception as e:
        print(f"Config file error: {e}")
        return None, {}

# Get configuration at startup
node_number, favorites = read_config()
if node_number is None:
    print("Failed to read node number from favourites.txt")
    exit(1)

# Handle button presses with edge detection
def handle_buttons(display_mode, selection_index, connected_nodes, favorites_list):
    current_time = time.time()
    global last_button_a_time, last_button_b_time, last_button_a_state, last_button_b_state
    new_mode = display_mode
    new_index = selection_index
    error_message = ""
    
    # Button A: Cycle selection
    button_a_state = not button_a.value
    if button_a_state and not last_button_a_state and (current_time - last_button_a_time) > debounce_delay:
        if display_mode == "main":
            new_index = (selection_index + 1) % (1 + len(connected_nodes))  # Include Favourites
        else:  # favorites mode
            new_index = (selection_index + 1) % len(favorites_list)  # Include Exit
        last_button_a_time = current_time
        print(f"Button A: Selected index {new_index}")
    
    # Button B: Connect/disconnect or switch modes
    button_b_state = not button_b.value
    if button_b_state and not last_button_b_state and (current_time - last_button_b_time) > debounce_delay:
        if display_mode == "main":
            if selection_index == 0:  # Favourites selected
                new_mode = "favorites"
                new_index = 0
                print("Button B: Switched to favorites mode")
            elif selection_index <= len(connected_nodes):  # Node selected
                node = connected_nodes[selection_index - 1]
                try:
                    cmd = f"sudo asterisk -rx 'rpt cmd {node_number} ilink 1 {node}'"
                    result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode("utf-8")
                    print(f"Button B: Disconnected node {node} (Result: {result})")
                except subprocess.CalledProcessError as e:
                    error_message = "Disconnect failed"
                    print(f"Button B disconnect error: {e.output.decode('utf-8')}")
                except Exception as e:
                    error_message = "Disconnect error"
                    print(f"Button B disconnect error: {e}")
        else:  # favorites mode
            print(f"Button B pressed in favorites mode, selection_index: {selection_index}, favorites_list length: {len(favorites_list)}")
            if selection_index < len(favorites_list) - 1:  # Node selected (not Exit)
                name, node = favorites_list[selection_index]
                print(f"Attempting to connect to {name}: {node}")
                try:
                    cmd = f"sudo asterisk -rx 'rpt cmd {node_number} ilink 3 {node}'"
                    print(f"Executing command: {cmd}")  # Debug
                    result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode("utf-8")
                    print(f"Button B: Connected node {node} (Result: {result})")
                    new_mode = "main"
                    new_index = 0
                except subprocess.CalledProcessError as e:
                    error_message = "Connect failed"
                    print(f"Button B connect error: {e.output.decode('utf-8')}")
                except Exception as e:
                    error_message = "Connect error"
                    print(f"Button B connect error: {e}")
            else:  # Exit selected
                print("Button B: Exit selected")
                new_mode = "main"
                new_index = 0
                print("Button B: Exited to main mode")
        last_button_b_time = current_time
    
    last_button_a_state = button_a_state
    last_button_b_state = button_b_state
    return new_mode, new_index, error_message

# Initialize state
display_mode = "main"
selection_index = 0
last_button_a_time = 0
last_button_b_time = 0
last_button_a_state = False
last_button_b_state = False
debounce_delay = 0.05  # 50ms debounce
last_display_update = 0
last_nodes_update = 0
display_update_interval = 1.0  # Update display every 1s
nodes_update_interval = 5.0  # Update nodes every 5s
error_message = ""
connected_nodes = []  # Cache nodes
Nodes = ["Nodes: None"]  # Cache display

# Wait for Asterisk to be ready
time.sleep(10)

while True:
    current_time = time.time()
    
    # Update node status periodically
    if current_time - last_nodes_update >= nodes_update_interval:
        try:
            cmd = f"sudo asterisk -rx 'rpt lstats {node_number}'"
            result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode("utf-8")
            print("AllStarLink output:", result)  # Debug
            lines = result.splitlines()[2:]  # Skip header lines
            connected_nodes = []
            for line in lines:
                if "ESTABLISHED" in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        connected_nodes.append(parts[0])
            Nodes = [f"{favorites.get(node, 'Node')}: {node}" for node in connected_nodes[:3]] if connected_nodes else ["Nodes: None"]
        except subprocess.CalledProcessError as e:
            print(f"AllStarLink error: {e.output.decode('utf-8')}")  # Debug
            Nodes = ["Nodes: Err"]
        except FileNotFoundError:
            print("Asterisk/sudo not found")  # Debug
            Nodes = ["Nodes: No Asterisk"]
        last_nodes_update = current_time
    
    # Get system info
    IP = "IP: Error"
    Uptime = "Uptime: Error"
    
    try:
        IP = "IP: " + subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode("utf-8").strip()
    except Exception as e:
        print(f"IP error: {e}")
    
    try:
        seconds = float(subprocess.check_output("cat /proc/uptime | awk '{print $1}'", shell=True).decode("utf-8").strip())
        days = int(seconds // (24 * 3600))
        hours = int((seconds % (24 * 3600)) // 3600)
        minutes = int((seconds % 3600) // 60)
        Uptime = f"Uptime: {days:02d}:{hours:02d}:{minutes:02d}"
    except Exception as e:
        print(f"Uptime error: {e}")
    
    # Prepare favorites list (add Exit)
    favorites_list = [(name, num) for num, name in favorites.items()][:6]
    favorites_list.append(("Exit", "0"))
    print(f"Current favorites_list: {favorites_list}")  # Debug
    
    # Handle buttons
    display_mode, selection_index, error_message = handle_buttons(display_mode, selection_index, connected_nodes, favorites_list)
    
    # Update display if interval elapsed
    if current_time - last_display_update >= display_update_interval:
        draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
        
        # Prepare display
        y = top
        if display_mode == "main":
            # Line 1: IP
            draw.text((x, y), IP, font=font, fill="#FFFFFF")
            y += font.getbbox(IP)[3] - font.getbbox(IP)[1] + 12
            
            # Line 2: Uptime
            draw.text((x, y), Uptime, font=font, fill="#0000FF")  # Blue
            y += font.getbbox(Uptime)[3] - font.getbbox(Uptime)[1] + 12
            
            # Line 3: Favourites
            label = "> Favourites" if selection_index == 0 else "  Favourites"
            draw.text((x, y), label, font=font, fill="#FFFF00")  # Yellow
            y += font.getbbox(label)[3] - font.getbbox(label)[1] + 12
            
            # Lines 4-6: Nodes
            for i, node in enumerate(Nodes):
                label = f"> {node}" if selection_index == i + 1 else f"  {node}"
                draw.text((x, y), label, font=font, fill="#00FF00")
                y += font.getbbox(node)[3] - font.getbbox(node)[1] + 12
            
            # Error message (if any)
            if error_message:
                draw.text((x, y), error_message, font=font, fill="#FF0000")
        else:  # favorites mode
            print(f"Displaying favorites, selection_index: {selection_index}")  # Debug
            for i, (name, num) in enumerate(favorites_list):
                label = f"> {name}" if selection_index == i else f"  {name}"
                if name != "Exit":
                    label += f": {num}"
                draw.text((x, y), label, font=font, fill="#FFFF00" if name == "Exit" else "#00FF00")  # Yellow for Exit
                y += font.getbbox(label)[3] - font.getbbox(label)[1] + 12
            
            # Error message (if any)
            if error_message:
                draw.text((x, y), error_message, font=font, fill="#FF0000")
        
        # Display image
        disp.image(image, rotation)
        last_display_update = current_time
    
    time.sleep(0.005)  # Fast loop for button responsiveness