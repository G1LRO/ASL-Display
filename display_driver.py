#!/home/admin/myenv/bin/python
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
import threading
import queue
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

# AllStarLink node number
node_number = "58175"

# Read favorites from file
def read_favorites():
    try:
        with open("/home/admin/favourites.txt", "r") as f:
            lines = f.readlines()[:6]  # Up to 6 favorites
        favorites = {}
        for line in lines:
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1].isdigit():
                favorites[parts[1]] = parts[0]
        return favorites
    except Exception as e:
        print(f"Favorites file error: {e}")
        return {}

# Event queue for button presses and display updates
event_queue = queue.Queue()

# Button monitoring thread
def button_monitor():
    global last_button_a_state, last_button_b_state
    last_button_a_time = 0
    last_button_b_time = 0
    debounce_delay = 0.05
    
    while True:
        current_time = time.time()
        
        # Button A: Cycle selection
        button_a_state = not button_a.value
        if button_a_state and not last_button_a_state and (current_time - last_button_a_time) > debounce_delay:
            event_queue.put({'type': 'button_a', 'time': current_time})
            last_button_a_time = current_time
            print("Button A pressed")
        
        # Button B: Connect/disconnect or switch modes
        button_b_state = not button_b.value
        if button_b_state and not last_button_b_state and (current_time - last_button_b_time) > debounce_delay:
            event_queue.put({'type': 'button_b', 'time': current_time})
            last_button_b_time = current_time
            print("Button B pressed")
        
        last_button_a_state = button_a_state
        last_button_b_state = button_b_state
        
        time.sleep(0.01)  # 10ms polling for buttons

# Periodic timer thread
def periodic_timer():
    while True:
        time.sleep(10)  # 10 second interval
        event_queue.put({'type': 'periodic_update', 'time': time.time()})
        print("Periodic update triggered")

# Node status update thread
def node_status_updater():
    global connected_nodes, Nodes
    while True:
        try:
            cmd = f"sudo asterisk -rx 'rpt lstats {node_number}'"
            result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode("utf-8")
            print("AllStarLink output:", result)  # Debug
            lines = result.splitlines()[2:]  # Skip header lines
            new_connected_nodes = []
            for line in lines:
                if "ESTABLISHED" in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        new_connected_nodes.append(parts[0])
            
            # Only trigger display update if nodes changed
            if new_connected_nodes != connected_nodes:
                connected_nodes = new_connected_nodes
                Nodes = [f"{favorites.get(node, 'Node')}: {node}" for node in connected_nodes[:3]] if connected_nodes else ["Nodes: None"]
                event_queue.put({'type': 'node_update', 'time': time.time()})
                print("Node status changed, triggering display update")
                
        except subprocess.CalledProcessError as e:
            print(f"AllStarLink error: {e.output.decode('utf-8')}")  # Debug
            if Nodes != ["Nodes: Err"]:
                Nodes = ["Nodes: Err"]
                event_queue.put({'type': 'node_update', 'time': time.time()})
        except FileNotFoundError:
            print("Asterisk/sudo not found")  # Debug
            if Nodes != ["Nodes: No Asterisk"]:
                Nodes = ["Nodes: No Asterisk"]
                event_queue.put({'type': 'node_update', 'time': time.time()})
        
        time.sleep(5)  # Check nodes every 5 seconds

# Handle button events
def handle_button_event(event_type, display_mode, selection_index, connected_nodes, favorites_list):
    new_mode = display_mode
    new_index = selection_index
    error_message = ""
    
    if event_type == 'button_a':
        if display_mode == "main":
            new_index = (selection_index + 1) % (1 + len(connected_nodes))  # Include Favourites
        else:  # favorites mode
            new_index = (selection_index + 1) % len(favorites_list)  # Include Exit
        print(f"Button A: Selected index {new_index}")
        
    elif event_type == 'button_b':
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
            if selection_index < len(favorites_list) - 1:  # Node selected (not Exit)
                node = favorites_list[selection_index][1]
                try:
                    cmd = f"sudo asterisk -rx 'rpt cmd {node_number} ilink 3 {node}'"
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
            elif selection_index == len(favorites_list) - 1:  # Exit selected
                new_mode = "main"
                new_index = 0
                print("Button B: Exited to main mode")
    
    return new_mode, new_index, error_message

