# 动态模型用例生成 Profile

将 ScriptIR 编码为动态模型 pytest 用例。IR 决定操作、参数、顺序、循环和用户预期；本 Profile 决定真实框架 API、命名、步骤记录、采集与等待规则。历史脚本只供接口参考，采集口径以本文为准。允许使用 Python 标准库 time、itertools、re，其他接口限于本文明确说明的能力。

## 用例结构

- 文件名 `test_*.py`，类名 `Test*`，方法名 `test_*`，继承 `exfw.models.dynamic.base_case.DynamicCase`。用“应用/功能 + 核心场景”的两到四个词命名，例如 `test_douyin_search.py`、`TestDouyinSearch`、`test_douyin_search`；标识符建议不超过40字符。名称冲突时加最小区分词，不把整段流程翻译成标识符，不用时间戳或本次随机标题。完整中文目标保留在简短用例 docstring 中，不改写 IR 的业务要求。
- 代码中**不要添加任何多余的解释性注释**。仅当 IR 中的操作或验证无法在框架找到对应方法时，才使用 `# TODO: ...` 注释说明。
- `self.device` 是 testbed 中名为 `main` 的设备；不要在用例中自行连接 ADB。框架自动注入步骤、Trace、页面等待和键盘等能力。
- 每个有意义的测试步骤先调用 `self.step("简短中文描述")`，放在 Trace 外；它返回记录字典，不是上下文管理器。描述说明当前业务动作或连续滑动组，不复述整份用例。它可能截图，失败截图由框架处理。循环内步骤在实际执行位置记录；可带当前迭代序号。偶发弹窗条件守护不单独记录为必做步骤，用户明确要求的业务确认仍须记录并执行。
- 用例通过普通 Python `assert` 表达已知的预期结果；对没有可靠验证依据的步骤，不要编造断言。

不要生成 ADB 连接、设备创建、采集器创建、pytest 插件装配、上传或报告初始化代码。这些由运行环境提供。下文示例只演示特定规则，按实际 IR 选择内容，不复制示例业务目标。

## 操作映射

| IR 操作意图 | 框架写法与约束 |
|---|---|
| 按应用名称启动 | `self.device.start_app(app_name="设置")`；通过桌面图标查找应用，会先返回桌面。 |
| 按包名启动 | `self.device.start_pkg(package_name="com.example.app")`；包名必须已知。 |
| 点击 | `self.device.click(text="搜索")`、`click(description="返回")`、`click(resourceId="包名:id/控件")` 或 `click(point=[x, y])`。所有参数为关键字；可用 `textMatches`、`descriptionMatches`、`className`。 |
| 双击 / 长按 | `self.device.double_click(text="相册")`；`self.device.long_click(text="相册", duration=1.0)`。定位参数与点击相同。 |
| 方向滑动 | `self.device.swipe(direction=Direction.UP, times=2)`；方向支持 `UP`、`DOWN`、`LEFT`、`RIGHT`、`DOWN_SLIGHT`；`interval` 为多次滑动间隔秒数。 |
| 按路径滑动 | `self.device.swipe(start=(0.5, 0.8), end=(0.5, 0.3), times=2, interval=1.0)`；起止点直接使用 IR 的0～1坐标。方向与起止点两种形式只选一种。 |
| 拖动 | `self.device.drag(start=(0.2, 0.5), end=(0.8, 0.5), duration=1.0)`；使用 IR 坐标和 duration，不能用普通滑动替代；缺少必要时长则 TODO 和 notes。 |
| 文本输入 | 聚焦输入框后调用 `self.device.set_text("内容")`；需要模拟键盘点击时可用 `self.keyboard_factory(self.device).input_text("内容")`。 |
| 返回 / 桌面 | `self.device.back()`、`self.device.home()`；`method="key"` 为默认值，也支持 `method="swipe"`。 |
| 多任务 | `self.device.open_multitask(method="key")`，也支持 `method="swipe"`。 |
| 控制中心 | `self.device.open_control()`。 |
| 通知栏 | `self.device.open_notification(method="key")`，也支持 `method="swipe"`。 |
| 等待 | `time.sleep(秒数)`，完整保留 IR 明确要求的 duration 和所在位置，不用页面等待替换观看/固定等待。 |
| 关闭应用 | `self.device.stop_app(package_name="com.example.app")`；省略包名时关闭当前前台应用。 |

