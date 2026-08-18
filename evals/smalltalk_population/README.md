# Ddalangoo 65+ Smalltalk Evaluation

65세 이상 고령자 페르소나가 실제 구어체로 딸랑구 LangGraph와 대화하고,
프로필 형성 및 대화 품질을 정량화하는 실행 하네스다.

## 평가 범위

- 12개 페르소나: 66~84세, 성별·가구·건강·소비 성향·디지털 숙련도 다양화
- 4개 시나리오: 탐색형, 즉시 요청형, 애매한 요청형, 화제 이탈형
- 말투: 표준 구어체와 경상·전라·충청 지역 말투, 과묵·다변·혼잣말 포함
- 실제 평가 대상: `build_graph()`로 생성한 딸랑구 백엔드 그래프
- 제외 범위: STT, Flutter UI, 실제 결제

## 실행

저장소 루트의 `.env`에서 `OPENAI_API_KEY`를 자동으로 읽는다.

```powershell
cd backend/vendor/ddalangoo-langgraph

# 가장 작은 파일럿: 1 persona × 1 scenario × 1회
python -m evals.smalltalk_population.runner `
  --persona-id P01 `
  --scenario-id exploratory

# Trust/Ease/Frustration LLM Judge까지 실행
python -m evals.smalltalk_population.runner `
  --persona-id P01 `
  --scenario-id exploratory `
  --judge

# 본 실험: 12 personas × 4 scenarios × 3회 = 144 runs
python -m evals.smalltalk_population.runner --repeat 3 --judge
```

필요하면 `--model gpt-4o-mini`, `--output <directory>`로 모델과 출력 위치를
고정한다. LLM Judge 모델은 `EVAL_JUDGE_MODEL` 환경변수로 별도 지정한다.

모든 case는 기본적으로 `temperature=0`(결정론적)으로 실행된다. 다른 값으로
바꾸려면 `--temperature 0.3`처럼 지정한다 — `experiment_config.json`과 각
run의 `input.json`에 실제 사용된 값이 기록되므로 실험 간 비교가 가능하다.
LLM Judge(`--judge`) 채점 호출은 온보딩 재현성과 무관하게 항상 `temperature=0`
으로 고정이다(대화 생성 temperature와 별개).

## 산출물

```text
logs/population_evals/<experiment_id>/
├── experiment_config.json
├── progress.json
├── runs/<run_id>/
│   ├── input.json
│   ├── conversation.jsonl
│   ├── state_trace.jsonl
│   ├── final_profile.json
│   ├── metrics.json
│   └── errors.json
├── summary.csv
├── persona_summary.csv
├── report.json
├── detailed_report.json
└── detailed_report.md
```

`input.json`에는 모델·프롬프트 hash·페르소나·시나리오를 기록한다.
`conversation.jsonl`에는 원문 발화와 해당 턴에 공개된 정답 정보를,
`state_trace.jsonl`에는 상태 전후와 프로필 snapshot을 저장한다.
각 run이 끝날 때마다 `progress.json`, CSV와 상세 보고서를 다시 저장하므로 장시간
실험이 중단되어도 완료된 run의 결과는 보존된다. `detailed_report.md`에는 합격
기준, 시나리오·페르소나·말투별 결과, 실패 원인 및 취약 실행 10건이 포함된다.

## 정량 지표

- Profile Precision / Recall / F1
- Hallucination Rate
- Health Recall
- Question Rate
- Question Limit Violation Rate
- Semantic Repeat Rate
- Trust competence / benevolence
- Perceived empathy / helpfulness
- Ease / Frustration
- Goal Status / Goal Reasoning

프로필 Recall은 페르소나의 모든 숨은 정보를 분모로 쓰지 않고, 해당 실행에서
사용자가 실제 발화로 공개한 필드만 대상으로 한다. 공개하지 않은 값을 저장하면
환각으로 판정한다.

## 보고 시 주의

LLM Judge 점수는 자동 평가값이므로 사람 평가를 대체하지 않는다. 보고서에는
코드 기반 지표와 Judge 지표를 분리하고, 평균뿐 아니라 persona별 최솟값과 실패
대화를 함께 제시한다.
