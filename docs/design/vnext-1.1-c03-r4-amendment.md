# vNext 1.1 C03-R4 英文括号大小写修正案

## 1. 修订原因

`CANDIDATE-03-R3` 已经修复命令主体和 npm 解释范围，但括号内通用英文类别写成 `package manager`；用户要求括号内普通英文名称和类别使用标题式大小写，因此该版本转为 `REJECTED-03-R3`

这项修订只处理大小写与来源边界；Gold 快照、第一轮 20 个未见答案和 vNext 1.1 权威计划保持不变

## 2. 确定规则

- 普通英文名称和类别在括号内使用标题式大小写，例如 `Package Manager`、`Continuous Integration` 和 `Hypertext Transfer Protocol`
- 官方品牌、产品名称和正式拼写优先，例如 `npm`、`Node.js`、`iOS`、`macOS` 和 `scikit-learn`
- 缩写保持登记形式，例如 `CI` 和 `HTTP`
- `npm` 不是 `Node Package Manager` 的首字母缩写；`Package Manager` 只说明通用类别，来源见 [npm 官方命名规则](https://docs.npmjs.com/policies/logos-and-usage/)
- 代码块、行内代码、网址、路径和逐字引用保持原始字符；逐字材料中的 `NPM` 不接受正文规范化
- 未登记名称先核对官方来源；官方大小写仍无法确认时返回 `REVIEW_REQUIRED`

## 3. 规则等级

登记表已经提供确定形式时，官方大小写、括号英文形式和禁止展开规则属于 `MACHINE_FINAL`；程序能够比较精确值，因此错误会直接阻止候选继续

未登记术语的官方形式不属于确定事实；程序只报告证据缺口并返回 `REVIEW_REQUIRED`，因为猜测大小写可能制造不存在的官方名称

## 4. C03 生命周期

- `CANDIDATE-03-R3` 转为 `REJECTED-03-R3`；拒绝证据与用户决定摘要绑定
- `CANDIDATE-03-R4` 只把 `package manager` 改为 `Package Manager`
- R4 的命令主体、npm 官方小写、三种用途、退出码、CI 和证据边界保持不变
- R4 继续是 Candidate；自动检查通过不能代替用户接受

## 5. 验收边界

本轮增加 12 个确定性案例、4 个语境案例和 4 个运行时测试；新增测试分别覆盖标题式大小写、官方混合大小写、逐字材料豁免、伪造全称阻断和未知官方写法复核

第一轮未见测试中的 3 个中文句号硬错误保持原样；第二轮未见案例继续停止生成，因为修复历史候选不能代替前向泛化证据