IR 中 point、start、end 已统一为0～1比例坐标，直接传入设备方法，边界值也保持浮点数。不乘屏幕宽高、不再除以1000、不套用示例像素。属性定位只使用 IR 已选择的 selector，不重新挑控件或用坐标覆盖已确定的属性定位。未提供的可选参数省略，不将 null 映射成方法参数 None；times、interval、duration 有值时完整传递。

stop_app 的 package_name 是包名，app_name 是显示名称，不能相互替代。IR 只有应用显示名时，不根据名称猜包名；仅在要求明确指向当前前台应用时省略包名，否则 TODO 和 notes。start_pkg 仅在有明确包名依据时使用；不能为了方便绕过 IR 的按应用名称启动要求。

## 定位与读取

- IR 属性映射：resource_id→resourceId，text→text，description→description，class_name→className；同一 selector 的属性组合使用，不删掉限定条件。
- `self.device.find_element(text=..., textMatches=..., resourceId=..., description=..., descriptionMatches=..., className=..., timeout=1)` 返回 UiObject 或 None；不会返回列表。`click(obj=obj)`、`double_click(obj=obj)`、`long_click(obj=obj, duration=...)` 支持已定位对象。
- 对需要区域、序号或读取的目标，允许访问框架已有连接 `self.device.device(**selector)`，得到 uiautomator2 UiObject；这里不是新建设备。已核对可用接口为 `obj[index]`（0起）、`obj.child(**selector)`、`obj.exists`（布尔属性）、`obj.count`（整数属性）、`obj.info`（实际控件属性字典）、`obj.get_text()`（读取文本）。`exists`、`count`、`info` 不写成方法。
- 无 within：按 selector 构造目标，有 index 时再取 `obj[index]`。有 within：先按区域 selector 定位，存在 within_index 时先选区域，再 `region.child(**target_selector)`，最后应用目标 index。区域必须具备能支持该查找的层级依据；多区域未指定序号时不能自行取第一个。不能把 within、index、scope_index 当关键字传给框架 click/find_element。
- 操作前需要确认对象存在时用 `assert obj.exists, "具体目标未找到"`；这是动作前置检查，不新增业务预期。不能对 UiObject 使用 `if obj` 代替 exists，也不能漏判 find_element 返回的 None。
- 非UI验证仅在本文有明确支持的实现时生成；没有对应 API 时保留 TODO 和 notes，不调用未知的网络、数据库或业务客户端。

## 验证与弹窗

存在验证可使用 `assert self.page_waiter.wait_ui(judge_elements={"text": "用户指定文本"}, timeout=8), "具体失败原因"`。Activity 验证使用 `assert self.page_waiter.wait_activity(activity="已知的完整Activity", timeout=5), "具体失败原因"`，只用于原要求确实验证 Activity 或有明确依据的页面就绪检查，不能代替业务预期。

`wait_ui` 和 `wait_activity` 用于等待并验证页面，返回布尔值；需要判定用例失败时必须 `assert`。`wait_ui` 的条件支持 `text`、`textContains`、`description`、`descriptionContains`、`resourceId`、`resourceIdMatches`；同一条件传列表表示**全部存在**，不是“任一存在”。等待器先验证页面，验证连续失败时才尝试按传入的 watcher 或 `cv` 处理弹窗；页面一开始就满足条件时不会主动清理弹窗。

