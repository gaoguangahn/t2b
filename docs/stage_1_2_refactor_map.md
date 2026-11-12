# 前两阶段重构清单：数据契约、状态与目录

历史迁移建议。当前代码与完成情况见 exploration_workflow_current.md、script_generation_current.md。

日期：2026-11-11。本文是重构建议，不表示代码已经改动。

沿用已确认的执行语义：每个目标块 step 只探索一遍，repeat 仅用于第三阶段生成循环；探索不执行业务验证。本文细化 `stage_1_2_design.md`，其中目录与迁移方案以本文为准。

提示词、工具说明和模型实际上下文的同步改造见 [提示词与上下文设计](stage_1_2_prompt_design.md)。前两阶段是主体，第三阶段同步做新契约适配，其独立效果优化后续进行。

## 1. 重构范围与依据

建议集中整理核心链路，而不是给旧 dict 继续逐个加字段。重点是把四类对象分清：

1. **阶段契约**：用例描述、探索事实、生成 IR，跨模块传递且可序列化。
2. **模型交互结构**：工具参数、模型决策、模型审查输出，只服务某次模型调用。
3. **运行时上下文**：设备客户端、模型客户端、事件发布器、当前消息历史，只在运行期间使用。
4. **接口与存储对象**：HTTP 请求、WebSocket 报文、RunRecord、SQLite 数据，负责系统接入和持久化。

同一份业务内容只保留一个权威版本。不同对象之间允许有显式映射，不允许各层各自猜字段。

当前可确认的问题：

- CaseSpec 定义在 `agent/case_preparation/structure_cases.py` 这个解析节点内，但执行和生成都依赖它。
- 新执行侧写 `steps/verifications` 和 `semantic_ref.step_id`，生成侧仍有多处读取 `operation_steps/verification_steps/operation_step_id`。
- `MobileAgentState` 混合 request、模型进度、轨迹、run、result 和 event_publisher；多数值是宽泛 dict。
- `loop_node.py` 返回 `current_step_result`，但共享 TypedDict 未声明该字段；目前它由外层直接函数调用读取，说明内部返回值和图状态的边界尚未分开。
- `completed_steps` 和 `step_results` 保存重叠信息，`script_candidate` 与 `execution.success` 重复；`trace_role` 当前固定写 normal，不能充当已经完成的路径审查结论。
- 核心解析、执行、生成代码 import `runs.event_publisher` 中的 `json_event/python_event`，直接构造插件展示格式。
- `execution_plan.py` 仍保留旧版 repeat 展开和 sample_once；当前主图已不调用它。旧 `progress_summary.py` 仍读取旧字段，现有 loop 使用的是另一套 step_context。
- `utils/__init__.py` 和 `utils/targets.py` 均定义控件召回实现，入口文件承载了整段算法。
- `observations/media.py` 同时做图片消息适配和轨迹摘要，混合了不同职责，摘要还读取旧语义字段。
- 快照读写在 `src/atestservice/tests/snapshot_io.py`，但阶段交接和离线调试需要长期依赖这项能力。
- `RunService` 接收 agent_config，但 runner 内部重新创建配置，当前链路未把这份配置传下去。配置注入需要统一。

## 2. 数据结构的具体调整

### 2.1 CaseSpec / CaseStep / CaseVerification：保留核心语义，重定义公共契约

从解析节点中提取到 `contracts/case.py`，跨阶段统一使用。

```text
CaseSpec
  schema_version
  case_name
  case_goal?                 可选摘要，不作为执行参数来源
  source_revision
  source_units[]
  steps: list[CaseStep]
  verifications: list[VerificationSpec]
  issues: list[PreparationIssue]

CaseStep
  id
  goal                       一轮目标，不包含 repeat 指令
  repeat                     >=1，仅供代码生成使用
  instructions: list[Instruction]
  source_refs[]

Instruction
  id, text
  parameters                 显式参数，按支持的指令参数类型校验
  source_refs[]

VerificationSpec
  id, goal
  anchor: VerificationAnchor
  scope: each_iteration | outside_repeat
  source_refs[]

VerificationAnchor
  step_id
  instruction_id?            为空时是整块边界
  position: before | after
```

