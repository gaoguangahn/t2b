# -*- coding: utf-8 -*-
"""框架编码规范（codegen profile）加载。

每个目标框架的编码规范以 .md 文件放在 ``profiles/`` 目录下，
是框架相关的能力清单：可用方法、参数、验证方式、用例编写规则。

codegen 层把 IR + 任务描述 + profile 喂给模型生成代码。
IR 是框架无关的唯一事实来源，profile 是框架相关能力清单，两者正交。

用 .md 而非 .py：profile 是纯文本规范，不是代码逻辑，独立文件便于维护和增补框架。
"""

from __future__ import annotations

from pathlib import Path

_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"

# 已注册的框架 profile 名 → 文件名。
# 新增框架时在 profiles/ 下放对应 .md 并在此登记。
_PROFILE_FILES = {
    "dynamic_framework": "agent_case_profile.md",
}

# 默认框架。
DEFAULT_PROFILE = "dynamic_framework"


def load_profile(name: str | None = None) -> str:
    """加载框架 profile 文本。

    Args:
        name: 框架标识；不传或 None 用 ``DEFAULT_PROFILE``。
            未知名称抛 ValueError。
    """
    key = name or DEFAULT_PROFILE
    filename = _PROFILE_FILES.get(key)
    if filename is None:
        raise ValueError(
            f"unknown codegen profile: {key}; "
            f"available: {', '.join(sorted(_PROFILE_FILES))}"
        )
    path = _PROFILE_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"profile file not found: {path}")
    return path.read_text(encoding="utf-8")
