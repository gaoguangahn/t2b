# 当前第二阶段工作流与交付数据

依据：当前代码实现。本文区分实际行为和未完成能力，不以历史设计稿替代实现。

## 1. 入口和职责

完整图：initialize → build_case_spec → run_case_steps → generate_script。没有操作时跳过生成；探索返回失败状态时结束，不进入脚本生成。

第二阶段入口是 exploration/case_step_runner.py 的 CaseStepRunnerNode。输入是已确认文本解析后的 CaseSpec、设备能力、模型客户端、配置和事件发布器。

第二阶段负责实现操作并保留事实，不执行业务断言。step.repeat 不参与探索调度；用户要求的轮内手势次数和时长仍属于操作要求。

## 2. 外层目标块循环

```text
建立全局 trajectory、step_results
  → 按 CaseSpec.steps 顺序取当前块
  → 取 id、goal、instructions，不把 repeat 传入操作任务
  → 调用该块的 ExploreAgentLoopNode
  → 合并轨迹，保存 StepResult，发送插件事件
      completed → 下一个块
      blocked/error → 停止，保留已采集结果
  → 全部完成 → 校验 ExplorationResult、保存 bundle、进入第三阶段
```

一个 ExploreAgentLoopNode 实例可以服务多个块；每次调用重新创建 InstructionProgress、CheckpointRecorder 和 AgentLoopContext。模型客户端可以复用，但不向下一个块保留上一块的工具对话。

跨块延续：设备当前状态、全量轨迹和步骤结果。当前块上下文只看到最近六个前序结果摘要，而非完整前序轨迹。

## 3. 一个块内部的 agent loop

准备：

1. 获取本块有序 instructions；只有旧输入缺失时才用 goal 构造一条指令。
2. 建立指令游标，当前指令为第一条。
3. 没有 observation 时采集初始页面；否则可复用上一块出口。
4. 为块 before 和第一指令 before 的验证锚点绑定已有页面。

每轮：

```text
由真实状态重建任务消息
  → 必要时在请求前刷新过期 observation
  → 发送 system、任务状态、最新截图和工具 schema
  → 模型必须返回一个工具调用
  → 参数校验与决策事件
  → 按工具类型处理
  → 更新反馈，进入下一轮或返回 StepResult
```

工具分支：

| 分支 | 程序行为 |
| --- | --- |
| 手机动作 | 标记为false时执行当前指令；true时先校验前后两条指令与动作，再保存边界、推进并执行下一条动作；先登记 pending，再执行并自动采集新页面 |
| Observe | 检查预算，可短暂等待，新增 observation；不新增 operation |
| CompleteInstruction | 检查规定方法，绑定当前指令 after 检查点，推进游标，绑定下一条 before 检查点；不执行动作 |
| CompleteStep | 仅剩最后一条时可同时完成该指令并结束整块；全部已完成也可结束；多条尚未完成则拒绝；error 可直接结束 |
| ReportBlocker | 返回阻塞结果，外层停止后续目标块 |

方法策略：Instruction.kind 为 app_launch/app_stop/system_home/multitask 时分别要求 start_app/stop_app/home/open_multitask。方法不匹配则不下发；相应规定动作尚无成功记录时，也不能报告该指令完成。

普通 ui 指令完成由原操作 Agent 结合最新截图、实际控件状态和执行记录判断，可以随下一条手机动作报告，也可以通过独立控制工具报告。额外的完成复核模型调用及其专用协议、提示词和配置已经撤掉。

例如“关闭Wi-Fi”应从对应控件状态确认开关已关闭；不执行业务断言，也不向第三阶段声明用户验证通过。该完成判断仍依赖原Agent与页面证据，程序没有通用自然语言目标证明器，不能保证消除模型误判；控件状态缺失时不补造。

## 4. 完成标记与控制工具

只有手机动作工具接收 complete_current_instruction：false 表示动作属于当前指令；true 表示当前指令在本动作之前已完成，本动作属于紧邻的下一条指令。它不能表达动作执行后的完成预期。Observe、CompleteInstruction、CompleteStep、ReportBlocker不携带该标记，避免控制工具叠加完成语义。

true 的执行顺序：先检查存在下一条指令、当前规定方法已有成功记录、动作满足下一条的方法约束（policy.validate_action_transition），参数在工具解析时已校验；全部检查通过后，才捕获当前 after 边界、推进游标、捕获下一条 before 边界、登记并下发动作。任何校验失败均不推进、不提前记录边界、不下发动作，反馈给原 Agent 纠正。

