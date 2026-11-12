# Agent Loop 重构计划

历史规划。当前实现以 exploration_workflow_current.md 和 script_generation_current.md 为准；旧 execution_plan 与 operation_step_id 不再适用。

## 1. 背景

当前工程目标是：根据用户描述控制手机完成操作探索，并记录可用于后续测试脚本生成的轨迹数据。

前面已经确定第一阶段不做脚本生成，只聚焦：

1. 用户输入整理；
2. 结构化用例；
3. 编译 Agent Loop 执行计划；
4. 控制手机执行；
5. 记录设备状态和操作轨迹。

本次重构重点是 Agent Loop 的上下文设计、工具调用结果设计、执行计划设计、轨迹数据结构和目录边界整理。

当前主链路已经按职责拆到以下模块：

```text
case_preparation：用户输入整理、结构化用例、执行计划编译
mobile_execution：手机执行 Agent Loop、工具定义、动作执行、轨迹构建
observations：设备状态采集和截图数据转换
llm：模型调用与消息构造适配
script_trace：后续脚本生成可消费的轨迹投影
legacy：旧探索/抽取/代码生成实现，仅作为后续重写参考，不参与当前主链路
```

---

## 2. 总体设计结论

### 2.1 用户任务固定一份，动作历史裁剪保留

Agent Loop 的上下文不应该每轮重复拼接“当前任务”“当前进度”“历史截图”。

推荐每次 LLM 请求都按下面的稳定结构构造：

```text
system: 固定 Agent Loop 规则
user: 固定任务文本，即 render_execution_plan(execution_plan) 的结果，只出现这一条任务消息
assistant: 最近第 1 个动作 tool_call
tool: 最近第 1 个动作极简执行结果
assistant: 最近第 2 个动作 tool_call
tool: 最近第 2 个动作极简执行结果
...
user: 当前最新截图
```

也就是说：

- 固定任务文本每次请求都保留一份，用于避免模型遗忘完整操作步骤；
- 固定任务文本在同一次请求中只出现一次，不再作为历史 user message 被反复追加；
- 历史只保留最近 N 个动作回合，推荐默认 8 个动作回合；
- 一个动作回合指 `assistant tool_call + tool result`，裁剪必须按这一对一起裁剪；
- 历史中不保存无图的 `当前手机截图如下。` user 占位消息；
- 当前最新截图永远作为最后一条 user message，且只携带一张图。

这样同时满足：

1. 模型每轮都能看到完整任务，降低遗忘；
2. 历史不会无限增长；
3. 历史截图不会污染当前页面判断；
4. 当前页面永远以最后一条带图 user message 为准。

### 2.2 不保留历史截图给模型

历史截图不进入模型上下文，只保留最新截图。

原因：

1. 避免图片上下文过大；
2. 避免模型混淆当前页面和历史页面；
3. 当前决策只应该依赖当前最新页面。

内部仍然完整保存 observations 数组。

### 2.3 tool result 给模型保持极简

给模型看的 tool result 只需要：

```json
{
  "success": true,
  "message": "点击成功"
}
```

复杂信息，例如：

- operation_id；
- before_observation_id；
- after_observation_id；
- resolved_action；
- raw_tool_call；
- source_path；
- repeat_context；

都只写入内部 trajectory，不放进模型上下文。

### 2.4 operation_step_id 需要保留

`operation_step_id` 需要保留，但语义要明确：

> 当前工具动作正在尝试推进哪个用户语义操作步骤。

注意：

- 一个 `operation_step_id` 不等于一个工具动作；
- 一个用户语义步骤可能需要多个工具动作；
- 模型每轮只是判断当前动作在推进哪一步；
- 后续插入验证步骤和生成脚本时，可以根据 operation_step_id 做关联。

例如：

```text
op_step_006：返回首页
```

可能对应多个底层动作：

```text
Back
Back
Click 首页 Tab
Wait
```

这些动作都可以关联到同一个 `operation_step_id=op_step_006`。

---

## 3. 输入和执行计划设计

### 3.1 CaseSpec 继续保留结构化用例

当前 CaseSpec 建议保持：

```json
{
  "case_name": "",
  "operation_steps": [],
  "verification_steps": []
}
```

其中 `operation_steps` 可以包含 repeat：

```json
{
  "id": "repeat_001",
  "type": "repeat",
  "text": "重复执行首页浏览与评论区交互流程",
  "times": 5,
  "body": [
    {
      "id": "op_step_002",
      "type": "step",
      "text": "在首页上滑 1 次，等待观看 3 秒"
    },
    {
      "id": "op_step_003",
      "type": "step",
      "text": "点击评论区入口，随后收起评论区"
    }
  ]
}
```

