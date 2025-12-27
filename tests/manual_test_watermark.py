import asyncio
import sys
import os
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.core.database import Database
from src.services.proxy_manager import ProxyManager
from src.services.sora_client import SoraClient
from src.services.google_drive_uploader import GoogleDriveUploader
from src.core.config import config

async def main():
    token = None
    if len(sys.argv) >= 2 and sys.argv[1] != "auto":
        token = sys.argv[1]
    
    generation_id = sys.argv[2] if len(sys.argv) > 2 else "gen_01kdfd4ba4efztcysha3vq5m0g"
    prompt = sys.argv[3] if len(sys.argv) > 3 else "test prompt"

    # Initialize services
    db = Database()
    
    if not token:
        print("No token provided, attempting to fetch from database...")
        tokens = await db.get_active_tokens()
        if tokens:
            token = tokens[0].token
            print(f"✅ Found active token in database: {token[:10]}...")
        else:
            print("❌ No active tokens found in database. Please provide a token manually.")
            print("Usage: python tests/manual_test_watermark.py <token|auto> <generation_id> [prompt]")
            return

    print(f"Testing with:")
    print(f"Token: {token[:10]}...")
    print(f"Generation ID: {generation_id}")
    print(f"Prompt: {prompt}")

    proxy_manager = ProxyManager(db)
    sora_client = SoraClient(proxy_manager)
    uploader = GoogleDriveUploader()

    # Check if generation_id is actually a URL
    if generation_id.startswith("http"):
        print(f"\nℹ️ Detected direct URL test mode")
        share_url = generation_id
        # Extract post_id from URL for cleanup later (optional)
        import re
        match = re.search(r's_[a-f0-9]{32}', share_url)
        post_id = match.group(0) if match else None
        print(f"Target URL: {share_url}")
        print(f"Extracted Post ID: {post_id}")
        
        # Skip step 1 (Publish)
        
        # 2. Construct URL (using third-party logic)
        # If we have post_id, we can construct the third-party URL
        if post_id:
            watermark_free_url = f"https://oscdn2.dyysy.com/MP4/{post_id}.mp4"
            print(f"\n2. Constructed Watermark-free URL: {watermark_free_url}")
        else:
            print("❌ Could not extract post_id from URL to construct download link")
            return
            
    else:
        # Standard flow: Publish -> Parse -> Upload
        try:
            # 1. Post video for watermark free
            print("\n1. Posting video for watermark-free processing...")
            post_id = await sora_client.post_video_for_watermark_free(generation_id, prompt, token)
            print(f"✅ Post successful. Post ID: {post_id}")

            # 2. Construct URL
            watermark_free_url = f"https://oscdn2.dyysy.com/MP4/{post_id}.mp4"
            print(f"\n2. Constructed Watermark-free URL: {watermark_free_url}")
            
        except Exception as e:
            print(f"❌ Failed in publish step: {e}")
            return

    try:
        # 3. Upload to Google Drive
        print("\n3. Uploading to Google Drive...")
        print(f"Target Space: {uploader.space_url}")
        
        # Wait loop for file availability
        print("Waiting for file to be ready on third-party server...")
        from curl_cffi.requests import AsyncSession
        
        ready = False
        for i in range(10):
            try:
                async with AsyncSession() as session:
                    resp = await session.head(watermark_free_url, timeout=10)
                    if resp.status_code == 200:
                        print(f"File is ready! (Attempt {i+1})")
                        ready = True
                        break
                    else:
                        print(f"File not ready yet (Status {resp.status_code})... waiting 3s")
            except Exception as e:
                print(f"Check failed: {e}... waiting 3s")
            
            await asyncio.sleep(3)
            
        if not ready:
            print("⚠️ File did not become ready in time. Attempting upload anyway (might fail)...")

        drive_link = await uploader.upload_file_via_api(watermark_free_url)
        
        if drive_link:
            print(f"✅ Google Drive Upload Successful!")
            print(f"Download Link: {drive_link}")
        else:
            print("❌ Google Drive Upload Failed.")

        # 4. Cleanup (Delete post)
        # Only delete post if we created it (not direct URL mode) or if we extracted ID and user wants to clean up
        if post_id and not generation_id.startswith("http"):
            print("\n4. Cleaning up (Deleting post)...")
            try:
                await sora_client.delete_post(post_id, token)
                print("✅ Post deleted.")
            except Exception as e:
                print(f"⚠️ Failed to delete post: {e}")
        else:
            print("\n4. Skipping cleanup (Direct URL mode)")

    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
