# 重构执行清单与交接状态

第三阶段当前交付清单与限制见 [script_generation_current.md](script_generation_current.md)。下文首轮勾选保留历史状态，不按旧生成流水线继续实施。

更新日期：2026-11-12。

本轮第三阶段已完成：动作计划、共用目标解析、类型化 IR、生产/离线入口统一、旧实现清理与接口/事件配套；68 个离线测试、编译和模块导入检查通过。详细交付清单与真实联调限制见 script_generation_current.md。

## 当前状态

- 用户已授权开始实施。
- 已完成项目静态审查、前两阶段设计、数据与目录重构方案、提示词设计。
- **核心链路首轮重构已实现，提示词已同步替换；仍有下列增强项未完成，不表示整份设计已全部落地。**
- 本清单用于继续实施，完成一项后更新状态和验证结果，不能把设计完成当成实现完成。
- 工作目录：`D:\dev\projects\ai_test`。现已使用 Git 管理，远程仓库为 `https://github.com/gaoguangahn/t2b.git`。
- 已在工程内安装 Python 3.11.18 和锁定依赖；使用 `.venv/Scripts/python.exe` 验证，运行环境无需依赖 Windows 的 python 占位程序。

### 本轮实施记录

已实现：共享 CaseSpec/Instruction/Anchor 与动作、观测、探索结果模型；三阶段目录归位；块内进度工具和检查点；单轮探索到整块循环 IR；新提示词与消息构造；设备协议；详细事件；图状态与事件依赖分离；配置贯通；动作先登记与 unknown 停止；观测时间与过期拒绝；bundle 拆图存取；生产与 probe 共用生成入口；生成代码语法检查。

验证：10 个离线测试通过，源码编译检查通过；FastAPI 启动、health 与 OpenAPI 检查通过；73 个模块导入检查通过。未连接真实手机，未调用真实模型，不声称已经验证实际生成质量。

仍未完整实现：source_units/issues、草稿存储与免二次解析、完整手势计数账本、按状态有界等待和恢复策略、组合观察与命令结果查询、逐动作/取消时快照、完整定位证据评分。部分需要插件提供新能力，当前保持现有插件命令可用。下面未勾选项保留为待办，不能以本轮首轮重构代替其验收。

## 已确认的约束：实施时不重新讨论

更新：用户已确认整理和生成都只处理一个用例。批量整理能力已删除；新增批量体验将由插件另行实现。CasePreparationService 和 StructureCaseNode 共用独立 CaseParser，不再由 Node 调用 Node。整理 API 的单对象协议见 README，插件需同步适配。

1. 产品是用例脚本生成服务。第一阶段整理意图，第二阶段探索手机，第三阶段生成脚本。
2. 每个目标块 step 只探索一遍；step.repeat 仅用于代码生成，不引入循环探索/采样策略。
3. 块内滑动次数、等待时长等明确参数在这一遍内完整执行。
4. 业务验证不在探索中执行；用户预期保留，验证位置在第一阶段确定，第二阶段绑定证据。
5. 循环内部验证可锚定块内 instruction；通过 scope 区分每轮验证与整个循环结束后验证。
6. event_publisher 保留详细过程展示，包括决策简述、执行开始/结果、截图、进度、恢复、阻塞和产物。
7. 以前两阶段为重构主体；第三阶段同步适配契约、repeat、验证与证据，独立效果优化另行推进。
8. prompt、工具 schema、解析器和完整上下文同步修改；只向模型提供当前职责需要的信息。
9. 复用已有手机动作、插件 WS 和模型客户端；内部结构可以重构，HTTP/WS 外部协议尽量保持。

## 设计来源及优先级

下一批 explore 优化以 [Explore 下一轮优化清单](exploration_next_iteration.md) 为当前讨论汇总。它区分已明确方向与待定细节，尚未实施；后续不能沿用首轮实现中“每条指令都必须单独完成调用”等机制而不重新审视。

- [总体设计](stage_1_2_design.md)：业务职责和探索机制。
- [重构清单](stage_1_2_refactor_map.md)：权威数据结构、目标目录和依赖边界。
- [提示词设计](stage_1_2_prompt_design.md)：模型输入、工具与上下文。
- 最新用户确认与本清单约束优先于旧规划。尤其不要重新引入 repeat body 展开或 exact/sample_once 策略。

## 执行批次

### 0. 环境与基线

- [ ] 阅读适用的 AGENTS.md；检查当前文件状态，避免覆盖用户新增修改。
- [x] 通过 uv 确认 Python 与依赖，记录可复用的检查命令。
- [ ] 确认现有 HTTP/WS 报文、插件动作参数和框架 profile 的使用位置。
- [x] 准备固定用例、假模型和假设备，确保离线验证不调用真实手机或模型。

### 1. 建立唯一公共契约

- [ ] 新建 contracts：CaseSpec、CaseStep、Instruction、VerificationSpec/Anchor。
- [ ] 定义 DeviceAction、Observation、OperationRecord、ActionOutcome。
- [x] 定义 StepResult、VerificationCheckpoint、ExplorationResult/Bundle。
- [ ] 明确模型交互 schema 与业务契约的区别；原值、引用、状态、版本有校验。
- [ ] 验收：参数逐字符保留；锚点引用合法；repeat 与轮内动作次数不混淆。

### 2. 重构第一阶段