- wait_ui 不接收 className、textMatches、descriptionMatches、index 或 within；需要这些限定时使用上述 UiObject 定位，不能删除定位条件来迁就等待器。
- 不存在验证在原锚点使用 `assert not obj.exists`；数量验证读取 `obj.count`，文本/数值验证读取 `obj.get_text()`，按用户要求比较。需要等待消失或数值变化时，可用 time.monotonic 与 time.sleep 做有界轮询，不能无期限等待。读取值的格式和单位必须有依据，不使用宽泛数字提取悄悄改变语义。
- “增加1”先在对应业务操作之前读取运行时基准，再在验证锚点比较。循环内基准按原验证 scope 每轮更新；循环外验证保持在循环外。基准读取和验证不采 Trace，不把探索时数字当运行时基准。
- 开关关闭/开启、选中/取消选中的验证，定位对应控件后先确认存在，再读取 `obj.info` 中实际提供的 checked/selected；例如 `assert obj.info.get("checked") is False, "Wi-Fi开关未关闭"`。不能用元素存在代替关闭状态，不能把属性缺失默认当false，也不能由UI开关状态推导网络必然断开。目标或属性无可靠依据时保留 TODO 和 notes。
- 验证按target.verification选择方式，而不是全部套wait_ui。attribute用obj.info读取指定状态；text用get_text；number按证据中明确的数字格式与单位转换后比较，不猜万元/百分比含义；count用obj.count统计完整集合，预期为0时不能先assert obj.exists。delta在指定baseline_operation_id动作前读取实时基准，最终仍在原验证位置比较。
- 缺少可读状态属性时，允许使用target.verification中有明确等价依据的UI特征：例如IR给出“WLAN已关闭”这一真实状态提示及exists判断，可用wait_ui等待该提示；有限定区域/序号时，用相同作用域内UiObject.exists进行有界轮询。not_exists用有界轮询或原锚点的not obj.exists，wait_ui没有负向参数，不能编造。特征来自历史帧不表示当前通过，仍需在原位置检查实时页面；检查消失时要保持其所属页面/区域的身份依据，不能因为整页导航走了就宣布开关关闭。
- 等价UI特征必须来自IR的证据策略，不能由编码模型临时挑一个相邻文字替代。没有checked不等于框架完全不支持验证；先检查明确状态文案或描述等可表达方式。Wi-Fi“未连接”不等于开关已关闭，控件存在也不等于开启，禁止这类弱化断言。证据确实不足时才TODO并写notes，不能无限尝试或自动切换成AI判断。
- 无可靠目标但用户明确要求固定文本存在/不存在时，可以按该文本实现；不能把缺少定位当成预期已满足。无法实现则 TODO 和 notes。所有示例的文本、Activity 和超时按实际依据使用，不自行加“首页存在”等额外业务断言。

需要单独处理弹窗时，使用 `self.popup_handler`：

```python
watcher = [{"text": "始终允许", "action": {"type": "click"}}]
self.popup_handler.handle(watcher=watcher)  # 检测并处理一次，返回 bool
self.popup_handler.handle_continuously(watcher=watcher, timeout=5, interval=0.5)  # 持续检测，返回处理次数
```

`handle_continuously` 会持续到 `timeout`，适合连续或延迟出现的弹窗。`cv=True` 可启用图像弹窗检测兜底，默认关闭，应按任务需求明确开启。watcher 不是全局自动监听；只生成已知且允许处理的弹窗规则。单独调用 `handle` 返回 `False` 可能只是没有弹窗，不应默认视为测试失败。

watcher 检测字段支持 text、description、text_regex、description_regex；正则是 fullmatch，不能把“包含”误写成未加范围的正则。action.type 支持 click、back、cv；click 未给 target 时点击命中对象，另给 target 时使用字典，例如 `{"text": "升级提示", "action": {"type": "click", "target": {"text": "取消"}}}`。target 可用 text、description、resourceId，不能把 target 写成字符串。`cv=False` 只关闭未命中规则时的 CV 兜底，不阻止规则中显式的 action.type=cv。

只有 IR 条件明确允许的偶发环境处理才能转换为 watcher，保持原始发生位置、目标和作用范围。框架单次 handle 只处理一次命中；不能把需要连续多步处理的 condition 简化成只执行一次 handle，也不能将普通业务确认变成 watcher。无法等价表达的条件保留显式存在判断与完整 body，不能删除条件或吞掉后续错误。

## Trace 约定

用 `with self.tracer.collect(self.device.serial, name=..., description=...):` 采集。默认一个符合采集条件的动作一个 Trace，不把整个 step 或循环体包成一个 Trace。

- 启动应用：`AppLaunch1`；退出应用或返回桌面：`AppExit1`。
- 滑动操作：`AppSwipe1`。
- 点击类动作（click/double_click/long_click）：仅当 IR 的 activity_changed=true 时采集 `AppClick`；false 或缺少依据时不采集。Tab、页面、面板发生变化不能替代 Activity 切换依据。普通点击、输入、等待、验证、偶发弹窗处理不采集；back、系统面板、多任务、drag 不自行归为 AppClick 或 AppSwipe。

### 连续滑动分组

