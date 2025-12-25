"""Configuration management with environment variable priority for HuggingFace Spaces"""
import os
import tomli
import toml
from pathlib import Path
from typing import Dict, Any, Optional


def _is_hf_spaces() -> bool:
    """Check if running on HuggingFace Spaces"""
    return os.environ.get("HF_SPACES", "").lower() == "true" or os.environ.get("SPACE_ID") is not None


def _get_env(key: str, default: Any = None, cast_type: type = str) -> Any:
    """Get environment variable with type casting"""
    value = os.environ.get(key)
    if value is None:
        return default
    if cast_type == bool:
        return value.lower() in ("true", "1", "yes", "on")
    return cast_type(value)


class Config:
    """Application configuration with environment variable priority"""

    def __init__(self):
        self._config = self._load_config()
        self._admin_username: Optional[str] = None
        self._admin_password: Optional[str] = None
        self._is_hf_spaces = _is_hf_spaces()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from setting.toml"""
        config_path = Path(__file__).parent.parent.parent / "config" / "setting.toml"
        try:
            with open(config_path, "rb") as f:
                return tomli.load(f)
        except FileNotFoundError:
            # Return default config if file not found (e.g., in HF Spaces)
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "global": {
                "api_key": "han1234",
                "admin_username": "admin",
                "admin_password": "admin"
            },
            "sora": {
                "base_url": "https://sora.chatgpt.com/backend",
                "timeout": 120,
                "max_retries": 3,
                "poll_interval": 2.5,
                "max_poll_attempts": 600
            },
            "server": {
                "host": "0.0.0.0",
                "port": 7860
            },
            "debug": {
                "enabled": False,
                "log_requests": True,
                "log_responses": True,
                "mask_token": True
            },
            "cache": {
                "enabled": False,
                "timeout": 600,
                "base_url": ""
            },
            "generation": {
                "image_timeout": 300,
                "video_timeout": 1500
            },
            "admin": {
                "error_ban_threshold": 3
            },
            "proxy": {
                "proxy_enabled": False,
                "proxy_url": ""
            },
            "watermark_free": {
                "watermark_free_enabled": False,
                "parse_method": "third_party",
                "custom_parse_url": "",
                "custom_parse_token": ""
            },
            "token_refresh": {
                "at_auto_refresh_enabled": False
            },
            "google_drive": {
                "enabled": False,
                "space_url": "https://iyougame-url2drive.hf.space",
                "password": ""
            }
        }

    def reload_config(self):
        """Reload configuration from file"""
        self._config = self._load_config()

    def get_raw_config(self) -> Dict[str, Any]:
        """Get raw configuration dictionary"""
        return self._config
    
    @property
    def admin_username(self) -> str:
        # Environment variable takes priority
        env_val = _get_env("ADMIN_USERNAME")
        if env_val:
            return env_val
        # If admin_username is set from database, use it; otherwise fall back to config file
        if self._admin_username is not None:
            return self._admin_username
        return self._config["global"]["admin_username"]

    @admin_username.setter
    def admin_username(self, value: str):
        self._admin_username = value
        self._config["global"]["admin_username"] = value

    def set_admin_username_from_db(self, username: str):
        """Set admin username from database"""
        self._admin_username = username

    @property
    def sora_base_url(self) -> str:
        return _get_env("SORA_BASE_URL") or self._config["sora"]["base_url"]
    
    @property
    def sora_timeout(self) -> int:
        return _get_env("SORA_TIMEOUT", self._config["sora"]["timeout"], int)
    
    @property
    def sora_max_retries(self) -> int:
        return _get_env("SORA_MAX_RETRIES", self._config["sora"]["max_retries"], int)
    
    @property
    def poll_interval(self) -> float:
        return _get_env("POLL_INTERVAL", self._config["sora"]["poll_interval"], float)
    
    @property
    def max_poll_attempts(self) -> int:
        return _get_env("MAX_POLL_ATTEMPTS", self._config["sora"]["max_poll_attempts"], int)
    
    @property
    def server_host(self) -> str:
        return _get_env("SERVER_HOST") or self._config["server"]["host"]
    
    @property
    def server_port(self) -> int:
        # HuggingFace Spaces requires port 7860
        if self._is_hf_spaces:
            return _get_env("SERVER_PORT", 7860, int)
        return _get_env("SERVER_PORT", self._config["server"]["port"], int)

    @property
    def debug_enabled(self) -> bool:
        return _get_env("DEBUG_ENABLED", self._config.get("debug", {}).get("enabled", False), bool)

    @property
    def debug_log_requests(self) -> bool:
        return _get_env("DEBUG_LOG_REQUESTS", self._config.get("debug", {}).get("log_requests", True), bool)

    @property
    def debug_log_responses(self) -> bool:
        return _get_env("DEBUG_LOG_RESPONSES", self._config.get("debug", {}).get("log_responses", True), bool)

    @property
    def debug_mask_token(self) -> bool:
        return _get_env("DEBUG_MASK_TOKEN", self._config.get("debug", {}).get("mask_token", True), bool)

    # Mutable properties for runtime updates
    @property
    def api_key(self) -> str:
        return _get_env("API_KEY") or self._config["global"]["api_key"]

    @api_key.setter
    def api_key(self, value: str):
        self._config["global"]["api_key"] = value
        # Only persist to file if not on HF Spaces (read-only filesystem)
        if not self._is_hf_spaces:
            self._persist_single("global", "api_key", value)

    @property
    def admin_password(self) -> str:
        # Environment variable takes priority
        env_val = _get_env("ADMIN_PASSWORD")
        if env_val:
            return env_val
        # If admin_password is set from database, use it; otherwise fall back to config file
        if self._admin_password is not None:
            return self._admin_password
        return self._config["global"]["admin_password"]

    @admin_password.setter
    def admin_password(self, value: str):
        self._admin_password = value
        self._config["global"]["admin_password"] = value

    def set_admin_password_from_db(self, password: str):
        """Set admin password from database"""
        self._admin_password = password

    def _persist_single(self, section: str, key: str, value: Any):
        """
        持久化单个配置项到 setting.toml，避免用内存态覆盖其它字段。
        在 HuggingFace Spaces 上跳过（只读文件系统）
        """
        if self._is_hf_spaces:
            return
        
        config_path = Path(__file__).parent.parent.parent / "config" / "setting.toml"
        try:
            data = self._load_config()  # 重新读取磁盘，确保拿到最新值
            if section not in data:
                data[section] = {}
            data[section][key] = value
            with open(config_path, "w", encoding="utf-8") as f:
                toml.dump(data, f)
            # 更新内存副本
            self._config = data
        except (FileNotFoundError, PermissionError):
            # Skip if file not found or permission denied
            pass

    def set_debug_enabled(self, enabled: bool):
        """Set debug mode enabled/disabled"""
        if "debug" not in self._config:
            self._config["debug"] = {}
        self._config["debug"]["enabled"] = enabled

    @property
    def cache_timeout(self) -> int:
        """Get cache timeout in seconds"""
        return _get_env("CACHE_TIMEOUT", self._config.get("cache", {}).get("timeout", 7200), int)

    def set_cache_timeout(self, timeout: int):
        """Set cache timeout in seconds"""
        if "cache" not in self._config:
            self._config["cache"] = {}
        self._config["cache"]["timeout"] = timeout

    @property
    def cache_base_url(self) -> str:
        """Get cache base URL"""
        return _get_env("CACHE_BASE_URL") or self._config.get("cache", {}).get("base_url", "")

    def set_cache_base_url(self, base_url: str):
        """Set cache base URL"""
        if "cache" not in self._config:
            self._config["cache"] = {}
        self._config["cache"]["base_url"] = base_url

    @property
    def cache_enabled(self) -> bool:
        """Get cache enabled status"""
        return _get_env("CACHE_ENABLED", self._config.get("cache", {}).get("enabled", False), bool)

    def set_cache_enabled(self, enabled: bool):
        """Set cache enabled status"""
        if "cache" not in self._config:
            self._config["cache"] = {}
        self._config["cache"]["enabled"] = enabled

    @property
    def image_timeout(self) -> int:
        """Get image generation timeout in seconds"""
        return _get_env("IMAGE_TIMEOUT", self._config.get("generation", {}).get("image_timeout", 300), int)

    def set_image_timeout(self, timeout: int):
        """Set image generation timeout in seconds"""
        if "generation" not in self._config:
            self._config["generation"] = {}
        self._config["generation"]["image_timeout"] = timeout

    @property
    def video_timeout(self) -> int:
        """Get video generation timeout in seconds"""
        return _get_env("VIDEO_TIMEOUT", self._config.get("generation", {}).get("video_timeout", 1500), int)

    def set_video_timeout(self, timeout: int):
        """Set video generation timeout in seconds"""
        if "generation" not in self._config:
            self._config["generation"] = {}
        self._config["generation"]["video_timeout"] = timeout

    @property
    def watermark_free_enabled(self) -> bool:
        """Get watermark-free mode enabled status"""
        return _get_env("WATERMARK_FREE_ENABLED", self._config.get("watermark_free", {}).get("watermark_free_enabled", False), bool)

    def set_watermark_free_enabled(self, enabled: bool):
        """Set watermark-free mode enabled/disabled"""
        if "watermark_free" not in self._config:
            self._config["watermark_free"] = {}
        self._config["watermark_free"]["watermark_free_enabled"] = enabled

    @property
    def watermark_free_parse_method(self) -> str:
        """Get watermark-free parse method"""
        return _get_env("WATERMARK_FREE_PARSE_METHOD") or self._config.get("watermark_free", {}).get("parse_method", "third_party")

    @property
    def watermark_free_custom_url(self) -> str:
        """Get custom parse server URL"""
        return _get_env("WATERMARK_FREE_CUSTOM_URL") or self._config.get("watermark_free", {}).get("custom_parse_url", "")

    @property
    def watermark_free_custom_token(self) -> str:
        """Get custom parse server access token"""
        return _get_env("WATERMARK_FREE_CUSTOM_TOKEN") or self._config.get("watermark_free", {}).get("custom_parse_token", "")

    @property
    def at_auto_refresh_enabled(self) -> bool:
        """Get AT auto refresh enabled status"""
        return _get_env("AT_AUTO_REFRESH_ENABLED", self._config.get("token_refresh", {}).get("at_auto_refresh_enabled", False), bool)

    def set_at_auto_refresh_enabled(self, enabled: bool):
        """Set AT auto refresh enabled/disabled"""
        if "token_refresh" not in self._config:
            self._config["token_refresh"] = {}
        self._config["token_refresh"]["at_auto_refresh_enabled"] = enabled

    @property
    def data_dir(self) -> Path:
        """Get data directory path (for database, cache files, etc.)"""
        if self._is_hf_spaces:
            return Path(os.environ.get("DATA_DIR", "/data"))
        return Path(__file__).parent.parent.parent

    # Google Drive 配置属性
    @property
    def google_drive_enabled(self) -> bool:
        """Get Google Drive upload enabled status"""
        return _get_env("GOOGLE_DRIVE_ENABLED", self._config.get("google_drive", {}).get("enabled", False), bool)

    @property
    def google_drive_space_url(self) -> str:
        """Get Google Drive Gradio Space URL"""
        return _get_env("GOOGLE_DRIVE_SPACE_URL") or self._config.get("google_drive", {}).get("space_url", "https://iyougame-url2drive.hf.space")

    @property
    def google_drive_password(self) -> str:
        """Get Google Drive password from environment variable or config"""
        # 优先从环境变量读取
        env_password = _get_env("GOOGLE_DRIVE_PASSWORD")
        if env_password:
            return env_password
        # 否则从配置文件读取
        return self._config.get("google_drive", {}).get("password", "")

    def set_google_drive_enabled(self, enabled: bool):
        """Set Google Drive upload enabled/disabled"""
        if "google_drive" not in self._config:
            self._config["google_drive"] = {}
        self._config["google_drive"]["enabled"] = enabled


# Global config instance
config = Config()
