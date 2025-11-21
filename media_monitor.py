import os
import time
import logging
import psutil
import win32gui
import win32process
from threading import Thread, Event
from watch_status import WatchStatusManager

class MediaPlayerMonitor:
    def __init__(self, watch_manager=None):
        self.watch_manager = watch_manager or WatchStatusManager()
        self.monitoring = False
        self.stop_event = Event()
        self.current_file = None
        self.monitor_thread = None
        
        # Common media player process names
        self.media_players = {
            'wmplayer.exe': 'Windows Media Player',
            'vlc.exe': 'VLC',
            'mpc-hc64.exe': 'Media Player Classic',
            'mpc-hc.exe': 'Media Player Classic',
            'PotPlayerMini64.exe': 'PotPlayer',
            'PotPlayerMini.exe': 'PotPlayer',
            'Movies&TV.exe': 'Windows Movies & TV'
        }

    def start_monitoring(self, file_path):
        """Start monitoring playback for a specific file"""
        self.current_file = file_path
        if not self.monitor_thread or not self.monitor_thread.is_alive():
            self.stop_event.clear()
            self.monitoring = True
            self.monitor_thread = Thread(target=self._monitor_playback, daemon=True)
            self.monitor_thread.start()

    def stop_monitoring(self):
        """Stop monitoring playback"""
        self.monitoring = False
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        self.current_file = None

    def _monitor_playback(self):
        """Monitor media player status and update watch progress"""
        start_time = time.time()
        last_active = time.time()
        player_found = False

        while self.monitoring and not self.stop_event.is_set():
            try:
                # Look for media player processes
                for proc in psutil.process_iter(['name', 'pid']):
                    if proc.info['name'] and proc.info['name'].lower() in [p.lower() for p in self.media_players.keys()]:
                        player_found = True
                        # Check if window is still open
                        if not self._is_process_window_visible(proc.info['pid']):
                            # Player window closed - check if enough time passed
                            elapsed_time = time.time() - start_time
                            if elapsed_time > 60:  # Minimum 1 minute of playback
                                self._update_watch_status()
                            self.stop_monitoring()
                            return
                        last_active = time.time()
                        break

                # If no player found for 5 seconds, stop monitoring
                if not player_found and time.time() - last_active > 5:
                    self.stop_monitoring()
                    return

                time.sleep(1)  # Check every second
                
            except Exception as e:
                logging.error(f"Error monitoring playback: {str(e)}")
                self.stop_monitoring()
                return

    def _is_process_window_visible(self, pid):
        """Check if a process has any visible windows"""
        def callback(hwnd, results):
            try:
                _, process_pid = win32process.GetWindowThreadProcessId(hwnd)
                if process_pid == pid and win32gui.IsWindowVisible(hwnd):
                    results.append(hwnd)
            except:
                pass
            return True

        results = []
        win32gui.EnumWindows(callback, results)
        return len(results) > 0

    def _update_watch_status(self):
        """Update watch status when playback ends"""
        if self.current_file:
            self.watch_manager.mark_watched(self.current_file, True)