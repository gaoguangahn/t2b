# 模型交互 Schema 修复与检查

## 原因与处理

prepare 曾直接发送共享业务模型 CaseSpec。其默认字段不全部进入 required，旧 Instruction.parameters 的开放字典也不符合严格结构化输出约束。SDK 的自动补齐行为不足以保证整份请求符合接口要求。后续按职责划分删除了第一阶段参数提取，不保留字典或参数条目表。

当前职责分开：

```text
用户描述 → CaseExtraction（模型协议）
         → 业务引用校验、程序填写版本/修订号
         → CaseSpec（保留目标块、描述、类别、循环、验证锚点）
```

case_preparation/models.py 定义 CaseExtraction。instruction 只包含 id/text/kind，不提取参数；用户指定的应用、输入原文、次数、时长等完整保留在描述。schema_version 与 source_revision 由程序填写。确认稿和生成时的解析复用同一入口，HTTP 和探索结果接口不变，CaseSpec 中移除了 instruction.parameters。旧快照若仍带该字段需重新整理用例，不静默丢掉其中的原值。

无循环（repeat=1）的验证统一为 each_iteration，保留原 instruction_id 和 before/after 位置，避免将内部锚点移到整块末尾。repeat>1 时不自动改变验证 scope，跨字段矛盾继续交给 CaseSpec 检查。CaseParser 对 Pydantic 结构/业务校验错误和 JSON 解析错误最多纠正两次（共三次调用）；反馈原始描述、校验错误及可用的上一份结构，要求保留验证与原意。网络、接口拒绝等提供方错误不走这套结构纠正机制，失败继续向上报告。

第二阶段结合描述、当前页面与工具定义决定调用方式和参数，实际参数进入 operations[].action.args，第三阶段 IR 的动作 parameters 继续保留。实际调用账本不依赖第一阶段参数表。固定方法、工具参数类型、原轨迹引用与边界检查保留；输入原值及数量的语义核对由模型结合描述和记录完成，不声称程序已经从自然语言精确抽取并验证。

第三阶段曾出现 `PlanningResponse ... items: schema must have a type key`。本地捕获的 SDK 请求中，`ScriptPlan.actions.items` 只有 `$ref`，指向 `$defs.PlannedAction`；标准 JSON Schema 与 OpenAI Structured Outputs 允许这种表达，但部分兼容网关可能要求数组元素直接声明类型。当前在发送前展开所有本地引用，使该处直接包含 `type: object`、properties、required 和 additionalProperties。未修改 PlanningResponse 的业务字段或第三阶段流程。用户已在实际环境复测确认流程可跑通。

## 共用模型边界

llm/schema.py 在调用 LangChain/SDK 前生成明确的 wire schema：

- 所有对象声明的属性都进入 required，包括嵌套对象和可空字段。
- 可空字段继续保留 null 分支；有默认值不再意味着线上协议可以省略字段。
- 所有对象 additionalProperties=false，移除 default，将单值 const 表达为 enum。
- 展开本地 $ref，移除 $defs，数组元素和嵌套对象直接携带类型定义；可空字段保留 anyOf 分支。
- 开放字典直接报错，不能通过强制关闭 additionalProperties 丢掉业务参数。
- 未声明的 required key、未知或递归引用、无类型值，以及当前不支持的 tuple/组合等结构会在发送前报出模型名或 Schema 路径。当前模型输出和工具参数没有递归结构。

这是一套本工程使用的严格子集，不承诺支持 JSON Schema 的所有功能或所有模型厂商扩展。原 Pydantic 模型不修改，返回结果仍由原类型校验，数值边界与业务引用检查继续生效。

llm/client.py 显式传入转换后的字典，不依赖 SDK 从 Pydantic 类隐式生成协议：

- json_schema：明确 strict=true 的 response_format。
- function_calling：明确 strict=true 的函数参数。
- json_mode：相同 Schema 加入 JSON 输出指令，结果在本地校验；此模式不提供接口级严格约束。
- 探索工具：使用相同的严格参数 Schema；上层工具数量、参数与动作检查保持不变。
- 普通和 debug 结构化调用共用请求构建方法。能力配置不支持该模式时发送前报错，不静默切换方式。

第三阶段的路径计划、目标解析和编码统一遵守模型 INI 的 structured_output_method，不再由节点写死 function_calling 覆盖配置；各节点仍保留自己的温度、输出长度和超时。探索的手机动作继续使用工具调用，这与结构化结果的格式配置是两种用途。

json_schema 和 json_mode 都在消息正文中明确要求输出 JSON，以满足部分千问接口的关键词检查。json_schema 的结构仍通过 response_format 传递，正文不重复整份 Schema；json_mode 的正文包含完整 Schema。配置 json_schema 却收到 json_object 相关错误，可能涉及网关转换或下游接口校验，单凭错误不能确认实际是否仍有严格结构约束。本地不自动降级，返回结果继续由原 Pydantic 类型校验。

