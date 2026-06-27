import sys
import os

# vendor/ddalangoo-langgraph/src 경로 등록 (로컬 테스트용)
_backend = os.path.dirname(__file__)
_vendor = os.path.join(_backend, "vendor", "ddalangoo-langgraph")

for p in [_vendor, _backend]:
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("PROJECT_ROOT", _backend)
