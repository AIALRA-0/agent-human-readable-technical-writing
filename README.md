<div align="center">

<h1 align="center">AIALRA 可验证中文写作</h1>

<p><strong>完整保留源信息，分开追踪补充解释，再生成能够阅读、核对和局部修复的中文</strong></p>

<p><strong>当前状态：vNext 1.1 运行时候选等待第二轮用户审核</strong></p>

<p>
  <a href="evals/candidate/REVIEW-PACKET.md">第二轮审核包</a> ·
  <a href="docs/design/vnext-1.1-authoritative-plan.md">权威设计</a> ·
  <a href="docs/audits/2026-08-30-vnext-1.1-round-1/audit.md">实施审计</a> ·
  <a href="README.en.md">English</a>
</p>

</div>

这个仓库维护 `human-readable-technical-writing` Codex Skill；vNext 1.1 把写作任务拆成基础操作和解释增量，并把原文、用户补充、外部背景与推断分别登记

首轮人工审核已经形成 2 个 gold 和 10 个 rejected；10 个拒绝案例已经生成 R2 修订版，但这些修订版仍是 `candidate`，需要用户再次逐项审核

## 1. 项目解决什么问题

普通改写容易只保留大意；普通解释又可能加入没有来源的背景，甚至把补充内容写成原作者结论

vNext 1.1 同时保护：

- 源内容完整；改写和翻译保留所有承担信息作用的原文内容
- 补充来源清楚；背景、定义、机制、例子和推断分别登记
- 修复范围可控；一个词或一段有问题时，只修改对应范围
- 人工决定有效；模型评分不能把候选自动改成 gold

这套系统不强制所有中文使用同一种句式；事实、条件、范围、数值、来源和原文完整性属于硬边界，语气与普通叙述顺序主要由用户金标持续校准

## 2. 当前处理流程

```mermaid
flowchart TD
    A["编译基础操作、解释增量与读者配置"] --> B{"歧义是否会改变事实、范围或输出规模"}
    B -->|"会"| C["一次说明问题、选项、推荐默认和影响"]
    C --> A
    B -->|"不会"| D["登记源语义、补充背景和推断"]
    D --> E["建立段落合同与覆盖矩阵"]
    E --> F["直接生成目标正文"]
    F --> G["运行确定性检查与结构验证"]
    G --> H["生成摘要绑定的精确补丁"]
    H --> I["验证局部与全文"]
    I --> J["用户人工审核"]
    J -->|"接受"| K["进入 gold"]
    J -->|"拒绝"| L["进入 rejected 并生成下一版 candidate"]
```

图 2.1 vNext 1.1 从任务编译到用户金标的处理路径

图中的前半段保证来源与内容覆盖，后半段保证确定性问题能够定位和回滚；流程结果只有在用户明确接受后才会进入 gold，自动测试通过只允许生成审核包

## 3. 任务合同

每个任务由两个独立维度组成：

- 基础操作；决定对原始材料执行改写、翻译、压缩、解释、生成或仅排版
- 解释增量；决定允许增加术语注释、必要背景、教学说明或带来源的研究补充

| 维度 | 可选值 | 决定内容 |
| --- | --- | --- |
| 基础操作 | `TRANSFORM`、`TRANSLATE`、`COMPRESS`、`EXPLAIN`、`GENERATE`、`FORMAT_ONLY` | 对原始材料做什么 |
| 解释增量 | `NONE`、`GLOSS`、`EXPLANATORY`、`TEACHING`、`RESEARCHED` | 为了让目标读者理解，可以增加多少说明 |

表 3.1 写作任务的两个独立维度

`TRANSLATE + EXPLANATORY` 表示完整翻译原文，同时补充理解原文所需的背景和机制；补充解释具有独立来源，不能抵消原文遗漏

## 4. 来源与覆盖

中间层区分：

- `SOURCE`；原文直接表达，并指向原文位置
- `USER_SUPPLIED`；用户在当前任务中补充的事实或要求
- `EXTERNAL_BACKGROUND`；为了理解而加入，并登记外部来源
- `INFERENCE`；根据已经登记的内容推导，并保留证据与置信度

改写和翻译分别计算源信息覆盖与补充背景来源覆盖；当前 10 个 R2 的源信息映射为 `35/35`，补充背景映射为 `35/35`，原因是每个语义单元都具有支持映射；该结果只能证明结构覆盖完整，不能证明文字已经达到用户偏好

## 5. 可执行运行时

本地入口提供：

