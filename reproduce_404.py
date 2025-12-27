from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_double_slash():
    print("Testing POST //v1/chat/completions")
    # Note: TestClient might normalize URLs, so we need to be careful.
    # But let's try to send it exactly as seen.
    response = client.post("//v1/chat/completions", json={
        "model": "sora-1.0-turbo",
        "messages": [{"role": "user", "content": "test"}]
    })
    print(f"Status: {response.status_code}")
    
def test_single_slash():
    print("Testing POST /v1/chat/completions")
    response = client.post("/v1/chat/completions", json={
        "model": "sora-1.0-turbo",
        "messages": [{"role": "user", "content": "test"}]
    })
    print(f"Status: {response.status_code}")

if __name__ == "__main__":
    try:
        test_double_slash()
        test_single_slash()
    except Exception as e:
        print(f"Error: {e}")
