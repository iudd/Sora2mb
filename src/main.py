"""Main application entry point"""
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# Import modules
from .core.config import config
from .core.database import Database
from .services.token_manager import TokenManager
from .services.proxy_manager import ProxyManager
from .services.load_balancer import LoadBalancer
from .services.sora_client import SoraClient
from .services.generation_handler import GenerationHandler
from .services.concurrency_manager import ConcurrencyManager
from .api import routes as api_routes
from .api import admin as admin_routes

# Initialize FastAPI app
app = FastAPI(
    title="Sora2API",
    description="OpenAI compatible API for Sora",
    version="1.0.0"
)

# Middleware to fix double slashes in URL path
@app.middleware("http")
async def fix_double_slashes(request: Request, call_next):
    if "//" in request.url.path:
        new_path = request.url.path.replace("//", "/")
        request.scope["path"] = new_path
    response = await call_next(request)
    return response

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
db = Database()
token_manager = TokenManager(db)
proxy_manager = ProxyManager(db)
concurrency_manager = ConcurrencyManager()
load_balancer = LoadBalancer(token_manager, concurrency_manager)
sora_client = SoraClient(proxy_manager)
generation_handler = GenerationHandler(sora_client, token_manager, load_balancer, db, proxy_manager, concurrency_manager)

# Set dependencies for route modules
api_routes.set_generation_handler(generation_handler)
admin_routes.set_dependencies(token_manager, proxy_manager, db, generation_handler, concurrency_manager)

# Include routers
app.include_router(api_routes.router)
app.include_router(admin_routes.router)

# Static files
static_dir = Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon to avoid 404 spam"""
    icon_path = static_dir / "favicon.ico"
    if icon_path.exists():
        return FileResponse(str(icon_path))
    # Fallback: empty 204
    from fastapi import Response
    return Response(status_code=204)

# Chrome DevTools discovery 文件占位，避免 404 噪声
@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_placeholder_exact():
    return JSONResponse(content={}, status_code=200)

# Cache files (tmp directory)
tmp_dir = Path(__file__).parent.parent / "tmp"
tmp_dir.mkdir(exist_ok=True)
app.mount("/tmp", StaticFiles(directory=str(tmp_dir)), name="tmp")

# Frontend routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to login page"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="0; url=/login">
    </head>
    <body>
        <p>Redirecting to login...</p>
    </body>
    </html>
    """

@app.get("/login", response_class=FileResponse)
async def login_page():
    """Serve login page"""
    return FileResponse(str(static_dir / "login.html"))

@app.get("/manage", response_class=FileResponse)
async def manage_page():
    """Serve management page"""
    return FileResponse(str(static_dir / "manage.html"))

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    # Get config from setting.toml
    config_dict = config.get_raw_config()

    # Check if database exists
    is_first_startup = not db.db_exists()

    # Initialize database tables
    await db.init_db()

    # Handle database initialization based on startup type
    if is_first_startup:
        print("🎉 First startup detected. Initializing database and configuration from setting.toml...")
        await db.init_config_from_toml(config_dict, is_first_startup=True)
        print("✓ Database and configuration initialized successfully.")
    else:
        print("🔄 Existing database detected. Checking for missing tables and columns...")
        await db.check_and_migrate_db(config_dict)
        print("✓ Database migration check completed.")

    # Load admin credentials and API key from database
    admin_config = await db.get_admin_config()
    config.set_admin_username_from_db(admin_config.admin_username)
    config.set_admin_password_from_db(admin_config.admin_password)
    config.api_key = admin_config.api_key

    # Load cache configuration from database
    cache_config = await db.get_cache_config()
    config.set_cache_enabled(cache_config.cache_enabled)
    config.set_cache_timeout(cache_config.cache_timeout)
    config.set_cache_base_url(cache_config.cache_base_url or "")

    # Load generation configuration from database
    generation_config = await db.get_generation_config()
    config.set_image_timeout(generation_config.image_timeout)
    config.set_video_timeout(generation_config.video_timeout)

    # Load token refresh configuration from database
    token_refresh_config = await db.get_token_refresh_config()
    config.set_at_auto_refresh_enabled(token_refresh_config.at_auto_refresh_enabled)

    # Initialize concurrency manager with all tokens
    all_tokens = await db.get_all_tokens()
    await concurrency_manager.initialize(all_tokens)
    print(f"✓ Concurrency manager initialized with {len(all_tokens)} tokens")

    # Sync from JSONBin on startup if configured
    if config.jsonbin_master_key and config.jsonbin_bin_id:
        try:
            print(f"[JSONBin] Syncing from cloud on startup (Bin ID: {config.jsonbin_bin_id[:8]}...)")
            from .services.jsonbin_service import JsonBinService
            
            # Fetch tokens from JSONBin
            remote_tokens = await JsonBinService.get_tokens()
            
            if remote_tokens:
                added_count = 0
                updated_count = 0
                
                for item in remote_tokens:
                    email = item.get("email")
                    access_token = item.get("access_token") or item.get("token")
                    
                    if not email or not access_token:
                        continue
                    
                    existing_token = await db.get_token_by_email(email)
                    
                    if existing_token:
                        # Update existing token
                        await token_manager.update_token(
                            token_id=existing_token.id,
                            token=access_token,
                            st=item.get("session_token") or item.get("st"),
                            rt=item.get("refresh_token") or item.get("rt"),
                            image_enabled=item.get("image_enabled", True),
                            video_enabled=item.get("video_enabled", True),
                            image_concurrency=item.get("image_concurrency", -1),
                            video_concurrency=item.get("video_concurrency", -1)
                        )
                        await token_manager.update_token_status(existing_token.id, item.get("is_active", True))
                        if concurrency_manager:
                            await concurrency_manager.reset_token(
                                existing_token.id,
                                image_concurrency=item.get("image_concurrency", -1),
                                video_concurrency=item.get("video_concurrency", -1)
                            )
                        updated_count += 1
                    else:
                        # Add new token
                        new_token = await token_manager.add_token(
                            token_value=access_token,
                            st=item.get("session_token") or item.get("st"),
                            rt=item.get("refresh_token") or item.get("rt"),
                            update_if_exists=False,
                            image_enabled=item.get("image_enabled", True),
                            video_enabled=item.get("video_enabled", True),
                            image_concurrency=item.get("image_concurrency", -1),
                            video_concurrency=item.get("video_concurrency", -1)
                        )
                        if not item.get("is_active", True):
                            await token_manager.disable_token(new_token.id)
                        if concurrency_manager:
                            await concurrency_manager.reset_token(
                                new_token.id,
                                image_concurrency=item.get("image_concurrency", -1),
                                video_concurrency=item.get("video_concurrency", -1)
                            )
                        added_count += 1
                
                print(f"[JSONBin] Startup sync completed: {added_count} added, {updated_count} updated")
            else:
                print("[JSONBin] No tokens found in cloud")
        except Exception as e:
            print(f"[JSONBin] Warning: Failed to sync from cloud on startup: {e}")
    else:
        print("[JSONBin] Startup sync skipped: credentials not configured")

    # Start file cache cleanup task
    await generation_handler.file_cache.start_cleanup_task()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await generation_handler.file_cache.stop_cleanup_task()

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=config.server_host,
        port=config.server_port,
        reload=False
    )
