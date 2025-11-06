"""
IP Access Control System
=========================
Controls network access to mobile attendance functionality.

Author: AI Assistant
Version: 2.0 (Simplified)
Purpose: Restrict network devices to mobile attendance page only
"""

import json
import os
from datetime import datetime, timedelta

# Configuration
ACCESS_CONTROL_FILE = "mobile_access_control.json"
DEFAULT_EXPIRY_MINUTES = 5

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_lan_ip():
    """
    Get the server's LAN IP address.
    
    Returns:
        str: LAN IP address or "UNKNOWN" if detection fails
    
    Example:
        >>> get_lan_ip()
        '192.168.1.100'
    """
    import socket
    try:
        # Create UDP socket (doesn't actually send data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Google DNS
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"[ERROR] Failed to get LAN IP: {e}")
        return "UNKNOWN"


def is_localhost(ip):
    """
    Check if IP address is localhost.
    
    Args:
        ip (str): IP address to check
    
    Returns:
        bool: True if localhost, False otherwise
    
    Examples:
        >>> is_localhost('127.0.0.1')
        True
        >>> is_localhost('192.168.1.5')
        False
    """
    return ip in ['127.0.0.1', 'localhost', '::1']


def is_network_device(ip):
    """
    Check if IP is from network (not localhost).
    
    Args:
        ip (str): IP address to check
    
    Returns:
        bool: True if network device, False if localhost
    """
    return not is_localhost(ip)


# ============================================================================
# JSON STORAGE OPERATIONS
# ============================================================================

