"""Admin routes - Management endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import List, Optional
from datetime import datetime
import asyncio
import re
import secrets
import zipfile
from urllib.parse import urlparse
from pathlib import Path
from pydantic import BaseModel
from ..core.auth import AuthManager
from ..core.config import config
from ..services.token_manager import TokenManager
from ..services.proxy_manager import ProxyManager
from ..services.sora_client import SoraClient
from ..services.concurrency_manager import ConcurrencyManager
from ..core.database import Database
from ..core.models import Token, AdminConfig, ProxyConfig, CharacterCard

router = APIRouter()

# Dependency injection
token_manager: TokenManager = None
proxy_manager: ProxyManager = None
db: Database = None
generation_handler = None
concurrency_manager: ConcurrencyManager = None

# Store active admin tokens (in production, use Redis or database)
active_admin_tokens = set()

def set_dependencies(tm: TokenManager, pm: ProxyManager, database: Database, gh=None, cm: ConcurrencyManager = None):
    """Set dependencies"""
    global token_manager, proxy_manager, db, generation_handler, concurrency_manager
    token_manager = tm
    proxy_manager = pm
    db = database
    generation_handler = gh
    concurrency_manager = cm

def verify_admin_token(authorization: str = Header(None)):
    """Verify admin token from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    # Support both "Bearer token" and "token" formats
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]

    if token not in active_admin_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return token

# Request/Response models
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: Optional[str] = None

class AddTokenRequest(BaseModel):
    token: str  # Access Token (AT)
    st: Optional[str] = None  # Session Token (optional, for storage)
    rt: Optional[str] = None  # Refresh Token (optional, for storage)
    client_id: Optional[str] = None  # Client ID (optional)
    remark: Optional[str] = None
    image_enabled: bool = True  # Enable image generation
    video_enabled: bool = True  # Enable video generation
    image_concurrency: int = -1  # Image concurrency limit (-1 for no limit)
    video_concurrency: int = -1  # Video concurrency limit (-1 for no limit)

class ST2ATRequest(BaseModel):
    st: str  # Session Token

class RT2ATRequest(BaseModel):
    rt: str  # Refresh Token

class UpdateTokenStatusRequest(BaseModel):
    is_active: bool

class UpdateTokenRequest(BaseModel):
    token: Optional[str] = None  # Access Token
    st: Optional[str] = None
    rt: Optional[str] = None
    client_id: Optional[str] = None  # Client ID
    remark: Optional[str] = None
    image_enabled: Optional[bool] = None  # Enable image generation
    video_enabled: Optional[bool] = None  # Enable video generation
    image_concurrency: Optional[int] = None  # Image concurrency limit
    video_concurrency: Optional[int] = None  # Video concurrency limit

class ImportTokenItem(BaseModel):
    email: str  # Email (primary key)
    access_token: str  # Access Token (AT)
    session_token: Optional[str] = None  # Session Token (ST)
    refresh_token: Optional[str] = None  # Refresh Token (RT)
    is_active: bool = True  # Active status
    image_enabled: bool = True  # Enable image generation
    video_enabled: bool = True  # Enable video generation
    image_concurrency: int = -1  # Image concurrency limit
    video_concurrency: int = -1  # Video concurrency limit

class ImportTokensRequest(BaseModel):
    tokens: List[ImportTokenItem]

class UpdateAdminConfigRequest(BaseModel):
    error_ban_threshold: int

class UpdateProxyConfigRequest(BaseModel):
    proxy_enabled: bool
    proxy_url: Optional[str] = None

class UpdateAdminPasswordRequest(BaseModel):
    old_password: str
    new_password: str
    username: Optional[str] = None  # Optional: new username

class UpdateAPIKeyRequest(BaseModel):
    new_api_key: str

class UpdateDebugConfigRequest(BaseModel):
    enabled: bool

class UpdateCacheTimeoutRequest(BaseModel):
    timeout: int  # Cache timeout in seconds

class UpdateCacheBaseUrlRequest(BaseModel):
    base_url: str  # Cache base URL (e.g., https://yourdomain.com)

class UpdateGenerationTimeoutRequest(BaseModel):
    image_timeout: Optional[int] = None  # Image generation timeout in seconds
    video_timeout: Optional[int] = None  # Video generation timeout in seconds

class UpdateWatermarkFreeConfigRequest(BaseModel):
    watermark_free_enabled: bool
    parse_method: Optional[str] = "third_party"  # "third_party" or "custom"
    custom_parse_url: Optional[str] = None
    custom_parse_token: Optional[str] = None

# Character card responses
class CharacterCardResponse(BaseModel):
    id: int
    token_id: Optional[int] = None
    username: str
    display_name: str
    description: Optional[str] = None
    character_id: Optional[str] = None
    cameo_id: Optional[str] = None
    avatar_path: Optional[str] = None
    source_video: Optional[str] = None
    created_at: Optional[str] = None

