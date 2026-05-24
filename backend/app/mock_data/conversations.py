MOCK_CONVERSATIONS = [
    {
        "id": 42,
        "user_id": 1,
        "status": "waiting_user_confirmation",
        "stage": "product_confirming",
        "keyword": "strawberry",
    },
    {
        "id": 43,
        "user_id": 1,
        "status": "waiting_user_confirmation",
        "stage": "product_confirming",
        "keyword": "sesame_oil",
    },
    {
        "id": 44,
        "user_id": 1,
        "status": "waiting_user_confirmation",
        "stage": "product_confirming",
        "keyword": "soy_milk",
    },
    {
        "id": 45,
        "user_id": 1,
        "status": "idle",
        "stage": "idle",
        "keyword": None,
    },
]

MOCK_CONVERSATION_MESSAGES = [
    {"id": 1, "conversation_id": 42, "role": "user", "content": "저번에 먹었던 딸기 다시 사줘"},
    {"id": 2, "conversation_id": 42, "role": "assistant", "content": "설향 딸기 500g 추천드립니다."},
]

MOCK_AGENT_INTENTS = [
    {"id": 1, "conversation_id": 42, "intent": "reorder", "keyword": "strawberry"},
]

MOCK_AGENT_EVENTS = [
    {"id": 1, "conversation_id": 42, "event_type": "recommendation_created", "payload": {}},
]
