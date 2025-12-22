import asyncio
import aiosqlite
from pathlib import Path

# 假设数据库路径
DB_PATH = Path("e:/code/Sora2mb/data/sora2mb.db")

async def check_db():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Check table existence
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='character_cards'")
        table = await cursor.fetchone()
        if not table:
            print("Table 'character_cards' does not exist!")
            return
        
        # Count rows
        cursor = await db.execute("SELECT count(*) FROM character_cards")
        count = await cursor.fetchone()
        print(f"Total rows in character_cards: {count[0]}")
        
        # Show first 5 rows
        cursor = await db.execute("SELECT * FROM character_cards LIMIT 5")
        rows = await cursor.fetchall()
        for row in rows:
            print(dict(row))

if __name__ == "__main__":
    asyncio.run(check_db())