业务对象由 Pydantic 校验，使用具体子模型；不要用 `dict[str, Any]` 掩盖协议。原始供应商响应、原始插件参数、不同扩展的未知元数据可以保留受约束的 JSON 字段。

Instruction 记录用户明确要求，不预先展开成 Click/InputText。普通块可只有一条指令；循环内有中间验证时必须能锚定内部指令，不能只保存一个不可定位的长 goal。

来源信息属于本次确认稿，原始输入另留审计。对用户编辑过的内容，不从旧版本恢复已被主动删除的指令。

### 2.2 PreparedTestCaseDraft / PreparedTestCase：合并业务内容，保留展示映射

目前草稿是 operation_steps/verification_steps 两个字符串数组，确认稿是 editable_text，之后又生成 CaseSpec。

建议业务层使用 `PreparedCase(case_id, revision, case_spec)`；editable_text 是从 case_spec 渲染出的展示值。HTTP 响应可以继续返回 `caseId/title/editableText`，由接口映射生成，不要求插件立即改协议。

若需要用户未修改时直接复用草稿，再引入草稿存储、draft_id 和版本校验。不在第一批仅为减少一次调用而引入未配套的草稿 ID。

LLM 的解析输出模型留在 `case_preparation/llm_schemas.py`，只包含模型负责的语义字段。schema_version、revision、运行 ID 和采集时间由程序填写。可以复用契约中的语义子模型，不复制出另一套同义业务 schema。

### 2.3 ExecutionPlan：取消旧循环展开，收缩为执行视图

每个 step 只执行一次后，旧版展开器、repeat_context、source_path 和 strategy=sample_once 都没有继续存在的必要。

不需要为简单顺序再建立一套可编辑、可持久化的语义模型。编译结果可以是内部 `ExecutionView`：

```text
case_revision
step_ids_in_order[]
instructions_by_step
checkpoints_by_boundary
```

它是从 CaseSpec 派生的索引和运行视图，不修改 CaseSpec，不拥有另一份 repeat 值，不进入图状态反复复制。提供 `compile_execution_view(case_spec)` 即可，除非将来确有恢复运行需求，否则无需独立落盘。

### 2.4 ResolvedAction / ActionArgs：复用动作能力，明确执行边界

目前 ResolvedAction 仍包含 0–1000 的 bounds/start/end，插件收到的则是转换后的坐标。名称容易让人误认为已是最终插件参数。

建议公共动作叫 `DeviceAction`，放在 `contracts/device.py`。优先逐步使用按 action 类型区分的参数模型，例如 ClickAction、InputTextAction、SwipeAction、WaitAction；减少一个 ActionArgs 容纳所有可空字段的情况。

- 模型工具参数：放 `exploration/tools/schemas.py`，包含 reason、指令引用等模型字段。
- DeviceAction：记录规范化的执行意图，有明确坐标空间。
- DispatchInfo：记录实际 command_id 与下发参数，保留插件边界的真实执行信息。
- ActionOutcome：统一 `pending/succeeded/failed/unknown`、错误类别、实际完成数量。

不把这四种对象合成一份大工具参数。现有坐标转换、动作白名单和插件方法可以继续复用。

### 2.5 DeviceObservation / OperationRecord：保留事实骨架，补证据完整性

Observation 提取到 `contracts/device.py`，采集实现归探索阶段；新增时间、截图实际尺寸/旋转、采集质量、资源引用。

OperationRecord 放 `contracts/exploration.py`：

```text
id, sequence
semantic_ref: {step_id, instruction_id?, step_instance_id}
before_observation_id
after_observation_id?
intent: {tool_name, reason}
requested_action: DeviceAction
dispatch: DispatchInfo?
outcome: ActionOutcome
debug_ref?
```

