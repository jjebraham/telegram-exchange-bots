"""
API Settings helper - gets settings from database
"""

import json
import logging
from typing import Dict, Any, List

from .database import get_db

logger = logging.getLogger(__name__)

def get_api_settings(setting_type: str) -> Dict[str, Any]:
    """Get API settings from database"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT settings_json FROM api_settings WHERE setting_type = ? ORDER BY id DESC LIMIT 1",
            (setting_type,)
        ).fetchone()
        
        if row:
            return json.loads(row["settings_json"])
        return {}

def get_ehraz_settings() -> Dict[str, Any]:
    """Get EHRAZ settings"""
    return get_api_settings("ehraz")

def get_ghasedak_settings() -> Dict[str, Any]:
    """Get Ghasedak settings"""
    return get_api_settings("ghasedak")

def get_ehraz_token() -> str:
    """Get EHRAZ token"""
    settings = get_ehraz_settings()
    return settings.get("token", "")

def get_ehraz_proxies() -> List[str]:
    """Get EHRAZ proxy list"""
    settings = get_ehraz_settings()
    return settings.get("proxy_list", [])

def get_ehraz_test_mode() -> bool:
    """Get EHRAZ test mode"""
    settings = get_ehraz_settings()
    return settings.get("test_mode", False)

def get_ghasedak_api_key() -> str:
    """Get Ghasedak API key"""
    settings = get_ghasedak_settings()
    return settings.get("api_key", "")

def get_ghasedak_template() -> str:
    """Get Ghasedak template name"""
    settings = get_ghasedak_settings()
    return settings.get("template_name", "")

def get_ghasedak_line_number() -> str:
    """Get Ghasedak line number"""
    settings = get_ghasedak_settings()
    return settings.get("line_number", "")

def get_ghasedak_proxy_format() -> str:
    """Get Ghasedak proxy format"""
    settings = get_ghasedak_settings()
    return settings.get("proxy_format", "http://jjebraham-{n}:Amir1234@59.152.60.100:6040")

def get_ghasedak_proxy_pool() -> tuple[int, int]:
    """Get Ghasedak proxy pool range"""
    settings = get_ghasedak_settings()
    start = settings.get("proxy_pool_start", 1)
    end = settings.get("proxy_pool_end", 100)
    return (start, end)

# Initialize settings table if it doesn't exist
def init_settings():
    """Initialize settings table"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_type TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)

# Initialize on import
init_settings()
