---
name: human-readable-technical-writing
description: 所有面向用户的中文回答、中文技术写作、改写、翻译、解释、压缩、README、状态、报告、UI、API、图片、表格和代码说明都使用；把任务编译为基础操作与解释增量，完整保留原文信息，分开追踪原文、用户补充、外部背景和推断，再按照读者与媒介生成自然中文；只要求纯代码、纯 JSON、纯数字或非中文机械格式时不触发
---

# AIALRA 可验证中文写作

## 1. 启动

完整读取 `constitution/principles.md`；该文件规定源信息、来源分层、最小修复和用户金标边界

只处理用户当前要求的内容；没有授权时，不增加发布、账户、权限、安装或其他无关架构

## 2. 编译任务契约

读取 `runtime/task-compiler.md` 和 `runtime/clarification-gate.md`；确定两个独立维度：

- 基础操作：`TRANSFORM`、`TRANSLATE`、`COMPRESS`、`EXPLAIN`、`GENERATE` 或 `FORMAT_ONLY`
- 解释增量：`NONE`、`GLOSS`、`EXPLANATORY`、`TEACHING` 或 `RESEARCHED`

默认配置：

- 只要求翻译：`TRANSLATE + GLOSS`
- 要求翻译到能够看懂：`TRANSLATE + EXPLANATORY`
- 只要求同语种忠实改写：`TRANSFORM + NONE`
- 只要求调整版式：`FORMAT_ONLY + NONE`

同时登记读者、文体、媒介、内容组件和用户配置；任务契约的结构以 `contracts/task-contract.schema.json` 为准

只有不同解释会改变事实、范围、结论、来源要求或输出规模时才提问；一次说明问题、选项、推荐默认和各选项的实际影响

## 3. 理解原文与来源

改写和翻译读取 `constitution/source-vs-background.md` 与 `runtime/source-understanding.md`

来源固定分为：

- `SOURCE`：原文直接表达，并指向原文位置
- `USER_SUPPLIED`：用户在当前任务中补充
- `EXTERNAL_BACKGROUND`：帮助理解的外部知识，并登记来源
- `INFERENCE`：根据已登记内容推导，并保留置信度

`TRANSFORM` 和 `TRANSLATE` 的源信息覆盖率为 `100%`；原文事实、条件、否定、范围、数值、关系和不确定程度不得丢失或改变

解释增量可以增加必要背景、定义、机制、例子和关系说明；补充内容必须与原文分开追踪，不能伪装成原作者主张，也不能代替原文证据

原意无法确认时停止推断并进入一次性问答确认

## 4. 建立骨架并成文

复杂原文、长文、解释性改写和解释性翻译读取 `runtime/content-blueprint.md` 与 `runtime/constrained-rendering.md`

先把所有源语义单元分配到段落，再插入具有明确用途的背景；没有源信息、背景、推断、组件解释或必要逻辑作用的句子不进入正文

直接根据骨架生成目标风格正文；禁止先全文翻译、再全文解释、再全文润色，因为连续重写会扩大事实漂移

启用 Lucas 配置时读取 `profiles/users/lucas.yaml`；普通中文正文不使用中文句号，句内使用中文分号，段落末尾不保留中文句号或中文分号；逐字引文、日志、代码和用户要求原样保存的材料保持原文

## 5. 按组件加载

- 图片：读取 `profiles/components/images.yaml`；解释有效元素、关系、背景、推断和证据边界
- 表格：读取 `profiles/components/tables.yaml`；解释列、行、数据格、比较、趋势、异常和不能证明的内容
- 代码：读取 `profiles/components/code.yaml`；解释工具、动作、原因、语法、输入、结果、失败表现、副作用和边界
- 术语：读取 `registries/terms.yaml`；使用登记形式，未登记术语根据官方名称和当前读者自然解释
- 单位与机器标识：读取 `registries/units.yaml` 和 `registries/protected-patterns.yaml`

## 6. 规则等级

读取 `constitution/hard-vs-advisory.md` 与 `validators/rule-severity.yaml`

- `MACHINE_FINAL`：代码能够确定，失败时阻断
- `MACHINE_CANDIDATE`：代码只定位疑似问题，由上下文判断
- `PROFILE_REQUIRED`：当前任务或用户配置要求，失败时阻断
- `ADVISORY`：用于优化，不单独阻断

普通词语、固定句长、常见语序和单一章节模板不能成为通用硬门

## 7. 验证与修复

事实、条件、范围、数值、来源和源内容完整性优先于风格；发现确定性问题时读取 `runtime/verification-and-repair.md`

修复只改最小范围；补丁绑定文档摘要、节点、旧文本和出现次数；低一级范围能够修复时不得扩大，默认禁止重新生成全文

## 8. 用户金标边界

修改本技能、规则、检查器或案例时读取 `constitution/user-gold-standard.md`

模型生成的案例只能进入 `evals/candidate/`；用户明确接受后才能进入 `evals/gold/`；用户明确拒绝后进入 `evals/rejected/`

脚本通过和模型评分不能替代用户审核；候选案例未审核时，最终状态只能写成“候选版本等待用户审核”
