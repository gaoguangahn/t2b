# 脚本生成

正式输入：CaseSpec + ExplorationResult；入口：pipeline.generate_script。

动作计划 → 来源/删除边界检查 → 共用目标解析 → 确定性 IR → 框架编码。

- planning/ 整理路径，可按需读取已有观察；targeting/ 共用点击、验证和条件目标解析。
- evidence.py 提供只读证据，ui/elements.py 提供属性/几何查询。
- ir_builder.py 按 CaseSpec 装配动作、条件、循环和验证，不改写预期。
- codegen.py 只接收 IR/profile；script_gen_node.py 适配工作流和详细事件。
- 正式类型位于 contracts/script.py，模型协议留在各子模块 models.py。

结果包含 status（ready/draft/blocked）、plan、可选 ir/script。坐标限制和 TODO 进入 notes；路径证据不足阻塞生成并保留问题。条件块通用化，不含弹窗专属标志。

生产与 tools/probes/script_gen_probe.py 使用同一正式 bundle 和生成入口。详见 [当前设计](../../../docs/script_generation_current.md)。
