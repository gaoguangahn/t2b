# 第三阶段当前实现

更新：2026-11-12。本文替代旧 mobile_script_generation_plan.md。

## 流程

```text
CaseSpec + ExplorationResult
  → 形成 ScriptPlan（可按需读取已有完整观察）
  → 校验来源、顺序、删除边界、显式参数覆盖
  → 共用目标解析：action / verification / condition
  → 确定性组装 ScriptIR：action / condition / repeat / verify
  → IR + codegen_profile → Python → 语法检查和限制说明
```

二阶段输出结构不增加字段，只细化 reason：可见依据、目的、环境处理、发现偏离后的恢复背景。原始记录不回写生成判断。探索仍每块一次，不执行业务断言，repeat 只用于代码。

## 类型与归属

正式产物位于 contracts/script.py，拒绝未知字段：

| 类型 | 职责 |
| --- | --- |
| ScriptPlan | 保留动作引用、条件分组、删除片段、问题，不复制轨迹 |
| PlannedAction | operation_id、整理描述、可选 condition_id |
| OmittedSegment | 连续原操作、删除原因、必要状态影响、边界观察引用 |
| ExecutionCondition | 通用可观察条件，不含框架 API 或弹窗特化字段 |
| GenerationIssue | 问题、来源、是否阻塞 |
| TargetResolution | 描述、定位/坐标/未解决/非UI状态、观察引用、理由和限制 |
| VerificationPlan | 验证方式、操作符、用户预期、运行时基准操作和证据来源；仅存于验证目标的 verification |
| Locator / Selector | 属性组合、所属区域、用户指定位置 |
| ScriptIR | 可编码步骤树，保留参数、循环和验证位置 |
| GenerationResult | ready/draft/blocked、plan、可选 ir/script |

```text
script_generation/evidence.py            共用只读证据索引/多模态材料
script_generation/planning/              计划、路径/来源校验、私有 LLM schema
script_generation/targeting/context.py   固定锚点、相关动作与前后控件证据
script_generation/targeting/locators.py  同一目标的属性组合、区域消歧与唯一性
script_generation/targeting/verification.py 验证策略与来源校验，不执行断言
script_generation/targeting/resolver.py  三种目标用途编排、私有 LLM schema 校验
script_generation/ir_builder.py          确定性装配
script_generation/codegen.py             框架翻译和语法检查
script_generation/pipeline.py            生产/离线共用入口
script_generation/script_gen_node.py     工作流与事件适配
script_generation/prompts/               plan.md、targets.md、codegen.md
script_generation/profiles/              框架编码描述
ui/elements.py                          属性归一化、几何和匹配
ui/spatial.py                           统一坐标的空间关系与候选排序，内部按需计算像素距离，不判断语义
runtime/artifacts.py                     正式 bundle 拆图存取
```

模型交互 schema 不进入探索契约或全局 state。依赖通过注入传递。旧 review/projection/locator/path_validation/schemas、ui/targets.py 及 review/locator 提示词已经移除。

## 路径整理

输入包含完整 CaseSpec、原动作参数/状态/reason、前后观察引用、页面摘要和 step_results/checkpoints。失败与未知先作上下文保留，不能提前过滤。reason 是意图证据，不代表结果。

模型可请求已有 ID 的完整 UI/截图，最多两轮十二帧；文本模型读取 UI，视觉模型同时读取图片。每个原操作恰好被保留或归入删除片段，保持原顺序与原值，不虚构捷径。

错误与恢复作为完整片段判断；正常多级返回和必要的“改设置→回首页”不能因页面回退而删除。程序检查边界和验证位置；UI 相同不证明业务状态等价，模型仍需说明必要状态影响，判断不清时 blocking。非闭合且缺少可靠 UI 衔接证据的删除保守阻塞，未实现自动补探索。整条指令原动作全被删除也需复核；没有原动作的纯导航要求允许无动作。

Instruction只保留id/text，已删除指令类别与规定方法映射，也删除基于类别的missing_required_action检查，不增加替代的方法合规审查。第一阶段不提取参数；描述中的原文、次数与时长继续保留，程序仍校验来源、顺序、删除边界和指令覆盖，计划模型按现有职责整理可回放路径。

## 共用目标解析

点击/双击/长按用操作前 observation；验证只用对应检查点，不能拿最终页替代；条件用组内第一个操作前的观察。