没有下一条指令时，动作加true会被拒绝；最后一条仍需动作时用false，看到动作后页面已达到要求再CompleteStep。不能先推进到末尾再丢弃动作。下一动作下发后的实际执行失败属于下一条指令，已经合法完成的上一条不回滚；原有执行结果与恢复逻辑继续生效。

例如当前指令 i1 是搜索，下一条 i2 是返回首页：

```text
模型看到搜索后的页面
  → 调用 Back，complete_current_instruction=true，说明搜索已完成与返回目的
  → 程序记录 i1 的完成页面和验证检查点
  → 游标推进到 i2
  → 同一轮执行 Back，该动作归属 i2
  → 自动观察返回后的页面
  → 若最后一条要求已达到，调用 CompleteStep，保存 i2 和整块完成边界
```

当前指令已完成但暂时不选下一动作时，可单独CompleteInstruction。最后一条可直接通过CompleteStep完成，不必先CompleteInstruction；也支持全部先CompleteInstruction再CompleteStep。控制工具不下发给手机、不新增operation，正常快速路径每轮仍只调用一个工具，不增加独立模型请求。原有动作预算、Observe预算、方法约束和失败停止行为继续生效。

## 5. 实际发送给模型的上下文

格式是三条消息，工具 schema 单独随模型请求提供：

```text
system：固定操作规则
user：当前块任务与执行状态
user：当前 observation ID + 当前截图 + 控件状态证据
```

第二条 user 内容按当前代码包含：

- 当前块 id、单轮 goal、全部 instructions（JSON，包含 id/text/kind，不包含参数表；原值和次数完整保留在描述中）。
- 最近六个前序 step 的 id、状态、summary。
- 当前块已报告完成的指令 ID。
- 当前活动指令 ID。
- 本块最近六条手机操作的工具名、reason、实际请求参数、命令状态和消息。
- 本块全程的次数与时长账本，分别表达请求量与设备报告量。
- 最近一次执行或控制反馈 success/message。

示意文本（未逐字符模拟 JSON/Python 字典渲染）：

```text
当前操作块：step_002
单轮目标：搜索手机后返回首页
有序指令：
  i1 搜索手机，参数 text=手机
  i2 返回首页
前序实际结果：
  step_001 completed：已启动应用
已完成指令：[]
当前指令：i1
当前目标块已执行动作：
  op_0001 Click：点击搜索入口。结果：成功。
最近一次结果：已打开搜索页
```

第三条 user 带 observation ID、可用的前台 package/activity 和图片，不重复整段任务。

目前不会发送：完整原文、完整操作大纲、全部历史截图、完整 UI 树、验证预期、repeat、框架 profile、IR、事件协议和产物路径。全量数据保存在轨迹中，不代表全量进入模型上下文。

模型每轮独立决策，不在后台持续看手机。程序执行工具后，在下一次请求中把新页面与实际反馈提供给模型。没有历史 assistant/tool 消息；最近反馈由程序保存，消息文本按需生成。

## 6. observation 与 operation 的关联

通过 before_observation_id / after_observation_id 关联，不按数组位置配对。例如：

```text
obs0 → Observe → obs1 → Observe → obs2 → 点击 op0 → obs3

op0.before = obs2
op0.after  = obs3
```

Observe 不进入 operations。额外观察、没有动作的刷新和动作后采集失败都合法。轨迹校验 ID 唯一、引用存在、前后顺序，不要求 observation 数量等于 operation 数量加一。

采集内容：截图、屏幕尺寸、package/activity、UI 元素、采集时间、采集原因和限制说明。UI 树当前供保存与后续生成使用，未进入常规操作模型请求。

## 7. 完成、预算与异常

- StepResult.status 为 completed/blocked/error；completed 只表示一轮操作探索完成。
- 指令快照目前记录 completed/in_progress/pending；块失败时不会自动把当前指令改为“测试失败”。
- 单块模型轮次上限取配置或覆盖值与“指令数 × step_attempt_limit”的较大值，当前 step_attempt_limit 为 12。没有实现整用例统一 80 次的硬上限。
- 工具参数错误可以反馈修正，执行错误累计上限当前为 3；不等同于“无页面进展”的检测。
- 模型返回零个或多个工具调用时，当前直接返回 error，没有实现单独的修复轮。
- 连续 Observe 默认最多 3 次；单次最多等待 5 秒，块内请求等待累计最多 15 秒。手机动作会重置连续观察计数。
- 观察超过 30 秒时在模型请求前刷新，不因模型本次推理超过 30 秒丢弃动作。
- 命令结果 unknown：再获取页面后停止该块，避免自动重复提交。
- 动作后截图失败：保留已经登记和执行的动作，返回 blocked。