执行前登记 pending，执行后补结果。观测失败允许 after 引用缺失并记录原因，不能丢掉已经执行的动作。

移除事实层中的 script_candidate，停止把默认 trace_role 当作业务结论。必要的角色判断保存为独立 ActionAssessment。失败动作和未知结果仍在原始轨迹中，不能在进入路径审查前机械清除所有上下文。

截图正文不重复放到每个事件和结果 JSON 中。使用 ArtifactRef，运行时由 ArtifactStore 解析成图片；当前内存里的 base64 可作为过渡实现。不能只换成插件本地文件名，却没有可读取内容的存取机制。

### 2.6 StepResult / InstructionProgress / VerificationCheckpoint：补齐当前缺失结构

`StepResult` 是完成一个块后交给外层的稳定结果；`InstructionProgress` 是块内运行进度；二者职责不同。

```text
StepResult
  step_id, step_instance_id
  status: completed | blocked | error
  summary
  operation_ids[]
  start_observation_id, end_observation_id?
  instruction_results[]
  limitations[]

VerificationCheckpoint
  verification_id
  anchor, step_instance_id
  observation_ids[], primary_observation_id?
  capture_status: captured | unavailable
  limitations[]
```

completed 表示单轮操作已探索完成，不表示 repeat 轮次已执行，也不表示测试通过。VerificationCheckpoint 只绑定证据，没有业务断言的 passed/failed 字段。

移除手工维护的第二份 completed_steps；给模型看的历史块摘要从 step_results 派生。块内指令账本在运行期维护，结束时产生 instruction_results，避免两份可独立修改的事实。

### 2.7 MobileAgentState / run / result：缩小共享状态，分离运行上下文

建议把图状态收缩为：

```text
WorkflowState（TypedDict，图层专用）
  request: GenerationRequest
  case_spec: CaseSpec?
  exploration_result: ExplorationResult?
  generation_result: GenerationResult?
```

Graph node 包装各阶段服务；阶段内部普通函数返回自己的类型，不再把所有更新都伪装成 MobileAgentState。

```text
ExecutionContext（运行期依赖，不序列化）
  device_client, llm, event_sink, artifact_store, config, run_id

ExplorationRuntime（探索阶段内部，不直接返回插件）
  current_step, instruction_progress
  message_history, budgets
  trajectory_builder, completed_step_results
```

current_step、current_step_index 和 current_step_result 不再成为整个三阶段共享状态。事件发布器从可序列化状态移出，在组装节点时注入。TypedDict 仅描述图状态，不能替代运行时校验；进入图前和阶段返回处校验 Pydantic 契约。

外部 RunStatus 保留任务生命周期。ActionOutcome 是单命令结果，StepResult 是单块探索结果，ExplorationResult 是整个探索结果，GenerationResult 是脚本生成结果。分别命名并显式映射，避免多个不同语义的 RunStatus 和 run dict 互相覆盖。

### 2.8 ExplorationResult / ExplorationBundle：正式定义阶段交接物

`ExplorationResult` 包括 trajectory、step_results、verification_checkpoints、target_evidence、assessments、coverage、limitations 和探索状态。

`ExplorationBundle(schema_version, case_spec, exploration_result)` 是可导出的完整离线产物。工作流内不用再把同一 CaseSpec 同时嵌进 result、run 和 trajectory，导出时组合一次即可。

第三阶段的入口改为 `generate_script(case_spec, exploration_result, profile)`。离线调试先读 bundle，再调用同一入口。不要继续让生产生成函数依赖含任意字段的 snapshot state。

## 3. 建议目标目录

三阶段直接成为业务目录，共享数据与基础能力各有明确位置。无需为了重构再增加完整的多层企业架构。