class UpdateCharacterNameRequest(BaseModel):
    display_name: str

# Batch download (ZIP) models
class BatchZipItem(BaseModel):
    url: str
    filename: str

class BatchZipRequest(BaseModel):
    title: Optional[str] = None
    items: List[BatchZipItem]

# Auth endpoints
@router.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Admin login"""
    if AuthManager.verify_admin(request.username, request.password):
        # Generate simple token
        token = f"admin-{secrets.token_urlsafe(32)}"
        # Store token in active tokens
        active_admin_tokens.add(token)
        return LoginResponse(success=True, token=token, message="Login successful")
    else:
        return LoginResponse(success=False, message="Invalid credentials")

@router.post("/api/logout")
async def logout(token: str = Depends(verify_admin_token)):
    """Admin logout"""
    # Remove token from active tokens
    active_admin_tokens.discard(token)
    return {"success": True, "message": "Logged out successfully"}

# Token management endpoints
@router.get("/api/tokens")
async def get_tokens(token: str = Depends(verify_admin_token)) -> List[dict]:
    """Get all tokens with statistics"""
    tokens = await token_manager.get_all_tokens()
    result = []

    for token in tokens:
        stats = await db.get_token_stats(token.id)
        result.append({
            "id": token.id,
            "token": token.token,  # 完整的Access Token
            "st": token.st,  # 完整的Session Token
            "rt": token.rt,  # 完整的Refresh Token
            "client_id": token.client_id,  # Client ID
            "email": token.email,
            "name": token.name,
            "remark": token.remark,
            "expiry_time": token.expiry_time.isoformat() if token.expiry_time else None,
            "is_active": token.is_active,
            "cooled_until": token.cooled_until.isoformat() if token.cooled_until else None,
            "created_at": token.created_at.isoformat() if token.created_at else None,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
            "use_count": token.use_count,
            "image_count": stats.image_count if stats else 0,
            "video_count": stats.video_count if stats else 0,
            "error_count": stats.error_count if stats else 0,
            # 订阅信息
            "plan_type": token.plan_type,
            "plan_title": token.plan_title,
            "subscription_end": token.subscription_end.isoformat() if token.subscription_end else None,
            # Sora2信息
            "sora2_supported": token.sora2_supported,
            "sora2_invite_code": token.sora2_invite_code,
            "sora2_redeemed_count": token.sora2_redeemed_count,
            "sora2_total_count": token.sora2_total_count,
            "sora2_remaining_count": token.sora2_remaining_count,
            "sora2_cooldown_until": token.sora2_cooldown_until.isoformat() if token.sora2_cooldown_until else None,
            # 功能开关
            "image_enabled": token.image_enabled,
            "video_enabled": token.video_enabled,
            # 并发限制
            "image_concurrency": token.image_concurrency,
            "video_concurrency": token.video_concurrency
        })

    return result

@router.post("/api/tokens")
async def add_token(request: AddTokenRequest, token: str = Depends(verify_admin_token)):
    """Add a new Access Token"""
    try:
        new_token = await token_manager.add_token(
            token_value=request.token,
            st=request.st,
            rt=request.rt,
            client_id=request.client_id,
            remark=request.remark,
            update_if_exists=False,
            image_enabled=request.image_enabled,
            video_enabled=request.video_enabled,
            image_concurrency=request.image_concurrency,
            video_concurrency=request.video_concurrency
        )
        # Initialize concurrency counters for the new token
        if concurrency_manager:
            await concurrency_manager.reset_token(
                new_token.id,
                image_concurrency=request.image_concurrency,
                video_concurrency=request.video_concurrency
            )
        return {"success": True, "message": "Token 添加成功", "token_id": new_token.id}
    except ValueError as e:
        # Token already exists
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"添加 Token 失败: {str(e)}")

@router.post("/api/tokens/st2at")
async def st_to_at(request: ST2ATRequest, token: str = Depends(verify_admin_token)):
    """Convert Session Token to Access Token (only convert, not add to database)"""
    try:
        result = await token_manager.st_to_at(request.st)
        return {
            "success": True,
            "message": "ST converted to AT successfully",
            "access_token": result["access_token"],
            "email": result.get("email"),
            "expires": result.get("expires")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/tokens/rt2at")
async def rt_to_at(request: RT2ATRequest, token: str = Depends(verify_admin_token)):
    """Convert Refresh Token to Access Token (only convert, not add to database)"""
    try:
        result = await token_manager.rt_to_at(request.rt)
        return {
            "success": True,
            "message": "RT converted to AT successfully",
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token"),
            "expires_in": result.get("expires_in")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/api/tokens/{token_id}/status")
async def update_token_status(
    token_id: int,
    request: UpdateTokenStatusRequest,
    token: str = Depends(verify_admin_token)
):
    """Update token status"""
    try:
        await token_manager.update_token_status(token_id, request.is_active)

        # Reset error count when enabling token
        if request.is_active:
            await token_manager.record_success(token_id)

        return {"success": True, "message": "Token status updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/tokens/{token_id}/enable")
async def enable_token(token_id: int, token: str = Depends(verify_admin_token)):
    """Enable a token and reset error count"""
    try:
        await token_manager.enable_token(token_id)
        return {"success": True, "message": "Token enabled", "is_active": 1, "error_count": 0}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/tokens/{token_id}/disable")
async def disable_token(token_id: int, token: str = Depends(verify_admin_token)):
    """Disable a token"""
    try:
        await token_manager.disable_token(token_id)
        return {"success": True, "message": "Token disabled", "is_active": 0}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/tokens/{token_id}/test")
async def test_token(token_id: int, token: str = Depends(verify_admin_token)):
    """Test if a token is valid and refresh Sora2 info"""
    try:
        result = await token_manager.test_token(token_id)
        response = {
            "success": True,
            "status": "success" if result["valid"] else "failed",
            "message": result["message"],
            "email": result.get("email"),
            "username": result.get("username")
        }

        # Include Sora2 info if available
        if result.get("valid"):
            response.update({
                "sora2_supported": result.get("sora2_supported"),
                "sora2_invite_code": result.get("sora2_invite_code"),
                "sora2_redeemed_count": result.get("sora2_redeemed_count"),
                "sora2_total_count": result.get("sora2_total_count"),
                "sora2_remaining_count": result.get("sora2_remaining_count")
            })

        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/api/tokens/{token_id}")
async def delete_token(token_id: int, token: str = Depends(verify_admin_token)):
    """Delete a token"""
    try:
        await token_manager.delete_token(token_id)
        return {"success": True, "message": "Token deleted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/tokens/import")
async def import_tokens(request: ImportTokensRequest, token: str = Depends(verify_admin_token)):
    """Import tokens in append mode (update if exists, add if not)"""
    try:
        added_count = 0
        updated_count = 0

        for import_item in request.tokens:
            # Check if token with this email already exists
            existing_token = await db.get_token_by_email(import_item.email)

            if existing_token:
                # Update existing token
                await token_manager.update_token(
                    token_id=existing_token.id,
                    token=import_item.access_token,
                    st=import_item.session_token,
                    rt=import_item.refresh_token,
                    image_enabled=import_item.image_enabled,
                    video_enabled=import_item.video_enabled,
                    image_concurrency=import_item.image_concurrency,
                    video_concurrency=import_item.video_concurrency
                )
                # Update active status
                await token_manager.update_token_status(existing_token.id, import_item.is_active)
                # Reset concurrency counters
                if concurrency_manager:
                    await concurrency_manager.reset_token(
                        existing_token.id,
                        image_concurrency=import_item.image_concurrency,
                        video_concurrency=import_item.video_concurrency
                    )
                updated_count += 1
            else:
                # Add new token
                new_token = await token_manager.add_token(
                    token_value=import_item.access_token,
                    st=import_item.session_token,
                    rt=import_item.refresh_token,
                    update_if_exists=False,
                    image_enabled=import_item.image_enabled,
                    video_enabled=import_item.video_enabled,
                    image_concurrency=import_item.image_concurrency,
                    video_concurrency=import_item.video_concurrency
                )
                # Set active status
                if not import_item.is_active:
                    await token_manager.disable_token(new_token.id)
                # Initialize concurrency counters
                if concurrency_manager:
                    await concurrency_manager.reset_token(
                        new_token.id,
                        image_concurrency=import_item.image_concurrency,
                        video_concurrency=import_item.video_concurrency
                    )
                added_count += 1

        return {
            "success": True,
            "message": f"Import completed: {added_count} added, {updated_count} updated",
            "added": added_count,
            "updated": updated_count
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")

@router.put("/api/tokens/{token_id}")
async def update_token(
    token_id: int,
    request: UpdateTokenRequest,
    token: str = Depends(verify_admin_token)
):
    """Update token (AT, ST, RT, remark, image_enabled, video_enabled, concurrency limits)"""
    try:
        await token_manager.update_token(
            token_id=token_id,
            token=request.token,
            st=request.st,
            rt=request.rt,
            client_id=request.client_id,
            remark=request.remark,
            image_enabled=request.image_enabled,
            video_enabled=request.video_enabled,
            image_concurrency=request.image_concurrency,
            video_concurrency=request.video_concurrency
        )
        # Reset concurrency counters if they were updated
        if concurrency_manager and (request.image_concurrency is not None or request.video_concurrency is not None):
            await concurrency_manager.reset_token(
                token_id,
                image_concurrency=request.image_concurrency if request.image_concurrency is not None else -1,
                video_concurrency=request.video_concurrency if request.video_concurrency is not None else -1
            )
        return {"success": True, "message": "Token updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Admin config endpoints
@router.get("/api/admin/config")
async def get_admin_config(token: str = Depends(verify_admin_token)) -> dict:
    """Get admin configuration"""
    admin_config = await db.get_admin_config()
    return {
        "error_ban_threshold": admin_config.error_ban_threshold,
        "api_key": config.api_key,
        "admin_username": config.admin_username,
        "debug_enabled": config.debug_enabled
    }

@router.post("/api/admin/config")
async def update_admin_config(
    request: UpdateAdminConfigRequest,
    token: str = Depends(verify_admin_token)
):
    """Update admin configuration"""
    try:
        # Get current admin config to preserve username and password
        current_config = await db.get_admin_config()

        # Update only the error_ban_threshold, preserve username and password
        current_config.error_ban_threshold = request.error_ban_threshold

        await db.update_admin_config(current_config)
        return {"success": True, "message": "Configuration updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/admin/password")
async def update_admin_password(
    request: UpdateAdminPasswordRequest,
    token: str = Depends(verify_admin_token)
):
    """Update admin password and/or username"""
    try:
        # Verify old password
        if not AuthManager.verify_admin(config.admin_username, request.old_password):
            raise HTTPException(status_code=400, detail="Old password is incorrect")

        # Get current admin config from database
        admin_config = await db.get_admin_config()

        # Update password in database
        admin_config.admin_password = request.new_password

        # Update username if provided
        if request.username:
            admin_config.admin_username = request.username

        # Update in database
        await db.update_admin_config(admin_config)

        # Update in-memory config
        config.set_admin_password_from_db(request.new_password)
        if request.username:
            config.set_admin_username_from_db(request.username)

        # Invalidate all admin tokens (force re-login)
        active_admin_tokens.clear()

        return {"success": True, "message": "Password updated successfully. Please login again."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update password: {str(e)}")

@router.post("/api/admin/apikey")
async def update_api_key(
    request: UpdateAPIKeyRequest,
    token: str = Depends(verify_admin_token)
):
    """Update API key"""
    try:
        # Get current admin config from database
        admin_config = await db.get_admin_config()

        # Update api_key in database
        admin_config.api_key = request.new_api_key
        await db.update_admin_config(admin_config)

        # Update in-memory config
        config.api_key = request.new_api_key

        return {"success": True, "message": "API key updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update API key: {str(e)}")

@router.post("/api/admin/debug")
async def update_debug_config(
    request: UpdateDebugConfigRequest,
    token: str = Depends(verify_admin_token)
):
    """Update debug configuration"""
    try:
        # Update in-memory config
        config.set_debug_enabled(request.enabled)

        status = "enabled" if request.enabled else "disabled"
        return {"success": True, "message": f"Debug mode {status}", "enabled": request.enabled}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update debug config: {str(e)}")

# Proxy config endpoints
@router.get("/api/proxy/config")
async def get_proxy_config(token: str = Depends(verify_admin_token)) -> dict:
    """Get proxy configuration"""
    config = await proxy_manager.get_proxy_config()
    return {
        "proxy_enabled": config.proxy_enabled,
        "proxy_url": config.proxy_url
    }

@router.post("/api/proxy/config")
async def update_proxy_config(
    request: UpdateProxyConfigRequest,
    token: str = Depends(verify_admin_token)
):
    """Update proxy configuration"""
    try:
        await proxy_manager.update_proxy_config(request.proxy_enabled, request.proxy_url)
        return {"success": True, "message": "Proxy configuration updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Watermark-free config endpoints
@router.get("/api/watermark-free/config")
async def get_watermark_free_config(token: str = Depends(verify_admin_token)) -> dict:
    """Get watermark-free mode configuration"""
    config_obj = await db.get_watermark_free_config()
    return {
        "watermark_free_enabled": config_obj.watermark_free_enabled,
        "parse_method": config_obj.parse_method,
        "custom_parse_url": config_obj.custom_parse_url,
        "custom_parse_token": config_obj.custom_parse_token
    }

@router.post("/api/watermark-free/config")
async def update_watermark_free_config(
    request: UpdateWatermarkFreeConfigRequest,
    token: str = Depends(verify_admin_token)
):
    """Update watermark-free mode configuration"""
    try:
        await db.update_watermark_free_config(
            request.watermark_free_enabled,
            request.parse_method,
            request.custom_parse_url,
            request.custom_parse_token
        )

        # Update in-memory config
        from ..core.config import config
        config.set_watermark_free_enabled(request.watermark_free_enabled)

        return {"success": True, "message": "Watermark-free mode configuration updated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Statistics endpoints
@router.get("/api/stats")
async def get_stats(token: str = Depends(verify_admin_token)):
    """Get system statistics"""
    tokens = await token_manager.get_all_tokens()
    active_tokens = await token_manager.get_active_tokens()

    total_images = 0
    total_videos = 0
    total_errors = 0
    today_images = 0
    today_videos = 0
    today_errors = 0

    for token in tokens:
        stats = await db.get_token_stats(token.id)
        if stats:
            total_images += stats.image_count
            total_videos += stats.video_count
            total_errors += stats.error_count
            today_images += stats.today_image_count
            today_videos += stats.today_video_count
            today_errors += stats.today_error_count

    return {
        "total_tokens": len(tokens),
        "active_tokens": len(active_tokens),
        "total_images": total_images,
        "total_videos": total_videos,
        "today_images": today_images,
        "today_videos": today_videos,
        "total_errors": total_errors,
        "today_errors": today_errors
    }

# Sora2 endpoints
@router.post("/api/tokens/{token_id}/sora2/activate")
async def activate_sora2(
    token_id: int,
    invite_code: str,
    token: str = Depends(verify_admin_token)
):
    """Activate Sora2 with invite code"""
    try:
        # Get token
        token_obj = await db.get_token(token_id)
        if not token_obj:
            raise HTTPException(status_code=404, detail="Token not found")

        # Activate Sora2
        result = await token_manager.activate_sora2_invite(token_obj.token, invite_code)

        if result.get("success"):
            # Get new invite code after activation
            sora2_info = await token_manager.get_sora2_invite_code(token_obj.token)

            # Get remaining count
            sora2_remaining_count = 0
            try:
                remaining_info = await token_manager.get_sora2_remaining_count(token_obj.token)
                if remaining_info.get("success"):
                    sora2_remaining_count = remaining_info.get("remaining_count", 0)
            except Exception as e:
                print(f"Failed to get Sora2 remaining count: {e}")

            # Update database
            await db.update_token_sora2(
                token_id,
                supported=True,
                invite_code=sora2_info.get("invite_code"),
                redeemed_count=sora2_info.get("redeemed_count", 0),
                total_count=sora2_info.get("total_count", 0),
                remaining_count=sora2_remaining_count
            )

            return {
                "success": True,
                "message": "Sora2 activated successfully",
                "already_accepted": result.get("already_accepted", False),
                "invite_code": sora2_info.get("invite_code"),
                "redeemed_count": sora2_info.get("redeemed_count", 0),
                "total_count": sora2_info.get("total_count", 0),
                "sora2_remaining_count": sora2_remaining_count
            }
        else:
            return {
                "success": False,
                "message": "Failed to activate Sora2"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to activate Sora2: {str(e)}")

# Logs endpoints
@router.get("/api/logs")
async def get_logs(limit: int = 100, token: str = Depends(verify_admin_token)):
    """Get recent logs with token email"""
    logs = await db.get_recent_logs(limit)
    return [{
        "id": log.get("id"),
        "token_id": log.get("token_id"),
        "token_email": log.get("token_email"),
        "token_username": log.get("token_username"),
        "operation": log.get("operation"),
        "status_code": log.get("status_code"),
        "duration": log.get("duration"),
        "created_at": log.get("created_at")
    } for log in logs]

# Download endpoints
def _sanitize_filename_component(name: str, fallback: str = "download") -> str:
    """Sanitize for Windows/macOS/Linux safe filenames (no path traversal, no reserved chars)."""
    s = (name or "").strip()
    if not s:
        return fallback
    # Remove control chars
    s = re.sub(r"[\x00-\x1f\x7f]+", "", s)
    # Windows forbidden: \ / : * ? " < > |
    s = re.sub(r'[\\/:*?"<>|]+', "-", s)
    # Normalize spaces
    s = re.sub(r"\s+", " ", s).strip()
    # No trailing dot/space (Windows)
    s = re.sub(r"[. ]+$", "", s)
    if not s:
        return fallback
    if len(s) > 120:
        s = s[:120].strip()
    return s or fallback

def _extract_tmp_relpath(url: str) -> Optional[str]:
    """Map a URL like http://host/tmp/xx.mp4 (or /tmp/xx.mp4) to a safe relative path 'tmp/xx.mp4'."""
    raw = (url or "").strip()
    if not raw:
        return None
    path = raw
    try:
        parsed = urlparse(raw)
        if parsed and parsed.path:
            path = parsed.path
    except Exception:
        path = raw

    if path.startswith("/tmp/"):
        rel = path.lstrip("/")  # tmp/xx.mp4
    elif path.startswith("tmp/"):
        rel = path
    else:
        return None

    # Disallow traversal
    if ".." in Path(rel).parts:
        return None
    return rel