模型获得用户要求、整理说明、操作区域和已保存 UI，视觉模型附对应帧。目标选择包含候选 ID、来源帧和属性名，程序复制现场值；验证额外给出 VerificationPlan，明确如何检查原预期。位置不再要求控件包含原点击框中心：支持有意义的重叠和小幅偏移，空间关系只辅助语义判断，整页大容器和仅擦边相交不能替代原操作。

多个候选与最终定位多匹配分开处理。选中目标后，程序可补充同一节点的最小稳定属性组合；有真实 parent_id 时可尝试所属区域。用户没有明确位置要求时不固定索引；完全相同、无法稳定区分的控件仍保留坐标。几何包含不证明 UI 祖先关系，框架不支持的区域/索引不能用猜测 API 实现。

验证上下文含锚点之前最多两个相关动作、其前后控件及可确定的对应和变化；不借用锚点后的页面。直接 checked/selected/enabled、明确等价状态文案、文本、数值或完整集合数量均可成为验证方式。支持帧仅提供身份和特征来源，验证仍在原锚点检查实时状态，不声称已经通过。未保留的探索动作不能作为运行时基准。详细输入与边界见 [目标解析说明](target_resolution_current.md)。

加入点赞数量/价格/时间、hint/placeholder、搜索推荐词、序号目标随机标题的保守拒绝规则。动态 ID、状态标签等仍需模型语义判断，规则不构成长期稳定性的证明。

点击无可靠 locator 时保留坐标与限制。验证没有控件仍保留 expectation，可依据用户明确文本和框架能力实现存在/不存在；不能用观察值改预期或随意归为非UI。数量增加1需要运行时基准，不能固定快照值，框架不支持就 TODO。

## IR 和框架编码

偶发环境处理使用通用 condition，同组整体条件执行，位置不变；业务确认保持普通必做 action。没有 is_popup_handler。框架可用专用方法或等价条件逻辑；无法表达则整组 TODO 与 notes。

CaseSpec.anchor/scope 决定验证位置：整块动作、条件、each_iteration 验证一起进入 repeat.body，outside_repeat 留在外侧。VerifyNode.target.verification 保存验证策略，不在节点或全局 state 再复制一份。代码生成仅接收 IR/profile，不重新整理路径、选择 locator、改参数或预期；按策略映射框架 API，不因 wait_ui 无法读取开关属性就宣称整个框架无法验证。

## 接口、工具和事件

Run 请求及 ExplorationResult 不变；result 为 status（ready/draft/blocked）、plan、可选 ir/script。script.filename/content/notes 保持可用，读取 IR 的插件需适配新结构。坐标限制、目标缺口和框架 TODO 使结果成为 draft；blocked 无脚本，保留计划，外层 Run 为 error。draft 的生成任务可完成，但结果明确待完善。

plan_script、resolve_targets、encode_script、generate_script 事件展示计划、定位依据、限制及代码，详细探索事件不变。

生产和 tools/probes/script_gen_probe.py 共用 pipeline.generate_script。load_exploration_bundle 返回 ExplorationBundle 2.0，不再展平为旧 state；旧未版本化快照不再支持。probe 输出 generation.json 和可选脚本。

## 交付核对与限制

- [x] 二阶段输出不增加分类字段，reason 调整。
- [x] 生产者/消费者、正式 bundle、生产图与 probe 配套。
- [x] 动作取舍可追溯，原始证据不修改。
- [x] 通用条件块，业务确认保持必做。
- [x] 点击、验证与条件共用目标解析。
- [x] 类型化 IR，循环内外与指令前后验证位置回归。
- [x] ready/draft/blocked、notes、事件与外层 Run 状态配套。
- [x] 旧入口、schema、提示词和失效工具引用清理。
- [ ] 真实模型/手机验证：当前配置是占位地址和密钥，未执行。

离线测试覆盖固定证据、程序规则、消息输入与完整编排，不证明实际模型分类、框架调用或手机回放正确。完整业务状态等价、跨步骤对象绑定、未采集 UI 属性、自动补探索仍有实际限制。

模型配置使用 llm/models.ini，服务配置使用 config.ini，两份实际 INI 仅在本地维护，不入库，也不附带示例文件。回归使用标准库 unittest，无新增测试框架依赖。
