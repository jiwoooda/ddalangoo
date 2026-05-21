Use all files in /docs as source-of-truth.

Do not redesign:
- state schema
- pending_action lifecycle
- router logic
- payment lifecycle

Goal:
Build executable LangGraph orchestration baseline.

External integrations may be mocked/stubbed.
State/interface contracts must remain intact.