动作后等待目前仍是固定延时：启动应用 2 秒、Wait 后 0.2 秒、其他动作 1 秒。Wait 工具本身会先执行请求的等待时长。不能把这些延时理解为可靠的页面稳定检测。

## 8. 二阶段保留的数据

```text
ExplorationResult
  trajectory
    observations: DeviceObservation[]
    operations: OperationRecord[]
  step_results: StepResult[]
    step_id、status、summary
    instruction_results[]：instruction_id、status
    checkpoints[]：verification_id、observation_id、after_operation_id、capture_status
```

OperationRecord 包含：

```text
id、index
semantic_ref：step_id、instruction_id
observation_transition：before_observation_id、after_observation_id?
intent：tool_name、reason
action：type、规范化 args
execution：status、message、completed_count?
debug：原始工具调用
observation_error?
```

execution.status 统一为 pending/succeeded/failed/unknown。success 只用于模型反馈或旧插件结果的入口转换，不在正式操作执行结果中重复保存。

完整 CaseSpec 不复制进 ExplorationResult。导出时才组成 ExplorationBundle(schema_version, case_spec, exploration_result)。整体任务状态当前由外层 run 保存，并非 ExplorationResult 中另有 status。

正常生产调用会在探索节点返回后，保存到 data/debug_snapshots/<runId>/snapshot.json 和 screenshots/；失败返回也可保存。中途取消/进程崩溃尚未实现逐动作 bundle 恢复，已有进度事件仍由 Run 层保存。

## 9. 第三阶段如何使用

| 输入信息 | 用途 |
| --- | --- |
| CaseSpec.steps / instructions | 还原用户顺序、目标、描述中的原值要求及操作归属 |
| step.repeat | 将整块有效动作和循环内验证一起重复 |
| CaseSpec.verifications | 保留用户预期、anchor 与 scope |
| operations 及执行结果 | 审查有效动作、错误路径、恢复路径；失败记录也保留作上下文 |
| 操作前 observation | 结合 bounds 召回控件候选、确定定位方式 |
| 操作后 observation | 理解页面变化、activity 和 UI 路径衔接 |
| checkpoints | 找到验证位置的页面与执行边界，不执行断言 |
| step_results / instruction_results | 表达完成情况和未完成部分；细粒度覆盖校验仍需增强 |

当前第三阶段：动作计划（按需读取已有完整观察）→ 来源/路径/覆盖检查 → 点击、验证与条件共用目标解析 → 条件/循环/验证 IR → profile 代码生成。

定位读取保存的 UI，视觉模型可查看对应截图。UI 衔接不证明业务状态等价；证据不足返回 blocked 并保留问题，不移动验证或虚构路径。详见 script_generation_current.md。

## 10. 插件进度事件

每个目标块的最终结果只由外层 `case_step_finished` 发布一次，标题按实际状态区分执行完成、执行失败和遇到阻塞。结果事件包含摘要、步骤结果 JSON，以及模型结束决策 JSON（若有）；原始工具调用可在结束决策中查看。结束决策只作为事件详情传递，不加入跨阶段探索结果。

内层不再额外发布 `step_agent_loop` 结束通知，已接受的 CompleteStep / ReportBlocker 决策合入最终结果。CompleteStep 同时完成最后一条指令时也合并通知；其他指令进度、操作与观察事件继续保留。提前结束请求被拒绝时发布 `step_finish_rejected`，不会显示成步骤成功。全部目标块完成后，额外发布一次 `run_case_steps`，标题为“探索阶段完成”。现有事件封装与 blocks 格式不变。

## 11. 当前边界

- 单轮 CaseSpec、轨迹和结果已有具体类型与引用校验；内部运行视图仍允许临时字典。
- 细粒度手势实际计数、跨步骤对象记忆、自适应等待与完整定位稳定性评估尚未完成。
- 检查点当前绑定已有最新 observation，不保证在每个边界重新采集一次，也不会额外执行验证。
- 操作记录保存规范化参数，尚未完整保存插件命令 ID、真实下发像素参数等 dispatch 信息。
- 上述为实际实现说明，不代表真实模型与手机效果已经经过验证。
