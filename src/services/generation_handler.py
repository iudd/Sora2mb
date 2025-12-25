"""Generation handling module"""
import json
import asyncio
import base64
import time
import random
import re
from pathlib import Path
from typing import Optional, AsyncGenerator, Dict, Any
from datetime import datetime
from curl_cffi.requests import AsyncSession
from .sora_client import SoraClient
from .token_manager import TokenManager
from .load_balancer import LoadBalancer
from .file_cache import FileCache
from .concurrency_manager import ConcurrencyManager
from .google_drive_uploader import GoogleDriveUploader
from ..core.database import Database
from ..core.models import Task, RequestLog, CharacterCard
from ..core.config import config
from ..core.logger import debug_logger

# Model configuration
MODEL_CONFIG = {
    "sora-image": {
        "type": "image",
        "width": 360,
        "height": 360
    },
    "sora-image-landscape": {
        "type": "image",
        "width": 540,
        "height": 360
    },
    "sora-image-portrait": {
        "type": "image",
        "width": 360,
        "height": 540
    },
    # Video models with 10s duration (300 frames)
    "sora-video-10s": {
        "type": "video",
        "orientation": "landscape",
        "n_frames": 300
    },
    "sora-video-landscape-10s": {
        "type": "video",
        "orientation": "landscape",
        "n_frames": 300
    },
    "sora-video-portrait-10s": {
        "type": "video",
        "orientation": "portrait",
        "n_frames": 300
    },
    # Video models with 15s duration (450 frames)
    "sora-video-15s": {
        "type": "video",
        "orientation": "landscape",
        "n_frames": 450
    },
    "sora-video-landscape-15s": {
        "type": "video",
        "orientation": "landscape",
        "n_frames": 450
    },
    "sora-video-portrait-15s": {
        "type": "video",
        "orientation": "portrait",
        "n_frames": 450
    }
}

class GenerationHandler:
    """Handle generation requests"""

    def __init__(self, sora_client: SoraClient, token_manager: TokenManager,
                 load_balancer: LoadBalancer, db: Database, proxy_manager=None,
                 concurrency_manager: Optional[ConcurrencyManager] = None):
        self.sora_client = sora_client
        self.token_manager = token_manager
        self.load_balancer = load_balancer
        self.db = db
        self.concurrency_manager = concurrency_manager
        self.file_cache = FileCache(
            cache_dir="tmp",
            default_timeout=config.cache_timeout,
            proxy_manager=proxy_manager
        )
        # 初始化 Google Drive 上传器
        self.google_drive_uploader = GoogleDriveUploader()
        self.tmp_dir = Path(__file__).parent.parent.parent / "tmp"
        self.tmp_dir.mkdir(exist_ok=True)

        # Watermark-free waiting cancellation controls (in-memory).
        # Keyed by Sora task_id. This is intentionally memory-only because it is
        # a short-lived UI interaction (cancel the current waiting loop).
        self._watermark_cancel_events: Dict[str, asyncio.Event] = {}
        self._watermark_cancel_lock = asyncio.Lock()