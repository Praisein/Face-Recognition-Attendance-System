# init_ip_config.py - Initialize IP access configuration
import json
import os

IP_ACCESS_CONFIG_FILE = "ip_access_config.json"

def init_ip_access_config():
    """Initialize IP access configuration file if it doesn't exist"""
    if not os.path.exists(IP_ACCESS_CONFIG_FILE):
        default_config = {
            "enabled": False,
            "expiry_time": None,
            "enabled_at": None,
            "enabled_by": None,
            "disabled_at": None,
            "disabled_by": None
        }
        
        try:
            with open(IP_ACCESS_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            print(f"[INFO] Created {IP_ACCESS_CONFIG_FILE}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to create {IP_ACCESS_CONFIG_FILE}: {e}")
            return False
    else:
        print(f"[INFO] {IP_ACCESS_CONFIG_FILE} already exists")
        return True

if __name__ == '__main__':
    init_ip_access_config()