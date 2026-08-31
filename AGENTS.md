# 仓库范围

本仓库只维护 `human-readable-technical-writing` 写作技能

- 开始修改仓库以前完整读取 `constitution/principles.md`；口头声明不算完成，执行记录必须出现读取动作
- `docs/design/vnext-1.1-authoritative-plan.md` 是 vNext 1.1 的权威设计；不得用旧架构、旧测试目标或自行设计的发布系统替换
- 保持 `SKILL.md` 精简；详细契约、任务配置、组件规则和测试数据进入对应目录
- 候选案例只能进入 `evals/candidate/`；只有用户明确接受后才能进入 `evals/gold/`
- 普通词语、固定句长、常见语序和自然度检测不得升级成通用硬门
- 修改 vNext 基础以后运行 `scripts/validate_vnext_foundation.py` 和精确提交器专用测试；旧架构评测不作为候选版本的验收依据
- 用户没有要求时，不增加发布架构、账户权限、密钥、远端规则或其他无关基础设施
- GitHub 是托管远端代码的平台；向 GitHub 推送前使用 `$github-safe-publish`，并遵守用户明确指定的分支和发布范围