- `compile`；填充确定性默认值并验证任务合同
- `verify`；检查来源、段落、术语、组件、支持映射和证据边界
- `repair`；验证精确补丁并执行最小替换
- `report`；输出 `PASS`、`FAIL` 或 `REVIEW_REQUIRED`，同时说明原因、影响和下一步

```powershell
python scripts/run_vnext.py --help # 显示 compile、verify、repair 和 report 四个入口；该命令只查看帮助，不修改文件
```

运行时代码不自动猜测任意自然语言含义；Agent 负责建立语义模型，程序负责检查结构、引用、覆盖状态和精确修改，因此项目没有声称能够用代码绝对证明完全同义

## 6. 首次验证

需要 Python `3.12` 或兼容版本，并安装 `jsonschema` 与 `PyYAML`；前者验证 JSON Schema，后者读取 YAML 配置

```powershell
python scripts/validate_vnext_foundation.py # 核对权威计划摘要、合同、YAML 分类、链接、SVG 和公开文件隐私模式

python scripts/run_vnext_fixtures.py # 执行 160 个确定性正反例；预期结果为 160/160

python scripts/validate_vnext_round2.py # 核对 22 个生命周期记录、10 个拒绝回归、10 个 R2 和全部来源映射

python -m unittest discover -s tests -p "test_deterministic_committer.py" -v # 执行 18 个摘要、范围、冲突、回滚和原子写入测试

python -m unittest discover -s tests -p "test_vnext_runtime.py" -v # 执行 6 个 compile、verify、repair 和 report 运行时测试

python scripts/build_candidate_review_packet.py # 从 10 个结构化 R2 重新生成第二轮人工审核包
```

当前本地结果：

- 160 个确定性案例全部符合预期；原因是九类规则分别具有通过与失败输入，影响是已登记硬规则可以自动回归
- 22 个生命周期记录全部有效；原因是 gold、rejected 与 candidate 使用同一状态合同，影响是模型不能越过用户决定
- 10 个旧拒绝答案全部被发现，10 个 R2 硬错误为 0；原因是案例级回归锁直接对应首轮反馈，影响是 R2 可以进入人工复审
- 18 个精确补丁测试与 6 个运行时测试全部通过；原因是摘要、范围、次数、冲突和结构入口都具有可执行测试，影响是无效修改会在写入前停止

这些数字不等于用户验收；R2 必须继续由用户逐项决定

## 7. 仓库结构

| 目录 | 作用 |
| --- | --- |
| `constitution/` | 保存源信息优先、来源分层、规则等级和用户金标边界 |
| `runtime/` | 保存任务编译、来源理解、内容骨架、成文、验证和修复说明 |
| `contracts/` | 保存任务、来源、段落、支持映射、Finding、Patch 与案例生命周期 Schema |
| `profiles/` | 保存操作、解释增量、文体、媒介、读者、组件和 Lucas 配置 |
| `registries/` | 保存术语、单位和受保护模式 |
| `validators/` | 分离确定性规则、语境候选和建议性检查 |
| `patcher/` | 保存补丁规划、冲突处理、事务验证和确定性提交器 |
| `evals/` | 分开保存 candidate、gold、rejected 和确定性案例 |

表 7.1 vNext 1.1 目录职责

完整设计见 [vNext 1.1 权威计划](docs/design/vnext-1.1-authoritative-plan.md)；首轮实施证据与差距见 [实施审计](docs/audits/2026-08-30-vnext-1.1-round-1/audit.md)

## 8. 隐私与安全

公开仓库只保存合成案例、脱敏技术反馈、仓库相对路径和公开资料链接

禁止进入仓库：

- 原始完整对话、账户信息和个人绝对路径
- 令牌、密码、Cookie、私钥和连接字符串
- 未脱敏图片、远程图片请求和含活动内容的 SVG
- 没有来源却作为事实写入的补充解释

每次远程推送以前执行独立发布安全门禁；发现真实秘密已经进入远端时停止普通更新，先轮换凭据并按照事故流程处理历史内容

## 9. 当前边界与下一步

`main` 在第二轮审核完成前保持冻结；候选 Skill 不安装到本机正式目录

下一步逐项审核 [10 个 R2 候选](evals/candidate/REVIEW-PACKET.md)；只有全部接受后，首批锚点才会统一成为 12 个 gold，并进入正式分支、安装和新任务触发验收

## 10. 许可

仓库采用 [MIT License](LICENSE)；第三方方法与实质内容的来源和许可证记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