CaseSpec 是内部事实来源，后续脚本生成需要它还原循环和验证步骤。

### 3.2 Agent Loop 不直接消费 repeat

Agent Loop 不应该直接理解 repeat。

需要在进入 Agent Loop 前，把 CaseSpec 编译为线性执行计划 `execution_plan`。

规则：

1. 普通 step 直接进入 execution_plan；
2. 业务 repeat 默认采样一轮，展开 body；
3. 连续滑动 N 次这类单步重复动作不展开，保留在 step 文本里；
4. repeat 来源信息保存在内部 metadata，不给模型看。

### 3.3 execution_plan 示例

```json
{
  "case_name": "红果短剧浏览搜索及重复交互测试",
  "steps": [
    {
      "id": "op_step_001",
      "text": "启动红果免费短剧应用",
      "source_path": ["op_step_001"]
    },
    {
      "id": "op_step_002",
      "text": "在首页上滑 1 次，等待观看 3 秒",
      "source_path": ["repeat_001", "op_step_002"],
      "repeat_context": {
        "repeat_id": "repeat_001",
        "repeat_text": "重复执行首页浏览与评论区交互流程",
        "times": 5,
        "strategy": "sample_once"
      }
    },
    {
      "id": "op_step_003",
      "text": "点击评论区入口，随后收起评论区",
      "source_path": ["repeat_001", "op_step_003"],
      "repeat_context": {
        "repeat_id": "repeat_001",
        "repeat_text": "重复执行首页浏览与评论区交互流程",
        "times": 5,
        "strategy": "sample_once"
      }
    }
  ]
}
```

给模型看的任务文本当前渲染为：

```text
用户确认后的任务如下：

用例名称：红果短剧浏览搜索及重复交互测试

操作步骤：
1. [op_step_001] 启动红果免费短剧应用
2. [op_step_002] 在首页上滑 1 次，等待观看 3 秒
3. [op_step_003] 点击评论区入口，随后收起评论区

```

说明类规则当前放在 `mobile_execution/prompts/explore.py` 的 system prompt 中，避免固定任务文本过长。

---

## 4. Agent Loop 上下文规划

### 4.0 当前代码审视结论和目标结构

旧实现中 Agent Loop 上下文大致是：

```text
system
历史 user 文本 / assistant tool_call / tool result
当前 user: 当前截图文本 + 当前截图
```

并且当前 `_history` 里会保存每轮 user 文本。第一轮 user 文本包含任务文本和 `当前手机截图如下。`，后续 user 文本通常只是 `当前手机截图如下。`。这些历史 user 文本不带图片。

这会导致几个问题：

1. 历史中出现大量没有图片的 `当前手机截图如下。`，信息价值低；
2. 第一轮历史 user 中保留了 `当前手机截图如下。`，但图片已经不在历史里，语义不够干净；
3. `max_history_turns=None` 时历史无限增长；
4. 任务文本虽然只在第一轮新增，但后续作为历史继续混在 user 历史里，不利于清晰区分“固定任务”和“动作历史”。

当前实现已经把上下文拆成四类，代码位于：

```text
src/atestservice/agent/mobile_execution/context/message_context.py
```

结构为：

```text
固定规则：system_prompt
固定任务：task_text，只一条 user message，不带图
动作历史：最近 N 个 assistant/tool pair
当前状态：最后一条 user message，带当前最新截图
```

每轮实际发送给模型的 messages 应为：

```text
[
  system_prompt,
  user(task_text),
  assistant(tool_call_最近第 N 步),
  tool(result_最近第 N 步),
  ...,
  assistant(tool_call_最近第 1 步),
  tool(result_最近第 1 步),
  user(CURRENT_SCREEN_TEXT + 当前最新截图),
]
```

注意：

- `task_text` 每次请求都保留，但同一次请求里只出现一次；
- `_history` 不再保存 user message；
- `_history` 只保存动作历史，即 `assistant_message + tool_message`；
- 裁剪按动作回合裁剪，不能拆开 assistant/tool；
- 当前截图永远只在最后一条 user message 中出现；
- 历史中不保留任何图片。
### 4.1 System Prompt

system prompt 放固定规则：

