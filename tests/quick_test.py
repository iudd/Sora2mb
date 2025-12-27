import sys
import re
import time
import urllib.request

def main():
    # Parse arguments
    # Support both: python quick_test.py <url> <password>
    # And: python quick_test.py <password> <url> (in case user mixes them up)
    
    args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    
    if len(args) < 2:
        print("Usage: python tests/quick_test.py <sora_url> <password>")
        print("Example: python tests/quick_test.py \"https://sora...\" \"123456\"")
        return

    # Simple heuristic to distinguish URL and password
    if args[0].startswith("http"):
        sora_url = args[0]
        password = args[1]
    else:
        password = args[0]
        sora_url = args[1]

    print(f"Testing URL: {sora_url}")
    print(f"Using Password: {password}")
    
    # 1. Extract Post ID
    match = re.search(r's_[a-f0-9]{32}', sora_url)
    if not match:
        print("❌ Could not find post ID in URL")
        return
    
    post_id = match.group(0)
    print(f"Post ID: {post_id}")
    
    # 2. Construct Download URL
    download_url = f"https://oscdn2.dyysy.com/MP4/{post_id}.mp4"
    print(f"Download URL: {download_url}")
    
    # 3. Check availability (using standard library)
    print("Checking file availability...")
    try:
        req = urllib.request.Request(download_url, method='HEAD')
        # User-Agent is sometimes needed
        req.add_header('User-Agent', 'Mozilla/5.0')
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print("✅ File is ready on third-party server.")
            else:
                print(f"⚠️ File returned status: {response.status}")
    except Exception as e:
        print(f"⚠️ Availability check warning: {e}")
        print("Attempting upload anyway...")

    # 4. Upload to Google Drive using gradio_client
    space_url = "https://leeykike-url2drive.hf.space"
    print(f"\nUploading to: {space_url}...")
    
    try:
        from gradio_client import Client
    except ImportError:
        print("❌ Error: gradio_client is not installed.")
        print("Please run: pip install gradio_client")
        return

    try:
        client = Client(space_url)
        print("Client connected. Sending upload request...")
        
        # Predict expects: url, password
        result = client.predict(
            download_url,
            password,
            api_name="/upload"
        )
        
        print("\n✅ Result:")
        print(result)
        
    except Exception as e:
        print(f"\n❌ Upload failed: {e}")

if __name__ == "__main__":
    main()