# System info cache
IP = "IP: Loading..."
Uptime = "Uptime: Loading..."

# Update system information
def update_system_info():
    global IP, Uptime
    try:
        IP = "IP: " + subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode("utf-8").strip()
    except Exception as e:
        IP = "IP: Error"
        print(f"IP error: {e}")
    
    try:
        seconds = float(subprocess.check_output("cat /proc/uptime | awk '{print $1}'", shell=True).decode("utf-8").strip())
        days = int(seconds // (24 * 3600))
        hours = int((seconds % (24 * 3600)) // 3600)
        minutes = int((seconds % 3600) // 60)
        Uptime = f"Uptime: {days:02d}:{hours:02d}:{minutes:02d}"
    except Exception as e:
        Uptime = "Uptime: Error"
        print(f"Uptime error: {e}")

# Display update function
def update_display(display_mode, selection_index, favorites_list, error_message):
    t1 = time.time()
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
    t2 = time.time()
    disp.image(image, rotation)
    t3 = time.time()
    
    print(f"Display render time: {t2 - t1:.3f}s, Display update time: {t3 - t2:.3f}s")

# Initialize state
display_mode = "main"
selection_index = 0
favorites = read_favorites()
last_button_a_state = False
last_button_b_state = False
error_message = ""
connected_nodes = []  # Cache nodes
Nodes = ["Nodes: None"]  # Cache display

# Initial system info update
update_system_info()

# Wait for Asterisk to be ready
time.sleep(10)

# Start background threads
button_thread = threading.Thread(target=button_monitor, daemon=True)
periodic_thread = threading.Thread(target=periodic_timer, daemon=True)
node_thread = threading.Thread(target=node_status_updater, daemon=True)

button_thread.start()
periodic_thread.start()
node_thread.start()

# Initial display update
favorites_list = [(name, num) for num, name in favorites.items()][:6]
favorites_list.append(("Exit", "0"))
update_display(display_mode, selection_index, favorites_list, error_message)

print("Event-driven display driver started")

# Main event loop
while True:
    try:
        # Wait for events (blocking)
        event = event_queue.get(timeout=1.0)  # 1 second timeout
        
        display_updated = False
        
        if event['type'] in ['button_a', 'button_b']:
            # Handle button events
            favorites_list = [(name, num) for num, name in favorites.items()][:6]
            favorites_list.append(("Exit", "0"))
            
            display_mode, selection_index, error_message = handle_button_event(
                event['type'], display_mode, selection_index, connected_nodes, favorites_list
            )
            
            # Update display immediately on button press
            update_display(display_mode, selection_index, favorites_list, error_message)
            display_updated = True
            
        elif event['type'] == 'periodic_update':
            # Update system info and display
            update_system_info()
            favorites_list = [(name, num) for num, name in favorites.items()][:6]
            favorites_list.append(("Exit", "0"))
            update_display(display_mode, selection_index, favorites_list, error_message)
            display_updated = True
            
        elif event['type'] == 'node_update':
            # Node status changed, update display
            favorites_list = [(name, num) for num, name in favorites.items()][:6]
            favorites_list.append(("Exit", "0"))
            update_display(display_mode, selection_index, favorites_list, error_message)
            display_updated = True
        
        if display_updated:
            print(f"Display updated due to {event['type']} event")
            
    except queue.Empty:
        # Timeout - no events to process
        continue
    except KeyboardInterrupt:
        print("\nShutting down...")
        break
    except Exception as e:
        print(f"Error in main loop: {e}")
        time.sleep(1)
