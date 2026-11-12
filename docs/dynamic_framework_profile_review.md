# 动态框架代码生成 Profile 审查

审查日期：2026-11-12。框架来源：`D:/dev/projects/test_framework-agent`；服务端 Profile：`src/atestservice/script_generation/profiles/agent_case_profile.md`。

静态扫描 `tests/dynamic_pnm` 的 35 个文件、38 个测试方法，重点阅读启动、搜索、消息、图库、多应用循环和小红书循环等实际脚本，以及操作、采集、等待和报告实现；没有连接设备执行。以下保留审查依据和建议，落实情况见文末。

## 1. 命名应给模型可执行的规则

现有 Profile 已要求简短，但“尽可能简短”没有明确取舍方式。

建议：

- 文件、类、方法只包含应用/功能和核心场景，例如 `test_douyin_search.py`、`TestDouyinSearch`、`test_douyin_search`；避免把完整操作流程翻译成标识符。
- 默认取两到四个有意义的词；场景冲突时加最小区分词。建议控制在约 30～40 字符内，这是生成规范建议，不是框架硬限制。
- 完整中文目标保留在用例说明中，当前步骤用简短 `self.step` 描述，Trace 的 `description` 描述采集场景；不截断原始 CaseSpec 的业务要求。
- 标识符稳定，不使用探索时的动态文本、时间戳、随机商品标题。

依据：[搜索用例](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_19_douyin_search.py:7)、[多应用启动用例](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_21_multi_launch.py:7)。

## 2. Trace 必须区分框架轮次和脚本内部循环

已确认：

- `DynamicTraceCollector` 只补 `<case>_loop<round>_` 前缀，`round` 来自 pytest 执行轮次，不读取脚本内部循环下标。
- 同一个用例、同一轮中多次传相同短名，生成的设备端文件路径相同，没有自动递增或重名避让。
- 实际多应用用例使用 `trace_idx = i * 4 + 1`；小红书用例也按内部循环计算名称。

建议明确为：同一个测试方法内，每次实际开始采集的短名必须唯一，同类型编号跨内部循环、多个循环块、循环外步骤和条件块继续递增。不重复添加框架轮次或用例名前缀，不用时间戳替换指标分类名。

通用写法可使用普通 Python 计数器，适用于条件分支和嵌套循环：

```python
from itertools import count

swipe_seq = count(1)
for _ in range(3):
    self.step("首页向上滑动")
    with self.tracer.collect(
        self.device.serial,
        name=f"AppSwipe{next(swipe_seq)}",
        description="首页向上滑动",
    ):
        self.device.swipe(direction=Direction.UP, times=2)
        # 此处是否增加动画收尾等待，由明确的采集时序规则决定。
```

简单固定循环也可用样例中的公式编号，但循环前后的编号必须连续避让。每类计数器在测试方法内初始化，不能在循环体内重置。

`AppLaunch`、`AppExit`、`AppClick` 还被解析调度器用于选择指标，因此名称不是纯展示文本，不能随意换成中文或随机词。当前默认 analyse/profile.yaml 没有配置 AppSwipe 的 Trace 指标解析；采集 AppSwipe 文件与自动生成滑动指标是两件事，不应在 Profile 中混为一谈。

依据：[命名前缀](D:/dev/projects/test_framework-agent/src/exfw/models/dynamic/capture/trace.py:29)、[设备端路径](D:/dev/projects/test_framework-agent/src/exfw/aw/trace/collector.py:134)、[多应用循环](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_21_multi_launch.py:12)、[小红书循环](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_25_xiaohongshu.py:43)。

## 3. 采集条件以用户确认的现行规则为准

