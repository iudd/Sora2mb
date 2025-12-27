import aiohttp
import json
from typing import List, Dict, Any, Optional
from ..core.config import config

class JsonBinService:
    """Service for interacting with JSONBin.io"""
    
    BASE_URL = "https://api.jsonbin.io/v3/b"

    @classmethod
    async def get_tokens(cls) -> List[Dict[str, Any]]:
        """Fetch tokens from JSONBin"""
        bin_id = config.jsonbin_bin_id
        master_key = config.jsonbin_master_key
        
        if not bin_id:
            raise ValueError("JSONBin Bin ID is not configured")
            
        url = f"{cls.BASE_URL}/{bin_id}?meta=false"
        headers = {}
        if master_key:
            headers["X-Master-Key"] = master_key
            
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"Failed to fetch from JSONBin: {response.status} {text}")
                
                data = await response.json()
                
                # Handle potential wrapping (though meta=false should return raw data)
                if isinstance(data, dict) and "record" in data:
                    data = data["record"]
                    
                if not isinstance(data, list):
                    # It might be a single object or empty
                    if not data:
                        return []
                    if isinstance(data, dict):
                         # If it's a dict but looks like a token, wrap in list
                         if "access_token" in data or "token" in data:
                             return [data]
                    raise ValueError("JSONBin data is not a list of tokens")
                    
                return data

    @classmethod
    async def update_tokens(cls, tokens: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update tokens in JSONBin (overwrite)"""
        bin_id = config.jsonbin_bin_id
        master_key = config.jsonbin_master_key
        
        if not bin_id:
            raise ValueError("JSONBin Bin ID is not configured")
        if not master_key:
            raise ValueError("JSONBin Master Key is not configured (required for updates)")
            
        url = f"{cls.BASE_URL}/{bin_id}"
        headers = {
            "Content-Type": "application/json",
            "X-Master-Key": master_key
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json=tokens, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"Failed to update JSONBin: {response.status} {text}")
                
                return await response.json()
