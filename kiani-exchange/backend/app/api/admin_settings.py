"""
Admin settings for API configurations
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, validator

from ..database import get_db
# Import from users module since _require_roles is defined there
from .users import _require_roles as require_roles

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# Models
# ============================================================================

class AdminAuthRequest(BaseModel):
    username: str
    password: str

class EhrazSettings(BaseModel):
    enabled: bool = True
    token: str = ""
    test_mode: bool = False
    proxy_list: List[str] = []
    timeout_seconds: int = 6
    max_retries: int = 3

class GhasedakSettings(BaseModel):
    enabled: bool = True
    api_key: str = ""
    template_name: str = ""
    line_number: str = ""
    otp_endpoint: str = "https://gateway.ghasedak.me/rest/api/v1/WebService/SendOtpWithParams"
    simple_endpoint: str = "https://api.ghasedak.me/v2/sms/send/simple"
    proxy_format: str = "http://jjebraham-{n}:Amir1234@59.152.60.100:6040"
    proxy_pool_start: int = 1
    proxy_pool_end: int = 100
    timeout_seconds: int = 15
    max_retries: int = 3

class ApiSettingsUpdate(BaseModel):
    ehraz: Optional[EhrazSettings] = None
    ghasedak: Optional[GhasedakSettings] = None

class ApiTestRequest(BaseModel):
    api_type: str  # "ehraz" or "ghasedak"
    test_data: Dict[str, Any] = {}

# ============================================================================
# Database functions
# ============================================================================

def init_settings_tables():
    """Initialize settings tables if they don't exist"""
    with get_db() as conn:
        # API settings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_type TEXT NOT NULL,  -- 'ehraz' or 'ghasedak'
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT
            )
        """)
        
        # API test logs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_test_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_type TEXT NOT NULL,
                test_data TEXT NOT NULL,
                result TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert default settings if not exists
        ehraz_exists = conn.execute(
            "SELECT 1 FROM api_settings WHERE setting_type = 'ehraz'"
        ).fetchone()
        
        if not ehraz_exists:
            default_ehraz = EhrazSettings(
                token="5942b9d62abc20405dadfb2c0f546b669cf1471c",
                proxy_list=[f"http://jjebraham-{i}:Amir1234@p.webshare.io:80" for i in range(1, 101)],
                test_mode=False
            )
            conn.execute(
                "INSERT INTO api_settings (setting_type, settings_json) VALUES (?, ?)",
                ("ehraz", json.dumps(default_ehraz.dict()))
            )
        
        ghasedak_exists = conn.execute(
            "SELECT 1 FROM api_settings WHERE setting_type = 'ghasedak'"
        ).fetchone()
        
        if not ghasedak_exists:
            default_ghasedak = GhasedakSettings(
                api_key="e065bed2072abf1b45ff990251b9e103bf1979332a70c07ecb7afd9807086f1egDGE3wCJddwRUFwY",
                template_name="ghasedak2",
                line_number="30005088",
                proxy_format="http://jjebraham-{n}:Amir1234@59.152.60.100:6040"
            )
            conn.execute(
                "INSERT INTO api_settings (setting_type, settings_json) VALUES (?, ?)",
                ("ghasedak", json.dumps(default_ghasedak.dict()))
            )

def get_settings(setting_type: str) -> Dict[str, Any]:
    """Get settings from database"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT settings_json FROM api_settings WHERE setting_type = ? ORDER BY id DESC LIMIT 1",
            (setting_type,)
        ).fetchone()
        
        if row:
            return json.loads(row["settings_json"])
        return {}

def save_settings(setting_type: str, settings: Dict[str, Any], updated_by: str = "admin"):
    """Save settings to database"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO api_settings (setting_type, settings_json, updated_by) 
               VALUES (?, ?, ?)""",
            (setting_type, json.dumps(settings), updated_by)
        )

