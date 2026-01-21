#!/usr/bin/env python3
"""
Minecraft Server Manager TUI (mctool)
A single-file Python TUI for installing and managing Minecraft servers.
No external dependencies - uses only Python stdlib.
"""

import argparse
import curses
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
PAPER_API_URL = "https://api.papermc.io/v2/projects/paper"
DEFAULT_SERVER_DIR = os.path.expanduser("~/minecraft")
CONFIG_FILENAME = ".mctool.json"
SCREEN_SESSION_NAME = "minecraft"


class Config:
    """Manages configuration stored in .mctool.json"""
    
    def __init__(self, server_dir: str = DEFAULT_SERVER_DIR):
        self.server_dir = server_dir
        self.config_path = os.path.join(server_dir, CONFIG_FILENAME)
        self.data = self._load()
    
    def _default_config(self) -> Dict[str, Any]:
        return {
            "server_dir": self.server_dir,
            "ram_gb": 4,
            "current_version": None,
            "server_type": "vanilla",
            "auto_backup": True,
            "max_backups": 5,
            "command_history": []
        }
    
    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    # Merge with defaults for any missing keys
                    defaults = self._default_config()
                    defaults.update(data)
                    return defaults
            except (json.JSONDecodeError, IOError):
                pass
        return self._default_config()
    
    def save(self) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()


# ═══════════════════════════════════════════════════════════════════════════════
# Minecraft Server Management
# ═══════════════════════════════════════════════════════════════════════════════

