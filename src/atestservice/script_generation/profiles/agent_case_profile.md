# 动态模型用例生成 Profile

本文供根据操作 IR 生成 pytest 脚本的 Agent 使用。它描述框架接口和代码生成约定，不规定 IR 格式；操作目标、坐标、页面条件等应来自已验证的 IR 或运行环境，缺失时不要猜测。

## 用例结构

- 默认生成动态模型用例：文件名 `test_*.py`，类名 `Test*`，方法名 `test_*`，继承 `exfw.models.dynamic.DynamicCase`。**类名、方法名和文件名应当尽可能简短**，提取用例名称的核心关键词即可，不要使用冗长的自然语言拼音或直译。
- 代码中**不要添加任何多余的解释性注释**。仅当 IR 中的操作或验证无法在框架找到对应方法时，才使用 `# TODO: ...` 注释说明。
- `self.device` 是 testbed 中名为 `main` 的设备；不要在用例中自行连接 ADB。框架自动注入步骤、Trace、页面等待和键盘等能力。
- 每个有意义的测试步骤先调用 `self.step("描述")`；它返回记录字典，**不是上下文管理器**。配置启用时会在调用时截图，失败截图由框架处理。弹窗处理（`popup_handler.handle(...)`）是不确定出现的条件守护，不写 `self.step(...)`——`self.step` 只用于确定的测试步骤。
- 用例通过普通 Python `assert` 表达已知的预期结果；对没有可靠验证依据的步骤，不要编造断言。

```python
from exfw.aw.device import Direction
from exfw.models.dynamic.base_case import DynamicCase


class TestDemo(DynamicCase):
    def test_demo(self):
        self.step("启动应用")
        with self.tracer.collect(self.device.serial, name="AppLaunch1", description="启动应用"):
            self.device.start_app(app_name="应用名称")

        assert self.page_waiter.wait_ui(
            judge_elements={"text": "首页"}, timeout=8
        ), "启动应用后未进入首页"

        self.step("向上滑动两次")
        with self.tracer.collect(self.device.serial, name="AppSwipe1", description="向上滑动两次"):
            self.device.swipe(direction=Direction.UP, times=2)

        self.step("返回桌面")
        with self.tracer.collect(self.device.serial, name="AppExit1", description="返回桌面"):
            self.device.home(method="swipe")
```

示例中的应用名称和页面文本仅为占位数据，生成实际用例时必须替换为已知值。

## 操作映射

| IR 操作意图 | 框架写法与约束 |
|---|---|
| 按应用名称启动 | `self.device.start_app(app_name="设置")`；通过桌面图标查找应用，会先返回桌面。 |
| 按包名启动 | `self.device.start_pkg(package_name="com.example.app")`；包名必须已知。 |
| 点击 | `self.device.click(text="搜索")`、`click(description="返回")`、`click(resourceId="包名:id/控件")` 或 `click(point=[x, y])`。所有参数为关键字；可用 `textMatches`、`descriptionMatches`、`className`。 |
| 双击 / 长按 | `self.device.double_click(text="相册")`；`self.device.long_click(text="相册", duration=1.0)`。定位参数与点击相同。 |
| 方向滑动 | `self.device.swipe(direction=Direction.UP, times=2)`；方向支持 `UP`、`DOWN`、`LEFT`、`RIGHT`、`DOWN_SLIGHT`；`interval` 为多次滑动间隔秒数。 |
| 按路径滑动 | `self.device.swipe(start=(100, 800), end=(100, 300), times=1)`；仅当 IR 提供了可靠坐标时使用。 |
| 文本输入 | 聚焦输入框后调用 `self.device.set_text("内容")`；需要模拟键盘点击时可用 `self.keyboard_factory(self.device).input_text("内容")`。 |
| 返回 / 桌面 | `self.device.back()`、`self.device.home()`；`method="key"` 为默认值，也支持 `method="swipe"`。 |
| 等待 | `time.sleep(秒数)` 用于 IR 明确要求的固定等待；页面可验证时优先使用下方等待接口。 |
| 关闭应用 | `self.device.stop_app(package_name="com.example.app")`；省略包名时关闭当前前台应用。 |

坐标直接传给设备操作：整数通常表示像素，`uiautomator2` 支持的相对坐标可使用 0～1 小数。不得把 1～1000 的坐标直接当作相对坐标；必须先依据 IR 坐标系及屏幕尺寸转换。优先使用可靠的 `resourceId`、文本或描述定位；坐标需明确来源与适用设备。

## 验证与弹窗

```python
watcher = [{"text": "始终允许", "action": {"type": "click"}}]
assert self.page_waiter.wait_ui(
    judge_elements={"text": "首页"}, timeout=8, watcher=watcher
), "未找到首页"
assert self.page_waiter.wait_activity(activity="com.example.MainActivity", timeout=5)
```

`wait_ui` 和 `wait_activity` 用于等待并验证页面，返回布尔值；需要判定用例失败时必须 `assert`。`wait_ui` 的条件支持 `text`、`textContains`、`description`、`descriptionContains`、`resourceId`、`resourceIdMatches`；同一条件传列表表示**全部存在**，不是“任一存在”。等待器先验证页面，验证连续失败时才尝试按传入的 watcher 或 `cv` 处理弹窗；页面一开始就满足条件时不会主动清理弹窗。

需要单独处理弹窗时，使用 `self.popup_handler`：

```python
watcher = [{"text": "始终允许", "action": {"type": "click"}}]
self.popup_handler.handle(watcher=watcher)  # 检测并处理一次，返回 bool
self.popup_handler.handle_continuously(watcher=watcher, timeout=5, interval=0.5)  # 持续检测，返回处理次数
```

`handle_continuously` 会持续到 `timeout`，适合连续或延迟出现的弹窗。`cv=True` 可启用图像弹窗检测兜底，默认关闭，应按任务需求明确开启。watcher 不是全局自动监听；只生成已知且允许处理的弹窗规则。单独调用 `handle` 返回 `False` 可能只是没有弹窗，不应默认视为测试失败。

## Trace 约定

仅对以下操作采集 Trace，用 `with self.tracer.collect(self.device.serial, name=..., description=...):` 包住实际操作：

- 启动应用：`AppLaunch1`；退出应用或返回桌面：`AppExit1`。
- 滑动操作：`AppSwipe1`。
- 引起 Activity 切换的点击操作：`AppClick1`。直接依据 IR action 节点的 `activity_changed` 字段判定——`activity_changed=true` 的点击才采集，`false` 的不采集；不要自己比较 activity 字符串或凭猜测判定。普通点击、输入、等待等操作不采集。

以上名称按用例内同类型操作顺序独立递增。`self.tracer` 自动添加用例名和轮次前缀，不要手动重复添加。一个 Trace 块可以包含 IR 中明确属于同一采集场景的多次操作。

## 生成检查

- 保持 IR 的操作顺序、次数、方向、等待和预期；不自行添加可能改变业务状态的操作。
- 区分返回上一页与返回桌面；不要把应用名称当包名或把像素坐标当比例坐标。
- 仅在目标、检查条件、设备或资源信息可靠时生成对应调用；不支持或信息不足的操作应明确标记，不能静默省略或虚构接口。
- 用例集需加载 `exfw.pytest_framework.plugin` 和 `exfw.models.dynamic.dynamic_pytest.plugin`；测试配置需提供 `main` 设备与存在的资源目录。是否上传由项目配置决定。
- 生成后至少做 Python 语法检查和 pytest 收集检查；设备行为、键盘资源和页面断言仍需在目标环境验证。
