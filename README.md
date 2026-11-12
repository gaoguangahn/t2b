# ATestService

根据用户描述探索手机操作，并生成 Python 用例脚本。手机能力由已连接的 VS Code 插件提供。

## 运行

```powershell
# 在下述两份本地 INI 中填写配置后启动。
uv sync --locked
uv run atestservice
```

只使用两份本地 INI：服务端配置在 `src/atestservice/config.ini`，模型配置在 `src/atestservice/llm/models.ini`。两份配置被 Git 忽略，仓库不附带个人配置，换机器时自行复制或创建。模型配置可写多个节，通过 `[models]` 的 `default` 选择默认模型；修改后重启服务即可，不需要环境变量或 `.env`。直接启动和 PM2 启动都读取同一份 INI。离线检查不需要连接真实模型或手机，也没有新增测试框架依赖。

模型节可通过 `extra_body` 配置接口专用参数，值必须是 JSON 对象，例如 `extra_body = {"enable_thinking": false}`。支持嵌套对象；不填写时使用空对象，不额外发送参数。布尔值使用 JSON 的 `true` / `false`，字段名使用双引号，值后不要追加行尾注释。配置只应用于所属模型，修改后重启服务，具体参数以该模型接口或网关支持情况为准。

模型输出在发送前统一生成并校验严格 Schema；prepare 使用独立的 CaseExtraction 协议，只整理描述与结构，再转换为 CaseSpec，不提前提取参数。工具和实际参数由探索阶段决定，HTTP 接口不变。正常/debug 输出、三阶段模型调用和探索工具均经过相同的 Schema 边界，详见 [模型交互检查说明](docs/llm_schema_contracts.md)。

## 当前链路

1. 整理用户输入为 CaseSpec，从同一结构渲染有序确认稿。
2. 用户确认后，按业务目标块逐块探索。每块只执行一轮，轮内指令按顺序完成。
3. 在验证锚点保存页面证据，不执行业务断言。
4. 审查动作、选择定位、组装 IR，按框架 profile 生成代码。repeat 仅控制整块代码的重复次数。

用户预期不会被实际观察改写。循环内部验证跟随循环体，循环外验证保持在外。模型声明完成操作并不代表业务测试通过。

## 目录

```text
src/atestservice/
  contracts/          共享用例、动作、观测和探索结果
  case_preparation/   描述解析、校验与确认稿
  exploration/        单轮目标块执行、工具、指令进度和页面采集
  script_generation/  审查、定位、IR、框架 profile 与代码生成
  workflow/           阶段编排及序列化图状态
  runtime/            事件接口、展示 payload、快照存取
  device/             设备客户端协议
  ui/                 坐标与控件候选算法
  llm/                模型客户端、消息适配与配置
  plugin/             VS Code 插件 WS、会话与设备接口实现
  runs/               HTTP、任务生命周期和持久化
  main.py             应用装配
```

核心阶段通过设备协议访问插件，通过事件接口报告详细进度；事件发布器在图节点装配时注入，不进入图的持久化状态。现有 HTTP/WS 主体保持不变。

### 单用例整理接口

`POST /api/v1/runs/prepare` 只接收一个用例：

```json
{"pluginSessionId": "ps_...", "input": "启动应用，搜索手机并返回首页"}
```

返回一个草稿对象：

```json
{"title": "搜索流程", "editableText": "用户可编辑的有序确认稿"}
```

批量 `inputs/cases` 和 `caseId` 已移除；旧批量请求返回 422。插件需将请求 `inputs[]` 改成 `input`，直接读取响应的 `title/ editableText`，不再读取 `cases[0]`。整理事件节点改为 `prepare_case`，产物为 `prepared_case.json`，内容是单个对象。创建 Run 的接口保持不变。

`CasePreparationService` 负责单个草稿和进度事件，`CaseParser` 负责提示词与模型解析；执行前的 `StructureCaseNode` 复用同一个 parser。解析提示词位于 `case_preparation/prompts/parse_case.md`，模型仍参与整理。

## 关键结构

CaseSpec 包含 steps 与 verifications。step 保留 goal、repeat 和有序 instructions；verification 使用 anchor(step_id、可选 instruction_id、before/after) 和 scope(each_iteration/outside_repeat)。instruction 只有 id、text、kind；用户指定的原文、次数、时长等完整保留在 text，实际调用参数记录在 operations[].action.args。

探索记录使用 semantic_ref.step_id/instruction_id 关联用户操作。CompleteInstruction 报告指令完成，CompleteStep 报告单轮目标块完成。探索状态为 completed/blocked/error，外层任务生命周期仍由 Run 管理。

正常返回的探索结果保存为 `data/debug_snapshots/<runId>/snapshot.json` 与截图文件。正式 bundle 包含版本、CaseSpec 和 ExplorationResult。动作执行后截图失败仍保留动作；命令结果未知时停止当前块以避免重复提交。

