"""Progress payload builders; no persistence or transport dependencies."""
from typing import Any

def text_event(title: str, text: str | None = None) -> dict[str, Any]:
    """构建插件可直接展示的文本事件。"""
    return {
        "title": title,
        "blocks": [
            {
                "type": "text",
                "text": text or title,
            }
        ],
    }


def screenshot_event(title: str, text: str, screenshot_name: str) -> dict[str, Any]:
    """构建带截图入口的事件。"""
    return {
        "title": title,
        "blocks": [
            {
                "type": "text",
                "text": text,
            },
            {
                "type": "screenshot",
                "title": "查看截图",
                "screenshotName": screenshot_name,
            },
        ],
    }


def json_event(title: str, text: str, filename: str, content: Any) -> dict[str, Any]:
    """构建带 JSON 内容入口的事件。"""
    return {
        "title": title,
        "blocks": [
            {
                "type": "text",
                "text": text,
            },
            {
                "type": "json",
                "title": "查看 JSON",
                "filename": filename,
                "content": content,
            },
        ],
    }


def python_event(title: str, text: str, filename: str, code: str) -> dict[str, Any]:
    """构建带 Python 代码入口的事件。"""
    return {
        "title": title,
        "blocks": [
            {
                "type": "text",
                "text": text,
            },
            {
                "type": "python",
                "title": "查看 Python",
                "filename": filename,
                "code": code,
            },
        ],
    }


def label_node(node: str) -> str:
    """节点名展示文案。"""
    return {
        "analyze_input": "任务拆分",
        "prepare_case": "用例描述优化",
        "structure_case": "解析测试用例",
        "observe": "页面观察",
        "plan_intent": "步骤规划",
        "resolve_action": "动作选择",
        "execute": "动作执行",
        "extract_solution": "有效步骤筛选",
        "resolve_codegen_selectors": "控件定位解析",
        "plan_codegen_valid_steps": "验证步骤规划",
        "resolve_codegen_valid_available": "最终 DSL 生成",
        "generate_code": "测试脚本生成",
        "plan_script": "可回放动作整理",
        "resolve_targets": "操作与验证目标解析",
        "encode_script": "框架脚本编码",
        "generate_script": "脚本生成",
        "run": "任务",
    }.get(node, node)