```text
src/atestservice/
  contracts/                 跨阶段公共数据，无框架/插件/数据库依赖
    case.py
    device.py
    exploration.py
    generation.py

  case_preparation/          阶段一
    service.py              整理、校验、确认稿编排
    parser.py               模型解析
    llm_schemas.py          解析模型的输入输出
    validation.py
    rendering.py
    prompts/

  exploration/              阶段二
    service.py              每个 step 执行一次
    step_runner.py          一个目标块内的闭环
    execution_view.py       指令/检查点索引
    observation.py          页面采集与一致性
    trajectory.py           事实登记、动作执行前后补齐
    progress.py             指令进度与次数账本
    checkpoints.py
    context.py              消息裁剪与任务渲染
    tools/                  工具 schema、决策解析、动作执行
    prompts/

  script_generation/        阶段三，继续复用现有生成能力
    service.py
    projection.py
    review.py
    locator.py
    ir_builder.py
    codegen.py
    llm_schemas.py
    prompts/
    profiles/

  workflow/                 仅负责串联三阶段
    runner.py
    graph.py
    state.py

  runtime/                  运行依赖和产物能力
    context.py
    events.py               进度事件协议，不包含插件 UI blocks
    artifacts.py            产物、快照导入导出

  device/                   核心阶段依赖的最小设备接口
    client.py               DeviceClient 协议

  ui/                       探索和生成共用的 UI 算法
    coordinates.py
    targets.py

  llm/                      模型客户端、消息/图片消息适配、模型配置
  plugin/                   设备接口的插件实现、WS 会话、协议、展示映射
  runs/                     Run 生命周期、HTTP DTO、存储与事件分发
  main.py                   装配依赖
  config.py
  auth.py

tests/                      自动化测试与固定样本
tools/probes/               显式调用真实模型的离线调试工具
```

这些是职责落点，不要求机械地每行建立一个文件；小规模功能可以合并。关键是模型、事件和设备访问都通过明确接口传入，避免业务模块反向依赖 runs/plugin 的具体实现。

`agent/` 当前同时包含解析、执行、生成和基础设施，名称难以体现三阶段，建议最终拆开并消除旧目录，而不是长期保留两棵同义目录。

## 4. 依赖方向和事件边界

```text
HTTP / 插件接入 → RunService → Workflow
                                ↓
                       三个阶段的 service
                                ↓
               contracts + LLM/设备接口/事件接口

PluginActionClient 实现设备接口
Run 事件适配器实现事件接口，并做持久化/插件推送
main.py 负责注入这些实现
```

核心阶段可以发出“观察完成”“动作已执行”“块已完成”等语义事件，携带对象或产物引用。Run/Plugin 适配器再转成现有 `node_finished/blocks/screenshotName` 报文。这样插件现有展示协议可以保留，而核心执行不再 import runs.event_publisher 的 UI 构造函数。

事件详细程度必须保留：每次模型动作选择及简短原因、执行开始/结果、新页面、指令进度、检查点、恢复/重试、阻塞和阶段产物都应让插件可见。事件由执行模块在实际发生处主动发布，publisher 负责统一封装、存储和推送；可继续沿用 node_started/node_finished/node_failed，不要求为了分层重写全部协议。完整事件信息和喂给模型的精简上下文分别组织，不能把“模型只需少量信息”误解为“插件也只展示少量信息”。

LLM 图片适配放 llm，不放观察契约中；动作摘要放 exploration/context，不放 media 工具里。ui.targets 只保留一份实现，包 __init__ 仅按需导出符号。

## 5. 哪些可以保留，哪些应该替换或退出