## 审查范围

| 调用位置 | 模型输出 | 本轮结果 |
| --- | --- | --- |
| case_preparation/parser.py | 原 CaseSpec | 改为独立 CaseExtraction，去除开放字典与程序元数据 |
| script_generation/planning/planner.py | PlanningResponse / ScriptPlan | 展开 actions 等嵌套引用，补齐 required、移除默认值 |
| script_generation/targeting/resolver.py | TargetResponse / TargetPick | 同上；新增候选来源帧、可空 VerificationPlan，预期值按字符串/布尔/数字/null 声明联合类型 |
| script_generation/codegen.py | CodegenResult | 同上，输出后继续执行代码与文件名检查 |
| exploration/loop_node.py | 19 个探索工具 | 统一转换工具参数，保留原工具名、参数与解码逻辑 |
| llm/client.py | invoke_structured_debug | 与正常请求使用同一 Schema 路径 |

ScriptIR 只是代码生成的输入数据，不作为模型的响应 Schema 发送；其中的步骤树和坐标元组无需为了接口限制修改。

目标解析在同一次 TargetResponse 调用中输出定位与验证策略，没有独立复核调用。提示词明确顶层为 {"targets": [...]}，包含一个 TargetPick；不能只输出内部对象、空数组或空参数。VerificationPlan 的字段类型经过严格 Schema 发送，方法/操作符/预期值的组合、实际 UI 属性与证据来源再由 targeting/verification.py 检查；不合法的策略成为 unresolved 并保留限制，不会通过读取现场值改写用户预期。离线 SDK 检查包含非空的嵌套状态验证策略和布尔 false，避免只验证 null 分支。

## 运行诊断

联调确认后已移除临时 Schema 打印、HTTP 请求打印 hook、依赖版本打印及 `debug_schema` 配置项。旧 models.ini 中若有该项，可直接删除；保留时也不会再读取。

Schema 转换、发送前校验和异常传播继续生效，保留正常运行日志。结构化响应解析失败时，额外记录一条WARNING：模型、实际输出方式、Schema名、finish_reason、token用量、工具名与参数状态（empty_string/null/empty_object等）；不打印请求、参数正文或推理内容。正常调用在同一次请求中保留LangChain响应消息到完成校验，再返回类型化结果；失败继续抛出原异常类型，第一阶段纠正逻辑仍可处理。

`invoke_structured_debug` 返回响应 metadata、解析错误和transport摘要，本身不打印；非法结构也能取得诊断，不再在构造诊断前直接抛出Pydantic错误。工具空参数在SDK中可能被解析为{}，因此仅凭 input_value={} 不能判断服务端原始输出。当前LangChain对有效工具参数不保留原始字符串；日志明确arguments_source=parsed，此时空字符串与{}都报告empty_object，不能再区分原始值；旧版本保留原始参数时标记raw。离线回归分别模拟空字符串、{}与finish_reason=length，均可复现targets缺失，并检查解析层级与截断标志，不声称恢复已丢失的原始值。

DeepSeek兼容性需以实际接口为准。官方JSON Output使用json_object；可显式配置structured_output_method=json_mode，工程会将完整Schema加入提示词，并在本地继续校验。它不保证必填字段一定生成。官方严格工具调用要求Beta入口，且Schema子集不支持minLength/maxLength、minItems/maxItems等，不能只凭strict=true认定当前兼容网关已强约束；工程不自动改入口、删除业务约束或降级模式。依据：[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)。

## 验证

离线检查覆盖描述保留、没有参数表、实际动作参数记录和所有严格 Schema；未新增测试框架依赖。

tests/test_llm_schema.py 通过真实 LangChain/OpenAI SDK 与 httpx.MockTransport 捕获最终请求。覆盖用例解析、动作计划、目标解析和代码输出在 json_schema/function_calling 下的序列化、19 个工具、JSON mode、debug 调用、Schema 发送前拒绝、业务转换、错误返回与能力配置。手机动作包含类型明确的complete_current_instruction布尔字段，控制工具不包含该字段；严格Schema仍将动作的该字段列入required。探索不再调用独立完成复核模型，标记的执行前语义和游标推进合法性由提示词及本地策略共同约束。

针对第三阶段报错，增加独立的网关限制检查：数组 items 缺少显式 type 时拒绝。原始 PlanningResponse Schema 能复现此错误；转换后的 SDK 请求通过该检查。另检查多处引用展开后互不影响、可空字段保留、未知和递归引用在本地报错。此前的离线校验接受标准 $ref，未覆盖这类网关限制。

这些离线检查验证最终发出的结构和程序行为；不调用公司模型网关或真实手机。实际环境联调由用户完成。若厂商额外限制某些标准约束，需要结合完整错误定位，不能靠删除字段或静默降级掩盖。

依据：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。
