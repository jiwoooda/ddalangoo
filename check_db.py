from dotenv import load_dotenv
load_dotenv('.env')
import asyncio, sys
sys.path.insert(0, 'backend')
sys.path.insert(0, 'backend/vendor/ddalangoo-langgraph')

async def check():
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        result = await session.execute(text('SELECT COUNT(*) FROM purchase_histories WHERE user_id=1'))
        print(f'DB 구매이력: {result.scalar()}건')

asyncio.run(check())

# memory_agent의 _fetch_purchase_histories 테스트
from src.agents.memory_agent import _fetch_purchase_histories
histories = _fetch_purchase_histories('1')
print(f'_fetch_purchase_histories: {len(histories)}건')
if histories:
    h = histories[0]
    print(f'  첫번째: {h.get("product_name")} / {h.get("platform")} / {h.get("price_at_purchase")}원')
