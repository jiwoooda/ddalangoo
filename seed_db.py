"""mock purchase_histories.json → DB 삽입 스크립트"""
from dotenv import load_dotenv
load_dotenv('.env')
import asyncio, sys, json
from datetime import datetime
sys.path.insert(0, 'backend')

async def seed():
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import text

    with open('backend/app/mock_data/purchase_histories.json', encoding='utf-8') as f:
        records = json.load(f)

    # user_id=1 데이터만 사용
    records = [r for r in records if r.get('user_id') == 1]

    async with AsyncSessionLocal() as session:
        # 기존 데이터 확인
        result = await session.execute(text('SELECT COUNT(*) FROM purchase_histories WHERE user_id=1'))
        existing = result.scalar()
        if existing > 0:
            print(f'이미 {existing}건 존재. 삽입 건너뜀.')
            return

        for r in records:
            await session.execute(text("""
                INSERT INTO purchase_histories (
                    user_id, product_id, product_option_id, platform, keyword,
                    product_name_snapshot, option_snapshot, brand_snapshot, category_snapshot,
                    price_at_purchase, product_url_snapshot, selected_options,
                    quantity, total_price, purchased_at, satisfaction, memo, created_at
                ) VALUES (
                    :user_id, :product_id, :product_option_id, :platform, :keyword,
                    :product_name, :option_text, :brand, :category,
                    :price_at_purchase, :product_url, :selected_options,
                    :quantity, :total_price, :purchased_at, :satisfaction, :memo, NOW()
                )
            """), {
                'user_id': r['user_id'],
                'product_id': None,
                'product_option_id': None,
                'platform': r.get('platform'),
                'keyword': r.get('keyword'),
                'product_name': r['product_name'],
                'option_text': r.get('option_text'),
                'brand': r.get('brand'),
                'category': r.get('category'),
                'price_at_purchase': r['price_at_purchase'],
                'product_url': r.get('product_url'),
                'selected_options': json.dumps(r.get('selected_options') or {}, ensure_ascii=False),
                'quantity': r.get('quantity', 1),
                'total_price': r.get('total_price', r['price_at_purchase']),
                'purchased_at': datetime.fromisoformat(r['purchased_at']),
                'satisfaction': r.get('satisfaction_score'),
                'memo': r.get('memo'),
            })

        await session.commit()
        print(f'{len(records)}건 삽입 완료')

asyncio.run(seed())