class MinecraftServer:
    """Handles server installation, lifecycle, and commands"""
    
    def __init__(self, config: Config):
        self.config = config
        self.server_dir = config.get("server_dir", DEFAULT_SERVER_DIR)
    
    def fetch_versions(self, limit: int = 50) -> List[Dict[str, str]]:
        """Fetch available versions from Mojang API"""
        try:
            with urllib.request.urlopen(MANIFEST_URL, timeout=10) as response:
                data = json.load(response)
                versions = []
                for v in data.get("versions", [])[:limit]:
                    versions.append({
                        "id": v["id"],
                        "type": v["type"],
                        "url": v["url"]
                    })
                return versions
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            return []
    
    def fetch_paper_versions(self) -> List[str]:
        """Fetch available Paper versions from PaperMC API"""
        try:
            with urllib.request.urlopen(PAPER_API_URL, timeout=10) as response:
                data = json.load(response)
                return data.get("versions", [])
        except (urllib.error.URLError, json.JSONDecodeError):
            return []
    
    def get_paper_build(self, version: str) -> Optional[int]:
        """Get latest Paper build number for a version"""
        try:
            url = f"{PAPER_API_URL}/versions/{version}"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.load(response)
                builds = data.get("builds", [])
                return builds[-1] if builds else None
        except (urllib.error.URLError, json.JSONDecodeError):
            return None
    
    def get_paper_jar_url(self, version: str, build: int) -> Optional[str]:
        """Get Paper server.jar download URL"""
        try:
            url = f"{PAPER_API_URL}/versions/{version}/builds/{build}"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.load(response)
                downloads = data.get("downloads", {})
                app = downloads.get("application", {})
                filename = app.get("name")
                if filename:
                    return f"{PAPER_API_URL}/versions/{version}/builds/{build}/downloads/{filename}"
        except (urllib.error.URLError, json.JSONDecodeError):
            pass
        return None
    
    def install_paper(self, version: str, ram_gb: int = 4,
                      progress_callback=None, status_callback=None) -> Tuple[bool, str]:
        """Install Paper server"""
        if status_callback:
            status_callback("Creating server directory...")
        
        os.makedirs(self.server_dir, exist_ok=True)
        
        if status_callback:
            status_callback("Fetching latest Paper build...")
        
        build = self.get_paper_build(version)
        if not build:
            return False, f"No Paper builds available for {version}"
        
        jar_url = self.get_paper_jar_url(version, build)
        if not jar_url:
            return False, "Failed to get Paper jar URL"
        
        if status_callback:
            status_callback(f"Downloading Paper {version} build {build}...")
        
        jar_path = os.path.join(self.server_dir, "server.jar")
        if not self.download_file(jar_url, jar_path, progress_callback):
            return False, "Failed to download Paper jar"
        
        if status_callback:
            status_callback("Accepting EULA...")
        
        # Accept EULA
        eula_path = os.path.join(self.server_dir, "eula.txt")
        with open(eula_path, 'w') as f:
            f.write("# Auto-accepted by mctool\neula=true\n")
        
        # Save config
        self.config.set("current_version", version)
        self.config.set("ram_gb", ram_gb)
        self.config.set("server_type", "paper")
        
        return True, f"Paper {version} (build {build}) installed successfully!"
    
    def get_server_jar_url(self, version_url: str) -> Optional[str]:
        """Get server.jar download URL from version manifest"""
        try:
            with urllib.request.urlopen(version_url, timeout=10) as response:
                data = json.load(response)
                downloads = data.get("downloads", {})
                server = downloads.get("server", {})
                return server.get("url")
        except (urllib.error.URLError, json.JSONDecodeError):
            return None
    
    def download_file(self, url: str, dest: str, progress_callback=None) -> bool:
        """Download a file with optional progress callback"""
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                block_size = 8192
                
                with open(dest, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded += len(buffer)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)
            return True
        except (urllib.error.URLError, IOError):
            return False
    
    def install(self, version_id: str, version_url: str, ram_gb: int = 4, 
                progress_callback=None, status_callback=None) -> Tuple[bool, str]:
        """Install Minecraft server"""
        if status_callback:
            status_callback("Creating server directory...")
        
        os.makedirs(self.server_dir, exist_ok=True)
        
        if status_callback:
            status_callback("Fetching version metadata...")
        
        jar_url = self.get_server_jar_url(version_url)
        if not jar_url:
            return False, "Failed to get server.jar URL"
        
        if status_callback:
            status_callback("Downloading server.jar...")
        
        jar_path = os.path.join(self.server_dir, "server.jar")
        if not self.download_file(jar_url, jar_path, progress_callback):
            return False, "Failed to download server.jar"
        
        if status_callback:
            status_callback("Accepting EULA...")
        
        # Accept EULA
        eula_path = os.path.join(self.server_dir, "eula.txt")
        with open(eula_path, 'w') as f:
            f.write("# Auto-accepted by mctool\neula=true\n")
        
        # Save config
        self.config.set("current_version", version_id)
        self.config.set("ram_gb", ram_gb)
        self.config.set("server_type", "vanilla")
        
        return True, f"Minecraft {version_id} installed successfully!"
    
    def is_running(self) -> bool:
        """Check if server is running in screen session"""
        try:
            result = subprocess.run(
                ["screen", "-ls", SCREEN_SESSION_NAME],
                capture_output=True, text=True
            )
            return SCREEN_SESSION_NAME in result.stdout
        except FileNotFoundError:
            return False
    
    def start(self) -> Tuple[bool, str]:
        """Start the server in a screen session"""
        if self.is_running():
            return False, "Server is already running"
        
        jar_path = os.path.join(self.server_dir, "server.jar")
        if not os.path.exists(jar_path):
            return False, "server.jar not found. Please install first."
        
        ram_gb = self.config.get("ram_gb", 4)
        
        # Build the java command with output logging
        log_file = os.path.join(self.server_dir, "server.log")
        java_cmd = f"java -Xmx{ram_gb}G -Xms{ram_gb}G -jar server.jar nogui 2>&1 | tee -a {log_file}"
        
        try:
            result = subprocess.run(
                ["screen", "-dmS", SCREEN_SESSION_NAME, "bash", "-c", java_cmd],
                cwd=self.server_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return False, f"Screen failed: {result.stderr}"
            
            # Give it a moment to start
            time.sleep(1)
            
            # Check if it's actually running
            if self.is_running():
                return True, "Server started successfully!"
            else:
                # Try to read the log for errors
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        last_lines = f.readlines()[-10:]
                        log_tail = ''.join(last_lines)
                        if log_tail.strip():
                            return False, f"Server exited. Log:\n{log_tail}"
                return False, "Server started but exited immediately. Check Java installation."
                
        except subprocess.CalledProcessError as e:
            return False, f"Failed to start server: {e}"
        except FileNotFoundError:
            return False, "screen command not found. Please install screen."
    
    def stop(self, graceful: bool = True) -> Tuple[bool, str]:
        """Stop the server"""
        if not self.is_running():
            return False, "Server is not running"
        
        try:
            if graceful:
                # Send stop command to server via screen
                # -p 0 selects window 0, -X stuff sends keystrokes
                subprocess.run(
                    ["screen", "-S", SCREEN_SESSION_NAME, "-p", "0", "-X", "stuff", "stop\n"],
                    check=True,
                    capture_output=True
                )
                # Wait for server to stop
                for i in range(30):
                    time.sleep(1)
                    if not self.is_running():
                        return True, "Server stopped gracefully"
                return False, "Server did not stop in time (30s timeout)"
            else:
                subprocess.run(
                    ["screen", "-S", SCREEN_SESSION_NAME, "-X", "quit"],
                    check=True
                )
                return True, "Server terminated"
        except subprocess.CalledProcessError as e:
            return False, f"Failed to stop server: {e}"
    
    def send_command(self, command: str) -> Tuple[bool, str]:
        """Send a command to the running server"""
        if not self.is_running():
            return False, "Server is not running"
        
        try:
            subprocess.run(
                ["screen", "-S", SCREEN_SESSION_NAME, "-X", "stuff", f"{command}\n"],
                check=True
            )
            # Save to history
            history = self.config.get("command_history", [])
            if command not in history:
                history.insert(0, command)
                history = history[:20]  # Keep last 20 commands
                self.config.set("command_history", history)
            return True, f"Command sent: {command}"
        except subprocess.CalledProcessError as e:
            return False, f"Failed to send command: {e}"
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status information"""
        running = self.is_running()
        version = self.config.get("current_version", "Not installed")
        ram = self.config.get("ram_gb", 4)
        server_type = self.config.get("server_type", "vanilla")
        
        jar_exists = os.path.exists(os.path.join(self.server_dir, "server.jar"))
        
        return {
            "running": running,
            "installed": jar_exists,
            "version": version,
            "ram_gb": ram,
            "server_type": server_type,
            "server_dir": self.server_dir
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Backup Manager
# ═══════════════════════════════════════════════════════════════════════════════

class BackupManager:
    """Handles world backups"""
    
    def __init__(self, config: Config):
        self.config = config
        self.server_dir = config.get("server_dir", DEFAULT_SERVER_DIR)
        self.backup_dir = os.path.join(self.server_dir, "backups")
    
    def get_world_folders(self) -> List[str]:
        """Get list of world folders to backup"""
        worlds = []
        for item in os.listdir(self.server_dir):
            item_path = os.path.join(self.server_dir, item)
            if os.path.isdir(item_path):
                # Check if it's a world folder (has level.dat)
                if os.path.exists(os.path.join(item_path, "level.dat")):
                    worlds.append(item)
        return worlds
    
    def create_backup(self, status_callback=None) -> Tuple[bool, str]:
        """Create a backup of all world folders"""
        worlds = self.get_world_folders()
        if not worlds:
            return False, "No world folders found to backup"
        
        os.makedirs(self.backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = self.config.get("current_version", "unknown")
        backup_name = f"backup_{version}_{timestamp}.tar.gz"
        backup_path = os.path.join(self.backup_dir, backup_name)
        
        if status_callback:
            status_callback(f"Creating backup: {backup_name}")
        
        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                for world in worlds:
                    world_path = os.path.join(self.server_dir, world)
                    if status_callback:
                        status_callback(f"Backing up: {world}")
                    tar.add(world_path, arcname=world)
            
            self._cleanup_old_backups()
            return True, f"Backup created: {backup_name}"
        except (tarfile.TarError, IOError) as e:
            return False, f"Backup failed: {e}"
    
    def _cleanup_old_backups(self) -> None:
        """Remove old backups exceeding max_backups"""
        max_backups = self.config.get("max_backups", 5)
        
        backups = []
        for f in os.listdir(self.backup_dir):
            if f.endswith(".tar.gz"):
                path = os.path.join(self.backup_dir, f)
                backups.append((os.path.getmtime(path), path))
        
        backups.sort(reverse=True)
        
        for _, path in backups[max_backups:]:
            os.remove(path)
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups"""
        if not os.path.exists(self.backup_dir):
            return []
        
        backups = []
        for f in os.listdir(self.backup_dir):
            if f.endswith(".tar.gz"):
                path = os.path.join(self.backup_dir, f)
                stat = os.stat(path)
                backups.append({
                    "name": f,
                    "path": path,
                    "size": stat.st_size,
                    "date": datetime.fromtimestamp(stat.st_mtime)
                })
        
        backups.sort(key=lambda x: x["date"], reverse=True)
        return backups


# ═══════════════════════════════════════════════════════════════════════════════
# TUI Components
# ═══════════════════════════════════════════════════════════════════════════════

class TUI:
    """Curses-based Terminal User Interface"""
    
    # Box drawing characters
    BOX_CHARS = {
        'tl': '┌', 'tr': '┐', 'bl': '└', 'br': '┘',
        'h': '─', 'v': '│', 'lt': '├', 'rt': '┤',
        'tt': '┬', 'bt': '┴', 'cross': '┼'
    }
    
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.config = Config()
        self.server = MinecraftServer(self.config)
        self.backup = BackupManager(self.config)
        
        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Success/Running
        curses.init_pair(2, curses.COLOR_RED, -1)     # Error/Stopped
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warning
        curses.init_pair(4, curses.COLOR_CYAN, -1)    # Info
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Selected
        curses.init_pair(6, curses.COLOR_MAGENTA, -1) # Accent
        
        self.COLOR_GREEN = curses.color_pair(1)
        self.COLOR_RED = curses.color_pair(2)
        self.COLOR_YELLOW = curses.color_pair(3)
        self.COLOR_CYAN = curses.color_pair(4)
        self.COLOR_SELECTED = curses.color_pair(5)
        self.COLOR_ACCENT = curses.color_pair(6)
        
        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)
    
    def draw_box(self, y: int, x: int, h: int, w: int, title: str = "") -> None:
        """Draw a box with optional title"""
        bc = self.BOX_CHARS
        
        # Top border
        self.stdscr.addstr(y, x, bc['tl'] + bc['h'] * (w - 2) + bc['tr'])
        
        # Title
        if title:
            title_str = f" {title} "
            title_x = x + (w - len(title_str)) // 2
            self.stdscr.addstr(y, title_x, title_str, curses.A_BOLD | self.COLOR_CYAN)
        
        # Sides
        for i in range(1, h - 1):
            self.stdscr.addstr(y + i, x, bc['v'])
            self.stdscr.addstr(y + i, x + w - 1, bc['v'])
        
        # Bottom border
        self.stdscr.addstr(y + h - 1, x, bc['bl'] + bc['h'] * (w - 2) + bc['br'])
    
    def draw_separator(self, y: int, x: int, w: int) -> None:
        """Draw a horizontal separator"""
        bc = self.BOX_CHARS
        self.stdscr.addstr(y, x, bc['lt'] + bc['h'] * (w - 2) + bc['rt'])
    
    def show_menu(self, title: str, options: List[str], selected: int = 0) -> int:
        """Display a menu and return selected index, -1 for escape"""
        height, width = self.stdscr.getmaxyx()
        
        menu_w = max(len(title) + 4, max(len(o) for o in options) + 6, 35)
        menu_h = len(options) + 4
        start_y = (height - menu_h) // 2
        start_x = (width - menu_w) // 2
        
        while True:
            self.stdscr.clear()
            self.draw_box(start_y, start_x, menu_h, menu_w, title)
            
            for i, option in enumerate(options):
                y = start_y + 2 + i
                x = start_x + 2
                
                if i == selected:
                    self.stdscr.addstr(y, x, f" > {option} ", self.COLOR_SELECTED | curses.A_BOLD)
                else:
                    self.stdscr.addstr(y, x, f"   {option} ")
            
            # Footer hints
            hint = "↑↓ Navigate  Enter: Select  Q: Back"
            self.stdscr.addstr(height - 1, (width - len(hint)) // 2, hint, self.COLOR_CYAN)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            
            if key == curses.KEY_UP:
                selected = (selected - 1) % len(options)
            elif key == curses.KEY_DOWN:
                selected = (selected + 1) % len(options)
            elif key in (curses.KEY_ENTER, 10, 13):
                return selected
            elif key in (ord('q'), ord('Q'), 27):  # Q or Escape
                return -1
            elif ord('1') <= key <= ord('9'):
                idx = key - ord('1')
                if idx < len(options):
                    return idx
    
    def show_message(self, title: str, message: str, color=None, wait: bool = True) -> None:
        """Display a message box"""
        height, width = self.stdscr.getmaxyx()
        
        lines = message.split('\n')
        msg_w = max(len(title) + 4, max(len(l) for l in lines) + 4, 30)
        msg_h = len(lines) + 4
        start_y = (height - msg_h) // 2
        start_x = (width - msg_w) // 2
        
        self.stdscr.clear()
        self.draw_box(start_y, start_x, msg_h, msg_w, title)
        
        attr = color if color else curses.A_NORMAL
        for i, line in enumerate(lines):
            self.stdscr.addstr(start_y + 2 + i, start_x + 2, line, attr)
        
        if wait:
            hint = "Press any key to continue..."
            self.stdscr.addstr(height - 1, (width - len(hint)) // 2, hint, self.COLOR_CYAN)
        
        self.stdscr.refresh()
        
        if wait:
            self.stdscr.getch()
    
    def show_progress(self, title: str, status: str, progress: float = -1) -> None:
        """Show a progress/status screen"""
        height, width = self.stdscr.getmaxyx()
        
        box_w = 50
        box_h = 6
        start_y = (height - box_h) // 2
        start_x = (width - box_w) // 2
        
        self.stdscr.clear()
        self.draw_box(start_y, start_x, box_h, box_w, title)
        
        # Status text
        status_truncated = status[:box_w - 6]
        self.stdscr.addstr(start_y + 2, start_x + 2, status_truncated, self.COLOR_CYAN)
        
        # Progress bar
        if progress >= 0:
            bar_w = box_w - 6
            filled = int(bar_w * min(progress, 1.0))
            bar = "█" * filled + "░" * (bar_w - filled)
            pct = f" {int(progress * 100)}%"
            self.stdscr.addstr(start_y + 3, start_x + 2, bar, self.COLOR_GREEN)
            self.stdscr.addstr(start_y + 3, start_x + 2 + bar_w + 1, pct)
        
        self.stdscr.refresh()
    
    def get_input(self, prompt: str, default: str = "") -> str:
        """Get text input from user"""
        height, width = self.stdscr.getmaxyx()
        
        box_w = 50
        box_h = 5
        start_y = (height - box_h) // 2
        start_x = (width - box_w) // 2
        
        curses.curs_set(1)  # Show cursor
        curses.echo()
        
        self.stdscr.clear()
        self.draw_box(start_y, start_x, box_h, box_w, "Input")
        self.stdscr.addstr(start_y + 2, start_x + 2, f"{prompt}: ")
        
        if default:
            self.stdscr.addstr(f"[{default}] ")
        
        self.stdscr.refresh()
        
        try:
            value = self.stdscr.getstr(start_y + 2, start_x + 2 + len(prompt) + 2, 30)
            # Handle potential encoding issues gracefully
            try:
                value = value.decode('utf-8').strip()
            except UnicodeDecodeError:
                value = value.decode('latin-1').strip()
            return value if value else default
        except Exception:
            return default
        finally:
            curses.noecho()
            curses.curs_set(0)
    
    def show_version_picker(self, versions: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Show scrollable version picker"""
        height, width = self.stdscr.getmaxyx()
        
        visible_count = min(15, height - 10)
        scroll_offset = 0
        selected = 0
        
        # Filter for releases by default
        show_snapshots = False
        
        while True:
            filtered = [v for v in versions if show_snapshots or v["type"] == "release"]
            
            if not filtered:
                self.show_message("Error", "No versions available", self.COLOR_RED)
                return None
            
            box_w = 45
            box_h = visible_count + 5
            start_y = (height - box_h) // 2
            start_x = (width - box_w) // 2
            
            self.stdscr.clear()
            self.draw_box(start_y, start_x, box_h, box_w, "Select Version")
            
            # Toggle hint
            toggle_hint = "[S] Show Snapshots" if not show_snapshots else "[S] Hide Snapshots"
            self.stdscr.addstr(start_y + 1, start_x + 2, toggle_hint, self.COLOR_YELLOW)
            self.draw_separator(start_y + 2, start_x, box_w)
            
            # Version list
            for i in range(visible_count):
                idx = scroll_offset + i
                if idx >= len(filtered):
                    break
                
                v = filtered[idx]
                y = start_y + 3 + i
                x = start_x + 2
                
                version_str = f"{v['id']}"
                if v["type"] != "release":
                    version_str += f" ({v['type']})"
                
                if idx == selected:
                    self.stdscr.addstr(y, x, f" > {version_str:<38}", self.COLOR_SELECTED | curses.A_BOLD)
                else:
                    type_color = self.COLOR_GREEN if v["type"] == "release" else self.COLOR_YELLOW
                    self.stdscr.addstr(y, x, f"   {version_str}", type_color)
            
            # Scroll indicator
            if len(filtered) > visible_count:
                scroll_info = f"[{selected + 1}/{len(filtered)}]"
                self.stdscr.addstr(start_y + box_h - 1, start_x + box_w - len(scroll_info) - 2, 
                                  scroll_info, self.COLOR_CYAN)
            
            # Footer
            hint = "↑↓ Navigate  Enter: Select  S: Toggle Snapshots  Q: Back"
            self.stdscr.addstr(height - 1, (width - len(hint)) // 2, hint, self.COLOR_CYAN)
            
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            
            if key == curses.KEY_UP:
                if selected > 0:
                    selected -= 1
                    if selected < scroll_offset:
                        scroll_offset = selected
            elif key == curses.KEY_DOWN:
                if selected < len(filtered) - 1:
                    selected += 1
                    if selected >= scroll_offset + visible_count:
                        scroll_offset = selected - visible_count + 1
            elif key in (ord('s'), ord('S')):
                show_snapshots = not show_snapshots
                selected = 0
                scroll_offset = 0
            elif key in (curses.KEY_ENTER, 10, 13):
                return filtered[selected]
            elif key in (ord('q'), ord('Q'), 27):
                return None
    
    # ─────────────────────────────────────────────────────────────────────────
    # Menu Handlers
    # ─────────────────────────────────────────────────────────────────────────
    
    def handle_install(self) -> None:
        """Handle server installation"""
        # Select server type
        type_result = self.show_menu("Select Server Type", ["Vanilla (Official)", "Paper (Optimized)", "Cancel"])
        if type_result == -1 or type_result == 2:
            return
        
        is_paper = type_result == 1
        
        self.show_progress("Install Server", "Fetching version list...")
        
        if is_paper:
            # Paper versions
            paper_versions = self.server.fetch_paper_versions()
            if not paper_versions:
                self.show_message("Error", "Failed to fetch Paper versions.\nCheck internet connection.", self.COLOR_RED)
                return
            
            # Convert to format expected by version picker (newest first)
            versions = [{"id": v, "type": "release", "url": ""} for v in reversed(paper_versions)]
        else:
            # Vanilla versions
            versions = self.server.fetch_versions(100)
            if not versions:
                self.show_message("Error", "Failed to fetch versions.\nCheck internet connection.", self.COLOR_RED)
                return
        
        # Select version
        selected = self.show_version_picker(versions)
        if not selected:
            return
        
        # Get RAM allocation
        current_ram = self.config.get("ram_gb", 4)
        ram_str = self.get_input("RAM (GB)", str(current_ram))
        try:
            ram_gb = int(ram_str)
            if ram_gb < 1 or ram_gb > 64:
                raise ValueError()
        except ValueError:
            self.show_message("Error", "Invalid RAM value (1-64 GB)", self.COLOR_RED)
            return
        
        # Confirm
        server_type_name = "Paper" if is_paper else "Vanilla"
        result = self.show_menu("Confirm Installation", 
                               [f"Yes, Install {server_type_name} {selected['id']}", "Cancel"])
        if result != 0:
            return
        
        # Progress tracking
        def progress_cb(downloaded, total):
            pct = downloaded / total if total > 0 else 0
            self.show_progress("Installing", f"Downloading server.jar...", pct)
        
        def status_cb(status):
            self.show_progress("Installing", status)
        
        # Install based on type
        if is_paper:
            success, message = self.server.install_paper(
                selected["id"], ram_gb,
                progress_callback=progress_cb,
                status_callback=status_cb
            )
        else:
            success, message = self.server.install(
                selected["id"], selected["url"], ram_gb,
                progress_callback=progress_cb,
                status_callback=status_cb
            )
        
        color = self.COLOR_GREEN if success else self.COLOR_RED
        self.show_message("Installation Complete" if success else "Installation Failed", 
                         message, color)
    
    def handle_start(self) -> None:
        """Handle server start"""
        self.show_progress("Starting Server", "Launching server...")
        success, message = self.server.start()
        
        color = self.COLOR_GREEN if success else self.COLOR_RED
        self.show_message("Server Start", message, color)
    
    def handle_stop(self) -> None:
        """Handle server stop"""
        result = self.show_menu("Stop Server", ["Graceful Stop (save first)", "Force Stop", "Cancel"])
        
        if result == 0:
            self.show_progress("Stopping Server", "Sending stop command...")
            success, message = self.server.stop(graceful=True)
        elif result == 1:
            success, message = self.server.stop(graceful=False)
        else:
            return
        
        color = self.COLOR_GREEN if success else self.COLOR_RED
        self.show_message("Server Stop", message, color)
    
    def handle_status(self) -> None:
        """Show server status"""
        status = self.server.get_status()
        
        running_str = "● RUNNING" if status["running"] else "○ STOPPED"
        running_color = self.COLOR_GREEN if status["running"] else self.COLOR_RED
        
        height, width = self.stdscr.getmaxyx()
        box_w = 45
        box_h = 12
        start_y = (height - box_h) // 2
        start_x = (width - box_w) // 2
        
        self.stdscr.clear()
        self.draw_box(start_y, start_x, box_h, box_w, "Server Status")
        
        y = start_y + 2
        self.stdscr.addstr(y, start_x + 2, "Status:  ", curses.A_BOLD)
        self.stdscr.addstr(running_str, running_color | curses.A_BOLD)
        
        y += 2
        self.stdscr.addstr(y, start_x + 2, f"Version:     ", curses.A_BOLD)
        self.stdscr.addstr(str(status["version"]), self.COLOR_CYAN)
        
        y += 1
        self.stdscr.addstr(y, start_x + 2, f"RAM:         ", curses.A_BOLD)
        self.stdscr.addstr(f"{status['ram_gb']} GB", self.COLOR_CYAN)
        
        y += 1
        self.stdscr.addstr(y, start_x + 2, f"Type:        ", curses.A_BOLD)
        self.stdscr.addstr(status["server_type"].capitalize(), self.COLOR_CYAN)
        
        y += 1
        self.stdscr.addstr(y, start_x + 2, f"Directory:   ", curses.A_BOLD)
        dir_display = status["server_dir"][:25] + "..." if len(status["server_dir"]) > 28 else status["server_dir"]
        self.stdscr.addstr(dir_display, self.COLOR_CYAN)
        
        y += 1
        installed_str = "Yes" if status["installed"] else "No"
        installed_color = self.COLOR_GREEN if status["installed"] else self.COLOR_YELLOW
        self.stdscr.addstr(y, start_x + 2, f"Installed:   ", curses.A_BOLD)
        self.stdscr.addstr(installed_str, installed_color)
        
        hint = "Press any key to continue..."
        self.stdscr.addstr(height - 1, (width - len(hint)) // 2, hint, self.COLOR_CYAN)
        
        self.stdscr.refresh()
        self.stdscr.getch()
    
    def handle_command(self) -> None:
        """Handle command execution"""
        history = self.config.get("command_history", [])
        
        while True:
            options = ["Enter new command"] + history[:10] + ["Back"]
            result = self.show_menu("Execute Command", options)
            
            if result == -1 or result == len(options) - 1:
                return
            elif result == 0:
                command = self.get_input("Command")
                if not command:
                    continue
            else:
                command = history[result - 1]
            
            success, message = self.server.send_command(command)
            color = self.COLOR_GREEN if success else self.COLOR_RED
            self.show_message("Command", message, color)
    
    def handle_console(self) -> None:
        """Interactive console with live log output and command input"""
        log_file = os.path.join(self.server.server_dir, "server.log")
        
        height, width = self.stdscr.getmaxyx()
        
        # Calculate box dimensions
        box_w = min(width - 4, 100)
        box_h = min(height - 4, 30)
        start_y = 1
        start_x = (width - box_w) // 2
        visible_lines = box_h - 7  # Room for header, separator, input area
        
        scroll_offset = 0
        auto_scroll = True
        command_buffer = ""
        cursor_pos = 0
        
        # Get command history
        history = self.config.get("command_history", [])
        history_idx = -1
        
        # Non-blocking input with shorter timeout
        self.stdscr.nodelay(True)
        self.stdscr.timeout(200)  # 200ms refresh
        
        try:
            while True:
                # Read log file
                lines = []
                if os.path.exists(log_file):
                    try:
                        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                            lines = f.readlines()
                    except IOError:
                        pass
                
                # Clean lines - strip ANSI escape codes and truncate
                import re
                ansi_escape = re.compile(r'\x1b\[[0-9;]*m|\x1b\[[0-9;]*[A-Za-z]')
                lines = [ansi_escape.sub('', l).rstrip()[:box_w - 4] for l in lines]
                
                # Auto-scroll to bottom
                if auto_scroll:
                    scroll_offset = max(0, len(lines) - visible_lines)
                
                # Draw
                self.stdscr.clear()
                self.draw_box(start_y, start_x, box_h, box_w, "Server Console")
                
                # Status bar inside box
                running = self.server.is_running()
                status_str = "● LIVE" if running else "○ STOPPED"
                status_color = self.COLOR_GREEN if running else self.COLOR_RED
                self.stdscr.addstr(start_y + 1, start_x + 2, status_str, status_color | curses.A_BOLD)
                
                auto_str = "[A]uto-scroll: " + ("ON" if auto_scroll else "OFF")
                self.stdscr.addstr(start_y + 1, start_x + box_w - len(auto_str) - 2, auto_str, 
                                  self.COLOR_CYAN if auto_scroll else self.COLOR_YELLOW)
                
                self.draw_separator(start_y + 2, start_x, box_w)
                
                # Log lines
                for i in range(visible_lines):
                    line_idx = scroll_offset + i
                    if line_idx >= len(lines):
                        break
                    
                    line = lines[line_idx]
                    y = start_y + 3 + i
                    
                    # Color based on content
                    if "ERROR" in line or "Exception" in line:
                        color = self.COLOR_RED
                    elif "WARN" in line:
                        color = self.COLOR_YELLOW
                    elif "INFO" in line:
                        color = self.COLOR_CYAN
                    else:
                        color = curses.A_NORMAL
                    
                    try:
                        self.stdscr.addstr(y, start_x + 2, line[:box_w - 4], color)
                    except curses.error:
                        pass
                
                # Command input area
                input_y = start_y + box_h - 3
                self.draw_separator(input_y, start_x, box_w)
                
                # Command prompt
                prompt = "> "
                self.stdscr.addstr(input_y + 1, start_x + 2, prompt, self.COLOR_GREEN | curses.A_BOLD)
                
                # Command buffer (show what user is typing)
                display_cmd = command_buffer[:box_w - 6]
                self.stdscr.addstr(input_y + 1, start_x + 2 + len(prompt), display_cmd)
                
                # Cursor position
                cursor_x = start_x + 2 + len(prompt) + min(cursor_pos, len(display_cmd))
                
                # Footer hints
                hint = "Enter: Send  ↑↓: History  Esc: Back"
                self.stdscr.addstr(height - 1, (width - len(hint)) // 2, hint, self.COLOR_CYAN)
                
                # Show cursor
                try:
                    self.stdscr.move(input_y + 1, cursor_x)
                    curses.curs_set(1)
                except curses.error:
                    pass
                
                self.stdscr.refresh()
                
                # Handle input
                key = self.stdscr.getch()
                
                if key == 27:  # Escape
                    break
                elif key == curses.KEY_ENTER or key == 10 or key == 13:
                    # Send command
                    if command_buffer.strip():
                        if running:
                            self.server.send_command(command_buffer.strip())
                        command_buffer = ""
                        cursor_pos = 0
                        history_idx = -1
                        auto_scroll = True
                elif key == curses.KEY_UP:
                    # History up
                    if history and history_idx < len(history) - 1:
                        history_idx += 1
                        command_buffer = history[history_idx]
                        cursor_pos = len(command_buffer)
                elif key == curses.KEY_DOWN:
                    # History down
                    if history_idx > 0:
                        history_idx -= 1
                        command_buffer = history[history_idx]
                        cursor_pos = len(command_buffer)
                    elif history_idx == 0:
                        history_idx = -1
                        command_buffer = ""
                        cursor_pos = 0
                elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
                    # Backspace
                    if cursor_pos > 0:
                        command_buffer = command_buffer[:cursor_pos-1] + command_buffer[cursor_pos:]
                        cursor_pos -= 1
                elif key == curses.KEY_LEFT:
                    if cursor_pos > 0:
                        cursor_pos -= 1
                elif key == curses.KEY_RIGHT:
                    if cursor_pos < len(command_buffer):
                        cursor_pos += 1
                elif key == curses.KEY_PPAGE:  # Page Up - scroll log
                    auto_scroll = False
                    scroll_offset = max(0, scroll_offset - visible_lines)
                elif key == curses.KEY_NPAGE:  # Page Down - scroll log
                    scroll_offset = min(max(0, len(lines) - visible_lines), scroll_offset + visible_lines)
                    if scroll_offset >= len(lines) - visible_lines:
                        auto_scroll = True
                elif key == ord('a') or key == ord('A'):
                    # Toggle auto-scroll only if not typing
                    if not command_buffer:
                        auto_scroll = not auto_scroll
                    else:
                        command_buffer = command_buffer[:cursor_pos] + chr(key) + command_buffer[cursor_pos:]
                        cursor_pos += 1
                elif 32 <= key <= 126:  # Printable ASCII
                    command_buffer = command_buffer[:cursor_pos] + chr(key) + command_buffer[cursor_pos:]
                    cursor_pos += 1
                    history_idx = -1
                
        finally:
            self.stdscr.nodelay(False)
            self.stdscr.timeout(-1)
            curses.curs_set(0)
    
    def handle_version_change(self) -> None:
        """Handle version change"""
        current = self.config.get("current_version", "Not installed")
        
        self.show_message("Current Version", f"Current: {current}\n\nFetching available versions...", 
                         self.COLOR_CYAN, wait=False)
        
        versions = self.server.fetch_versions(100)
        if not versions:
            self.show_message("Error", "Failed to fetch versions", self.COLOR_RED)
            return
        
        selected = self.show_version_picker(versions)
        if not selected:
            return
        
        if selected["id"] == current:
            self.show_message("Info", "Already on this version", self.COLOR_YELLOW)
            return
        
        # Confirm
        auto_backup = self.config.get("auto_backup", True)
        msg = f"Change from {current} to {selected['id']}?"
        if auto_backup:
            msg += "\n\nA backup will be created first."
        
        result = self.show_menu("Confirm Version Change", ["Yes, Change Version", "Cancel"])
        if result != 0:
            return
        
        # Stop server if running
        if self.server.is_running():
            self.show_progress("Version Change", "Stopping server...")
            self.server.stop(graceful=True)
            time.sleep(2)
        
        # Backup if enabled
        if auto_backup:
            self.show_progress("Version Change", "Creating backup...")
            success, msg = self.backup.create_backup()
            if not success:
                self.show_message("Warning", f"Backup failed: {msg}\nContinue anyway?", self.COLOR_YELLOW)
                result = self.show_menu("Continue?", ["Yes", "Cancel"])
                if result != 0:
                    return
        
        # Install new version
        ram = self.config.get("ram_gb", 4)
        
        def progress_cb(downloaded, total):
            pct = downloaded / total if total > 0 else 0
            self.show_progress("Version Change", "Downloading new server.jar...", pct)
        
        success, message = self.server.install(
            selected["id"], selected["url"], ram,
            progress_callback=progress_cb
        )
        
        color = self.COLOR_GREEN if success else self.COLOR_RED
        self.show_message("Version Change", message, color)
    
    def handle_backup(self) -> None:
        """Handle backup operations"""
        while True:
            options = ["Create Backup Now", "View Backups", "Back"]
            result = self.show_menu("Backup Worlds", options)
            
            if result == -1 or result == 2:
                return
            elif result == 0:
                self.show_progress("Backup", "Creating backup...")
                success, message = self.backup.create_backup()
                color = self.COLOR_GREEN if success else self.COLOR_RED
                self.show_message("Backup", message, color)
            elif result == 1:
                backups = self.backup.list_backups()
                if not backups:
                    self.show_message("Backups", "No backups found", self.COLOR_YELLOW)
                else:
                    backup_list = []
                    for b in backups[:10]:
                        size_mb = b["size"] / (1024 * 1024)
                        date_str = b["date"].strftime("%Y-%m-%d %H:%M")
                        backup_list.append(f"{b['name'][:20]}  {size_mb:.1f}MB  {date_str}")
                    backup_list.append("Back")
                    self.show_menu("Available Backups", backup_list)
    
    def handle_settings(self) -> None:
        """Handle settings menu"""
        while True:
            current_dir = self.config.get("server_dir", DEFAULT_SERVER_DIR)
            current_ram = self.config.get("ram_gb", 4)
            auto_backup = self.config.get("auto_backup", True)
            max_backups = self.config.get("max_backups", 5)
            
            options = [
                f"Server Directory: {current_dir[:25]}...",
                f"Default RAM: {current_ram} GB",
                f"Auto-backup on version change: {'ON' if auto_backup else 'OFF'}",
                f"Max backups to keep: {max_backups}",
                "Back"
            ]
            
            result = self.show_menu("Settings", options)
            
            if result == -1 or result == 4:
                return
            elif result == 0:
                new_dir = self.get_input("Server Directory", current_dir)
                if new_dir:
                    self.config.set("server_dir", new_dir)
                    self.server.server_dir = new_dir
                    self.backup.server_dir = new_dir
                    self.backup.backup_dir = os.path.join(new_dir, "backups")
            elif result == 1:
                new_ram = self.get_input("Default RAM (GB)", str(current_ram))
                try:
                    ram = int(new_ram)
                    if 1 <= ram <= 64:
                        self.config.set("ram_gb", ram)
                except ValueError:
                    pass
            elif result == 2:
                self.config.set("auto_backup", not auto_backup)
            elif result == 3:
                new_max = self.get_input("Max backups", str(max_backups))
                try:
                    max_b = int(new_max)
                    if 1 <= max_b <= 100:
                        self.config.set("max_backups", max_b)
                except ValueError:
                    pass
    
    def run(self) -> None:
        """Main application loop"""
        while True:
            status = self.server.get_status()
            status_indicator = "● Running" if status["running"] else "○ Stopped"
            
            options = [
                "Install Server",
                "Start Server",
                "Stop Server",
                f"Server Status  [{status_indicator}]",
                "Execute Command",
                "View Console",
                "Change Version",
                "Backup Worlds",
                "Settings",
                "Exit"
            ]
            
            result = self.show_menu("🎮 Minecraft Server Manager", options)
            
            if result == -1 or result == 9:
                break
            elif result == 0:
                self.handle_install()
            elif result == 1:
                self.handle_start()
            elif result == 2:
                self.handle_stop()
            elif result == 3:
                self.handle_status()
            elif result == 4:
                self.handle_command()
            elif result == 5:
                self.handle_console()
            elif result == 6:
                self.handle_version_change()
            elif result == 7:
                self.handle_backup()
            elif result == 8:
                self.handle_settings()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Mode
# ═══════════════════════════════════════════════════════════════════════════════

def cli_main(args: argparse.Namespace) -> int:
    """Handle CLI commands"""
    config = Config()
    server = MinecraftServer(config)
    backup = BackupManager(config)
    
    if args.status:
        status = server.get_status()
        print(json.dumps(status, indent=2))
        return 0
    
    if args.start:
        success, message = server.start()
        print(message)
        return 0 if success else 1
    
    if args.stop:
        success, message = server.stop(graceful=True)
        print(message)
        return 0 if success else 1
    
    if args.backup:
        def status_cb(msg):
            print(f"  {msg}")
        success, message = backup.create_backup(status_callback=status_cb)
        print(message)
        return 0 if success else 1
    
    if args.command:
        success, message = server.send_command(args.command)
        print(message)
        return 0 if success else 1
    
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def check_requirements() -> Tuple[bool, List[str]]:
    """Check if required system dependencies are installed"""
    missing = []
    
    # Check for screen
    try:
        result = subprocess.run(["screen", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            missing.append("screen")
    except FileNotFoundError:
        missing.append("screen")
    
    # Check for java
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True)
        if result.returncode != 0:
            missing.append("java")
    except FileNotFoundError:
        missing.append("java")
    
    return len(missing) == 0, missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Minecraft Server Manager TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s              Open TUI interface
  %(prog)s --start      Start the server
  %(prog)s --stop       Stop the server
  %(prog)s --status     Show server status (JSON)
  %(prog)s --backup     Create world backup
  %(prog)s -c "say hi"  Send command to server
        """
    )
    
    parser.add_argument("--start", action="store_true", help="Start the server")
    parser.add_argument("--stop", action="store_true", help="Stop the server")
    parser.add_argument("--status", action="store_true", help="Show server status")
    parser.add_argument("--backup", action="store_true", help="Create world backup")
    parser.add_argument("-c", "--command", type=str, help="Send command to server")
    parser.add_argument("--skip-checks", action="store_true", help="Skip dependency checks")
    
    args = parser.parse_args()
    
    # Check requirements (unless skipped or just checking status)
    if not args.skip_checks and not args.status:
        ok, missing = check_requirements()
        if not ok:
            print("❌ Missing required dependencies:")
            for dep in missing:
                if dep == "screen":
                    print(f"  • {dep} — install with: sudo apt install screen")
                elif dep == "java":
                    print(f"  • {dep} — install with: sudo apt install openjdk-21-jre-headless")
            print("\nInstall missing dependencies and try again.")
            print("Or use --skip-checks to bypass (not recommended).")
            return 1
    
    # If any CLI args, run in CLI mode
    if args.start or args.stop or args.status or args.backup or args.command:
        return cli_main(args)
    
    # Otherwise, run TUI
    try:
        return curses.wrapper(lambda stdscr: TUI(stdscr).run() or 0)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