@router.post("/api/download/batch-zip")
async def create_batch_zip(request: BatchZipRequest, token: str = Depends(verify_admin_token)):
    """Create a ZIP bundle from existing /tmp cached files and return its /tmp URL.

    Notes:
    - Only allows bundling files under /tmp (static mount), never arbitrary filesystem paths.
    - Uses ZIP_STORED (no compression) for speed, videos are already compressed.
    """
    items = request.items if request and isinstance(request.items, list) else []
    if not items:
        raise HTTPException(status_code=400, detail="No items to bundle")
    if len(items) > 240:
        raise HTTPException(status_code=400, detail="Too many items (max 240)")

    root_dir = Path(__file__).parent.parent.parent
    tmp_root = root_dir / "tmp"
    tmp_root.mkdir(exist_ok=True)
    tmp_root_resolved = tmp_root.resolve()

    title_raw = (request.title or "").strip() if request else ""
    title = _sanitize_filename_component(title_raw, fallback="batch")
    title = re.sub(r"\s+", "_", title).strip("_") or "batch"
    if len(title) > 48:
        title = title[:48].strip("_") or "batch"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_urlsafe(8).replace("-", "").replace("_", "")
    zip_filename = f"{title}_{ts}_{rand}.zip"
    zip_path = (tmp_root / zip_filename)

    def _build_zip_sync() -> dict:
        added = 0
        skipped = 0
        used_names = set()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for it in items:
                rel = _extract_tmp_relpath(getattr(it, "url", None))
                if not rel:
                    skipped += 1
                    continue
                fs_path = (root_dir / rel).resolve()
                # Must stay within tmp root
                if tmp_root_resolved not in fs_path.parents and fs_path != tmp_root_resolved:
                    skipped += 1
                    continue
                if not fs_path.exists() or not fs_path.is_file():
                    skipped += 1
                    continue

                desired = getattr(it, "filename", None)
                arc = _sanitize_filename_component(desired, fallback=fs_path.name)
                # Strip any directories just in case
                arc = Path(arc).name
                # Ensure unique names inside zip
                stem = Path(arc).stem
                ext = Path(arc).suffix
                candidate = arc
                k = 2
                while candidate in used_names:
                    candidate = f"{stem}_{k}{ext}"
                    k += 1
                arc = candidate
                used_names.add(arc)

                zf.write(fs_path, arcname=arc)
                added += 1

        return {"added": added, "skipped": skipped}

    try:
        result = await asyncio.to_thread(_build_zip_sync)
    except Exception as e:
        # Best-effort cleanup
        try:
            if zip_path.exists():
                zip_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create zip: {str(e)}")

    if not result.get("added"):
        try:
            if zip_path.exists():
                zip_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="No valid /tmp files found for bundling")

    return {
        "success": True,
        "url": f"/tmp/{zip_filename}",
        "filename": zip_filename,
        "count": int(result.get("added") or 0),
        "skipped": int(result.get("skipped") or 0)
    }

