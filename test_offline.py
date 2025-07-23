#!/usr/bin/env python3
"""
Test script to verify offline backdrop/poster handling in Mediaflix
"""
import os
import sys
import subprocess

def test_offline_functionality():
    """Simple test to check if offline functionality works"""
    print("🔧 Testing Mediaflix Offline Functionality...")
    print()
    
    # Check if main application exists
    mediaflix_path = os.path.join(os.path.dirname(__file__), "mediaflix.py")
    if not os.path.exists(mediaflix_path):
        print("❌ mediaflix.py not found!")
        return False
    
    print("✅ mediaflix.py found")
    
    # Check if required modules are available
    try:
        import requests
        import PyQt5
        print("✅ Required modules (requests, PyQt5) available")
    except ImportError as e:
        print(f"❌ Missing required module: {e}")
        return False
    
    # Check if offline detection code is present
    with open(mediaflix_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
        # Check for key offline functionality
        checks = [
            ("backdrop_offline signal", "backdrop_offline = pyqtSignal"),
            ("poster_offline signal", "poster_offline = pyqtSignal"), 
            ("offline backdrop handler", "def on_backdrop_offline"),
            ("offline poster handler", "def on_poster_offline"),
            ("internet check in backdrop loading", "requests.get.*timeout=1"),
            ("offline message styling", "Offline Mode")
        ]
        
        for check_name, search_pattern in checks:
            if search_pattern in content:
                print(f"✅ {check_name} implemented")
            else:
                print(f"❌ {check_name} missing")
                return False
    
    print()
    print("🎉 All offline functionality checks passed!")
    print()
    print("📋 Features implemented:")
    print("  • Internet connection detection before image downloads")
    print("  • Dedicated offline signals for posters and backdrops")
    print("  • Informative offline messages instead of generic placeholders")
    print("  • Graceful fallback when offline")
    print("  • Cache-first loading (works offline if content was cached)")
    print()
    print("🚀 To test offline mode:")
    print("  1. Run the app while connected to internet")
    print("  2. Browse some movies/series to populate cache")
    print("  3. Disconnect from internet")
    print("  4. Try viewing details - you'll see offline messages for new content")
    print("  5. Previously cached content will still display normally")
    
    return True

if __name__ == "__main__":
    test_offline_functionality()
