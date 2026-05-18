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
import socket
import re
import threading
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import st7789

VERSION = "1.75"

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

draw = ImageDraw.Draw(image)
draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
disp.image(image, rotation)

padding = -2
top = padding
x = 0

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
except Exception as e:
    print(f"Font error: {e}")
    exit(1)

try:
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
except Exception:
    font_small = font

backlight = digitalio.DigitalInOut(board.D22)
backlight.switch_to_output()
backlight.value = True


def read_config():
    """Read node number (line 1) and up to 6 favourites from ~/favourites.txt."""
    favorites_file = os.path.expanduser("~/favourites.txt")
    try:
        with open(favorites_file, "r") as f:
            lines = f.readlines()

        if not lines:
            print("Error: favourites.txt is empty")
            return None, {}

        node_number_line = lines[0].strip()
        if not node_number_line or not node_number_line.isdigit():
            print(f"Error: First line '{node_number_line}' is not a valid node number")
            return None, {}

        node_number = node_number_line
        print(f"Using node number: {node_number}")

        favorites = {}
        favorite_count = 0
        for line in lines[1:]:
            if favorite_count >= 6:
                break
            parts = line.strip().split(",")
            if len(parts) == 2 and parts[1].isdigit():
                favorites[parts[1]] = parts[0]
                favorite_count += 1

        print(f"Loaded favorites: {favorites}")
        return node_number, favorites
    except Exception as e:
        print(f"Config file error: {e}")
        return None, {}


