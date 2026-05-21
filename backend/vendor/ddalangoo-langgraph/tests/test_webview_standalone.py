"""
웹뷰(Playwright + VLM) 단독 실행 테스트 스크립트
실행: python tests/test_webview_standalone.py
"""
import os
import sys
import json
from dotenv import load_dotenv

# .env 파일에서 ANTHROPIC_API_KEY, KURLY_EMAIL, KURLY_PASSWORD 환경변수 로드
load_dotenv()

# src 디렉토리를 모듈 경로에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.tools.webview_tool import run_kurly_purchase

def main():
    product_name = "[정지선의 티엔미미] 우삼겹 차우면"
    keywords = ["우삼겹 차우면"]
    quantity = 3  # 테스트를 위해 수량을 3개로 설정
    
    print("=== [Test] 컬리 웹뷰 단독 실행 시작 ===")
    print(f"검색 키워드: {keywords}")
    print(f"찾을 상품명: {product_name}")
    print(f"목표 수량: {quantity}개\n")
    
    result = run_kurly_purchase(
        product_name=product_name,
        keywords=keywords,
        quantity=quantity
    )
    
    print("\n=== [Test] 최종 결과 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()