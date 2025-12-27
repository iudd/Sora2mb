"""API routes - OpenAI compatible endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime
from typing import List
import json
import re
from ..core.auth import verify_api_key_header
from ..core.models import ChatCompletionRequest, VideoSyncRequest
from ..services.generation_handler import GenerationHandler, MODEL_CONFIG

router = APIRouter()

# Dependency injection will be set up in main.py
generation_handler: GenerationHandler = None

def set_generation_handler(handler: GenerationHandler):
    """Set generation handler instance"""
    global generation_handler
    generation_handler = handler

def _extract_remix_id(text: str) -> str:
    """Extract remix ID from text

    Supports two formats:
    1. Full URL: https://sora.chatgpt.com/p/s_68e3a06dcd888191b150971da152c1f5
    2. Short ID: s_68e3a06dcd888191b150971da152c1f5

    Args:
        text: Text to search for remix ID

    Returns:
        Remix ID (s_[a-f0-9]{32}) or empty string if not found
    """
    if not text:
        return ""

    # Match Sora share link format: s_[a-f0-9]{32}
    match = re.search(r's_[a-f0-9]{32}', text)
    if match:
        return match.group(0)

    return ""

@router.get("/v1/models")
async def list_models(api_key: str = Depends(verify_api_key_header)):
    """List available models"""
    models = []
    
    for model_id, config in MODEL_CONFIG.items():
        description = f"{config['type'].capitalize()} generation"
        if config['type'] == 'image':
            description += f" - {config['width']}x{config['height']}"
        else:
            description += f" - {config['orientation']}"
        
        models.append({
            "id": model_id,
            "object": "model",
            "owned_by": "sora2api",
            "description": description
        })
    
    return {
        "object": "list",
        "data": models
    }

@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_api_key_header)
):
    """Create chat completion (unified endpoint for image and video generation)"""
    try:
        # Extract prompt from messages
        if not request.messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")

        last_message = request.messages[-1]
        content = last_message.content

        # Handle both string and array format (OpenAI multimodal)
        prompt = ""
        image_data = request.image  # Default to request.image if provided
        video_data = request.video  # Video parameter
        remix_target_id = request.remix_target_id  # Remix target ID

        if isinstance(content, str):
            # Simple string format
            prompt = content
            # Extract remix_target_id from prompt if not already provided
            if not remix_target_id:
                remix_target_id = _extract_remix_id(prompt)
        elif isinstance(content, list):
            # Array format (OpenAI multimodal)
            text_parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")

                if item_type == "text":
                    txt = item.get("text", "")
                    if txt:
                        text_parts.append(txt)
                        if not remix_target_id:
                            remix_target_id = _extract_remix_id(txt)

                elif item_type == "image_url":
                    # Extract base64 image from data URI
                    image_url = item.get("image_url", {})
                    url = image_url.get("url", "")
                    if url.startswith("data:image"):
                        # Extract base64 data from data URI
                        if "base64," in url:
                            image_data = url.split("base64,", 1)[1]
                        else:
                            image_data = url

                elif item_type == "video_url":
                    # Extract video from video_url
                    video_url = item.get("video_url", {})
                    url = video_url.get("url", "")
                    if url.startswith("data:video") or url.startswith("data:application"):
                        # Extract base64 data from data URI
                        if "base64," in url:
                            video_data = url.split("base64,", 1)[1]
                        else:
                            video_data = url
                    else:
                        # It's a URL, pass it as-is (will be downloaded in generation_handler)
                        video_data = url

            if text_parts:
                prompt = " ".join(text_parts)
                # If remix id still missing, try full prompt
                if not remix_target_id:
                    remix_target_id = _extract_remix_id(prompt)
        else:
            raise HTTPException(status_code=400, detail="Invalid content format")

        # Validate model
        if request.model not in MODEL_CONFIG:
            raise HTTPException(status_code=400, detail=f"Invalid model: {request.model}")

        # Check if this is a video model
        model_config = MODEL_CONFIG[request.model]
        is_video_model = model_config["type"] == "video"

        # For video models with video parameter, we need streaming
        if is_video_model and (video_data or remix_target_id):
            if not request.stream:
                # Non-streaming mode: only check availability
                result = None
                async for chunk in generation_handler.handle_generation(
                    model=request.model,
                    prompt=prompt,
                    image=image_data,
                    video=video_data,
                    remix_target_id=remix_target_id,
                    stream=False
                ):
                    result = chunk

                if result:
                    import json
                    return JSONResponse(content=json.loads(result))
                else:
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": {
                                "message": "Availability check failed",
                                "type": "server_error",
                                "param": None,
                                "code": None
                            }
                        }
                    )

        # Handle streaming
        if request.stream:
            async def generate():
                import json as json_module  # Import inside function to avoid scope issues
                try:
                    async for chunk in generation_handler.handle_generation(
                        model=request.model,
                        prompt=prompt,
                        image=image_data,
                        video=video_data,
                        remix_target_id=remix_target_id,
                        stream=True
                    ):
                        yield chunk
                except Exception as e:
                    # Return OpenAI-compatible error format
                    error_response = {
                        "error": {
                            "message": str(e),
                            "type": "server_error",
                            "param": None,
                            "code": None
                        }
                    }
                    error_chunk = f'data: {json_module.dumps(error_response)}\n\n'
                    yield error_chunk
                    yield 'data: [DONE]\n\n'

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Non-streaming response (availability check only)
            result = None
            async for chunk in generation_handler.handle_generation(
                model=request.model,
                prompt=prompt,
                image=image_data,
                video=video_data,
                remix_target_id=remix_target_id,
                stream=False
            ):
                result = chunk

            if result:
                import json
                return JSONResponse(content=json.loads(result))
            else:
                # Return OpenAI-compatible error format
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "message": "Availability check failed",
                            "type": "server_error",
                            "param": None,
                            "code": None
                        }
                    }
                )

    except Exception as e:
        # Return OpenAI-compatible error format
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "param": None,
                    "code": None
                }
            }
        )


@router.post("/v1/tasks/{task_id}/watermark/cancel")
async def cancel_watermark_wait(
    task_id: str,
    api_key: str = Depends(verify_api_key_header),
):
    """Cancel watermark-free waiting for a running task (UI convenience endpoint)."""
    if not generation_handler:
        raise HTTPException(status_code=500, detail="Generation handler not initialized")

    ok = await generation_handler.cancel_watermark_wait(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or not waiting for watermark-free")

    return {"success": True, "task_id": task_id}

@router.post("/v1/videos/sync")
async def sync_latest_video(
    request: VideoSyncRequest,
    api_key: str = Depends(verify_api_key_header)
):
    """Sync latest video(s) from Sora account."""
    if not generation_handler:
        raise HTTPException(status_code=500, detail="Generation handler not initialized")

    if request.stream:
        return StreamingResponse(
            generation_handler.sync_latest_video(limit=request.limit, stream=True, force_upload=request.force_upload),
            media_type="text/event-stream"
        )
    else:
        # TODO: Implement non-streaming response if needed
        return {"status": "started", "message": "Streaming is required for sync endpoint currently"}