def load_access_control():
    """
    Load access control state from JSON file.
    
    Returns:
        dict: Access control data with keys:
            - enabled (bool): Whether mobile access is active
            - expiry_time (str): ISO format timestamp
            - activated_at (str): ISO format timestamp
    
    File Structure:
        {
            "enabled": false,
            "expiry_time": "2024-01-15T14:30:00",
            "activated_at": "2024-01-15T14:25:00",
            "duration_minutes": 5
        }
    """
    try:
        if os.path.exists(ACCESS_CONTROL_FILE):
            with open(ACCESS_CONTROL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        # Return default state if file doesn't exist
        return {
            "enabled": False,
            "expiry_time": None,
            "activated_at": None
        }
    except Exception as e:
        print(f"[ERROR] Failed to load access control: {e}")
        return {
            "enabled": False,
            "expiry_time": None,
            "activated_at": None
        }


def save_access_control(data):
    """
    Save access control state to JSON file (atomic write).
    
    Args:
        data (dict): Access control data to save
    
    Returns:
        bool: True if save successful, False otherwise
    """
    try:
        # Atomic write: write to temp file, then rename
        temp_file = ACCESS_CONTROL_FILE + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        
        # Rename (atomic on most systems)
        os.replace(temp_file, ACCESS_CONTROL_FILE)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save access control: {e}")
        return False


# ============================================================================
# ACCESS CONTROL LOGIC
# ============================================================================

def is_mobile_access_enabled():
    """
    Check if mobile access is currently enabled and not expired.
    
    Returns:
        bool: True if access is active and not expired
    
    Side Effects:
        - Automatically disables access if expired
    
    Logic Flow:
        1. Load current state from JSON
        2. Check if enabled flag is True
        3. Check if current time < expiry time
        4. Auto-disable if expired
    """
    data = load_access_control()
    
    # Check enabled flag
    if not data.get("enabled", False):
        return False
    
    # Check expiry time
    expiry_time = data.get("expiry_time")
    if not expiry_time:
        return False
    
    try:
        expiry_dt = datetime.fromisoformat(expiry_time)
        now = datetime.now()
        
        # Check if expired
        if now > expiry_dt:
            # Auto-disable expired access
            disable_mobile_access()
            return False
        
        return True
    except Exception as e:
        print(f"[ERROR] Failed to check expiry: {e}")
        return False


def enable_mobile_access(duration_minutes=DEFAULT_EXPIRY_MINUTES):
    """
    Enable mobile access for specified duration.
    
    Args:
        duration_minutes (int): How long to enable access (default: 5)
    
    Returns:
        tuple: (success: bool, expiry_time: datetime or None)
    
    Example:
        >>> success, expiry = enable_mobile_access(5)
        >>> if success:
        ...     print(f"Access enabled until {expiry}")
    """
    try:
        now = datetime.now()
        expiry_time = now + timedelta(minutes=duration_minutes)
        
        data = {
            "enabled": True,
            "activated_at": now.isoformat(),
            "expiry_time": expiry_time.isoformat(),
            "duration_minutes": duration_minutes
        }
        
        if save_access_control(data):
            print(f"[INFO] Mobile access enabled until {expiry_time.strftime('%H:%M:%S')}")
            return True, expiry_time
        
        print("[ERROR] Failed to enable mobile access")
        return False, None
    except Exception as e:
        print(f"[ERROR] Enable mobile access failed: {e}")
        return False, None


def disable_mobile_access():
    """
    Disable mobile access immediately.
    
    Returns:
        bool: True if successfully disabled
    
    Side Effects:
        - Clears expiry_time and activated_at
        - Sets enabled to False
    """
    try:
        data = {
            "enabled": False,
            "expiry_time": None,
            "activated_at": None,
            "disabled_at": datetime.now().isoformat()
        }
        
        if save_access_control(data):
            print("[INFO] Mobile access disabled")
            return True
        
        print("[ERROR] Failed to disable mobile access")
        return False
    except Exception as e:
        print(f"[ERROR] Disable mobile access failed: {e}")
        return False


def get_access_status():
    """
    Get detailed current access status with remaining time.
    
    Returns:
        dict: Status information with keys:
            - enabled (bool): Is access currently active
            - expiry_time (str): When access expires (ISO format)
            - remaining_seconds (int): Seconds until expiry
            - remaining_minutes (int): Minutes until expiry
            - remaining_formatted (str): "MM:SS" format
    
    Example:
        >>> status = get_access_status()
        >>> print(f"Enabled: {status['enabled']}")
        >>> print(f"Time left: {status['remaining_formatted']}")
    """
    data = load_access_control()
    
    # Default status (disabled)
    status = {
        "enabled": False,
        "expiry_time": None,
        "remaining_seconds": 0,
        "remaining_minutes": 0,
        "remaining_formatted": "0:00"
    }
    
    # Check if enabled
    if not data.get("enabled", False):
        return status
    
    expiry_time = data.get("expiry_time")
    if not expiry_time:
        return status
    
    try:
        expiry_dt = datetime.fromisoformat(expiry_time)
        now = datetime.now()
        
        # Check if expired
        if now > expiry_dt:
            disable_mobile_access()
            return status
        
        # Calculate remaining time
        remaining = expiry_dt - now
        remaining_seconds = int(remaining.total_seconds())
        
        status = {
            "enabled": True,
            "expiry_time": expiry_time,
            "remaining_seconds": remaining_seconds,
            "remaining_minutes": remaining_seconds // 60,
            "remaining_formatted": f"{remaining_seconds // 60}:{remaining_seconds % 60:02d}"
        }
        
        return status
    except Exception as e:
        print(f"[ERROR] Failed to get access status: {e}")
        return status


def check_mobile_access(client_ip):
    """
    Check if a client IP should have mobile access.
    
    This is the MAIN access control function used by middleware.
    
    Args:
        client_ip (str): Client's IP address
    
    Returns:
        tuple: (allowed: bool, reason: str)
    
    Logic:
        - Localhost → Always allowed
        - Network device + access enabled → Allowed
        - Network device + access disabled → Denied
    
    Example:
        >>> allowed, reason = check_mobile_access('127.0.0.1')
        >>> print(allowed)  # True
        >>> print(reason)   # 'localhost_access'
        
        >>> allowed, reason = check_mobile_access('192.168.1.5')
        >>> print(allowed)  # Depends on mobile access status
        >>> print(reason)   # 'mobile_access_enabled' or 'mobile_access_disabled'
    """
    # Rule 1: Localhost always has full access
    if is_localhost(client_ip):
        return True, "localhost_access"
    
    # Rule 2: Network devices need mobile access enabled
    if is_network_device(client_ip):
        if is_mobile_access_enabled():
            return True, "mobile_access_enabled"
        else:
            return False, "mobile_access_disabled"
    
    # Rule 3: Unknown source (shouldn't happen)
    return False, "unknown_source"


# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize():
    """
    Initialize access control system.
    Creates JSON file if it doesn't exist.
    """
    if not os.path.exists(ACCESS_CONTROL_FILE):
        save_access_control({
            "enabled": False,
            "expiry_time": None,
            "activated_at": None
        })
        print(f"[INFO] Created {ACCESS_CONTROL_FILE}")


# Auto-initialize on import
initialize()