| 场景 | 现行规则与参考 |
| --- | --- |
| 应用启动 | 样例使用 `AppLaunch`，沿用 |
| 应用返回桌面 | 样例通常使用 `AppExit`；系统多任务回桌面存在不采集的样例，不宜将所有 Home 一律归为应用退出 |
| 明确的滚动/滑动采集场景 | 使用 `AppSwipe`，连续相邻的滑动可共用一个 Trace，包含相邻的上下滑动调用 |
| 点击 | 仅在有明确 Activity 切换依据时采集 `AppClick`；同 Activity 内页面、Tab 或面板变化不因此采集 |
| 输入、单纯等待、普通选择/发送、偶发弹窗处理 | 样例通常不单独采集；不能仅因有 action 就包 Trace |
| 需要准备页面的辅助滑动 | 有不采集的样例，需与业务采集场景区分 |

用户已确认：部分样例较老，点击采集口径后来收紧为仅 Activity 切换。旧脚本用于核对接口及写法，不用于扩大现行采集范围。

当前服务端 Profile 要求 `activity_changed=true` 才采集点击，符合现行规则，应保留。现有 IR 构造把“缺少前后 Activity”也编码成 false，混合了不变与未知；若后续优化证据表达，应保持有明确变化依据才采集，不能将未知推测为变化。

Trace 原则上按单个动作采集：不因操作属于同一 step，就把启动、点击、输入、返回等多个动作整体包在一个 Trace 中。连续相邻滑动是用户确认的例外，可在一个 Trace 内执行一组滑动。采集规则属于框架 Profile，不要求第二阶段模型额外输出 Trace 分类。

依据：[微信 Tab 与页面转换](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_15_wechat_multi_scenario.py:99)、[Back 被标记 AppClick](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_26_bilibili.py:81)、[普通选择与发送未采集](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_35_yoyo.py:34)、[系统多任务场景](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_16_multi_task_swipe.py:10)、[服务端 Activity 标记](D:/dev/projects/ai_test/src/atestservice/script_generation/ir_builder.py:35)。

## 4. Trace 范围和等待规则目前不完整

实际用例普遍在 Trace 块内执行动作后，再保留短暂等待以覆盖动画。现有 Profile 只要求包住实际操作，其示例没有收尾等待，可能让生成代码在动作调用返回时立即停止采集。

建议区分三类时间：

1. 用户要求的等待/观看：来自 IR，保留原值、位置，不能被页面等待或默认延迟替换。
2. 页面就绪等待：使用有依据的页面条件及超时，不能借此增加新的业务预期。
3. 动画采集收尾时间：属于框架采集策略，应明确哪些场景需要、时长如何决定、放在 Trace 块内；不能照抄样例中的任意 1～3 秒为所有动作统一加等待。

`self.step` 放在 Trace 外，避免步骤截图进入采集区间。默认在采集结束后做业务断言和弹窗处理，防止轮询、CV、额外操作污染动作采集。`collect` 默认 `delete_on_error=True`，把业务断言放在块内还可能在断言失败时删除 Trace。不得生成嵌套 Trace 块，同一设备已有活跃 Trace 时框架会拒绝再次启动。

连续相邻滑动可以共享 Trace，方向不必相同，原有滑动次数与间隔保持不变；不能为了共享 Trace 而重排动作。点击、输入、导航或验证等其他动作会中断滑动组，不跨验证锚点、条件边界或用户循环边界合并。单次 swipe(times=N) 是一次批量动作，共用一个 Trace；同一组连续 swipe 调用也可共用一个 Trace。编号按实际 Trace 块递增，不按内部滑动次数递增。

依据：[搜索场景采集时序](D:/dev/projects/test_framework-agent/tests/dynamic_pnm/test_19_douyin_search.py:28)、[collect 异常行为](D:/dev/projects/test_framework-agent/src/exfw/aw/trace/collector.py:395)。

## 5. 操作与定位接口清单不完整

