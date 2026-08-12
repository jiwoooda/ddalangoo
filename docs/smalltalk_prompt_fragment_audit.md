# 스몰톡 조건부 프롬프트 조각 상호작용 감사표

코드의 우선순위는 `wrap-up > question suppression > name greeting > topic
pivot > normal style/episode`다. 높은 우선순위 조각이 질문을 금지하거나 특정
질문 하나를 요구하면 경쟁하는 생성 조각은 빈 문자열로 바꾼다.

| 조각 A | 조각 B | 동시 활성화 | 우선순위/처리 |
|---|---|---:|---|
| name greeting | style pattern | 아니요 | name greeting, style 제거 |
| name greeting | episode hint | 아니요 | name greeting, episode 제거 |
| name greeting | topic pivot | 아니요 | name greeting, pivot 제거 |
| name greeting | wrap-up | 아니요 | wrap-up, name greeting 제거 |
| name greeting | question suppression | 아니요 | question suppression, name greeting 제거 |
| wrap-up | question suppression | 아니요 | wrap-up 문구만 주입 |
| wrap-up | topic pivot | 아니요 | wrap-up, pivot 제거 |
| wrap-up | style/episode | 아니요 | 둘 다 질문·자기얘기 생성 신호 제거 |
| question suppression | topic pivot | 아니요 | question suppression, pivot 제거 |
| question suppression | style/episode | 제한적 | 질문 없는 override만 사용, episode 제거 |
| topic pivot | style pattern | 예 | guess/balance를 우선 선택 |
| topic pivot | episode hint | 예 | 표현 재구성 규칙과 사후 복제 검사 적용 |

이 표의 배타 관계는 `smalltalk_agent_node`의 조건 분기 순서와 일치해야 한다.