def lookup_node_name(node_number, favorites_dict=None):
    """Return display name for a node: favourites label → astdb callsign → 'Node'."""
    if favorites_dict and str(node_number) in favorites_dict:
        return favorites_dict[str(node_number)]
    try:
        astdb_path = "/var/www/html/allmon2/astdb.txt"
        with open(astdb_path, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if parts and parts[0].strip() == str(node_number):
                    if len(parts) >= 2:
                        return parts[1].strip()
    except Exception:
        pass
    return "Node"


def get_ip_address():
    """Get IP address using native Python — no subprocess."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"IP: {ip}"
    except Exception:
        return "IP: No connection"


def get_uptime():
    """Get uptime from /proc/uptime — no subprocess."""
    try:
        with open("/proc/uptime", "r") as f:
            seconds = float(f.read().split()[0])
        days = int(seconds // (24 * 3600))
        hours = int((seconds % (24 * 3600)) // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"Uptime: {days:02d}:{hours:02d}:{minutes:02d}"
    except Exception:
        return "Uptime: Error"


_sysinfo_cache = {"ip": "IP: Starting...", "uptime": "Uptime: Starting...", "last_update": 0}
SYSINFO_INTERVAL = 5.0


def get_cached_sysinfo(current_time):
    if current_time - _sysinfo_cache["last_update"] >= SYSINFO_INTERVAL:
        _sysinfo_cache["ip"] = get_ip_address()
        _sysinfo_cache["uptime"] = get_uptime()
        _sysinfo_cache["last_update"] = current_time
    return _sysinfo_cache["ip"], _sysinfo_cache["uptime"]


node_number, favorites = read_config()
if node_number is None:
    print("Failed to read node number from favourites.txt")
    exit(1)


# ===== DISPLAY THREAD =====
# The SPI transfer for a full 240x240 frame blocks for ~38ms at 24MHz.
# Running it in a background thread means button presses are never delayed
# waiting for the display hardware. PIL rendering also happens here.

_state_lock = threading.Lock()
_display_event = threading.Event()
_display_state = {
    "mode": "main",
    "selection_index": 0,
    "connected_nodes": [],
    "Nodes": ["Nodes: None"],
    "favorites_list": [],
    "linked_nodes_count": 0,
    "IP": "IP: Starting...",
    "Uptime": "Uptime: Starting...",
    "error_message": "",
    "status_message": "",
}


def _render():
    """Read shared state, draw to PIL image, push to SPI. Called only from display thread."""
    with _state_lock:
        s = dict(_display_state)

    draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
    y = top

    if s["mode"] == "shutdown":
        draw.text((x, y + 60), "SHUTTING DOWN", font=font, fill="#FF0000")
        y2 = y + 60 + font.getbbox("SHUTTING DOWN")[3] - font.getbbox("SHUTTING DOWN")[1] + 12
        draw.text((x, y2), "Safe to power off", font=font, fill="#FFFF00")
        y2 += font.getbbox("Safe to power off")[3] - font.getbbox("Safe to power off")[1] + 12
        draw.text((x, y2), "in 15 seconds", font=font, fill="#FFFF00")

    elif s["mode"] == "main":
        draw.text((x, y), s["IP"], font=font, fill="#FFFFFF")
        y += font.getbbox(s["IP"])[3] - font.getbbox(s["IP"])[1] + 12

        draw.text((x, y), s["Uptime"], font=font, fill="#0000FF")
        y += font.getbbox(s["Uptime"])[3] - font.getbbox(s["Uptime"])[1] + 12

        lbl = "> Favourites" if s["selection_index"] == 0 else "  Favourites"
        draw.text((x, y), lbl, font=font, fill="#FFFF00")
        y += font.getbbox(lbl)[3] - font.getbbox(lbl)[1] + 12

        for i, node in enumerate(s["Nodes"]):
            lbl = f"> {node}" if s["selection_index"] == i + 1 else f"  {node}"
            draw.text((x, y), lbl, font=font, fill="#00FF00")
            y += font.getbbox(node)[3] - font.getbbox(node)[1] + 12

        if s["linked_nodes_count"] > 0:
            draw.text((x, height - 28), f"{s['linked_nodes_count']} nodes linked",
                      font=font, fill="#00FF00")

        msg = s["status_message"] or s["error_message"]
        if msg:
            draw.text((x, y), msg, font=font,
                      fill="#FF8800" if s["status_message"] else "#FF0000")

    else:  # favorites
        for i, (name, num) in enumerate(s["favorites_list"]):
            lbl = f"> {name}" if s["selection_index"] == i else f"  {name}"
            if name != "Exit":
                lbl += f": {num}"
            draw.text((x, y), lbl, font=font,
                      fill="#FFFF00" if name == "Exit" else "#00FF00")
            y += font.getbbox(lbl)[3] - font.getbbox(lbl)[1] + 12

        msg = s["status_message"] or s["error_message"]
        if msg:
            draw.text((x, y), msg, font=font,
                      fill="#FF8800" if s["status_message"] else "#FF0000")

    disp.image(image, rotation)


def _display_worker():
    while True:
        _display_event.wait()
        _display_event.clear()
        try:
            _render()
        except Exception as e:
            print(f"Display error: {e}")


def mark_dirty(**updates):
    """Update display state and wake the display thread to re-render."""
    if updates:
        with _state_lock:
            _display_state.update(updates)
    _display_event.set()
# ===== END DISPLAY THREAD =====


# ===== ASYNC ASTERISK HELPER =====
def _run_asterisk(cmd, on_done=None):
    """Run an asterisk command in a daemon thread; call on_done(ok, output) when done."""
    def _run():
        try:
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
            if on_done:
                on_done(True, out)
        except subprocess.CalledProcessError as e:
            if on_done:
                on_done(False, e.output.decode())
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    threading.Thread(target=_run, daemon=True).start()
# ===== END ASYNC ASTERISK HELPER =====


def handle_buttons(display_mode, selection_index, connected_nodes, favorites_list):
    current_time = time.time()
    global last_button_a_time, last_button_b_time, last_button_a_state, last_button_b_state
    new_mode = display_mode
    new_index = selection_index
    button_pressed = False

    # Button A: Cycle selection
    button_a_state = not button_a.value
    if button_a_state and not last_button_a_state and (current_time - last_button_a_time) > debounce_delay:
        button_pressed = True
        if display_mode == "main":
            new_index = (selection_index + 1) % (1 + len(connected_nodes))
        else:
            new_index = (selection_index + 1) % len(favorites_list)
        last_button_a_time = current_time
        print(f"Button A: Selected index {new_index}")

    # Button B: Connect/disconnect or switch modes
    button_b_state = not button_b.value
    if button_b_state and not last_button_b_state and (current_time - last_button_b_time) > debounce_delay:
        button_pressed = True
        if display_mode == "main":
            if selection_index == 0:
                new_mode = "favorites"
                new_index = 0
                print("Button B: Switched to favorites mode")
            elif selection_index <= len(connected_nodes):
                node = connected_nodes[selection_index - 1]
                print(f"Button B: Disconnecting node {node}")
                mark_dirty(status_message=f"Disconnecting {node}...", error_message="")
                def _on_disconnect(ok, result, _node=node):
                    if ok:
                        print(f"Disconnected {_node}: {result}")
                        mark_dirty(status_message="")
                    else:
                        print(f"Disconnect error: {result}")
                        mark_dirty(status_message="", error_message="Disconnect failed")
                _run_asterisk(
                    f"sudo asterisk -rx 'rpt cmd {node_number} ilink 1 {node}'",
                    _on_disconnect,
                )
        else:  # favorites mode
            if selection_index < len(favorites_list) - 1:
                name, node = favorites_list[selection_index]
                print(f"Button B: Connecting to {name}: {node}")
                new_mode = "main"
                new_index = 0
                mark_dirty(mode="main", selection_index=0,
                           status_message=f"Connecting {name}...", error_message="")
                def _on_connect(ok, result, _name=name, _node=node):
                    if ok:
                        print(f"Connected to {_name} ({_node}): {result}")
                        mark_dirty(status_message="")
                    else:
                        print(f"Connect error: {result}")
                        mark_dirty(status_message="", error_message="Connect failed")
                _run_asterisk(
                    f"sudo asterisk -rx 'rpt cmd {node_number} ilink 3 {node}'",
                    _on_connect,
                )
            else:
                print("Button B: Exit favorites")
                new_mode = "main"
                new_index = 0
        last_button_b_time = current_time

    last_button_a_state = button_a_state
    last_button_b_state = button_b_state
    return new_mode, new_index, button_pressed


def check_shutdown():
    """Hold both buttons for 2 seconds to initiate a safe shutdown."""
    global shutdown_pressed, shutdown_start_time
    both_pressed = (not button_a.value) and (not button_b.value)
    if both_pressed:
        if not shutdown_pressed:
            shutdown_pressed = True
            shutdown_start_time = time.time()
        elif time.time() - shutdown_start_time >= shutdown_hold_duration:
            mark_dirty(mode="shutdown")
            time.sleep(0.5)  # Let display thread render before shutdown call
            print("Shutdown initiated by button press")
            subprocess.run("sudo shutdown -h now", shell=True)
            time.sleep(15)
            exit(0)
    else:
        shutdown_pressed = False
    return both_pressed


# Initialize state
display_mode = "main"
selection_index = 0
last_button_a_time = 0
last_button_b_time = 0
last_button_a_state = False
last_button_b_state = False
debounce_delay = 0.05
last_display_update = 0
last_nodes_update = 0
display_update_interval = 5.0
nodes_update_interval = 5.0
connected_nodes = []
Nodes = ["Nodes: None"]
linked_nodes_count = 0
shutdown_pressed = False
shutdown_start_time = 0
shutdown_hold_duration = 2.0


# ===== STARTUP SPLASH (synchronous — display thread not yet running) =====
draw.rectangle((0, 0, width, height), outline=0, fill=(0, 0, 0))
draw.text((x, top + 20),  f"RLNZ2 v{VERSION}",  font=font, fill="#FFFFFF")
draw.text((x, top + 60),  "Display Driver",      font=font, fill="#FFFFFF")
draw.text((x, top + 110), "Copyright 2026",      font=font, fill="#FFFFFF")
draw.text((x, top + 160), "G1LRO.UK",            font=font, fill="#FFFFFF")
disp.image(image, rotation)
time.sleep(1)
# ===== END STARTUP SPLASH =====


# Start display thread, then wait for Asterisk to be ready
_display_thread = threading.Thread(target=_display_worker, daemon=True)
_display_thread.start()

print("Waiting for Asterisk...")
time.sleep(10)

while True:
    current_time = time.time()

    if check_shutdown():
        continue

    # Update node status periodically
    if current_time - last_nodes_update >= nodes_update_interval:
        try:
            cmd = f"sudo asterisk -rx 'rpt lstats {node_number}'"
            result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
            print("AllStarLink output:", result)
            lines = result.splitlines()[2:]
            connected_nodes = []
            for line in lines:
                if "ESTABLISHED" in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        connected_nodes.append(parts[0])
            Nodes = (
                [f"{lookup_node_name(n, favorites)}: {n}" for n in connected_nodes[:3]]
                if connected_nodes else ["Nodes: None"]
            )
            try:
                count_result = subprocess.check_output(
                    f"sudo asterisk -rx 'rpt nodes {node_number}'",
                    shell=True, stderr=subprocess.STDOUT,
                ).decode()
                linked_nodes_count = max(0, len(re.findall(r"T[0-9A-Z]+", count_result)) - 1)
            except Exception:
                linked_nodes_count = 0
        except subprocess.CalledProcessError as e:
            print(f"AllStarLink error: {e.output.decode()}")
            Nodes = ["Nodes: Err"]
        except FileNotFoundError:
            print("Asterisk/sudo not found")
            Nodes = ["Nodes: No Asterisk"]
        last_nodes_update = current_time

    favorites_list = [(name, num) for num, name in favorites.items()][:6]
    favorites_list.append(("Exit", "0"))

    display_mode, selection_index, button_pressed = handle_buttons(
        display_mode, selection_index, connected_nodes, favorites_list
    )

    needs_update = button_pressed or (current_time - last_display_update >= display_update_interval)

    if needs_update:
        IP, Uptime = get_cached_sysinfo(current_time)
        # Push data to display thread. status_message/error_message are intentionally
        # omitted here — they are owned by button handlers and async callbacks.
        mark_dirty(
            mode=display_mode,
            selection_index=selection_index,
            connected_nodes=connected_nodes,
            Nodes=Nodes,
            favorites_list=favorites_list,
            linked_nodes_count=linked_nodes_count,
            IP=IP,
            Uptime=Uptime,
        )
        last_display_update = current_time

    time.sleep(0.02)  # 50Hz polling