```text
你是手机 UI 自动化 Agent。你只能通过工具操作设备，每一轮必须且只能调用一个工具。

上下文规则：
1. 每次请求都包含一条固定任务 user message，内容为用户确认后的线性操作步骤。
2. 每次请求最后一条 user message 只包含手机当前最新截图说明和当前最新截图。
3. 每条带截图的 user message 都表示手机当前最新页面状态；决策时只相信最后一张截图。
4. 历史截图不会保留，历史 user 截图占位文本也不保留。
5. 动作历史只保留最近若干个 assistant tool_call + tool result 回合。

任务规则：
1. 操作步骤是用户语义目标，不是底层工具动作；一个操作步骤可能需要多个工具动作完成。
2. 每次调用动作工具时，尽量填写当前动作正在推进的 operation_step_id；不确定时可以为空。
3. 验证步骤不参与当前探索执行。
4. 只有确认所有用户语义操作步骤都已完成后，才调用 FinishTask。
```

### 4.2 固定任务 User Message

固定任务 message 每次请求都保留一条，内容来自 `render_execution_plan(execution_plan)`，不带截图。

```text
用户确认后的任务如下：

用例名称：xxx

操作步骤：
1. [op_step_001] xxx
2. [op_step_002] xxx

说明：
- 上面的步骤是用户语义目标，不是底层工具动作。
- 一个步骤可能需要多个工具动作完成。
- 你看到的步骤已经是本次探索要执行的完整线性流程，不要推断隐藏重复次数。
```

规则：

- 同一次 LLM 请求中，固定任务 message 只能出现一次；
- 固定任务 message 不进入动作历史裁剪队列；
- 固定任务 message 不带 `当前手机截图如下。`，避免历史文本和图片语义错位；
- 当前实现中任务规则说明放在 system prompt，不重复追加到固定任务 message。
- 如果后续增加进度摘要，应追加在固定任务 message 后面，但必须保持简短，并且由内部 trajectory 计算得到。

### 4.3 当前截图 User Message

每次请求最后追加当前截图 message：

```text
当前手机截图如下。
```

并附带当前最新截图。

规则：

- 当前截图 message 永远是 messages 的最后一条 user message；
- 当前截图 message 是唯一带图片的消息；
- 历史中不保存当前截图 message；
- 后续轮次仍然只新增当前截图 message，不重新拼接任务文本到该消息里。
### 4.4 Tool Result

给模型看的 tool result：

```json
{
  "success": true,
  "message": "点击成功"
}
```

失败时：

```json
{
  "success": false,
  "message": "输入失败：当前没有聚焦输入框"
}
```

---

## 5. 工具定义规划

### 5.1 operation_step_id 字段

所有动作工具保留：

```python
operation_step_id: str | None
```

描述应改成：

```text
当前动作正在尝试推进的用户操作步骤 id。一个用户操作步骤可能需要多个工具动作；不确定时可为空。
```

### 5.2 FinishTask

FinishTask 保留：

```python
completed_operation_step_ids: list[str]
```

描述应改成：

```text
确认已完成的用户操作步骤 id 列表。只有确认对应用户语义步骤完成时才填写。
```

### 5.3 工具是否需要新增

当前工具集合基本够用：

- Click
- DoubleClick
- LongClick
- InputText
- DirectionSwipe
- CoordinateSwipe
- Drag
- Back
- Home
- OpenMultitask
- OpenControl
- OpenNotification
- StartApp
- StopApp
- Wait
- FinishTask
- ReportBlocker

暂时不需要新增工具。

需要优化的是字段描述和 Agent Loop 上下文，而不是工具数量。

---

## 6. State 和 Trajectory 规划

### 6.1 MobileAgentState

建议保持：

```python
class MobileAgentState(TypedDict, total=False):
    request: dict[str, Any]
    case_spec: dict[str, Any] | None
    execution_plan: dict[str, Any]
    trajectory: dict[str, list[dict[str, Any]]]
    run: dict[str, Any]
    result: dict[str, Any]
```

### 6.2 trajectory 总体规则

保持线性规则：

```text
observations[i] -- operations[i] --> observations[i + 1]
```

也就是：

```text
len(observations) == len(operations) + 1
```

### 6.3 observation 结构

每个 observation 表示一次完整设备状态：

```json
{
  "id": "obs_0000",
  "index": 0,
  "package": "...",
  "activity": "...",
  "screen_size": {
    "width": 1080,
    "height": 2400
  },
  "screenshot": {
    "filename": "obs_0000.jpg",
    "mime_type": "image/jpeg",
    "base64": "..."
  },
  "elements": []
}
```

### 6.4 operation 结构

每个 operation 表示一次底层工具动作，不等于用户语义步骤。

当前实现采用分层后的结构：