def log_test_result(api_type: str, test_data: Dict[str, Any], result: str, success: bool):
    """Log API test results"""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO api_test_logs (api_type, test_data, result, success) 
               VALUES (?, ?, ?, ?)""",
            (api_type, json.dumps(test_data), result, 1 if success else 0)
        )

# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/admin/api-settings")
async def get_api_settings(username: str, password: str):
    """Get all API settings"""
    require_roles(username, password, {"admin", "support"})
    
    init_settings_tables()
    
    ehraz_settings = get_settings("ehraz")
    ghasedak_settings = get_settings("ghasedak")
    
    return {
        "ehraz": ehraz_settings,
        "ghasedak": ghasedak_settings,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/admin/api-settings/update")
async def update_api_settings(req: AdminAuthRequest, update: ApiSettingsUpdate):
    """Update API settings"""
    require_roles(req.username, req.password, {"admin"})
    
    init_settings_tables()
    
    if update.ehraz:
        save_settings("ehraz", update.ehraz.dict(), req.username)
        logger.info(f"EHRAZ settings updated by {req.username}")
    
    if update.ghasedak:
        save_settings("ghasedak", update.ghasedak.dict(), req.username)
        logger.info(f"Ghasedak settings updated by {req.username}")
    
    return {"status": "success", "message": "Settings updated"}

@router.post("/admin/api-settings/test")
async def test_api(req: AdminAuthRequest, test_req: ApiTestRequest):
    """Test API connection"""
    require_roles(req.username, req.password, {"admin", "support"})
    
    init_settings_tables()
    
    if test_req.api_type == "ehraz":
        result = await _test_ehraz_api(test_req.test_data)
    elif test_req.api_type == "ghasedak":
        result = await _test_ghasedak_api(test_req.test_data)
    else:
        raise HTTPException(status_code=400, detail="Invalid API type")
    
    # Log test result
    log_test_result(
        test_req.api_type,
        test_req.test_data,
        json.dumps(result),
        result.get("success", False)
    )
    
    return result

async def _test_ehraz_api(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """Test EHRAZ API connection"""
    import aiohttp
    import asyncio
    
    settings = get_settings("ehraz")
    token = settings.get("token", "")
    proxy_list = settings.get("proxy_list", [])
    timeout = settings.get("timeout_seconds", 6)
    
    if not token:
        return {"success": False, "error": "EHRAZ token not configured"}
    
    if not proxy_list:
        return {"success": False, "error": "No proxies configured"}
    
    # Use test data or default
    phone = test_data.get("phone", "09121958296")
    nid = test_data.get("national_id", "0083263497")
    
    url = "https://ehraz.io/api/v1/match/national-with-mobile"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "nationalCode": nid,
        "mobileNumber": phone
    }
    
    # Try with first proxy
    proxy_url = proxy_list[0] if proxy_list else None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                proxy=proxy_url,
                timeout=timeout,
            ) as resp:
                body = await resp.text()
                
                try:
                    data = json.loads(body) if body.strip() else {}
                except:
                    data = {"raw_response": body[:500]}
                
                return {
                    "success": resp.status == 200,
                    "status_code": resp.status,
                    "response": data,
                    "proxy_used": proxy_url,
                    "test_data": {"phone": phone, "national_id": nid}
                }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "proxy_used": proxy_url,
            "test_data": {"phone": phone, "national_id": nid}
        }

async def _test_ghasedak_api(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """Test Ghasedak API connection"""
    import aiohttp
    import random
    
    settings = get_settings("ghasedak")
    api_key = settings.get("api_key", "")
    template = settings.get("template_name", "")
    proxy_format = settings.get("proxy_format", "")
    proxy_start = settings.get("proxy_pool_start", 1)
    proxy_end = settings.get("proxy_pool_end", 100)
    timeout = settings.get("timeout_seconds", 15)
    
    if not api_key:
        return {"success": False, "error": "Ghasedak API key not configured"}
    
    if not template:
        return {"success": False, "error": "Ghasedak template not configured"}
    
    # Use test data or default
    phone = test_data.get("phone", "09121958296")
    code = test_data.get("code", "123456")
    
    url = "https://gateway.ghasedak.me/rest/api/v1/WebService/SendOtpWithParams"
    headers = {
        "accept": "text/plain",
        "ApiKey": api_key,
        "Content-Type": "application/json",
    }
    
    payload = {
        "receptors": [{"mobile": phone, "clientReferenceId": "test"}],
        "templateName": template,
        "param1": code,
        "isVoice": False,
        "udh": False,
    }
    
    # Generate proxy URL
    proxy_num = random.randint(proxy_start, proxy_end)
    proxy_url = proxy_format.format(n=proxy_num)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                proxy=proxy_url,
                timeout=timeout,
            ) as resp:
                body = await resp.text()
                
                try:
                    data = json.loads(body) if body.strip() else {}
                except:
                    data = {"raw_response": body[:500]}
                
                # Check success
                success = resp.status == 200 and (data.get("isSuccess") is True or "isSuccess" not in data)
                
                return {
                    "success": success,
                    "status_code": resp.status,
                    "response": data,
                    "proxy_used": proxy_url,
                    "test_data": {"phone": phone, "code": code, "template": template}
                }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "proxy_used": proxy_url,
            "test_data": {"phone": phone, "code": code, "template": template}
        }

@router.get("/admin/api-test-logs")
async def get_test_logs(username: str, password: str, limit: int = 50):
    """Get API test logs"""
    require_roles(username, password, {"admin", "support"})
    
    init_settings_tables()
    
    with get_db() as conn:
        logs = conn.execute(
            """SELECT * FROM api_test_logs 
               ORDER BY created_at DESC 
               LIMIT ?""",
            (limit,)
        ).fetchall()
    
    return {"logs": [dict(log) for log in logs]}

# Initialize tables on import
init_settings_tables()
