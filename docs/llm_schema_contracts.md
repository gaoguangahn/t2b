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

第二阶段结合描述、当前页面与工具定义决定调用方式和参数，实际参数进入 operations[].action.args，第三阶段 IR 的动作 parameters 继续保留。实际调用账本不依赖第一阶段参数表。固定方法、工具参数类型、原轨迹引用与边界检查保留；输入原值及数量的语义核对由模型结合描述和记录完成，不声称程序已经从自然语言精确抽取并验证。

第三阶段曾出现 `PlanningResponse ... items: schema must have a type key`。本地捕获的 SDK 请求中，`ScriptPlan.actions.items` 只有 `$ref`，指向 `$defs.PlannedAction`；标准 JSON Schema 与 OpenAI Structured Outputs 允许这种表达，但部分兼容网关可能要求数组元素直接声明类型。当前在发送前展开所有本地引用，使该处直接包含 `type: object`、properties、required 和 additionalProperties。未修改 PlanningResponse 的业务字段或第三阶段流程。公司网关的具体行为仍需在公司环境复测确认。

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

## 审查范围

| 调用位置 | 模型输出 | 本轮结果 |
| --- | --- | --- |
| case_preparation/parser.py | 原 CaseSpec | 改为独立 CaseExtraction，去除开放字典与程序元数据 |
| script_generation/planning/planner.py | PlanningResponse / ScriptPlan | 展开 actions 等嵌套引用，补齐 required、移除默认值 |
| script_generation/targeting/resolver.py | TargetResponse / TargetPick | 同上，nullable 属性仍以 null 表达 |
| script_generation/codegen.py | CodegenResult | 同上，输出后继续执行代码与文件名检查 |
| exploration/loop_node.py | 19 个探索工具 | 统一转换工具参数，保留原工具名、参数与解码逻辑 |
| llm/client.py | invoke_structured_debug | 与正常请求使用同一 Schema 路径 |

ScriptIR 只是代码生成的输入数据，不作为模型的响应 Schema 发送；其中的步骤树和坐标元组无需为了接口限制修改。

## 排查日志

在 models.ini 的实际模型节设置 `debug_schema = true` 并重启。

1. 创建模型时输出依赖版本；原有创建信息中包含 debug_schema 的实际值。
2. 请求构造前输出 Preparing schema/method 或工具名；本地预校验失败也能看到入口。
3. 预校验成功输出 Validated wire schema。
4. HTTP hook 输出 SDK 最终发送的 response_format/tools/text.format。

日志不包含消息正文、截图或请求头。查看服务端终端或 PM2 日志，插件事件不会自动包含 stdout。无 Preparing 时检查实际运行版本、INI 选择与服务重启；有 Preparing 但无 HTTP 日志时，结合本地错误定位发送前失败。

## 验证

离线检查覆盖描述保留、没有参数表、实际动作参数记录和所有严格 Schema；未新增测试框架依赖。

tests/test_llm_schema.py 通过真实 LangChain/OpenAI SDK 与 httpx.MockTransport 捕获最终请求。覆盖四类输出在 json_schema/function_calling 下的序列化、19 个工具、JSON mode、debug 调用、Schema 发送前拒绝、业务转换、错误返回与能力配置。

针对第三阶段报错，增加独立的网关限制检查：数组 items 缺少显式 type 时拒绝。原始 PlanningResponse Schema 能复现此错误；转换后的 SDK 请求通过该检查。另检查多处引用展开后互不影响、可空字段保留、未知和递归引用在本地报错。此前的离线校验接受标准 $ref，未覆盖这类网关限制。

这些检查验证最终发出的结构和程序行为；未调用公司模型网关或真实手机，不能替代公司环境的实际联调。若厂商额外限制某些标准约束，需要以完整错误和新日志定位，不能靠删除字段或静默降级掩盖。

依据：[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。