- [ ] 解析输出统一 CaseSpec；整理/确认稿由同一业务模型生成，保留顺序。
- [ ] 有序 instructions 与验证 anchor/scope 落地；必要时记录具体 issue。
- [x] 重写第一阶段 prompt 与结构化 schema，移除采样、旧字段和不必要的后续阶段规则。
- [ ] 保持现有 prepare API 可用；草稿持久化/revision 复用若未配套，不先暴露无效 draftId。
- [ ] 验收：中间验证、循环内外验证、确认按钮、特殊文本、缺失数据的语义正确。

### 3. 重构第二阶段的数据流

- [x] 保留逐块一次；将旧 ExecutionPlan 收缩为轻量执行视图/检查点索引。
- [ ] 单块 runner 返回 StepResult；指令账本与 step_results 成为进度来源。
- [x] 块内检查点进度工具与模型决策解析配套，保存页面后再进入后续指令。
- [ ] 原始轨迹、派生角色判断、定位证据分离；移除冗余 script_candidate/default trace_role。
- [ ] 验收：长块不漏步、不重做；repeat>1 仍只探索一遍；业务预期不同不触发重做。

### 4. 同步适配第三阶段

- [x] production 与离线入口均接收 case_spec + exploration_result。
- [ ] 更新 projection/review/locator/IR/codegen 的字段读取及相关 prompt。
- [ ] 明确 ScriptIR 的块分组：整块动作与循环内验证一起重复，循环外验证置于其外。
- [x] 不根据实际观察改写用户预期；不因目标未出现就删除验证。
- [ ] 验收：固定探索产物可生成非空、关联正确的 IR；有/无验证、repeat=1/>1 均正确。

### 5. 抽运行边界并归位目录

- [ ] WorkflowState 只保留阶段交接；依赖由 ExecutionContext 注入，内部进度不污染全局 state。
- [x] 统一传递配置，消除 runner 内部重新创建配置导致注入无效的问题。
- [x] 核心依赖设备接口，现有 PluginActionClient 适配；保留现有基础动作实现。
- [x] 保留详细事件，整理发布/存储/插件展示边界，核心不直接依赖 Run 层展示 helper。
- [ ] 按重构清单移动三阶段、workflow、contracts、runtime、ui、llm 并更新全部 import/资源路径。
- [x] 核查后清理旧 plan、旧 summary、重复 targets 实现；包入口不承载整段算法。

### 6. 增强观察、执行结果与证据

- [ ] 动作下发前登记；补齐真实下发参数、结果与观测，截图失败不丢动作。
- [x] 区分 succeeded/failed/unknown；超时不盲目重复提交。
- [ ] 有界等待、观测质量与过期观察处理；明确等待不被系统去抖抵扣。
- [ ] 批量次数对账；插件缺少实际计数时保留限制，不伪造精度。
- [ ] 定位候选有引用和依据，未匹配不默认取第一；保留动态/序号目标语义。
- [ ] 能力增强按现有插件能力降级，不能要求未提供的新命令才能运行基本链路。

### 7. 正式产物与离线验证

- [x] 快照 IO 从 tests 迁入 runtime；图片与 JSON 分离，bundle 可导入导出并校验版本。
- [ ] 成功、阻塞、错误和停止均保留已采集证据；逐块保存进度。
- [x] probe 迁入 tools/probes，使用同一正式入口，不维护另一套生成流水线。
- [x] 假模型检查实际 messages：操作模型不接收 repeat、断言预期或框架规范；完整指令进度保留。
- [ ] 运行必要的契约、单块闭环、三阶段适配和 API/事件回归检查。
- [ ] 少量真实模型/手机效果验证需确认可用连接与配置；无法执行时明确记录，不声称已验证。

### 8. 交付

- [ ] 更新 README、运行命令、目标目录与旧规划的适用状态。
- [ ] 记录实际变更、通过的检查、未验证项与插件侧需要配合的能力。
- [ ] 确保无新旧字段静默混用、无假成功、无未经说明的空 IR/缺失验证。

## 继续执行方式

先阅读当前状态和已确认约束，再从第一个未完成项推进。每批保持生产者和消费者配套，不长时间留下新结构接旧生成器的断链。重构期间定期更新本文件的勾选和必要结论；设计取舍有新变化时同步三份设计文档。

## Explore 第二轮实施记录

已接入 Observe、方法策略、状态式上下文、进度随工具报告、独立 progress/checkpoints 模块、轨迹引用校验和保守路径审查。23 个离线测试与编译检查通过。剩余增强和限制见 exploration_next_iteration.md 的本轮状态；未进行真实模型/手机联调。

## Explore 类型与归属收尾

移除 exploration/state.py：探索私有运行协议位于 _runtime.py，工作流初始化归 workflow/initialize.py，任务渲染归 context/rendering.py。OperationRecord 的关键子结构、Observation、InstructionResult、ExecutionResult 均有具体类型；清除 completed_steps、operation_ids、顶层 trajectory/空 executionPlan、重复 verification.step_id、无效历史参数与旧 append_turn。新增序列化和接口边界回归检查。当前仍保留 UI/调试扩展 JSON，完整页面等待、设备实际计数与真实联调不在本次类型清理中假称完成。

## 稳定路径 Prompt 审视

补充独立的 operate_step.md，方法要求与程序策略共源，明确多动作语义目标、应用首页/桌面、输入/提交、业务等待/Observe、实际完成边界及恢复限制。补充参数事实账本和前台元数据，工具说明同步修正。测试针对实际请求和执行协议，不宣称真实模型效果已经验证。
