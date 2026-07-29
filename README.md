# Codex 中文技术写作技能

这个仓库提供一套面向第一次阅读者的中文技术写作规则

它重点解决下面几类问题：

- 技术词首次出现时没有解释
- 结论缺少原因和后果
- 多个事实挤在同一行
- 条件分支没有缩进
- 内部状态名称被当作自然语言使用
- 代码缺少帮助理解的注释

## 文件说明

- `SKILL.md` 是 Codex 按需读取的核心技能
- `AGENTS.example.md` 是可以复制到个人配置中的全局规则模板
- `references/style-rules.md` 保存详细写作规则和示例
- `scripts/Test-HumanReadableChinese.ps1` 检查机械写作错误
- `scripts/Test-HumanReadableChinese.Tests.ps1` 验证检查脚本的正反案例
- `evals/Invoke-QualityEvaluation.20260729.ps1` 保存二十六组完整问答测试
- `QA-CASES.md` 展示全部问题和完整回答

## 安装方式

把仓库复制到个人技能目录：

```powershell
git clone https://github.com/AIALRA-0/codex-human-readable-chinese.git "$HOME\.codex\skills\human-readable-technical-writing" # 下载技能并放入个人技能目录
Copy-Item "$HOME\.codex\skills\human-readable-technical-writing\AGENTS.example.md" "$HOME\.codex\AGENTS.md" # 把全局规则模板复制到个人配置目录
```

如果个人配置目录已经存在 `AGENTS.md`，先人工合并内容，避免覆盖原有规则

## 调用方式

普通中文技术写作任务可以由 Codex 自动匹配技能

需要强制调用时，在问题开头加入：

> 使用 `$human-readable-technical-writing`，按照我的中文技术写作规范回答；交付前运行写作检查，检查失败就先修改再回答

## 验证方式

运行规则测试：

```powershell
pwsh -NoProfile -File ".\scripts\Test-HumanReadableChinese.Tests.ps1" # 执行全部正反规则测试
pwsh -NoProfile -File ".\evals\Invoke-QualityEvaluation.20260729.ps1" # 执行二十六组完整问答质量测试
pwsh -NoProfile -File ".\scripts\Export-QualityCases.ps1" # 重新生成完整问答案例文档
```

当前版本包含：

- 五十二组规则测试
- 二十六组完整问答测试
- 五种回答长度
- 二十六个内容方向
- 二十二种表达语气
- 十六种内容结构

## 许可证

本仓库使用 MIT 开源许可证（MIT License，作用解释：允许使用、修改和分发，但需要保留许可证说明）