```json
{
  "id": "op_0000",
  "index": 0,
  "trace_role": "normal",
  "script_candidate": true,
  "observation_transition": {
    "before_observation_id": "obs_0000",
    "after_observation_id": "obs_0001"
  },
  "semantic_ref": {
    "operation_step_id": "op_step_001",
    "execution_step_index": 0,
    "text": "启动红果免费短剧应用",
    "source_path": ["op_step_001"],
    "repeat_context": null,
    "matched": true
  },
  "intent": {
    "tool_name": "Click",
    "goal": "点击红果免费短剧应用图标",
    "notes": null,
    "tool_args": {}
  },
  "action": {
    "type": "click",
    "args": {}
  },
  "execution": {
    "success": true,
    "message": "点击成功"
  },
  "debug": {
    "raw_tool_call": {}
  }
}
```

说明：

- `semantic_ref` 是用户语义步骤引用和执行计划来源信息；
- `intent` 是模型原始意图的规范化结果；
- `action` 是内部实际执行动作；
- `execution` 是插件执行结果；
- `debug.raw_tool_call` 保留原始工具调用，便于排查；
- `observation_transition` 是内部轨迹关联，不给模型看；
- `script_candidate` 表示该动作是否适合作为后续脚本生成候选动作。

---

## 7. Graph 规划

推荐 graph：

```text
initialize
  ↓
build_case_spec
  ↓
build_execution_plan
  ↓
route:
  - execution_plan.steps 为空：finish_without_execution
  - 非空：explore_agent_loop
  ↓
END
```

### 7.1 build_execution_plan 节点

输入：

```python
state["case_spec"]
```

输出：

```python
state["execution_plan"]
```

并发送事件：

```text
执行计划编译完成
```

### 7.2 finish_without_execution

如果 execution_plan.steps 为空，正常结束，不算失败。

输出：

```json
{
  "status": "done",
  "finish_reason": "no_execution_plan_steps"
}
```

---

## 8. 当前实现状态

主链路已经迁移到新的目录结构：

```text
src/atestservice/agent/state.py
src/atestservice/agent/case_preparation/execution_plan.py
src/atestservice/agent/case_preparation/structure_cases.py
src/atestservice/agent/case_preparation/prepare_cases.py
src/atestservice/agent/workflows/explore_graph.py
src/atestservice/agent/workflows/explore_runner.py
src/atestservice/agent/mobile_execution/loop_node.py
src/atestservice/agent/mobile_execution/context/message_context.py
src/atestservice/agent/mobile_execution/prompts/explore.py
src/atestservice/agent/mobile_execution/tools/tool_definitions.py
src/atestservice/agent/mobile_execution/tools/action_executor.py
src/atestservice/agent/mobile_execution/trace/operation_builder.py
src/atestservice/agent/observations/store.py
src/atestservice/agent/observations/media.py
src/atestservice/agent/llm/
src/atestservice/agent/script_trace/
src/atestservice/runs/service.py
```

已完成：

1. 同步工具字段描述，`operation_step_id` 和 `completed_operation_step_ids` 语义已更新；
2. `ExploreAgentLoopNode` 已接入新的 `AgentLoopContext`；
3. `runs/service.py` 返回结果已补充 `executionPlan`；
4. `build_execution_plan` 节点和空执行计划分支已接入 graph；
5. 新增协议测试覆盖执行计划、上下文、极简 tool result 和轨迹结构。

需要注意：

1. `legacy` 目录只作为旧实现参考，不参与当前主链路；其中可能保留旧导入路径；
2. 当前 trajectory 字段名以实现为准：`semantic_ref / intent / action / execution / debug`；
3. 后续代码生成应消费新的 trajectory 结构，不再依赖旧 `operation_step / decision / resolved_action` 命名。

---

## 9. 验证计划

### 9.1 静态检查

```powershell
uv run python - <<PY
import ast
from pathlib import Path
...
PY
```

检查所有 `.py` 文件 AST。

### 9.2 execution_plan 编译测试

输入包含 repeat 的 case_spec，验证：

- repeat body 被采样展开；
- execution_plan.steps 是线性的；
- repeat_context 被保留；
- agent_loop prompt 不出现 repeat 概念。

### 9.3 fake agent_loop 测试

用 fake LLM 和 fake action client 验证：

- 第一轮 user message 包含任务 + 当前截图；
- 后续 user message 只包含当前截图；
- tool result 只有 success/message；
- trajectory 满足 `len(observations) == len(operations) + 1`；
- operation 内部记录 operation_step、observation_transition。

---

## 10. 最终目标

重构完成后，应满足：

1. 模型上下文简单清晰；
2. 用户任务只出现一次；
3. 每轮只给模型最新截图；
4. tool result 极简；
5. 内部 trajectory 完整记录；
6. operation_step_id 能关联结构化用户步骤；
7. repeat 不暴露给 agent_loop，但后续脚本生成可还原；
8. 空执行计划正常结束；
9. 当前阶段不接入脚本生成。
