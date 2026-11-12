"""Load the stable-path policy and inject the actual execution method rules."""
from pathlib import Path

from atestservice.exploration.policy import render_method_rules

SYSTEM_PROMPT = (Path(__file__).parent / "operate_step.md").read_text(encoding="utf-8").replace(
    "{method_rules}", render_method_rules()
).strip()
CURRENT_SCREEN_TEXT = "当前手机页面："
