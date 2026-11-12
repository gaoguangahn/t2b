# 手机执行结果到脚本生成的后续规划

历史规划，已由 [script_generation_current.md](script_generation_current.md) 替代；旧 execution_plan、逐动作 verdict 和生成流水线不再适用。

## 背景

当前第一阶段已经能根据用例描述驱动手机执行，并在执行过程中形成 `case_spec`、`execution_plan`、`trajectory` 等数据。后续目标不是直接把完整执行轨迹硬转成脚本，而是先把“真实执行审计数据”和“可生成脚本的数据”分开，再逐层加工，保证错误路径、恢复路径、验证步骤、循环结构都能被明确处理。

## 核心原则

1. `trajectory` 保持事实记录，不要混入脚本生成结论。
2. 不再单独引入 `script_candidate` 这类重复字段；动作是否执行成功优先从 `execution.success` 判断。
3. 执行失败动作可以先在投影阶段粗筛掉，不需要污染原始轨迹结构。
4. 导致进入错误界面的动作，以及为了从错误界面恢复到正确轨迹的动作，不应该进入最终脚本。
5. 处理弹窗、权限框、业务确认框这类正常测试中可能出现的动作，可以保留，但应该明确标记为正常辅助动作或 watcher 候选。
6. 验证步骤需要进入脚本生成流程，尤其是 UI 验证，需要能关联到对应 observation，给后续断言生成提供上下文。
7. 执行阶段为了方便模型执行可以使用展平计划；脚本生成阶段需要恢复 repeat/group 等结构。

## 建议分层

### 1. 原始执行层

输入和产出保持现状：

- `case_spec`：结构化用例，包括操作步骤、验证步骤、循环/分组等语义结构。
- `execution_plan`：给 Agent Loop 执行的展平步骤。
- `trajectory`：真实执行轨迹，包括 observations 和 operations。

这一层只负责记录事实，不判断某个动作最终是否应该写入脚本。

### 2. 调试快照层

在执行完成后提供一个显式调试开关，把后续脚本生成需要的输入保存为 JSON 文件。这个能力应该独立于脚本生成逻辑，只做快照，不做业务判断。

建议保存内容：

- 请求参数和 run 信息。
- `case_spec`。
- `execution_plan`。
- `trajectory`。
- 必要时保存 observation 的轻量摘要，避免文件过大。

这个文件的价值是后续开发脚本生成时，可以直接读取快照反复调试，不必每次都重新跑手机执行。

### 3. 轨迹投影层

从 `trajectory.operations` 机械投影出“可审查动作列表”。这一层只做确定性处理：

- 过滤 `execution.success != true` 的动作。
- 保留动作 id、原始 index、目标描述、语义引用、action 参数、执行结果、前后 observation id。
- 不做错误路径判断。
- 不恢复循环结构。
- 不生成最终脚本。

这层输出可以叫 `action_trace` 或 `script_trace`，但它应该被定义为“中间投影”，不是最终候选结论。

### 4. 轨迹审查层

这一层可以引入模型或规则，对投影后的动作进行保留/丢弃判断。重点判断：

- 哪些动作进入了错误界面。
- 哪些动作只是错误路径恢复动作。
- 哪些动作是正常弹窗处理。
- 哪些动作虽然成功执行，但与测试目标无关。

建议输出每个动作的审查结论：

- `keep`：保留到脚本。
- `drop_wrong_path`：错误路径动作。
- `drop_recovery`：恢复正确路径动作。
- `keep_popup_handler`：正常弹窗处理动作。
- `needs_review`：不确定，需要人工或更强模型判断。

审查层需要引用前后 observation 信息，尤其是页面标题、关键控件、截图摘要、错误提示等。

### 5. 脚本 IR 层

脚本 IR 是框架无关结构，负责表达最终脚本应该做什么。它应该从“审查后的动作”加上 `case_spec` 生成：

- 恢复 repeat/group 结构。
- 插入验证步骤。
- 保留 watcher 或 popup handler。
- 标记动作来源，方便追溯到原始 trajectory。

循环恢复建议不要从轨迹反推，而是优先使用 `case_spec` 和 `execution_plan` 里的 `source_path`、`repeat_context`。执行给 Agent 的可以是展平计划，但代码生成前应按原始语义结构重组。

### 6. 代码生成层

最后一层才绑定具体自动化框架，例如 dynamic framework。输入应该是脚本 IR，而不是原始 trajectory。

代码生成层职责：

- 把 IR action 转换成框架 API。
- 把 UI 验证步骤转换成断言。
- 把 watcher/popup handler 转成可复用处理函数。
- 输出代码和必要的 selector/locator 说明。

## 验证步骤处理建议

验证步骤不要等到代码生成最后才补。建议在脚本 IR 层就插入：

1. 从 `case_spec.verification_steps` 读取验证目标。
2. 根据 `after_step_id` 或语义位置找到应该插入的位置。
3. 关联该位置附近的 observation，作为断言生成上下文。
4. 区分 UI 验证、数据验证、状态验证。
5. 如果 observation 不足，标记 `needs_observation_context`，不要硬生成不可靠断言。

## 调试快照实现建议

建议实现为独立模块，例如 `agent/script_debug/dump.py`，只负责保存和读取快照。

建议 API：

- `build_script_debug_snapshot(state) -> dict`
- `save_script_debug_snapshot(state, path: str | None = None) -> str`
- `load_script_debug_snapshot(path: str) -> dict`

开关建议放在内部调试配置或 run 请求参数中，但不要影响默认执行结果结构。默认不开启，开启后保存到固定 debug 目录。

## 推荐落地顺序

1. 先实现调试快照保存和读取，不引入 trace/IR。
2. 用一次真实流程生成快照，后续开发都基于该快照验证。
3. 实现纯函数式的轨迹投影，只过滤失败动作。
4. 基于快照写小测试，验证投影输出字段稳定。
5. 实现验证步骤插入逻辑。
6. 实现循环结构恢复逻辑。
7. 再考虑模型审查层，用于剔除错误路径和恢复路径。
8. 最后接代码生成，不要让代码生成直接读取原始 trajectory。

## 当前不建议做的事

- 不建议把 `script_candidate` 放回轨迹作为长期方案，它会和 `execution.success` 重复。
- 不建议在原始 `trajectory` 中直接写模型审查结果。
- 不建议一开始就把 trace、IR、artifact 保存、代码生成全部接进主流程。
- 不建议默认落盘大文件，应该显式开启调试快照。
- 不建议在没有 observation 上下文时生成 UI 断言。

## 最小下一步

下一步可以只做“调试快照”能力：执行 node 完成后，把 `request`、`case_spec`、`execution_plan`、`trajectory`、`run` 保存到一个 JSON 文件。这个能力不改变主流程输出，不引入 script trace/IR，也不做动作筛选。等快照稳定后，再在离线测试里逐步实现投影、审查和 IR。
