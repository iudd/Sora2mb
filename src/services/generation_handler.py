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
        self.tmp_dir = Path(__file__).parent.parent.parent / "tmp"
        self.tmp_dir.mkdir(exist_ok=True)

        # Watermark-free waiting cancellation controls (in-memory).
        # Keyed by Sora task_id. This is intentionally memory-only because it is
        # a short-lived UI interaction (cancel the current waiting loop).
        self._watermark_cancel_events: Dict[str, asyncio.Event] = {}
        self._watermark_cancel_lock = asyncio.Lock()

    def _get_base_url(self) -> str:
        """Get base URL for cache files"""
        # Use configured cache base URL if available
        if config.cache_base_url:
            return config.cache_base_url.rstrip('/')
        # Otherwise use server address
        return f"http://{config.server_host}:{config.server_port}"

    async def _wait_for_url_ready(self, url: str, attempts: int = 30, delay: int = 10):
        """
        Poll a URL until it returns HTTP 200 or attempts are exhausted.
        Mainly used to wait for freshly published watermark-free files to become available.
        """
        last_status = None
        last_error = None
        for i in range(attempts):
            try:
                async with AsyncSession() as session:
                    resp = await session.get(url, timeout=20, impersonate="chrome")
                    last_status = resp.status_code
                    if resp.status_code == 200:
                        return
                    if resp.status_code == 404:
                        await asyncio.sleep(delay)
                        continue
                    # Other status codes: break early
                    break
            except Exception as e:
                # Network jitter is common for freshly published / third-party parsed files.
                # Keep retrying, but remember the last error for better diagnostics.
                last_error = str(e)
                await asyncio.sleep(delay)
        raise Exception(f"Download not ready (last status {last_status}, last error {last_error})")

    async def _download_with_retry(self, url: str, media_type: str, attempts: int = 15, delay: int = 10) -> str:
        """
        Wrap file cache download with retry, mainly to tolerate 404 until file is ready.
        """
        for i in range(attempts):
            try:
                return await self.file_cache.download_and_cache(url, media_type)
            except Exception as e:
                msg = str(e)
                is_not_ready_404 = "404" in msg
                is_transient_network = self._is_transient_network_error(e)

                if i < attempts - 1 and (is_not_ready_404 or is_transient_network):
                    # 404: file not ready yet (normal for watermark-free parsing)
                    # network/TLS: transient, use exponential backoff to avoid hammering
                    sleep_s = delay
                    if is_transient_network and not is_not_ready_404:
                        sleep_s = min(delay * (2 ** i), 30)
                        sleep_s += random.uniform(0, 0.5)
                        debug_logger.log_info(
                            f"Transient network error while downloading {media_type}; retrying in {sleep_s:.1f}s "
                            f"({i + 1}/{attempts}): {msg}"
                        )
                    await asyncio.sleep(sleep_s)
                    continue
                raise

    def _is_transient_network_error(self, err: Exception) -> bool:
        """
        Best-effort detection of transient network/TLS errors (curl_cffi/libcurl style).

        We only use this for "safe to retry" follow-up steps (watermark-free publish / download),
        not for primary generation POST calls (to avoid accidental duplicate tasks).
        """
        msg = (str(err) or "").lower()
        # curl_cffi raises errors like:
        # - "Failed to perform, curl: (56) Recv failure: Connection was reset"
        # - "curl: (28) Failed to connect ..."
        # - "curl: (35) TLS connect error ..."
        keywords = [
            "curl:", "failed to perform", "recv failure", "send failure",
            "connection was reset", "connection closed", "connection closed abruptly",
            "could not connect", "timed out", "timeout", "tls", "openssl",
        ]
        return any(k in msg for k in keywords)

    async def cancel_watermark_wait(self, task_id: str) -> bool:
        """
        Request to cancel watermark-free waiting for a given Sora task_id.

        Returns:
            True if a running watermark wait loop was found and cancelled.
            False if the task is not currently in watermark waiting.
        """
        if not task_id:
            return False
        async with self._watermark_cancel_lock:
            ev = self._watermark_cancel_events.get(task_id)
            if not ev:
                return False
            ev.set()
            return True

    async def _get_watermark_cancel_event(self, task_id: str) -> asyncio.Event:
        """Get (or create) the cancel event for the given Sora task_id."""
        async with self._watermark_cancel_lock:
            ev = self._watermark_cancel_events.get(task_id)
            if not ev:
                ev = asyncio.Event()
                self._watermark_cancel_events[task_id] = ev
            return ev

    async def _cleanup_watermark_cancel_event(self, task_id: str):
        """Remove the cancel event for the task_id to avoid leaking memory."""
        async with self._watermark_cancel_lock:
            self._watermark_cancel_events.pop(task_id, None)

    def _save_avatar_file(self, avatar_bytes: bytes, username: str) -> str:
        """Persist avatar image to /tmp/avatars and return relative URL path"""
        avatar_dir = self.tmp_dir / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        filename = f"avatar_{username}_{int(time.time())}.png"
        path = avatar_dir / filename
        with open(path, "wb") as f:
            f.write(avatar_bytes)
        # Served via /tmp static mount
        return f"/tmp/avatars/{filename}"

    # -------------------- Chinese alias helper -------------------- #
    def _generate_cn_alias(self, display_name: str, description: str = "") -> str:
        """
        Generate a lightweight Chinese alias for a character, without calling external services.
        Heuristic: keyword mapping -> fallback initials.
        """
        name = (display_name or "").strip()
        desc = (description or "").strip()
        # If already contains CJK, keep it
        if any("\u4e00" <= ch <= "\u9fff" for ch in name):
            return name

        text = f"{name} {desc}".lower()
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

        # fallback: initials
        words = [w for w in name.split() if w]
        if words:
            initials = "".join(w[0].upper() for w in words if w[0].isalpha())
            return f"角色{initials}" if initials else name or "角色"

        return name or "角色"
    
    def _decode_base64_image(self, image_str: str) -> bytes:
        """Decode base64 image"""
        # Remove data URI prefix if present
        if "," in image_str:
            image_str = image_str.split(",", 1)[1]
        return base64.b64decode(image_str)

    def _decode_base64_video(self, video_str: str) -> bytes:
        """Decode base64 video"""
        # Remove data URI prefix if present
        if "," in video_str:
            video_str = video_str.split(",", 1)[1]
        return base64.b64decode(video_str)

    def _process_character_username(self, username_hint: str) -> str:
        """Process character username from API response

        Logic:
        1. Remove prefix (e.g., "blackwill." from "blackwill.meowliusma68")
        2. Keep the remaining part (e.g., "meowliusma68")
        3. Append 3 random digits
        4. Return final username (e.g., "meowliusma68123")

        Args:
            username_hint: Original username from API (e.g., "blackwill.meowliusma68")

        Returns:
            Processed username with 3 random digits appended
        """
        # Split by dot and take the last part
        if "." in username_hint:
            base_username = username_hint.split(".")[-1]
        else:
            base_username = username_hint

        # Generate 3 random digits
        random_digits = str(random.randint(100, 999))

        # Return final username
        final_username = f"{base_username}{random_digits}"
        debug_logger.log_info(f"Processed username: {username_hint} -> {final_username}")

        return final_username

    def _clean_remix_link_from_prompt(self, prompt: str) -> str:
        """Remove remix link from prompt

        Removes both formats:
        1. Full URL: https://sora.chatgpt.com/p/s_68e3a06dcd888191b150971da152c1f5
        2. Short ID: s_68e3a06dcd888191b150971da152c1f5

        Args:
            prompt: Original prompt that may contain remix link

        Returns:
            Cleaned prompt without remix link
        """
        if not prompt:
            return prompt

        # Remove full URL format: https://sora.chatgpt.com/p/s_[a-f0-9]{32}
        cleaned = re.sub(r'https://sora\.chatgpt\.com/p/s_[a-f0-9]{32}', '', prompt)

        # Remove short ID format: s_[a-f0-9]{32}
        cleaned = re.sub(r's_[a-f0-9]{32}', '', cleaned)

        # Clean up extra whitespace
        cleaned = ' '.join(cleaned.split())

        debug_logger.log_info(f"Cleaned prompt: '{prompt}' -> '{cleaned}'")

        return cleaned

    async def _resolve_cameo_ids_from_prompt(self, prompt: str, token_id: Optional[int] = None):
        """
        从提示词中解析 @username 并匹配本地存储的角色卡，提取 cameo_id

        Returns:
            cameo_ids: 已匹配的 cameo_id 列表
            matched_usernames: 成功匹配到卡片的用户名集合
            missing_usernames: 未匹配到卡片的用户名集合
            token_ids: 角色卡所属 token_id 集合
        """
        if not prompt:
            return [], set(), set(), set()

        # 支持字母/数字/下划线/点/短横线/中文昵称
        usernames = {m.group(1) for m in re.finditer(r"@([A-Za-z0-9_\\.\\-\\u4e00-\\u9fa5]+)", prompt)}
        if not usernames:
            return [], set(), set(), set()

        try:
            cards = await self.db.get_character_cards_by_usernames(list(usernames), token_id=token_id)
            matched = {c.get("username") for c in cards if c.get("username")}
            cameo_ids = [c.get("cameo_id") for c in cards if c.get("cameo_id")]
            token_ids = {c.get("token_id") for c in cards if c.get("token_id")}
            missing = usernames - matched
            if cameo_ids:
                debug_logger.log_info(f"Resolved cameo_ids from prompt: {cameo_ids}")
            if missing:
                debug_logger.log_info(f"Usernames not found in cards: {list(missing)}")
            return cameo_ids, matched, missing, token_ids
        except Exception as e:
            debug_logger.log_error(f"Failed to resolve cameo ids: {e}")
            return [], set(), usernames, set()

    def _strip_user_mentions(self, prompt: str) -> str:
        """移除 @username 提及，避免上游因缺少 cameo 报错"""
        if not prompt:
            return prompt
        cleaned = re.sub(r"@([A-Za-z0-9_\\.\\-\\u4e00-\\u9fa5]+)", "", prompt)
        cleaned = " ".join(cleaned.split())
        return cleaned

    async def _download_file(self, url: str) -> bytes:
        """Download file from URL

        Args:
            url: File URL

        Returns:
            File bytes
        """
        from curl_cffi.requests import AsyncSession

        proxy_url = await self.load_balancer.proxy_manager.get_proxy_url()

        kwargs = {
            "timeout": 30,
            "impersonate": "chrome"
        }

        if proxy_url:
            kwargs["proxy"] = proxy_url

        async with AsyncSession() as session:
            response = await session.get(url, **kwargs)
            if response.status_code != 200:
                raise Exception(f"Failed to download file: {response.status_code}")
            return response.content
    
    async def check_token_availability(self, is_image: bool, is_video: bool) -> bool:
        """Check if tokens are available for the given model type

        Args:
            is_image: Whether checking for image generation
            is_video: Whether checking for video generation

        Returns:
            True if available tokens exist, False otherwise
        """
        token_obj = await self.load_balancer.select_token(for_image_generation=is_image, for_video_generation=is_video)
        return token_obj is not None

    async def handle_generation(self, model: str, prompt: str,
                               image: Optional[str] = None,
                               video: Optional[str] = None,
                               remix_target_id: Optional[str] = None,
                               stream: bool = True) -> AsyncGenerator[str, None]:
        """Handle generation request

        Args:
            model: Model name
            prompt: Generation prompt
            image: Base64 encoded image
            video: Base64 encoded video or video URL
            remix_target_id: Sora share link video ID for remix
            stream: Whether to stream response
        """
        start_time = time.time()

        # Validate model
        if model not in MODEL_CONFIG:
            raise ValueError(f"Invalid model: {model}")

        model_config = MODEL_CONFIG[model]
        is_video = model_config["type"] == "video"
        is_image = model_config["type"] == "image"

        # Non-streaming mode: only check availability
        if not stream:
            available = await self.check_token_availability(is_image, is_video)
            if available:
                if is_image:
                    message = "All tokens available for image generation. Please enable streaming to use the generation feature."
                else:
                    message = "All tokens available for video generation. Please enable streaming to use the generation feature."
            else:
                if is_image:
                    message = "No available models for image generation"
                else:
                    message = "No available models for video generation"

            yield self._format_non_stream_response(message, is_availability_check=True)
            return

        # Handle character creation and remix flows for video models
        if is_video:
            # Remix flow: remix_target_id provided
            if remix_target_id:
                async for chunk in self._handle_remix(remix_target_id, prompt, model_config):
                    yield chunk
                return

            # Character creation flow: video provided
            if video:
                # Decode video if it's base64
                video_data = self._decode_base64_video(video) if video.startswith("data:") or not video.startswith("http") else video

                # If no prompt, just create character and return
                if not prompt:
                    async for chunk in self._handle_character_creation_only(video_data, model_config):
                        yield chunk
                    return
                else:
                    # If prompt provided, create character and generate video
                    async for chunk in self._handle_character_and_video_generation(video_data, prompt, model_config):
                        yield chunk
                    return

        # Streaming mode: proceed with actual generation
        # Select token (with lock for image generation, Sora2 quota check for video generation)
        token_obj = await self.load_balancer.select_token(for_image_generation=is_image, for_video_generation=is_video)
        if not token_obj:
            if is_image:
                raise Exception("No available tokens for image generation. All tokens are either disabled, cooling down, locked, or expired.")
            else:
                raise Exception("No available tokens for video generation. All tokens are either disabled, cooling down, Sora2 quota exhausted, don't support Sora2, or expired.")

        # Acquire lock for image generation
        if is_image:
            lock_acquired = await self.load_balancer.token_lock.acquire_lock(token_obj.id)
            if not lock_acquired:
                raise Exception(f"Failed to acquire lock for token {token_obj.id}")

            # Acquire concurrency slot for image generation
            if self.concurrency_manager:
                concurrency_acquired = await self.concurrency_manager.acquire_image(token_obj.id)
                if not concurrency_acquired:
                    await self.load_balancer.token_lock.release_lock(token_obj.id)
                    raise Exception(f"Failed to acquire concurrency slot for token {token_obj.id}")

        cameo_ids = []
        role_context = ""
        if is_video:
            usernames = {m.group(1) for m in re.finditer(r"@([A-Za-z0-9_\\.\\-\\u4e00-\\u9fa5]+)", prompt)}
            cards = []
            if usernames:
                cards = await self.db.get_character_cards_by_usernames(list(usernames), token_id=None)
                cameo_ids = [c.get("cameo_id") for c in cards if c.get("cameo_id")]

            final_prompt = prompt  # 保留 @ 提及，提升 cameo 识别概率

            # 视频并发占用
            if self.concurrency_manager:
                concurrency_acquired = await self.concurrency_manager.acquire_video(token_obj.id)
                if not concurrency_acquired:
                    raise Exception(f"Failed to acquire concurrency slot for token {token_obj.id}")
        else:
            final_prompt = prompt

        task_id = None
        is_first_chunk = True  # Track if this is the first chunk

        try:
            # Upload image if provided
            media_id = None
            if image:
                if stream:
                    yield self._format_stream_chunk(
                        reasoning_content="**Image Upload Begins**\n\nUploading image to server...\n",
                        is_first=is_first_chunk
                    )
                    is_first_chunk = False

                image_data = self._decode_base64_image(image)
                media_id = await self.sora_client.upload_image(image_data, token_obj.token)

                if stream:
                    yield self._format_stream_chunk(
                        reasoning_content="Image uploaded successfully. Proceeding to generation...\n"
                    )

            # Generate
            if stream:
                if is_first_chunk:
                    yield self._format_stream_chunk(
                        reasoning_content="**Generation Process Begins**\n\nInitializing generation request...\n",
                        is_first=True
                    )
                    is_first_chunk = False
                else:
                    yield self._format_stream_chunk(
                        reasoning_content="**Generation Process Begins**\n\nInitializing generation request...\n"
                    )
            
            if is_video:
                # Get n_frames from model configuration
                n_frames = model_config.get("n_frames", 300)  # Default to 300 frames (10s)

                # Check if prompt is in storyboard format
                if self.sora_client.is_storyboard_prompt(final_prompt):
                    # Storyboard mode（尝试 cameo）
                    if stream:
                        yield self._format_stream_chunk(
                            reasoning_content="Detected storyboard format. Converting to storyboard API format...\n"
                        )

                    formatted_prompt = self.sora_client.format_storyboard_prompt(final_prompt)
                    debug_logger.log_info(f"Storyboard mode detected. Formatted prompt: {formatted_prompt}")

                    task_id = await self.sora_client.generate_storyboard(
                        formatted_prompt, token_obj.token,
                        orientation=model_config["orientation"],
                        media_id=media_id,
                        n_frames=n_frames,
                        cameo_ids=cameo_ids or None
                    )
                else:
                    # Normal video generation，优先尝试 cameo_ids，失败则回退
                    try:
                        task_id = await self.sora_client.generate_video(
                            final_prompt, token_obj.token,
                            orientation=model_config["orientation"],
                            media_id=media_id,
                            n_frames=n_frames,
                            cameo_ids=cameo_ids or None
                        )
                    except Exception as gen_err:
                        if cameo_ids and "cameo" in str(gen_err).lower():
                            debug_logger.log_info(f"Retry without cameo_ids due to error: {gen_err}")
                            task_id = await self.sora_client.generate_video(
                                final_prompt, token_obj.token,
                                orientation=model_config["orientation"],
                                media_id=media_id,
                                n_frames=n_frames,
                                cameo_ids=None
                            )
                        else:
                            raise gen_err
            else:
                task_id = await self.sora_client.generate_image(
                    final_prompt, token_obj.token,
                    width=model_config["width"],
                    height=model_config["height"],
                    media_id=media_id
                )
            
            # Save task to database
            task = Task(
                task_id=task_id,
                token_id=token_obj.id,
                model=model,
                prompt=final_prompt,
                status="processing",
                progress=0.0
            )
            await self.db.create_task(task)
            
            # Record usage
            await self.token_manager.record_usage(token_obj.id, is_video=is_video)
            
            # Poll for results with timeout
            async for chunk in self._poll_task_result(task_id, token_obj.token, is_video, stream, prompt, token_obj.id):
                yield chunk
            
            # Record success
            await self.token_manager.record_success(token_obj.id, is_video=is_video)

            # Release lock for image generation
            if is_image:
                await self.load_balancer.token_lock.release_lock(token_obj.id)
                # Release concurrency slot for image generation
                if self.concurrency_manager:
                    await self.concurrency_manager.release_image(token_obj.id)

            # Release concurrency slot for video generation
            if is_video and self.concurrency_manager:
                await self.concurrency_manager.release_video(token_obj.id)

            # Log successful request
            duration = time.time() - start_time
            await self._log_request(
                token_obj.id,
                f"generate_{model_config['type']}",
                {"model": model, "prompt": prompt, "has_image": image is not None},
                {"task_id": task_id, "status": "success"},
                200,
                duration
            )

        except Exception as e:
            # Release lock for image generation on error
            if is_image and token_obj:
                await self.load_balancer.token_lock.release_lock(token_obj.id)
                # Release concurrency slot for image generation
                if self.concurrency_manager:
                    await self.concurrency_manager.release_image(token_obj.id)

            # Release concurrency slot for video generation on error
            if is_video and token_obj and self.concurrency_manager:
                await self.concurrency_manager.release_video(token_obj.id)

            # Record error
            if token_obj:
                await self.token_manager.record_error(token_obj.id)

            # Log failed request
            duration = time.time() - start_time
            await self._log_request(
                token_obj.id if token_obj else None,
                f"generate_{model_config['type'] if model_config else 'unknown'}",
                {"model": model, "prompt": prompt, "has_image": image is not None},
                {"error": str(e)},
                500,
                duration
            )
            raise e
    
    async def _poll_task_result(self, task_id: str, token: str, is_video: bool,
                                stream: bool, prompt: str, token_id: int = None) -> AsyncGenerator[str, None]:
        """Poll for task result with timeout"""
        # Get timeout from config
        timeout = config.video_timeout if is_video else config.image_timeout
        poll_interval = config.poll_interval
        max_attempts = int(timeout / poll_interval)  # Calculate max attempts based on timeout
        last_progress = 0
        start_time = time.time()
        last_heartbeat_time = start_time  # Track last heartbeat for image generation
        heartbeat_interval = 10  # Send heartbeat every 10 seconds for image generation
        last_status_output_time = start_time  # Track last status output time for video generation
        video_status_interval = 5  # Output status every 5 seconds for video generation (was 30)

        debug_logger.log_info(f"Starting task polling: task_id={task_id}, is_video={is_video}, timeout={timeout}s, max_attempts={max_attempts}")

        # Check and log watermark-free mode status at the beginning
        if is_video:
            watermark_free_config = await self.db.get_watermark_free_config()
            debug_logger.log_info(f"Watermark-free mode: {'ENABLED' if watermark_free_config.watermark_free_enabled else 'DISABLED'}")

        for attempt in range(max_attempts):
            # Check if timeout exceeded
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                debug_logger.log_error(
                    error_message=f"Task timeout: {elapsed_time:.1f}s > {timeout}s",
                    status_code=408,
                    response_text=f"Task {task_id} timed out after {elapsed_time:.1f} seconds"
                )
                # Release lock if this is an image generation task
                if not is_video and token_id:
                    await self.load_balancer.token_lock.release_lock(token_id)
                    debug_logger.log_info(f"Released lock for token {token_id} due to timeout")
                    # Release concurrency slot for image generation
                    if self.concurrency_manager:
                        await self.concurrency_manager.release_image(token_id)
                        debug_logger.log_info(f"Released concurrency slot for token {token_id} due to timeout")

                # Release concurrency slot for video generation
                if is_video and token_id and self.concurrency_manager:
                    await self.concurrency_manager.release_video(token_id)
                    debug_logger.log_info(f"Released concurrency slot for token {token_id} due to timeout")

                await self.db.update_task(task_id, "failed", 0, error_message=f"Generation timeout after {elapsed_time:.1f} seconds")
                raise Exception(f"Upstream API timeout: Generation exceeded {timeout} seconds limit")


            await asyncio.sleep(poll_interval)

            try:
                if is_video:
                    # Get pending tasks to check progress
                    pending_tasks = await self.sora_client.get_pending_tasks(token)

                    # Find matching task in pending tasks
                    task_found = False
                    for task in pending_tasks:
                        if task.get("id") == task_id:
                            task_found = True
                            # Update progress
                            progress_pct = task.get("progress_pct")
                            # Handle null progress at the beginning
                            if progress_pct is None:
                                progress_pct = 0
                            else:
                                progress_pct = int(progress_pct * 100)

                            # Update last_progress for tracking
                            last_progress = progress_pct
                            status = task.get("status", "processing")

                            # Output status every 30 seconds (not just when progress changes)
                            current_time = time.time()
                            if stream and (current_time - last_status_output_time >= video_status_interval):
                                last_status_output_time = current_time
                                debug_logger.log_info(f"Task {task_id} progress: {progress_pct}% (status: {status})")
                                yield self._format_stream_chunk(
                                    reasoning_content=f"**Video Generation Progress**: {progress_pct}% ({status})\n"
                                )
                            break

                    # If task not found in pending tasks, it's completed - fetch from drafts
                    if not task_found:
                        debug_logger.log_info(f"Task {task_id} not found in pending tasks, fetching from drafts...")
                        result = await self.sora_client.get_video_drafts(token)
                        items = result.get("items", [])

                        # Find matching task in drafts
                        for item in items:
                            if item.get("task_id") == task_id:
                                # ========= 新增：敏感内容/违规处理 =========
                                kind = item.get("kind")
                                reason_str = item.get("reason_str") or item.get("markdown_reason_str")
                                url = item.get("url") or item.get("downloadable_url")
                                debug_logger.log_info(f"Found task {task_id} in drafts with kind: {kind}, reason_str: {reason_str}, has_url: {bool(url)}")

                                # 违规判断：kind 标识 / 有 reason / 没有可用 URL
                                is_violation = (
                                    kind == "sora_content_violation"
                                    or (reason_str and reason_str.strip())
                                    or not url
                                )

                                if is_violation:
                                    error_message = f"Content policy violation: {reason_str or 'Content violates guardrails'}"

                                    debug_logger.log_error(
                                        error_message=error_message,
                                        status_code=400,
                                        response_text=json.dumps(item)
                                    )

                                    # 标记任务失败
                                    await self.db.update_task(task_id, "failed", 0, error_message=error_message)

                                    # 释放并发
                                    if token_id and self.concurrency_manager:
                                        await self.concurrency_manager.release_video(token_id)
                                        debug_logger.log_info(f"Released concurrency slot for token {token_id} due to content violation")

                                    # 流式返回提示
                                    if stream:
                                        yield self._format_stream_chunk(
                                            reasoning_content=f"**Content Policy Violation**\n\n{reason_str}\n"
                                        )
                                        yield self._format_stream_chunk(
                                            content=f"❌ 生成失败: {reason_str}",
                                            finish_reason="STOP"
                                        )
                                        yield "data: [DONE]\n\n"

                                    # 违规时立即停止轮询
                                    return

                                # ========= 正常处理 watermark-free =========
                                # Check if watermark-free mode is enabled
                                watermark_free_config = await self.db.get_watermark_free_config()
                                watermark_free_enabled = watermark_free_config.watermark_free_enabled

                                if watermark_free_enabled:
                                    # Watermark-free mode: keep waiting (no hard fail) until success or user cancels.
                                    debug_logger.log_info(f"Entering watermark-free mode for task {task_id}")
                                    generation_id = item.get("id")
                                    debug_logger.log_info(f"Generation ID: {generation_id}")
                                    if not generation_id:
                                        raise Exception("Generation ID not found in video draft")

                                    # Original downloadable URL (watermarked). Used for:
                                    # - Early preview in UI while waiting for watermark-free
                                    # - "Cancel waiting" fallback
                                    original_url = item.get("downloadable_url") or item.get("url") or url

                                    cancel_event = await self._get_watermark_cancel_event(task_id)
                                    wm_attempt = 0  # Unified counter for UI (publish/parse/ready)

                                    if stream:
                                        yield self._format_stream_chunk(
                                            reasoning_content=(
                                                "**Video Generation Completed**\n\n"
                                                "Watermark-free mode enabled. Waiting for watermark-free output (may take a while).\n"
                                                "Tip: if it takes too long, click 'Cancel watermark-free waiting' in the task card.\n"
                                            ),
                                            extra={
                                                "wm": {
                                                    "stage": "start",
                                                    "attempt": 0,
                                                    "can_cancel": False,
                                                    "task_id": task_id,
                                                },
                                                "output": ([{
                                                    "url": original_url,
                                                    "type": "video",
                                                    "task_id": task_id,
                                                    "watermark_free": False,
                                                }] if original_url else [])
                                            }
                                        )

                                    # Get watermark-free config to determine parse method
                                    watermark_config = await self.db.get_watermark_free_config()
                                    parse_method = watermark_config.parse_method or "third_party"

                                    try:
                                        while True:
                                            # User cancelled: return original URL (watermarked)
                                            if cancel_event.is_set():
                                                local_url = original_url
                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content="Watermark-free waiting cancelled. Returning original (may be watermarked) video URL.\n",
                                                        extra={
                                                            "wm": {
                                                                "stage": "cancelled",
                                                                "attempt": wm_attempt,
                                                                "can_cancel": True,
                                                                "task_id": task_id,
                                                            }
                                                        }
                                                    )
                                                break

                                            try:
                                                # 1) Publish to get post_id (retry forever unless cancelled)
                                                post_id = await self.sora_client.post_video_for_watermark_free(
                                                    generation_id=generation_id,
                                                    prompt=prompt,
                                                    token=token
                                                )
                                                debug_logger.log_info(f"Received post_id: {post_id}")
                                                if not post_id:
                                                    raise Exception("Failed to get post ID from publish API")

                                                # 2) Resolve watermark-free URL
                                                if parse_method == "custom":
                                                    if not watermark_config.custom_parse_url or not watermark_config.custom_parse_token:
                                                        raise Exception("Custom parse server URL or token not configured")
                                                    if stream:
                                                        yield self._format_stream_chunk(
                                                            reasoning_content=f"Video published successfully. Post ID: {post_id}\nUsing custom parse server to get watermark-free URL...\n",
                                                            extra={
                                                                "wm": {
                                                                    "stage": "parse",
                                                                    "attempt": wm_attempt,
                                                                    "can_cancel": wm_attempt >= 3,
                                                                    "task_id": task_id,
                                                                }
                                                            }
                                                        )
                                                    watermark_free_url = await self.sora_client.get_watermark_free_url_custom(
                                                        parse_url=watermark_config.custom_parse_url,
                                                        parse_token=watermark_config.custom_parse_token,
                                                        post_id=post_id,
                                                        access_token=token
                                                    )
                                                else:
                                                    # Use third-party parse (default)
                                                    watermark_free_url = f"https://oscdn2.dyysy.com/MP4/{post_id}.mp4"
                                                    debug_logger.log_info("Using third-party parse server")

                                                debug_logger.log_info(f"Watermark-free URL: {watermark_free_url}")

                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=(
                                                            f"Video published successfully. Post ID: {post_id}\n"
                                                            f"Now {'caching' if config.cache_enabled else 'preparing'} watermark-free video...\n"
                                                        ),
                                                        extra={
                                                            "wm": {
                                                                "stage": "published",
                                                                "attempt": wm_attempt,
                                                                "can_cancel": wm_attempt >= 3,
                                                                "task_id": task_id,
                                                            }
                                                        }
                                                    )

                                                # 3) Wait for watermark-free file to become available (retry forever unless cancelled)
                                                ready_checks = 0
                                                while True:
                                                    if cancel_event.is_set():
                                                        break

                                                    ready_checks += 1
                                                    status_code = None
                                                    last_err = None
                                                    try:
                                                        async with AsyncSession() as session:
                                                            resp = await session.head(
                                                                watermark_free_url,
                                                                timeout=20,
                                                                impersonate="chrome"
                                                            )
                                                            status_code = resp.status_code
                                                    except Exception as e:
                                                        last_err = str(e)

                                                    if status_code == 200:
                                                        break

                                                    wm_attempt += 1
                                                    if stream:
                                                        hint = f"HTTP {status_code}" if status_code else (last_err or "unknown")
                                                        yield self._format_stream_chunk(
                                                            reasoning_content=f"Watermark-free file not ready ({hint}), waiting... (attempt {wm_attempt})\n",
                                                            extra={
                                                                "wm": {
                                                                    "stage": "waiting",
                                                                    "attempt": wm_attempt,
                                                                    "can_cancel": wm_attempt >= 3,
                                                                    "task_id": task_id,
                                                                }
                                                            }
                                                        )

                                                    await asyncio.sleep(10 + random.uniform(0, 0.5))

                                                if cancel_event.is_set():
                                                    # Jump back to top and finish as cancelled
                                                    continue

                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=(
                                                            f"Watermark-free URL is ready (checked {ready_checks} times).\n"
                                                            f"Now {'caching' if config.cache_enabled else 'returning'} watermark-free video...\n"
                                                        ),
                                                        extra={
                                                            "wm": {
                                                                "stage": "ready",
                                                                "attempt": wm_attempt,
                                                                "can_cancel": wm_attempt >= 3,
                                                                "task_id": task_id,
                                                            }
                                                        }
                                                    )

                                                # 4) Cache watermark-free video (if cache enabled)
                                                if config.cache_enabled:
                                                    try:
                                                        cached_filename = await self._download_with_retry(watermark_free_url, "video")
                                                        local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
                                                        if stream:
                                                            yield self._format_stream_chunk(
                                                                reasoning_content="Watermark-free video cached successfully. Preparing final response...\n"
                                                            )

                                                        # Delete the published post after caching (best-effort)
                                                        try:
                                                            debug_logger.log_info(f"Deleting published post: {post_id}")
                                                            await self.sora_client.delete_post(post_id, token)
                                                            debug_logger.log_info(f"Published post deleted successfully: {post_id}")
                                                        except Exception as delete_error:
                                                            debug_logger.log_error(
                                                                error_message=f"Failed to delete published post {post_id}: {str(delete_error)}",
                                                                status_code=500,
                                                                response_text=str(delete_error)
                                                            )
                                                    except Exception as cache_error:
                                                        # Fallback to watermark-free URL if caching fails
                                                        local_url = watermark_free_url
                                                        if stream:
                                                            yield self._format_stream_chunk(
                                                                reasoning_content=(
                                                                    f"Warning: Failed to cache file - {str(cache_error)}\n"
                                                                    "Using original watermark-free URL instead...\n"
                                                                )
                                                            )
                                                else:
                                                    # Cache disabled: use watermark-free URL directly
                                                    local_url = watermark_free_url
                                                    if stream:
                                                        yield self._format_stream_chunk(
                                                            reasoning_content="Cache is disabled. Using watermark-free URL directly...\n"
                                                        )

                                                break  # success

                                            except Exception as publish_error:
                                                # Any error in watermark-free follow-up becomes a "wait and retry".
                                                wm_attempt += 1
                                                backoff_s = min(2 ** min(wm_attempt - 1, 6), 30)
                                                backoff_s += random.uniform(0, 0.5)
                                                debug_logger.log_error(
                                                    error_message=f"Watermark-free step error (attempt={wm_attempt}): {str(publish_error)}",
                                                    status_code=500,
                                                    response_text=str(publish_error)
                                                )
                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=(
                                                            f"Watermark-free step error (attempt {wm_attempt}): {str(publish_error)}\n"
                                                            f"Retrying in {backoff_s:.1f}s...\n"
                                                        ),
                                                        extra={
                                                            "wm": {
                                                                "stage": "retry",
                                                                "attempt": wm_attempt,
                                                                "can_cancel": wm_attempt >= 3,
                                                                "task_id": task_id,
                                                            }
                                                        }
                                                    )
                                                await asyncio.sleep(backoff_s)
                                                continue

                                        # If user cancelled, local_url is already set to original_url.
                                        if cancel_event.is_set():
                                            local_url = original_url

                                    finally:
                                        await self._cleanup_watermark_cancel_event(task_id)
                                else:
                                    # Normal mode: use downloadable_url instead of url
                                    url = item.get("downloadable_url") or item.get("url")
                                    if url:
                                        # Cache video file (if cache enabled)
                                        if config.cache_enabled:
                                            if stream:
                                                yield self._format_stream_chunk(
                                                    reasoning_content="**Video Generation Completed**\n\nVideo generation successful. Now caching the video file...\n"
                                                )

                                            try:
                                                cached_filename = await self.file_cache.download_and_cache(url, "video")
                                                local_url = f"{self._get_base_url()}/tmp/{cached_filename}"
                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content="Video file cached successfully. Preparing final response...\n"
                                                    )
                                            except Exception as cache_error:
                                                # Fallback to original URL if caching fails
                                                local_url = url
                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=f"Warning: Failed to cache file - {str(cache_error)}\nUsing original URL instead...\n"
                                                    )
                                        else:
                                            # Cache disabled: use original URL directly
                                            local_url = url
                                            if stream:
                                                yield self._format_stream_chunk(
                                                    reasoning_content="**Video Generation Completed**\n\nCache is disabled. Using original URL directly...\n"
                                                )

                                # Task completed
                                await self.db.update_task(
                                    task_id, "completed", 100.0,
                                    result_urls=json.dumps([local_url])
                                )

                                if stream:
                                    # Final response with content + 结构化 output
                                    yield self._format_stream_chunk(
                                        content=f"```html\n<video src='{local_url}' controls></video>\n```",
                                        finish_reason="STOP",
                                        extra={
                                            "output": [{
                                                "url": local_url,
                                                "type": "video",
                                                "task_id": task_id
                                            }]
                                        }
                                    )
                                    yield "data: [DONE]\n\n"
                                return
                else:
                    result = await self.sora_client.get_image_tasks(token)
                    task_responses = result.get("task_responses", [])

                    # Find matching task
                    task_found = False
                    for task_resp in task_responses:
                        if task_resp.get("id") == task_id:
                            task_found = True
                            status = task_resp.get("status")
                            progress = task_resp.get("progress_pct", 0) * 100

                            if status == "succeeded":
                                # Extract URLs
                                generations = task_resp.get("generations", [])
                                urls = [gen.get("url") for gen in generations if gen.get("url")]

                                if urls:
                                    # Cache image files
                                    if stream:
                                        yield self._format_stream_chunk(
                                            reasoning_content=f"**Image Generation Completed**\n\nImage generation successful. Now caching {len(urls)} image(s)...\n"
                                        )

                                    base_url = self._get_base_url()
                                    local_urls = []

                                    # Check if cache is enabled
                                    if config.cache_enabled:
                                        for idx, url in enumerate(urls):
                                            try:
                                                cached_filename = await self.file_cache.download_and_cache(url, "image")
                                                local_url = f"{base_url}/tmp/{cached_filename}"
                                                local_urls.append(local_url)
                                                if stream and len(urls) > 1:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=f"Cached image {idx + 1}/{len(urls)}...\n"
                                                    )
                                            except Exception as cache_error:
                                                # Fallback to original URL if caching fails
                                                local_urls.append(url)
                                                if stream:
                                                    yield self._format_stream_chunk(
                                                        reasoning_content=f"Warning: Failed to cache image {idx + 1} - {str(cache_error)}\nUsing original URL instead...\n"
                                                    )

                                        if stream and all(u.startswith(base_url) for u in local_urls):
                                            yield self._format_stream_chunk(
                                                reasoning_content="All images cached successfully. Preparing final response...\n"
                                            )
                                    else:
                                        # Cache disabled: use original URLs directly
                                        local_urls = urls
                                        if stream:
                                            yield self._format_stream_chunk(
                                                reasoning_content="Cache is disabled. Using original URLs directly...\n"
                                            )

                                    await self.db.update_task(
                                        task_id, "completed", 100.0,
                                        result_urls=json.dumps(local_urls)
                                    )

                                    if stream:
                                        # Final response with content (Markdown format) + 结构化 output
                                        content_markdown = "\n".join([f"![Generated Image]({url})" for url in local_urls])
                                        yield self._format_stream_chunk(
                                            content=content_markdown,
                                            finish_reason="STOP",
                                            extra={
                                                "output": [
                                                    {"url": url, "type": "image", "task_id": task_id}
                                                    for url in local_urls
                                                ]
                                            }
                                        )
                                        yield "data: [DONE]\n\n"
                                    return

                            elif status == "failed":
                                error_msg = task_resp.get("error_message", "Generation failed")
                                await self.db.update_task(task_id, "failed", progress, error_message=error_msg)
                                raise Exception(error_msg)

                            elif status == "processing":
                                # Update progress only if changed significantly
                                if progress > last_progress + 20:  # Update every 20%
                                    last_progress = progress
                                    await self.db.update_task(task_id, "processing", progress)

                                    if stream:
                                        yield self._format_stream_chunk(
                                            reasoning_content=f"**Processing**\n\nGeneration in progress: {progress:.0f}% completed...\n"
                                        )

                    # For image generation, send heartbeat every 10 seconds if no progress update
                    if not is_video and stream:
                        current_time = time.time()
                        if current_time - last_heartbeat_time >= heartbeat_interval:
                            last_heartbeat_time = current_time
                            elapsed = int(current_time - start_time)
                            yield self._format_stream_chunk(
                                reasoning_content=f"Image generation in progress... ({elapsed}s elapsed)\n"
                            )

                    # If task not found in response, send heartbeat for image generation
                    if not task_found and not is_video and stream:
                        current_time = time.time()
                        if current_time - last_heartbeat_time >= heartbeat_interval:
                            last_heartbeat_time = current_time
                            elapsed = int(current_time - start_time)
                            yield self._format_stream_chunk(
                                reasoning_content=f"Image generation in progress... ({elapsed}s elapsed)\n"
                            )

                # Progress update for stream mode (fallback if no status from API)
                if stream and attempt % 10 == 0:  # Update every 10 attempts (roughly 20% intervals)
                    estimated_progress = min(90, (attempt / max_attempts) * 100)
                    if estimated_progress > last_progress + 20:  # Update every 20%
                        last_progress = estimated_progress
                        yield self._format_stream_chunk(
                            reasoning_content=f"**Processing**\n\nGeneration in progress: {estimated_progress:.0f}% completed (estimated)...\n"
                        )
            
            except Exception as e:
                if attempt >= max_attempts - 1:
                    raise e
                continue

        # Timeout - release lock if image generation
        if not is_video and token_id:
            await self.load_balancer.token_lock.release_lock(token_id)
            debug_logger.log_info(f"Released lock for token {token_id} due to max attempts reached")
            # Release concurrency slot for image generation
            if self.concurrency_manager:
                await self.concurrency_manager.release_image(token_id)
                debug_logger.log_info(f"Released concurrency slot for token {token_id} due to max attempts reached")

        # Release concurrency slot for video generation
        if is_video and token_id and self.concurrency_manager:
            await self.concurrency_manager.release_video(token_id)
            debug_logger.log_info(f"Released concurrency slot for token {token_id} due to max attempts reached")

        await self.db.update_task(task_id, "failed", 0, error_message=f"Generation timeout after {timeout} seconds")
        raise Exception(f"Upstream API timeout: Generation exceeded {timeout} seconds limit")
    
    def _format_stream_chunk(self, content: str = None, reasoning_content: str = None,
                            finish_reason: str = None, is_first: bool = False,
                            extra: dict = None) -> str:
        """Format streaming response chunk

        Args:
            content: Final response content (for user-facing output)
            reasoning_content: Thinking/reasoning process content
            finish_reason: Finish reason (e.g., "STOP")
            is_first: Whether this is the first chunk (includes role)
            extra: Optional extra payload merged进delta（例如 output / task_id）
        """
        chunk_id = f"chatcmpl-{int(datetime.now().timestamp() * 1000)}"

        delta = {}

        # Add role for first chunk
        if is_first:
            delta["role"] = "assistant"

        # Add content fields
        if content is not None:
            delta["content"] = content
        else:
            delta["content"] = None

        if reasoning_content is not None:
            delta["reasoning_content"] = reasoning_content
        else:
            delta["reasoning_content"] = None

        delta["tool_calls"] = None

        # Merge附加字段
        if extra:
            for k, v in extra.items():
                delta[k] = v

        response = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(datetime.now().timestamp()),
            "model": "sora",
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
                "native_finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": 0
            }
        }

        # Add completion tokens for final chunk
        if finish_reason:
            response["usage"]["completion_tokens"] = 1
            response["usage"]["total_tokens"] = 1

        return f'data: {json.dumps(response)}\n\n'
    
    def _format_non_stream_response(self, content: str, media_type: str = None, is_availability_check: bool = False) -> str:
        """Format non-streaming response

        Args:
            content: Response content (either URL for generation or message for availability check)
            media_type: Type of media ("video", "image") - only used for generation responses
            is_availability_check: Whether this is an availability check response
        """
        if not is_availability_check:
            # Generation response with media
            if media_type == "video":
                content = f"```html\n<video src='{content}' controls></video>\n```"
            else:
                content = f"![Generated Image]({content})"

        response = {
            "id": f"chatcmpl-{datetime.now().timestamp()}",
            "object": "chat.completion",
            "created": int(datetime.now().timestamp()),
            "model": "sora",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }]
        }
        return json.dumps(response)

    async def _log_request(self, token_id: Optional[int], operation: str,
                          request_data: Dict[str, Any], response_data: Dict[str, Any],
                          status_code: int, duration: float):
        """Log request to database"""
        try:
            log = RequestLog(
                token_id=token_id,
                operation=operation,
                request_body=json.dumps(request_data),
                response_body=json.dumps(response_data),
                status_code=status_code,
                duration=duration
            )
            await self.db.log_request(log)
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"Failed to log request: {e}")

    # ==================== Character Creation and Remix Handlers ====================

    async def _handle_character_creation_only(self, video_data, model_config: Dict) -> AsyncGenerator[str, None]:
        """Handle character creation only (no video generation)

        Flow:
        1. Download video if URL, or use bytes directly
        2. Upload video to create character
        3. Poll for character processing
        4. Download and cache avatar
        5. Upload avatar
        6. Finalize character
        7. Set character as public
        8. Return success message
        """
        token_obj = await self.load_balancer.select_token(for_video_generation=True)
        if not token_obj:
            raise Exception("No available tokens for character creation")

        concurrency_acquired = False
        try:
            # Acquire video concurrency slot if enabled
            if self.concurrency_manager:
                concurrency_acquired = await self.concurrency_manager.acquire_video(token_obj.id)
                if not concurrency_acquired:
                    raise Exception(f"Failed to acquire concurrency slot for token {token_obj.id}")

            # Record usage for video
            await self.token_manager.record_usage(token_obj.id, is_video=True)

            yield self._format_stream_chunk(
                reasoning_content="**Character Creation Begins**\n\nInitializing character creation...\n",
                is_first=True
            )

            # Handle video URL or bytes
            if isinstance(video_data, str):
                # It's a URL, download it
                yield self._format_stream_chunk(
                    reasoning_content="Downloading video file...\n"
                )
                video_bytes = await self._download_file(video_data)
            else:
                video_bytes = video_data

            # Step 1: Upload video
            yield self._format_stream_chunk(
                reasoning_content="Uploading video file...\n"
            )
            cameo_id = await self.sora_client.upload_character_video(video_bytes, token_obj.token)
            debug_logger.log_info(f"Video uploaded, cameo_id: {cameo_id}")

            # Step 2: Poll for character processing
            yield self._format_stream_chunk(
                reasoning_content="Processing video to extract character...\n"
            )
            cameo_status = await self._poll_cameo_status(cameo_id, token_obj.token)
            debug_logger.log_info(f"Cameo status: {cameo_status}")

            # Extract character info immediately after polling completes
            username_hint = cameo_status.get("username_hint", "character")
            display_name = cameo_status.get("display_name_hint", "Character")

            # Process username: remove prefix and add 3 random digits
            username = self._process_character_username(username_hint)

            # Output character name immediately
            yield self._format_stream_chunk(
                reasoning_content=f"✨ 角色已识别: {display_name} (@{username})\n"
            )

            # Step 3: Download and cache avatar
            yield self._format_stream_chunk(
                reasoning_content="Downloading character avatar...\n"
            )
            profile_asset_url = cameo_status.get("profile_asset_url")
            if not profile_asset_url:
                raise Exception("Profile asset URL not found in cameo status")

            avatar_data = await self.sora_client.download_character_image(profile_asset_url)
            debug_logger.log_info(f"Avatar downloaded, size: {len(avatar_data)} bytes")

            # Step 4: Upload avatar
            yield self._format_stream_chunk(
                reasoning_content="Uploading character avatar...\n"
            )
            asset_pointer = await self.sora_client.upload_character_image(avatar_data, token_obj.token)
            debug_logger.log_info(f"Avatar uploaded, asset_pointer: {asset_pointer}")

            # Step 5: Finalize character
            yield self._format_stream_chunk(
                reasoning_content="Finalizing character creation...\n"
            )
            # instruction_set_hint is a string, but instruction_set in cameo_status might be an array
            instruction_set = cameo_status.get("instruction_set_hint") or cameo_status.get("instruction_set")

            character_id = await self.sora_client.finalize_character(
                cameo_id=cameo_id,
                username=username,
                display_name=display_name,
                profile_asset_pointer=asset_pointer,
                instruction_set=instruction_set,
                token=token_obj.token
            )
            debug_logger.log_info(f"Character finalized, character_id: {character_id}")

            # Step 6: Set character as public
            yield self._format_stream_chunk(
                reasoning_content="Setting character as public...\n"
            )
            await self.sora_client.set_character_public(cameo_id, token_obj.token)
            debug_logger.log_info(f"Character set as public")

            # Persist character card locally for可视化展示/复用
            avatar_path = self._save_avatar_file(avatar_data, username)
            # Persist character card locally，携带 instruction_set 作为描述，方便前端直接注入角色设定
            desc_text = instruction_set
            if isinstance(desc_text, list):
                desc_text = "\n".join(str(x) for x in desc_text)
            cn_alias = self._generate_cn_alias(display_name, desc_text)
            card_id = await self.db.create_character_card(CharacterCard(
                token_id=token_obj.id,
                username=username,
                display_name=cn_alias,  # 保存中文别名到库
                description=desc_text,
                character_id=character_id,
                cameo_id=cameo_id,
                avatar_path=avatar_path,
                source_video=None
            ))

            # Push character card info到前端，便于即时展示
            card_payload = {
                "event": "character_card",
                "card": {
                    "id": card_id,
                    "token_id": token_obj.id,
                    "username": username,
                    "display_name": display_name,
                    "description": desc_text,
                    "character_id": character_id,
                    "cameo_id": cameo_id,
                    "avatar_path": avatar_path,
                    "created_at": datetime.now().isoformat()
                }
            }
            yield self._format_stream_chunk(
                content=json.dumps(card_payload),
                reasoning_content="角色卡已保存并推送到前端。\n"
            )

            # Step 7: Return success message
            yield self._format_stream_chunk(
                content=f"角色创建成功，角色名@{username}",
                finish_reason="STOP"
            )
            yield "data: [DONE]\n\n"

            # Record success
            await self.token_manager.record_success(token_obj.id, is_video=True)

        except Exception as e:
            error_message = f"Character creation failed: {str(e)}"
            debug_logger.log_error(
                error_message=error_message,
                status_code=500,
                response_text=str(e)
            )
            if token_obj:
                await self.token_manager.record_error(token_obj.id)
            # 将失败原因返回前端，结束流
            yield self._format_stream_chunk(
                content=f"❌ 角色卡创建失败：{str(e)}",
                reasoning_content=error_message,
                finish_reason="STOP"
            )
            yield "data: [DONE]\n\n"
            return
        finally:
            if self.concurrency_manager and concurrency_acquired:
                await self.concurrency_manager.release_video(token_obj.id)

    async def _handle_character_and_video_generation(self, video_data, prompt: str, model_config: Dict) -> AsyncGenerator[str, None]:
        """Handle character creation and video generation

        Flow:
        1. Download video if URL, or use bytes directly
        2. Upload video to create character
        3. Poll for character processing
        4. Download and cache avatar
        5. Upload avatar
        6. Finalize character
        7. Generate video with character (@username + prompt)
        8. Delete character
        9. Return video result
        """
        token_obj = await self.load_balancer.select_token(for_video_generation=True)
        if not token_obj:
            raise Exception("No available tokens for video generation")

        character_id = None
        concurrency_acquired = False
        try:
            # Acquire video concurrency slot if enabled
            if self.concurrency_manager:
                concurrency_acquired = await self.concurrency_manager.acquire_video(token_obj.id)
                if not concurrency_acquired:
                    raise Exception(f"Failed to acquire concurrency slot for token {token_obj.id}")

            # Record usage for video
            await self.token_manager.record_usage(token_obj.id, is_video=True)

            yield self._format_stream_chunk(
                reasoning_content="**Character Creation and Video Generation Begins**\n\nInitializing...\n",
                is_first=True
            )

            # Handle video URL or bytes
            if isinstance(video_data, str):
                # It's a URL, download it
                yield self._format_stream_chunk(
                    reasoning_content="Downloading video file...\n"
                )
                video_bytes = await self._download_file(video_data)
            else:
                video_bytes = video_data

            # Step 1: Upload video
            yield self._format_stream_chunk(
                reasoning_content="Uploading video file...\n"
            )
            cameo_id = await self.sora_client.upload_character_video(video_bytes, token_obj.token)
            debug_logger.log_info(f"Video uploaded, cameo_id: {cameo_id}")

            # Step 2: Poll for character processing
            yield self._format_stream_chunk(
                reasoning_content="Processing video to extract character...\n"
            )
            cameo_status = await self._poll_cameo_status(cameo_id, token_obj.token)
            debug_logger.log_info(f"Cameo status: {cameo_status}")

            # Extract character info immediately after polling completes
            username_hint = cameo_status.get("username_hint", "character")
            display_name = cameo_status.get("display_name_hint", "Character")

            # Process username: remove prefix and add 3 random digits
            username = self._process_character_username(username_hint)

            # Output character name immediately
            yield self._format_stream_chunk(
                reasoning_content=f"✨ 角色已识别: {display_name} (@{username})\n"
            )

            # Step 3: Download and cache avatar
            yield self._format_stream_chunk(
                reasoning_content="Downloading character avatar...\n"
            )
            profile_asset_url = cameo_status.get("profile_asset_url")
            if not profile_asset_url:
                raise Exception("Profile asset URL not found in cameo status")

            avatar_data = await self.sora_client.download_character_image(profile_asset_url)
            debug_logger.log_info(f"Avatar downloaded, size: {len(avatar_data)} bytes")

            # Step 4: Upload avatar
            yield self._format_stream_chunk(
                reasoning_content="Uploading character avatar...\n"
            )
            asset_pointer = await self.sora_client.upload_character_image(avatar_data, token_obj.token)
            debug_logger.log_info(f"Avatar uploaded, asset_pointer: {asset_pointer}")

            # Step 5: Finalize character
            yield self._format_stream_chunk(
                reasoning_content="Finalizing character creation...\n"
            )
            # instruction_set_hint is a string, but instruction_set in cameo_status might be an array
            instruction_set = cameo_status.get("instruction_set_hint") or cameo_status.get("instruction_set")

            character_id = await self.sora_client.finalize_character(
                cameo_id=cameo_id,
                username=username,
                display_name=display_name,
                profile_asset_pointer=asset_pointer,
                instruction_set=instruction_set,
                token=token_obj.token
            )
            debug_logger.log_info(f"Character finalized, character_id: {character_id}")

            # Persist character card for仓库展示
            avatar_path = self._save_avatar_file(avatar_data, username)
            desc_text = instruction_set
            if isinstance(desc_text, list):
                desc_text = "\n".join(str(x) for x in desc_text)
            cn_alias = self._generate_cn_alias(display_name, desc_text)
            card_id = await self.db.create_character_card(CharacterCard(
                token_id=token_obj.id,
                username=username,
                display_name=cn_alias,  # 中文别名入库
                description=desc_text,
                character_id=character_id,
                cameo_id=cameo_id,
                avatar_path=avatar_path,
                source_video=None
            ))
            # 即时推送角色卡，前端无需等待刷新
            card_payload = {
                "event": "character_card",
                "card": {
                    "id": card_id,
                    "token_id": token_obj.id,
                    "username": username,
                    "display_name": display_name,
                    "description": desc_text,
                    "character_id": character_id,
                    "cameo_id": cameo_id,
                    "avatar_path": avatar_path,
                    "created_at": datetime.now().isoformat()
                }
            }
            yield self._format_stream_chunk(
                content=json.dumps(card_payload),
                reasoning_content="角色卡已保存并推送到前端。\n"
            )

            # Step 6: Generate video with character
            yield self._format_stream_chunk(
                reasoning_content="**Video Generation Process Begins**\n\nGenerating video with character...\n"
            )

            # Prepend @username to prompt
            full_prompt = f"@{username} {prompt}"
            debug_logger.log_info(f"Full prompt: {full_prompt}")

            # Get n_frames from model configuration
            n_frames = model_config.get("n_frames", 300)  # Default to 300 frames (10s)

            task_id = await self.sora_client.generate_video(
                full_prompt, token_obj.token,
                orientation=model_config["orientation"],
                n_frames=n_frames,
                cameo_ids=[cameo_id] if cameo_id else None
            )
            debug_logger.log_info(f"Video generation started, task_id: {task_id}")

            # Save task to database
            task = Task(
                task_id=task_id,
                token_id=token_obj.id,
                model=f"sora-video-{model_config['orientation']}",
                prompt=full_prompt,
                status="processing",
                progress=0.0
            )
            await self.db.create_task(task)

            # Record usage
            await self.token_manager.record_usage(token_obj.id, is_video=True)

            # Poll for results
            async for chunk in self._poll_task_result(task_id, token_obj.token, True, True, full_prompt, token_obj.id):
                yield chunk

            # Record success
            await self.token_manager.record_success(token_obj.id, is_video=True)

        except Exception as e:
            # Record error
            if token_obj:
                await self.token_manager.record_error(token_obj.id)
            debug_logger.log_error(
                error_message=f"Character and video generation failed: {str(e)}",
                status_code=500,
                response_text=str(e)
            )
            raise
        finally:
            if self.concurrency_manager and concurrency_acquired:
                await self.concurrency_manager.release_video(token_obj.id)
            # 暂不自动删除角色，便于在前端仓库复用/查看，后续可提供手动清理接口
            pass

    async def _handle_remix(self, remix_target_id: str, prompt: str, model_config: Dict) -> AsyncGenerator[str, None]:
        """Handle remix video generation

        Flow:
        1. Select token
        2. Clean remix link from prompt
        3. Call remix API
        4. Poll for results
        5. Return video result
        """
        token_obj = await self.load_balancer.select_token(for_video_generation=True)
        if not token_obj:
            raise Exception("No available tokens for remix generation")

        task_id = None
        concurrency_acquired = False
        try:
            # Acquire video concurrency slot if enabled
            if self.concurrency_manager:
                concurrency_acquired = await self.concurrency_manager.acquire_video(token_obj.id)
                if not concurrency_acquired:
                    raise Exception(f"Failed to acquire concurrency slot for token {token_obj.id}")

            # Record usage for video
            await self.token_manager.record_usage(token_obj.id, is_video=True)

            yield self._format_stream_chunk(
                reasoning_content="**Remix Generation Process Begins**\n\nInitializing remix request...\n",
                is_first=True
            )

            # Clean remix link from prompt to avoid duplication
            clean_prompt = self._clean_remix_link_from_prompt(prompt)

            # Get n_frames from model configuration
            n_frames = model_config.get("n_frames", 300)  # Default to 300 frames (10s)

            # Call remix API
            yield self._format_stream_chunk(
                reasoning_content="Sending remix request to server...\n"
            )
            task_id = await self.sora_client.remix_video(
                remix_target_id=remix_target_id,
                prompt=clean_prompt,
                token=token_obj.token,
                orientation=model_config["orientation"],
                n_frames=n_frames
            )
            debug_logger.log_info(f"Remix generation started, task_id: {task_id}")

            # Save task to database
            task = Task(
                task_id=task_id,
                token_id=token_obj.id,
                model=f"sora-video-{model_config['orientation']}",
                prompt=f"remix:{remix_target_id} {clean_prompt}",
                status="processing",
                progress=0.0
            )
            await self.db.create_task(task)

            # Record usage
            await self.token_manager.record_usage(token_obj.id, is_video=True)

            # Poll for results
            async for chunk in self._poll_task_result(task_id, token_obj.token, True, True, clean_prompt, token_obj.id):
                yield chunk

            # Record success
            await self.token_manager.record_success(token_obj.id, is_video=True)

        except Exception as e:
            # Record error
            if token_obj:
                await self.token_manager.record_error(token_obj.id)
            debug_logger.log_error(
                error_message=f"Remix generation failed: {str(e)}",
                status_code=500,
                response_text=str(e)
            )
            raise
        finally:
            if self.concurrency_manager and concurrency_acquired:
                await self.concurrency_manager.release_video(token_obj.id)

    async def _poll_cameo_status(self, cameo_id: str, token: str, timeout: int = 600, poll_interval: int = 5) -> Dict[str, Any]:
        """Poll for cameo (character) processing status

        Args:
            cameo_id: The cameo ID
            token: Access token
            timeout: Maximum time to wait in seconds
            poll_interval: Time between polls in seconds

        Returns:
            Cameo status dictionary with display_name_hint, username_hint, profile_asset_url, instruction_set_hint
        """
        start_time = time.time()
        max_attempts = int(timeout / poll_interval)
        consecutive_errors = 0
        max_consecutive_errors = 3  # Allow up to 3 consecutive errors before failing

        for attempt in range(max_attempts):
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                raise Exception(f"Cameo processing timeout after {elapsed_time:.1f} seconds")

            await asyncio.sleep(poll_interval)

            try:
                status = await self.sora_client.get_cameo_status(cameo_id, token)
                current_status = (status.get("status") or "").lower()
                status_message = status.get("status_message", "") or ""

                # Reset error counter on successful request
                consecutive_errors = 0

                debug_logger.log_info(f"Cameo status: {current_status} (message: {status_message}) (attempt {attempt + 1}/{max_attempts})")

                # Immediate failure conditions
                if current_status == "failed" or (status_message and status_message.lower().startswith("upload may violate")):
                    raise Exception(f"Cameo processing failed: {status_message or current_status}")

                # Check if processing is complete
                # Primary condition: status_message contains complete / finished / success (case-insensitive)
                msg_lower = status_message.lower()
                if any(k in msg_lower for k in ["complete", "finished", "success", "ready"]):
                    debug_logger.log_info(f"Cameo processing completed (status: {current_status}, message: {status_message})")
                    return status

                # Fallback condition: status in a set of completed markers
                if current_status in {"finalized", "complete", "completed", "ready", "finished", "success", "succeeded", "done"}:
                    debug_logger.log_info(f"Cameo processing completed (status: {current_status}, message: {status_message})")
                    return status

                # Extra safeguard: if profile asset already给出则视为完成
                if status.get("profile_asset_url") or status.get("instruction_set_hint") or status.get("characters"):
                    debug_logger.log_info("Cameo processing appears ready based on payload fields; returning early.")
                    return status

            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e)

                # Log error with context
                debug_logger.log_error(
                    error_message=f"Failed to get cameo status (attempt {attempt + 1}/{max_attempts}, consecutive errors: {consecutive_errors}): {error_msg}",
                    status_code=500,
                    response_text=error_msg
                )

                # Check if it's a TLS/connection error
                is_tls_error = "TLS" in error_msg or "curl" in error_msg or "OPENSSL" in error_msg

                if is_tls_error:
                    # For TLS errors, use exponential backoff
                    backoff_time = min(poll_interval * (2 ** (consecutive_errors - 1)), 30)
                    debug_logger.log_info(f"TLS error detected, using exponential backoff: {backoff_time}s")
                    await asyncio.sleep(backoff_time)

                # Fail if too many consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    raise Exception(f"Too many consecutive errors ({consecutive_errors}) while polling cameo status: {error_msg}")

                # Continue polling on error
                continue

        raise Exception(f"Cameo processing timeout after {timeout} seconds")