# Character card endpoints
@router.post("/api/characters/sync")
async def sync_characters(token: str = Depends(verify_admin_token)):
    """Sync characters from all active tokens to local database"""
    try:
        # Get active tokens
        active_tokens = await token_manager.get_active_tokens()
        if not active_tokens:
            return {"success": True, "message": "No active tokens found", "synced_count": 0}

        # Initialize SoraClient
        client = SoraClient(proxy_manager)
        
        synced_count = 0
        errors = []

        # Ensure avatar directory exists
        root_dir = Path(__file__).parent.parent.parent
        avatar_dir = root_dir / "tmp" / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)

        for t in active_tokens:
            try:
                # Fetch characters from API
                try:
                    characters = await client.get_characters(t.token)
                except Exception as e:
                    # If 401, try to refresh token
                    if "401" in str(e):
                        print(f"Token {t.id} expired during sync, trying to refresh...")
                        refreshed = await token_manager.auto_refresh_expiring_token(t.id, force=True)
                        if refreshed:
                            # Reload token
                            updated_token = await db.get_token(t.id)
                            if updated_token:
                                print(f"Token {t.id} refreshed, retrying sync...")
                                characters = await client.get_characters(updated_token.token)
                            else:
                                raise e
                        else:
                            raise Exception("Token expired and refresh failed")
                    else:
                        raise e
                
                for char in characters:
                    char_id = char.get("id")
                    if not char_id:
                        continue

                    # Check if already exists
                    existing = await db.get_character_card_by_remote_id(char_id)
                    if existing:
                        continue

                    # Download avatar
                    avatar_url = char.get("profile_asset_url")
                    avatar_path = None
                    if avatar_url:
                        try:
                            avatar_data = await client.download_character_image(avatar_url)
                            # Save to tmp/avatars/
                            filename = f"{char_id}.webp"
                            file_path = avatar_dir / filename
                            with open(file_path, "wb") as f:
                                f.write(avatar_data)
                            avatar_path = f"/tmp/avatars/{filename}"
                        except Exception as e:
                            print(f"Failed to download avatar for {char_id}: {e}")
                    
                    # Create CharacterCard
                    new_card = CharacterCard(
                        token_id=t.id,
                        username=char.get("username", ""),
                        display_name=char.get("display_name", ""),
                        description=char.get("description", ""),
                        character_id=char_id,
                        cameo_id=char.get("cameo_id"),
                        avatar_path=avatar_path,
                        source_video=None
                    )
                    
                    await db.create_character_card(new_card)
                    synced_count += 1

            except Exception as e:
                errors.append(f"Token {t.id} failed: {str(e)}")
                continue

        return {
            "success": True, 
            "message": f"Synced {synced_count} characters", 
            "synced_count": synced_count,
            "errors": errors
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")

@router.get("/api/characters", response_model=List[CharacterCardResponse])
async def get_characters(token: str = Depends(verify_admin_token)):
    """List stored character cards"""
    cards = await db.list_character_cards()
    return cards

@router.delete("/api/characters/{card_id}")
async def delete_character_card(card_id: int, token: str = Depends(verify_admin_token)):
    """Delete a stored character card (and its avatar file if exists)"""
    try:
        avatar_path = await db.delete_character_card(card_id)
        if avatar_path:
            # avatar_path starts with /tmp/..., map to filesystem
            static_path = Path(__file__).parent.parent.parent / avatar_path.lstrip("/")
            if static_path.exists():
                try:
                    static_path.unlink()
                except Exception:
                    pass
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete character card: {str(e)}")

def _guess_cn_alias(name: str, desc: str = "") -> str:
    """Lightweight Chinese alias generator, keep logic consistent with generation handler without external calls."""
    if name and any('\u4e00' <= ch <= '\u9fff' for ch in name):
        return name
    text = f"{name or ''} {desc or ''}".lower()
    kw = {
        "wolf": "狼", "fox": "狐", "cat": "猫", "dog": "犬", "dragon": "龙",
        "girl": "少女", "boy": "少年", "princess": "公主", "prince": "王子",
        "robot": "机甲", "mecha": "机甲", "mage": "法师", "wizard": "巫师",
        "witch": "女巫", "snow": "雪", "frost": "霜", "ice": "冰", "winter": "冬",
        "cold": "寒", "fire": "火", "flame": "焰", "summer": "夏", "autumn": "秋",
        "spring": "春", "sky": "天", "star": "星", "light": "光", "shadow": "影",
        "dark": "暗", "blue": "蓝", "red": "红", "green": "绿", "white": "白",
        "black": "黑", "pink": "粉", "gold": "金", "silver": "银", "moon": "月",
        "sun": "日", "forest": "林", "flower": "花", "fairy": "精灵", "angel": "天使"
    }
    hits = [v for k, v in kw.items() if k in text]
    if hits:
        alias = "".join(hits[:3])
        return alias or name or "角色"
    words = [w for w in (name or "").split() if w]
    if words:
        initials = "".join(w[0].upper() for w in words if w[0].isalpha())
        return f"角色{initials}" if initials else (name or "角色")
    return name or "角色"

@router.put("/api/characters/{card_id}/display_name")
async def update_character_display_name(card_id: int, request: UpdateCharacterNameRequest, token: str = Depends(verify_admin_token)):
    """Update character display_name (used for中文化名称修正)"""
    try:
        new_name = request.display_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="display_name cannot be empty")
        await db.update_character_card_display_name(card_id, new_name)
        return {"success": True, "display_name": new_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update character name: {str(e)}")

# Cache config endpoints
@router.post("/api/cache/config")
async def update_cache_timeout(
    request: UpdateCacheTimeoutRequest,
    token: str = Depends(verify_admin_token)
):
    """Update cache timeout"""
    try:
        if request.timeout < 60:
            raise HTTPException(status_code=400, detail="Cache timeout must be at least 60 seconds")

        if request.timeout > 86400:
            raise HTTPException(status_code=400, detail="Cache timeout cannot exceed 24 hours (86400 seconds)")

        # Update in-memory config
        config.set_cache_timeout(request.timeout)

        # Update database
        await db.update_cache_config(timeout=request.timeout)

        # Update file cache timeout
        if generation_handler:
            generation_handler.file_cache.set_timeout(request.timeout)

        return {
            "success": True,
            "message": f"Cache timeout updated to {request.timeout} seconds",
            "timeout": request.timeout
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update cache timeout: {str(e)}")

@router.post("/api/cache/base-url")
async def update_cache_base_url(
    request: UpdateCacheBaseUrlRequest,
    token: str = Depends(verify_admin_token)
):
    """Update cache base URL"""
    try:
        # Validate base URL format (optional, can be empty)
        base_url = request.base_url.strip()
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise HTTPException(
                status_code=400,
                detail="Base URL must start with http:// or https://"
            )

        # Remove trailing slash
        if base_url:
            base_url = base_url.rstrip('/')

        # Update in-memory config
        config.set_cache_base_url(base_url)

        # Update database
        await db.update_cache_config(base_url=base_url)

        return {
            "success": True,
            "message": f"Cache base URL updated to: {base_url or 'server address'}",
            "base_url": base_url
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update cache base URL: {str(e)}")

@router.get("/api/cache/config")
async def get_cache_config(token: str = Depends(verify_admin_token)):
    """Get cache configuration"""
    return {
        "success": True,
        "config": {
            "enabled": config.cache_enabled,
            "timeout": config.cache_timeout,
            "base_url": config.cache_base_url,  # 返回实际配置的值，可能为空字符串
            "effective_base_url": config.cache_base_url or f"http://{config.server_host}:{config.server_port}"  # 实际生效的值
        }
    }

@router.post("/api/cache/enabled")
async def update_cache_enabled(
    request: dict,
    token: str = Depends(verify_admin_token)
):
    """Update cache enabled status"""
    try:
        enabled = request.get("enabled", True)

        # Update in-memory config
        config.set_cache_enabled(enabled)

        # Update database
        await db.update_cache_config(enabled=enabled)

        return {
            "success": True,
            "message": f"Cache {'enabled' if enabled else 'disabled'} successfully",
            "enabled": enabled
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update cache enabled status: {str(e)}")

# Generation timeout config endpoints
@router.get("/api/generation/timeout")
async def get_generation_timeout(token: str = Depends(verify_admin_token)):
    """Get generation timeout configuration"""
    return {
        "success": True,
        "config": {
            "image_timeout": config.image_timeout,
            "video_timeout": config.video_timeout
        }
    }

@router.post("/api/generation/timeout")
async def update_generation_timeout(
    request: UpdateGenerationTimeoutRequest,
    token: str = Depends(verify_admin_token)
):
    """Update generation timeout configuration"""
    try:
        # Validate timeouts
        if request.image_timeout is not None:
            if request.image_timeout < 60:
                raise HTTPException(status_code=400, detail="Image timeout must be at least 60 seconds")
            if request.image_timeout > 3600:
                raise HTTPException(status_code=400, detail="Image timeout cannot exceed 1 hour (3600 seconds)")

        if request.video_timeout is not None:
            if request.video_timeout < 60:
                raise HTTPException(status_code=400, detail="Video timeout must be at least 60 seconds")
            if request.video_timeout > 7200:
                raise HTTPException(status_code=400, detail="Video timeout cannot exceed 2 hours (7200 seconds)")

        # Update in-memory config
        if request.image_timeout is not None:
            config.set_image_timeout(request.image_timeout)
        if request.video_timeout is not None:
            config.set_video_timeout(request.video_timeout)

        # Update database
        await db.update_generation_config(
            image_timeout=request.image_timeout,
            video_timeout=request.video_timeout
        )

        # Update TokenLock timeout if image timeout was changed
        if request.image_timeout is not None and generation_handler:
            generation_handler.load_balancer.token_lock.set_lock_timeout(config.image_timeout)

        return {
            "success": True,
            "message": "Generation timeout configuration updated",
            "config": {
                "image_timeout": config.image_timeout,
                "video_timeout": config.video_timeout
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update generation timeout: {str(e)}")

# AT auto refresh config endpoints
@router.get("/api/token-refresh/config")
async def get_at_auto_refresh_config(token: str = Depends(verify_admin_token)):
    """Get AT auto refresh configuration"""
    return {
        "success": True,
        "config": {
            "at_auto_refresh_enabled": config.at_auto_refresh_enabled
        }
    }

@router.post("/api/token-refresh/enabled")
async def update_at_auto_refresh_enabled(
    request: dict,
    token: str = Depends(verify_admin_token)
):
    """Update AT auto refresh enabled status"""
    try:
        enabled = request.get("enabled", False)

        # Update in-memory config
        config.set_at_auto_refresh_enabled(enabled)

        # Update database
        await db.update_token_refresh_config(enabled)

        return {
            "success": True,
            "message": f"AT auto refresh {'enabled' if enabled else 'disabled'} successfully",
            "enabled": enabled
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update AT auto refresh enabled status: {str(e)}")

@router.post("/api/token-refresh/refresh")
async def manual_refresh_at(token: str = Depends(verify_admin_token)):
    """
    Manually trigger AT auto-refresh for tokens that are about to expire.
    Reuses the same logic as load balancer: refresh tokens expiring within 24h using ST/RT.
    """
    if not token_manager:
        raise HTTPException(status_code=500, detail="Token manager not initialized")
    try:
        tokens = await token_manager.get_all_tokens()
        refreshed = 0
        checked = 0
        details = []
        for t in tokens:
            checked += 1
            expiry_before = t.expiry_time
            ok = await token_manager.auto_refresh_expiring_token(t.id, force=True)
            # reload token to read new expiry
            updated = await db.get_token(t.id)
            expiry_after = updated.expiry_time
            extended = False
            if expiry_before and expiry_after:
                extended = expiry_after > expiry_before
            if extended:
                refreshed += 1
            reason = "extended" if extended else ("no_new_at" if ok else "refresh_failed")
            details.append({
                "token_id": t.id,
                "email": t.email,
                "before": expiry_before.isoformat() if expiry_before else None,
                "after": expiry_after.isoformat() if expiry_after else None,
                "result": "success" if extended else "no_change",
                "reason": reason
            })
        return {
            "success": True,
            "checked": checked,
            "refreshed": refreshed,
            "message": f"已检查 {checked} 个 Token，刷新成功 {refreshed} 个",
            "details": details
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual refresh failed: {str(e)}")