- 当前 Profile 的像素滑动示例 `start=(100, 800)` 与服务端 IR 统一 0～1 坐标的约定不一致。应统一示例和文字，直接传 IR 的比例坐标，不二次缩放。
- 框架已有 `open_multitask`、`open_control`、`open_notification`、`drag`，需要补全签名与映射，避免代码生成因为“Profile 未列出”而输出无谓 TODO。
- `click`、`double_click`、`long_click` 支持 `obj`；`find_element` 返回 UiObject 或 None。现有 Profile 没有完整列出这些能力。
- 普通点击包装器不直接接收 `within`、`index`。应核对并明确可使用的 UiObject 定位接口后，再规定区域和序号的实现方式；不能把 IR 的属性直接作为不存在的包装器参数传入，也不能丢掉作用域限制。
- `stop_app` 接受的是包名，按名称的启动入口使用的是应用显示名；用户明确停止某应用时不能把名称当包名，省略包名只适用于已确认应停止当前前台应用的情况。
- 基于图像的模板/OCR接口需要资源或明确输入依据，不能从少量样例中推导出可随意调用的兜底策略。

依据：[定位和点击接口](D:/dev/projects/test_framework-agent/src/exfw/aw/device/adb/action.py:182)、[滑动实现](D:/dev/projects/test_framework-agent/src/exfw/aw/device/adb/action.py:337)。

## 6. 验证、弹窗与示例需要对齐

- 明确验证实现范围：存在/不存在、文本/数值读取、数量变化各允许哪些真实 API，缺少能力时保留 TODO 和 notes。
- `page_waiter` 返回 bool，需要让等待失败导致用例失败时必须断言；不能误把普通返回值当已验证通过。
- `wait_ui` 支持的字段与 `click` 并不完全一致，不能机械复用 selector。列表条件表示全部满足。
- watcher 有“检测对象”和“操作目标”之分；需要说明 `action.target`、back、正则匹配和 CV 的规则。`cv=False` 不会阻止显式 watcher 的 `action.type=cv`，它控制的是未命中时的 CV 兜底。
- 偶发环境弹窗守护与用户明确要求点击确认的业务动作需要保持区别，不能自动把后者变成可选。
- 示例中的首页断言只适用于 IR 中存在该验证或已明确允许的页面就绪检查，不意味着每次启动后都额外生成“首页”业务断言。

依据：[页面等待](D:/dev/projects/test_framework-agent/src/exfw/models/dynamic/services/page_verify.py:68)、[弹窗处理优先级](D:/dev/projects/test_framework-agent/src/exfw/models/dynamic/services/popup_handler.py:23)。

## 7. 建议实施顺序

1. 先重写框架 Profile：简短命名、循环内唯一 Trace 名、真实 API、统一坐标、等待类型、采集边界和示例。
2. 保留 AppClick 仅采 Activity 切换的现行口径；细化一动作一 Trace、连续滑动可合并的规则及循环命名示例。
3. 通用 codegen 提示词只保留 IR 顺序、条件、循环、验证和不虚构能力等规则，框架细节集中在 Profile。
4. 添加少量静态检查：循环体固定 Trace 名、同作用域重复名、非法 API/参数等可确定问题。保留现有语法检查；收集检查仅在框架依赖可用的离线环境中进行，不导入用例执行手机操作。

样例采用启动、普通点击/输入、滑动、条件处理、内部循环和循环外验证等最小组合，优先覆盖模型容易误写的边界，不复制整份真实长用例。Profile 的示例必须与正文规则一致。

## 8. 本次落实范围

已更新服务侧 agent_case_profile.md 和通用 codegen.md：简短命名、每动作采集与连续滑动例外、Activity切换点击规则、内部循环动态编号、采集收尾默认值、IR等待保留、真实操作/定位/读取接口、统一比例坐标，以及验证和 watcher 边界。循环示例改为运行时递增名称。当前采集收尾默认值为启动/退出/Activity切换点击2秒、滑动组结束1秒，后续可根据实际采集效果调整本 Profile。

本次未修改框架工程、第一二阶段、IR结构或生产生成后的校验逻辑；第7节的静态检查增强仍是后续建议，不表示已经实现。区域查找及读取能力已对照框架实际安装的 uiautomator2 接口核对。