| 当前内容 | 处理 |
| --- | --- |
| 插件 WS 注册、请求关联、会话管理 | 保留主要实现；补类型映射和必要结果信息 |
| PluginActionClient 的手机基础方法 | 保留，并让它适配 DeviceClient 接口 |
| LLM 客户端与 MessageBuilder | 保留主要实现，移动到共享位置，统一注入配置 |
| 坐标转换、控件几何召回 | 保留算法，归 ui，合并重复实现 |
| CaseStepRunnerNode | 保留逐块一次的思想，业务逻辑移为 exploration.service；图包装留 workflow |
| ExploreAgentLoopNode | 保留单块闭环，拆出轨迹、进度、检查点、消息构造，不在一个方法里完成所有职责 |
| StructureCasesNode 内业务模型 | 提取至 contracts；模型解析移 parser；节点仅作图适配 |
| 旧 execution_plan.py 的展开器 | 退出主实现；无真实调用后删除，不保留备用采样入口 |
| 旧 progress_summary.py / media.summarize_operations | 核查调用后删除或替换，只有一套当前语义的进度渲染 |
| script_candidate / 默认 trace_role | 从原始轨迹退出；需要的判断进入派生 assessment |
| src/atestservice/tests/snapshot_io.py | IO 能力归 runtime.artifacts；测试使用它，不反过来让业务依赖 tests |
| script_gen_probe.py | 归 tools/probes，并读取正式 bundle |
| RunRecord / SQLiteRepository | 主体保留，结果 JSON 加版本和明确结构；无需为改内部字段立即重建所有表 |
| codegen profile 与代码生成能力 | 保留；输入换成新 IR/交付物，统一步骤与验证字段 |

公共 IR 不能永远是无校验 dict。第三阶段消费新契约时，应同步定义 ScriptIR、步骤分组、action/verify 节点和 repeat 字段的类型，确保整组动作与循环内验证一起重复；无需在前两阶段实现一套新的测试执行框架。

## 6. 实施顺序与兼容范围

1. **定契约**：建立 contracts 与固定样本，统一 step_id、instruction_id、验证 anchor/scope、repeat 和各类状态。补能证明“单轮探索→循环生成”的契约检查。
2. **换数据流**：在现目录里先让第一、二、三阶段共同消费新结构，移除重复字段和跨层猜测；执行业务方法返回自己的结果，不再到处传整个图状态。
3. **抽边界**：注入设备、LLM、事件、配置；核心阶段退出插件展示格式，快照正式化。此时重点确保失败/停止也保留已有证据。
4. **移动模块并清理**：按目标目录移动代码和 prompts，更新 import、包导出、入口和 probe；核查后删除旧实现与重复工具。同步更新 README 和旧规划文档的适用状态。
5. **增强探索**：逐项接入有界观察、unknown 命令结果、内部检查点、定位证据等，使用固定快照和假设备验证后再连手机。

这些是提交/验证批次，不代表第一批后的功能可以长期处于新旧字段不兼容状态。开始迁移消费方之前，先提供可运行的端到端样本；实际切换应成对覆盖生产者与消费者。

HTTP/WS 协议可先保留，内部数据模型集中更新。历史快照有明确需求时提供单独 legacy importer，在入口转换一次；位置已经丢失的验证不能靠兼容层凭空补齐。内部不长期保留 `new_field or old_field` 分支。

本阶段不默认增加对旧 Python import 路径的兼容承诺，也不要求维持无人使用的旧中间 JSON；若插件确实读取旧轨迹字段，应先核查插件消费点并版本化切换，不能仅凭本仓库假定兼容。

## 7. 重构完成的判断

- CaseSpec、DeviceAction、Observation、OperationRecord 各只有一个权威定义。
- 第一阶段确认稿不会丢验证顺序，字面参数不改写。
- repeat 不进入探索次数控制；生成器正确重复整个块与循环内验证。
- 块内验证在指定指令完成后绑定观察，不执行业务断言。
- 核心阶段不 import runs 的插件展示 helper，不要求持有具体 PluginSessionManager。
- 图状态只描述阶段交接；运行依赖和消息历史可替换，不写入快照。
- 原始动作事实、模型判断和最终 IR 可以区分，并能追溯来源。
- 不再依赖 tests 中的代码完成生产交付或离线读取。
- 不存在主链路不消费却仍暴露为当前能力的旧 plan/summary；控件召回只保留一份实现。
- 同一 bundle 可以从文件读取后直接进入第三阶段，不必重新探索手机。