## 离线检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests tools
```

测试使用假模型与假设备，覆盖字面值、引用校验、单轮执行、验证锚点、循环 IR、异常记录、完整图与事件、快照往返。

显式调用真实模型的离线生成工具：

```powershell
.\.venv\Scripts\python.exe tools/probes/script_gen_probe.py <run_id_or_snapshot_directory>
```

此工具与生产路径共用 pipeline.generate_script，读取正式 ExplorationBundle，输出 generation.json 和可选脚本；代码做 Python 语法检查。

## 当前边界

尚未完成真实模型和手机联调。当前页面等待仍以固定延时为基础；组合采集、实际手势完成数量、命令结果查询需要插件配合。快照在探索节点正常返回（含阻塞结果）后保存，进程崩溃或节点中途取消仍主要依赖已持久化的进度事件，尚非逐动作恢复系统。

草稿暂不持久化，用户确认后会再次解析。第一阶段 source_units/issues 与真实定位效果评估尚未完整落地，不能将当前实现视为所有设计增强项已经完成。

设计与执行状态见 `docs/stage_1_2_design.md`、`docs/stage_1_2_refactor_map.md`、`docs/stage_1_2_prompt_design.md`、`docs/refactor_execution_checklist.md`。旧规划描述的是历史实现，以当前清单为准。

## Explore 本轮更新

- 模型使用状态式上下文：单轮任务、明确指令、完成游标、近期动作和最近结果、当前截图，不回灌 assistant/tool 历史。
- Observe 是额外采集控制；默认动作后自动观察，额外观察不生成 operation，连续观察与等待有预算。
- Instruction.kind 表达语义类别，exploration/policy.py 在下发前约束规定方法；强制方法未成功执行不能报告完成。探索模型依据完整描述填写实际参数，工具类型校验和调用账本继续保留，不依赖预提取参数表。
- 手机动作可用 complete_current_instruction=true 表示当前指令在动作前已完成，本动作属于紧邻的下一条；先校验下一条存在、当前规定方法已完成和下一动作合法，再保存边界并推进。当前指令仍需操作时为false，最后一条动作不得为true，完成后用CompleteStep结束。可单独使用CompleteInstruction，不增加独立模型复核调用。
- 过期刷新在模型决策前进行，不再仅因推理耗时超过 30 秒持续拒绝动作。
- progress.py 管理指令游标，checkpoints.py 绑定验证证据；轨迹使用 OperationRecord 并校验页面引用和顺序。
- 第三阶段保留失败动作作上下文，形成可追溯的动作计划，可按需读取已有完整观察；删除后检查 UI 衔接、指令覆盖与验证边界。证据不足返回 blocked，UI 相同不证明业务状态等价。

尚待增强：真实计数与对象引用账本、按页面状态等待、全局背景的精细提取、轨迹与返回值的进一步去重、动态定位评估。Run 返回只保留 explorationResult.trajectory，已删除顶层 trajectory 镜像和空 executionPlan；插件读取点需同步调整。未进行真实模型/手机效果验证。

## Explore 类型与模块归属

- workflow/state.py 描述跨阶段交接；workflow/initialize.py 初始化工作流。
- exploration/_runtime.py 仅供探索实现使用，区分 ExplorationInput、StepLoopUpdate、ExplorationUpdate；它不是持久化契约或跨阶段 state。
- exploration/context/rendering.py 负责当前任务、前序结果及动作摘要渲染；message_context.py 组装模型消息，已删除无效的历史窗口参数与 append_turn 接口。
- contracts/exploration.py 使用具体的语义引用、页面转换、动作意图、动作、执行结果、观测和指令结果模型。只有原始 debug 及 UI 扩展数据保留开放 JSON。
- contracts/execution.py 统一 execution.status，插件旧 success/executed/execution_status 在边界归一化；模型反馈中的 success 只是派生视图。
- step_results 是步骤完成事实的唯一来源；不再存储 completed_steps、重复 operation_ids 或无效当前步骤下标。验证只序列化 anchor.step_id，旧 step_id 输入在入口转换。

接口变化：Run 结果读取 explorationResult.trajectory；操作结果读取 execution.status（pending/succeeded/failed/unknown）。不要继续读取顶层 trajectory、executionPlan 或持久化的 execution.success。

## 稳定路径提示词

探索规则正文位于 exploration/prompts/operate_step.md，explore.py 注入与程序校验共用的方法规则。第一阶段只识别操作语义，工具说明负责局部参数，任务消息提供当前要求与真实进度；不把方法选择规则、原值、完成条件等稳定性要求当作无关信息删掉。

上下文现在包含实际请求参数、完整次数与时长账本和可用前台信息。请求量、命令状态、设备报告量分别呈现；仅靠最近六条 reason 不足以维持参数进度。当前有对应离线回归，仍未进行真实模型/手机效果评估。

## 第三阶段当前实现

二阶段输出结构不变，只细化 reason。第三阶段为动作计划、共用目标解析、类型化 IR 和框架编码。点击通过区域重叠/邻近及语义选目标，再用稳定属性和所属区域消歧。验证在原锚点结合相关操作前后控件，选择状态属性、等价UI特征或文本/数量等方式；动态展示值不直接作为控件身份，验证预期不因现场结果改写。详见 [目标解析说明](docs/target_resolution_current.md)。

Run 的 result 包含 status（ready/draft/blocked）、plan、可选 ir/script。script.filename/content/notes 保持可用，读取 IR 的插件需适配新结构。坐标限制和 TODO 输出 draft，路径证据不足输出 blocked 并保留问题；外层 Run 不误报完成。

分层、结构、旧实现清理、回归与限制见 [第三阶段当前说明](docs/script_generation_current.md)。