连续相邻滑动允许共用一个 AppSwipe Trace：单次 swipe(times=N) 是一个批量动作；相邻的上滑、下滑等多个 swipe 调用也可放在同一个 Trace 中，次数、方向、原有间隔和顺序完整保留。两次滑动间明确属于滑动组的间隔可保留在组内；独立的观看/等待指令不能并入。点击、输入、导航、验证、条件边界或循环边界会中断滑动组。不跨这些边界合并，不为合并而重排动作。

### 唯一命名

每个测试方法内按实际采集次数为各类型独立递增编号。连续滑动组按一个 Trace 编号，不按组内滑动次数编号。框架自动补 `<case>_loop<round>_`，round 是 pytest 外层轮次，不是脚本 for 下标；不要重复添加该前缀。

内部循环必须每次生成不同短名；多个循环、嵌套循环、条件分支和循环外动作共用该方法内的计数序列。推荐 `from itertools import count`，按需要在方法开头初始化 `launch_seq = count(1)`、`exit_seq = count(1)`、`swipe_seq = count(1)`、`click_seq = count(1)`，调用时 `name=f"AppSwipe{next(swipe_seq)}"`。只初始化实际使用的计数器；不要在循环内重置，不用固定 AppSwipe1 重复采集。保留 AppLaunch/AppExit/AppSwipe/AppClick 分类字符串，它们参与产物解析。

### 采集收尾与等待

Trace 块包含动作与动画收尾时间。当前生成默认：启动、退出、Activity切换点击后收尾2秒，滑动组最后一次滑动后收尾1秒。组内各调用已有明确间隔时原样保留，不给每次内部滑动重复加收尾等待。这些是采集策略，不能替代、抵扣或移动 IR 的用户等待；不为普通未采集动作机械添加此延迟。

`self.step`、控件定位和前置存在检查放在 Trace 外；与该动作有关的定位准备完成后再开始采集。业务断言、页面轮询和弹窗处理放在 Trace 外。采集器默认 delete_on_error=True，不能为了保留文件而吞异常或擅自改该配置。不能嵌套 Trace，同设备同时只允许一个活跃采集。

## 最小编码示例

仅适用于 IR 要求“启动应用，重复三轮上滑两次、下滑一次，然后返回桌面”的情况；示例没有额外业务验证。实际按 IR 的次数、应用和边界生成：

```python
import time
from itertools import count

from exfw.aw.device import Direction
from exfw.models.dynamic.base_case import DynamicCase


class TestFeedBrowse(DynamicCase):
    """应用信息流浏览。"""

    def test_feed_browse(self):
        swipe_seq = count(1)

        self.step("启动应用")
        with self.tracer.collect(self.device.serial, name="AppLaunch1", description="启动应用"):
            self.device.start_app(app_name="用户指定应用")
            time.sleep(2)

        for iteration in range(3):
            self.step(f"第{iteration + 1}轮浏览信息流")
            with self.tracer.collect(
                self.device.serial,
                name=f"AppSwipe{next(swipe_seq)}",
                description="信息流上滑两次、下滑一次",
            ):
                self.device.swipe(direction=Direction.UP, times=2)
                self.device.swipe(direction=Direction.DOWN, times=1)
                time.sleep(1)

        self.step("返回桌面")
        with self.tracer.collect(self.device.serial, name="AppExit1", description="返回桌面"):
            self.device.home(method="swipe")
            time.sleep(2)
```

## 生成检查

- 保持 IR 的操作顺序、次数、方向、等待和预期；不自行添加可能改变业务状态的操作。
- 区分返回上一页与返回桌面；不要把应用名称当包名或把像素坐标当比例坐标。
- 仅在目标、检查条件、设备或资源信息可靠时生成对应调用；不支持或信息不足的操作应明确标记，不能静默省略或虚构接口。
- 用例集需加载 `exfw.pytest_framework.plugin` 和 `exfw.models.dynamic.dynamic_pytest.plugin`；测试配置需提供 `main` 设备与存在的资源目录。是否上传由项目配置决定。
- 输出前核对：真实 API 及关键字、IR 节点覆盖、原值参数、验证位置、循环次数、采集条件、连续滑动分组和运行时 Trace 名唯一性。不能只检查源码里 name 是否不同，还要考虑循环执行。
- 语法与 pytest 收集检查由具备环境的调用方执行，不在脚本中编写检查器；没有实际运行就不能声称已通过。设备行为、键盘资源和页面断言仍需在目标环境验证。
