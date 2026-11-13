"""Load exploration instructions and tool-selection guidance."""
from pathlib import Path

SYSTEM_PROMPT = (Path(__file__).parent / "operate_step.md").read_text(encoding="utf-8").strip()
CURRENT_SCREEN_TEXT = "当前手机页面："
