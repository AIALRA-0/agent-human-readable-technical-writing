[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$lintPath = Join-Path $PSScriptRoot 'Test-HumanReadableChinese.ps1'

function Invoke-Lint(
    [string]$Value,
    [string]$CaptionStyle = 'Personal',
    [bool]$AllowQuestionHeadings = $false,
    [bool]$AllowEditorialProcessNarrative = $false,
    [string[]]$RequiredTerms = @()
) {
    # 把正文安全传给独立检查进程，避免测试文字被 PowerShell 当成命令解释
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Value))
    $encodedTerms = @(
        $RequiredTerms |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
            ForEach-Object {
                [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes([string]$_))
            }
    )
    $termExpressions = @($encodedTerms | ForEach-Object {
        "[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('$_'))"
    })
    $requiredTermSetup = if ($termExpressions.Count -gt 0) {
        "`$requiredTerms = @(" + ($termExpressions -join ',') + ")`n"
    } else {
        "`$requiredTerms = @()`n"
    }
    $questionHeadingArgument = if ($AllowQuestionHeadings) { ' -AllowQuestionHeadings' } else { '' }
    $editorialProcessArgument = if ($AllowEditorialProcessNarrative) { ' -AllowEditorialProcessNarrative' } else { '' }
    $child = @"
`$text = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('$encoded'))
$requiredTermSetup& '$lintPath' -Text `$text -CaptionStyle '$CaptionStyle' -RequiredTerm `$requiredTerms$questionHeadingArgument$editorialProcessArgument
"@
    $output = & pwsh -NoLogo -NoProfile -NonInteractive -Command $child 2>&1
    $exitCode = $LASTEXITCODE
    $json = $output -join [Environment]::NewLine
    return [pscustomobject]@{
        ExitCode = $exitCode
        Result = $json | ConvertFrom-Json
    }
}

$period = [char]0x3002
$fence = '```'
$cases = @(
    @{
        Name = '完整因果链通过'
        Text = '根据订单系统记录，每100笔订单约有9笔没有按时足量交付；继续积压会增加投诉，因此今天需要介入'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '原因先行的直接转折通过'
        Text = '真实硬件验证尚未完成，因此产品仍不能发布'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '自然中文语序通过'
        Text = '芯片本轮实现验证已经完成'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '明确动作主体通过'
        Text = '服务器继续运行任务；监督器在九条任务全部完成后生成报告'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '应用记录数值来源通过'
        Text = '服务器监测系统显示，数据盘剩余 8 GB 千兆字节（Gigabyte）；继续运行可能耗尽空间'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '计算数值来源通过'
        Text = '根据订单系统记录的每天新增 62 笔和完成 55 笔计算，积压每天净增 $62-55=7$ 笔'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '用户输入数值来源通过'
        Text = '根据用户本次提供的数据，按时足量交付率为 $91\%$'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '经验估计数值来源通过'
        Text = '根据运维团队最近十次同规模迁移的经验，本次预留 30 分钟属于经验估计'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '多行列表通过'
        Text = "继续积压会扩大损失，所以先处理这些订单：`n`n- 已经逾期的订单`n- 今天即将逾期的订单`n- 重要客户的订单`n`n这些订单最接近造成实际损失；先指定负责人，再安排处理时间"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '单结果分支通过'
        Text = "数据来源会影响可信度，所以先确认来源：`n`n- 如果来自过去结果，核对历史记录`n- 如果来自未来预测，核对预测依据`n`n两类数据的证明能力不同，因此不能按照相同可信程度使用"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '多结果分支通过'
        Text = "如果来自未来预测，需要完成下面两项检查：`n`n- 核对收入是否过于乐观`n- 核对成本是否漏算`n`n两项都通过后，才能使用预测结果"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '真实界面文字引号通过'
        Text = '界面显示“保存失败”；这说明修改没有写入文件'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '用户原始问题引用通过'
        Text = "> Cpk从1.45掉到1.08，DNS和API都报错，马上怎么办`n`n回答正文说明具体原因和后果"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '徽章和表格结构通过'
        Text = "[![Quality checks](https://example.com/badge.svg)](https://example.com/checks)`n`n<div align=`"center`">`n`n表 1 检查结果`n`n| 项目 | 内容 |`n|---|---|`n| 状态、原因和后果 | 原始证据 |`n`n</div>"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '缩写映射通过'
        Text = 'DNS 域名系统（Domain Name System）负责把网站名称转换成网络地址；转换失败后，新网页无法找到服务器'
        RequiredTerms = @('DNS')
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '内部名称与解释共同保留通过'
        Text = '项目把当前状态记录为 `FLOW_VALIDATED`；这个内部状态表示本轮软件流程已经完成'
        RequiredTerms = @('FLOW_VALIDATED')
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '内部名称映射通过'
        Text = '规定流程已经跑通，可以结束流程验证；原始记录中的 `FLOW_VALIDATED` 只证明流程完成，不代表产品发布'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '竖向流程图通过'
        Text = "流程图按照执行顺序从上到下排列：`n`n<div align=`"center`">`n`n${fence}mermaid`n%% 从输入开始展示完整处理顺序`nflowchart TD`n    A[读取输入] --> B[检查内容]`n    B --> C[输出结果]`n${fence}`n`n图 1 内容处理顺序`n`n</div>`n`n竖向排列让阅读顺序和执行顺序保持一致"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '十进制层级章节通过'
        Text = "## 1 环境`n`nVivado 芯片设计套件（Vivado Design Suite）负责完成芯片设计处理`n`n项目 Vivado 冻结版本为：2024.1`n`n### 1.1 目标器件`n`n目标器件冻结为：``xcvu19p-fsva3824-1-e```n`n## 2 结果`n`n全部检查已经完成"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '中文顺序步骤通过'
        Text = "第一步 安装依赖`n`n安装完成后检查命令能否正常运行`n`n第二步 运行检查`n`n检查失败时先修复问题，再生成交付文件"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '紧凑键值通过'
        Text = "Vivado 芯片设计套件（Vivado Design Suite）负责综合、布局、布线和时序检查`n`n项目 Vivado 冻结版本为：2024.1`n`n目标器件冻结为：``xcvu19p-fsva3824-1-e``"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '图表独立编号通过'
        Text = "<div align=`"center`">`n`n表 1 第一轮结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n表 2 第二轮结果`n`n| 项目 | 结果 |`n|---|---|`n| 第二轮 | 通过 |`n`n![处理结果](https://example.com/result.png)`n`n图 1 处理结果`n`n![复查结果](https://example.com/review.png)`n`n图 2 复查结果`n`n</div>"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '出版格式表题在上通过'
        Text = "<div align=`"center`">`n`n表 1 检查结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n</div>"
        CaptionStyle = 'Publication'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '陈述式标题通过'
        Text = "## 1 本项目禁止形式化验证的原因`n`n形式化验证不在当前范围内`n`n## 2 历史证据的独立保存方式`n`n历史证据保存在独立目录中"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '问答页面疑问句标题通过'
        Text = "## 1 为什么本项目禁止形式化验证`n`n形式化验证不在当前范围内`n`n## 2 历史证据怎样独立保存`n`n历史证据保存在独立目录中"
        AllowQuestionHeadings = $true
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '按章节重新编号图表通过'
        Text = "## 1 第一章`n`n<div align=`"center`">`n`n表 1.1 第一项结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一项 | 通过 |`n`n表 1.2 第二项结果`n`n| 项目 | 结果 |`n|---|---|`n| 第二项 | 通过 |`n`n![第一章结果](https://example.com/one.png)`n`n图 1.1 第一章结果`n`n</div>`n`n## 2 第二章`n`n<div align=`"center`">`n`n表 2.1 第三项结果`n`n| 项目 | 结果 |`n|---|---|`n| 第三项 | 通过 |`n`n![第二章结果](https://example.com/two.png)`n`n图 2.1 第二章结果`n`n</div>"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = 'IEEE顺序引用通过'
        Text = "正式文稿按照正文首次引用的顺序分配编号 [1]`n`n图题放在图形下方，表题放在表格上方 [2]`n`n## 1 参考文献`n`n[1] IEEE, IEEE Editorial Style Manual for Authors, 2025. [Online]. Available: https://example.com/style`n`n[2] IEEE, Guidelines for Figures and Tables, 2025. [Online]. Available: https://example.com/figures"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '独立语句逐行注释通过'
        Text = "两行代码能够分别执行，所以每行都说明目的：`n`n${fence}csharp`nvar request = BuildRequest(); // 创建发送请求需要的数据`nvar response = Send(request); // 发送请求并保存返回结果`n${fence}"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '网络故障说明通过'
        Text = "DNS 域名系统（Domain Name System）负责把网站名称转换成网络地址`n`n这个转换暂时失败，所以新网页打不开`n`n聊天软件仍在使用已经建立的连接，因此消息暂时还能发送"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '订单交付分析通过'
        Text = "OTIF 按时足量交付率（On Time In Full）统计订单是否按时并且数量完整地交付`n`n根据用户本次提供的订单数据：`n`n- 每100笔订单约有9笔没有同时满足这两个条件`n- 还有180笔订单尚未处理`n`n继续积压会增加逾期量和客户投诉，因此今天需要介入`n`n继续等待最容易扩大以下订单的客户损失：`n`n- 已经逾期的订单`n- 今天即将逾期的订单`n- 重要客户的订单`n- 因缺货而无法继续处理的订单`n`n这些订单最接近造成实际损失；先指定负责人和完成时间，再判断需要增加哪类资源：`n`n- 人员`n- 车辆`n- 库存"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '医疗结果说明通过'
        Text = "eGFR 估算肾小球滤过率（Estimated Glomerular Filtration Rate）用于估计肾脏过滤血液的能力`n`n这个数值低于正常范围，而且肌酐持续升高，所以肾功能可能正在下降`n`n单次结果还会受到脱水和药物影响，因此医生需要结合复查结果再判断原因"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '还款能力分析通过'
        Text = "DSCR 偿债能力覆盖倍数（Debt Service Coverage Ratio）比较可用于还款的资金和需要偿还的本息`n`n漏扣下面任何一项支出都会高估还款能力：`n`n- 税款`n- 设备投入`n- 日常经营资金`n`n数据来源会影响计算结果的可信度，所以需要分开核对：`n`n- 如果来自过去的实际结果，需要核对下面三类记录：`n  - 银行流水`n  - 纳税记录`n  - 财务记录`n`n- 如果来自未来的预测，需要核对下面三项假设：`n  - 收入是否过于乐观`n  - 成本是否漏算`n  - 回款时间是否过早`n`n两类数据的证明能力不同，因此不能按照相同可信程度使用"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '芯片验证说明通过'
        Text = "CDC 时钟区域跨越检查（Clock Domain Crossing）用于发现信号在不同时钟区域之间传递时可能出现的不稳定问题`n`n检查结果没有发现问题，所以这部分流程可以通过`n`n真实板卡尚未运行这些结果，因此流程通过不能替代产品发布"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '制造质量说明通过'
        Text = '$C_{pk}$ 过程能力指数（Process Capability Index）比较生产波动和允许范围' + "`n`n当前数值下降说明产品更容易接近或越过规格边界`n`n连续三批都出现相同趋势，所以先检查三类原因：`n`n- 设备是否漂移`n- 原料是否变化`n- 测量是否存在误差`n`n这些检查能够判断变化来自生产过程还是测量过程，再决定是否暂停生产"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '数学公式排版通过'
        Text = '根据本题给定条件，当 $x \geq 3$ 时，执行下一步'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '冒号行尾通过'
        Text = "需要检查下面三项：`n`n- 网络连接`n- 浏览器设置`n- 网站状态"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '问号行尾通过'
        Text = '是否继续执行？'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '感叹号行尾通过'
        Text = '请立即停止写入！'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '省略号行尾通过'
        Text = '任务仍在运行……'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '列表式代码同行注释通过'
        Text = "命令逐行执行，所以每一行都说明用途：`n`n${fence}powershell`nGet-Process # 查看当前运行的程序`nGet-Service # 查看系统服务及其状态`n${fence}"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '段落式代码开头注释通过'
        Text = "代码按照两个逻辑段处理资料：`n`n${fence}csharp`n// 先处理资料缺失情况，避免后续读取空值`nif (user.Profile is null)`n{`n    return ProfileResult.Missing();`n}`n`n// 资料存在后再读取城市并返回正常结果`nreturn ProfileResult.Found(user.Profile.City);`n${fence}"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '带注释数据示例通过'
        Text = "严格数据文件通过文件交付，对话只展示带注释的等价结构：`n`n${fence}jsonc`n// 这个配置限制请求等待时间，避免程序无限等待`n{`n  `"timeoutSeconds`": 30`n}`n${fence}"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '准确执行和完成状态通过'
        Text = '操作人员执行恢复命令；恢复任务完成后，监控系统保存结果'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '较长单一关系句通过'
        Text = '自动恢复时间目标说明系统故障后允许服务中断的最长时间以及技术团队必须恢复核心功能的期限，业务负责人据此安排人工接管方案'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '明确主体连续重复通过'
        Text = "质量负责人复核测量记录`n`n质量负责人批准货物放行`n`n质量负责人保存处置证据"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '直接状态结论前置通过'
        Text = "本轮备份任务已经完成`n`n摘要记录显示原文件和副本内容一致"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '单次证据边界通过'
        Text = '现有记录只覆盖软件测试，不能证明真实设备状态'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '列表式代码缺少同行注释失败'
        Text = "命令如下：`n`n${fence}powershell`nGet-Process`nGet-Service # 查看系统服务及其状态`n${fence}"
        ExpectedRule = 'LIST_CODE_LINE_REQUIRES_INLINE_COMMENT'
    },
    @{
        Name = '名词化弱动词失败'
        Text = '维护人员进行日志检查，并完成了对报警原因的分析'
        ExpectedRule = 'WEAK_NOMINALIZED_VERB_SHOULD_BE_PRECISE'
    },
    @{
        Name = '嵌套长句失败'
        Text = '服务器日志连续出现连接失败，客户端随后重复发送请求，网关队列继续增长，后端处理速度开始下降，因此用户等待时间越来越长并且新的请求也无法及时进入处理'
        ExpectedRule = 'OVERLONG_NESTED_SENTENCE_SHOULD_SPLIT'
    },
    @{
        Name = '重复边界申明失败'
        Text = '现有记录不能证明板卡稳定，也不能证明产品可以发布'
        ExpectedRule = 'REPEATED_DEFENSIVE_BOUNDARY_SHOULD_CONSOLIDATE'
    },
    @{
        Name = '段落式代码缺少开头注释失败'
        Text = "代码如下：`n`n${fence}csharp`n// 先处理资料缺失情况`nif (user.Profile is null)`n{`n    return ProfileResult.Missing();`n}`n`nreturn ProfileResult.Found(user.Profile.City);`n${fence}"
        ExpectedRule = 'CODE_PARAGRAPH_REQUIRES_LEADING_COMMENT'
    },
    @{
        Name = '独立语句只注释重要行失败'
        Text = "两行代码能够分别执行：`n`n${fence}csharp`nvar request = BuildRequest(); // 创建发送请求需要的数据`nvar response = Send(request);`n${fence}"
        ExpectedRule = 'INDEPENDENT_CODE_LINE_REQUIRES_INLINE_COMMENT'
    },
    @{
        Name = '严格数据代码块失败'
        Text = "配置如下：`n`n${fence}json`n{`n  `"timeoutSeconds`": 30`n}`n${fence}"
        ExpectedRule = 'STRICT_JSON_REQUIRES_ANNOTATED_JSONC'
    },
    @{
        Name = '中文句号失败'
        Text = "结果已经完成$period"
        ExpectedRule = 'FORBIDDEN_CHINESE_PERIOD'
    },
    @{
        Name = '含糊并列标题失败'
        Text = "# 结果与风险`n内容；"
        ExpectedRule = 'PARALLEL_OR_AMBIGUOUS_HEADING'
    },
    @{
        Name = '先说结论套话失败'
        Text = '先说结论：项目已经完成；'
        ExpectedRule = 'STOCK_META_WRITING_PHRASE'
    },
    @{
        Name = '简单来说套话失败'
        Text = '简单来说：项目已经完成；'
        ExpectedRule = 'STOCK_META_WRITING_PHRASE'
    },
    @{
        Name = '需要注意套话失败'
        Text = '需要注意的是，仍然存在风险；'
        ExpectedRule = 'STOCK_META_WRITING_PHRASE'
    },
    @{
        Name = '延迟主语失败'
        Text = '已经完成的是芯片本轮实现验证；'
        ExpectedRule = 'POSSIBLY_DELAYED_SUBJECT'
    },
    @{
        Name = '多个对象后的代词指向含糊失败'
        Text = '服务器和监督器都在运行，它完成后会生成报告'
        ExpectedRule = 'POSSIBLY_AMBIGUOUS_PRONOUN_REFERENCE'
    },
    @{
        Name = '发布动作缺少主体失败'
        Text = '持续集成检查完成后就会发布'
        ExpectedRule = 'POSSIBLY_MISSING_ACTION_SUBJECT'
    },
    @{
        Name = '业务数值缺少来源失败'
        Text = '数据盘只剩 8 GB，继续运行可能耗尽空间'
        ExpectedRule = 'NUMERIC_CLAIM_REQUIRES_PROVENANCE'
    },
    @{
        Name = '装饰性引号失败'
        Text = '更像是“查地址的服务”暂时失灵；'
        ExpectedRule = 'POSSIBLY_DECORATIVE_QUOTATION'
    },
    @{
        Name = '行内四类列表失败'
        Text = '优先找出四类订单：逾期订单、重要订单、缺货订单、停滞订单；'
        ExpectedRule = 'INLINE_ENUMERATION_SHOULD_BREAK'
    },
    @{
        Name = '行内以下列表失败'
        Text = '特别要确认：税款、设备投入、日常经营资金；'
        ExpectedRule = 'INLINE_ENUMERATION_SHOULD_BREAK'
    },
    @{
        Name = '行内分支失败'
        Text = '核对数字是过去结果还是未来预测；'
        ExpectedRule = 'INLINE_BRANCH_SHOULD_BREAK'
    },
    @{
        Name = '多个的堆叠失败'
        Text = '芯片本轮的实现流程的验证工作的结果已经完成；'
        ExpectedRule = 'POSSIBLY_STACKED_DE_MODIFIERS'
    },
    @{
        Name = '括号过载失败'
        Text = '结果（第一项）（第二项）（第三项）；'
        ExpectedRule = 'PARENTHESIS_OVERLOAD'
    },
    @{
        Name = '字段标签式解释失败'
        Text = 'Codex 编程智能体（Codex，作用解释：按照指令处理内容的工具）可以完成任务'
        ExpectedRule = 'FIELD_LABEL_EXPLANATION_SHOULD_BE_NATURAL_PROSE'
    },
    @{
        Name = '小写英文正文失败'
        Text = '当前 backlog 数量增加；'
        ExpectedRule = 'POSSIBLY_UNTRANSLATED_LOWERCASE_ENGLISH'
    },
    @{
        Name = '未解释缩写失败'
        Text = '当前 DNS 出现故障；'
        ExpectedRule = 'POSSIBLY_UNEXPLAINED_FIRST_ENGLISH_TERM'
    },
    @{
        Name = '原始术语被替换失败'
        Text = '域名系统负责把网站名称转换成网络地址'
        RequiredTerms = @('DNS')
        ExpectedRule = 'ORIGINAL_TERM_MUST_BE_RETAINED'
    },
    @{
        Name = '原始术语缺少解释失败'
        Text = '项目状态为 `FLOW_VALIDATED`'
        RequiredTerms = @('FLOW_VALIDATED')
        ExpectedRule = 'ORIGINAL_TERM_REQUIRES_EXPLANATION'
    },
    @{
        Name = '单位映射顺序失败'
        Text = '单位每升（U/L，表示样本活性）；'
        ExpectedRule = 'UNIT_ABBREVIATION_MUST_LEAD_MAPPING'
    },
    @{
        Name = '行内名词排比失败'
        Text = '问题可能来自网站名称转换、浏览器设置或网站本身；'
        ExpectedRule = 'INLINE_NOUN_ENUMERATION_SHOULD_BREAK'
    },
    @{
        Name = '项目符号内部排比失败'
        Text = '- 核对银行流水、纳税记录和财务记录；'
        ExpectedRule = 'INLINE_NOUN_ENUMERATION_SHOULD_BREAK'
    },
    @{
        Name = '行内数字证据失败'
        Text = '按时足量交付率为91%；180笔订单尚未处理；'
        ExpectedRule = 'PARALLEL_NUMERIC_FACTS_SHOULD_BREAK'
    },
    @{
        Name = '顶格条件分支失败'
        Text = "如果完成数量低于新增数量，积压会扩大；`n`n如果完成数量高于新增数量，检查最老订单；"
        ExpectedRule = 'PARALLEL_BRANCHES_REQUIRE_INDENTATION'
    },
    @{
        Name = '单结果分支错误缩进失败'
        Text = "- 如果切换手机流量后能够打开`n  - 当前无线网络更可能有问题"
        ExpectedRule = 'SINGLE_OUTCOME_BRANCH_SHOULD_STAY_INLINE'
    },
    @{
        Name = '行尾中文分号失败'
        Text = '当前无线网络更可能有问题；'
        ExpectedRule = 'FORBIDDEN_LINE_END_SEMICOLON'
    },
    @{
        Name = '引出句使用分号失败'
        Text = "面向普通读者的正文可以这样写；`n`n正文内容；"
        ExpectedRule = 'INTRODUCER_REQUIRES_COLON'
    },
    @{
        Name = '过程能力符号错误大写失败'
        Text = 'CPK 过程能力指数（Process Capability Index）用于比较生产波动和允许范围；'
        ExpectedRule = 'NONCANONICAL_CPK_CASE'
    },
    @{
        Name = '过程能力符号未使用数学排版失败'
        Text = 'Cpk 过程能力指数（Process Capability Index）用于比较生产波动和允许范围；'
        ExpectedRule = 'MATH_NOTATION_SHOULD_USE_LATEX'
    },
    @{
        Name = '上下标未使用数学排版失败'
        Text = 'Cₚₖ 用于比较生产波动和允许范围；'
        ExpectedRule = 'MATH_NOTATION_SHOULD_USE_LATEX'
    },
    @{
        Name = '不等式未使用数学排版失败'
        Text = '当 x>=3 时，执行下一步；'
        ExpectedRule = 'MATH_NOTATION_SHOULD_USE_LATEX'
    },
    @{
        Name = '多章节缺少编号失败'
        Text = "## 环境`n`n环境已经核对`n`n## 结果`n`n结果已经确认"
        ExpectedRule = 'SECTION_HEADING_REQUIRES_HIERARCHICAL_NUMBER'
    },
    @{
        Name = '章节从零开始失败'
        Text = "## 0 环境`n`n环境已经核对`n`n## 1 结果`n`n结果已经确认"
        ExpectedRule = 'SECTION_NUMBER_MUST_START_AT_ONE'
    },
    @{
        Name = '章节编号跳号失败'
        Text = "## 1 环境`n`n环境已经核对`n`n## 3 结果`n`n结果已经确认"
        ExpectedRule = 'SECTION_NUMBER_SEQUENCE_INVALID'
    },
    @{
        Name = '章节编号层级错误失败'
        Text = "## 1 环境`n`n### 2 版本`n`n版本已经核对`n`n## 2 结果`n`n结果已经确认"
        ExpectedRule = 'SECTION_NUMBER_DEPTH_MUST_MATCH_HEADING'
    },
    @{
        Name = '三级标题所属章节错误失败'
        Text = "## 1 环境`n`n### 2.1 版本`n`n版本已经核对`n`n## 2 结果`n`n结果已经确认"
        ExpectedRule = 'SECTION_NUMBER_PARENT_MISMATCH'
    },
    @{
        Name = '数字操作步骤失败'
        Text = "1. 安装依赖`n`n2. 运行检查"
        ExpectedRule = 'PROCEDURAL_STEPS_SHOULD_USE_CHINESE_ORDINALS'
    },
    @{
        Name = '步骤未从第一步开始失败'
        Text = "第二步 运行检查`n`n检查完成后生成结果"
        ExpectedRule = 'PROCEDURAL_STEPS_MUST_START_AT_FIRST'
    },
    @{
        Name = '步骤之间没有空行失败'
        Text = "第一步 安装依赖`n第二步 运行检查"
        ExpectedRule = 'PROCEDURAL_STEPS_REQUIRE_BLANK_LINE'
    },
    @{
        Name = '表格缺少编号标题失败'
        Text = "| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |"
        ExpectedRule = 'TABLE_REQUIRES_NUMBERED_TITLE'
    },
    @{
        Name = '表格编号跳号失败'
        Text = "表 1 第一轮结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n表 3 第二轮结果`n`n| 项目 | 结果 |`n|---|---|`n| 第二轮 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_SEQUENCE_INVALID'
    },
    @{
        Name = '默认表题在下失败'
        Text = "| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n表 1 检查结果"
        ExpectedRule = 'TABLE_TITLE_POSITION_INVALID'
    },
    @{
        Name = '出版格式表题在下失败'
        Text = "| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n表 1 检查结果"
        CaptionStyle = 'Publication'
        ExpectedRule = 'TABLE_TITLE_POSITION_INVALID'
    },
    @{
        Name = '表格章节编号不匹配失败'
        Text = "## 2 结果`n`n表 1.1 检查结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_SECTION_MISMATCH'
    },
    @{
        Name = '章节内表格使用单一编号失败'
        Text = "## 2 结果`n`n表 1 检查结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_FORMAT_MUST_MATCH_SECTION'
    },
    @{
        Name = '表格零编号失败'
        Text = "## 1 结果`n`n表 0.1 检查结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_MUST_NOT_USE_ZERO'
    },
    @{
        Name = '表格连字符编号失败'
        Text = "## 1 结果`n`n表 1-1 检查结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_FORMAT_MUST_MATCH_SECTION'
    },
    @{
        Name = '表格跨章节没有重新编号失败'
        Text = "## 1 第一章`n`n表 1.1 第一项结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一项 | 通过 |`n`n## 2 第二章`n`n表 2.2 第二项结果`n`n| 项目 | 结果 |`n|---|---|`n| 第二项 | 通过 |"
        ExpectedRule = 'TABLE_NUMBER_SEQUENCE_INVALID'
    },
    @{
        Name = '图片缺少编号图题失败'
        Text = '![处理结果](https://example.com/result.png)'
        ExpectedRule = 'FIGURE_REQUIRES_NUMBERED_CAPTION'
    },
    @{
        Name = '表格没有页面居中失败'
        Text = "| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n表 1 第一轮结果"
        ExpectedRule = 'TABLE_SHOULD_BE_CENTERED'
    },
    @{
        Name = '图片没有页面居中失败'
        Text = "![处理结果](https://example.com/result.png)`n`n图 1 处理结果"
        ExpectedRule = 'FIGURE_SHOULD_BE_CENTERED'
    },
    @{
        Name = '流程图没有页面居中失败'
        Text = "${fence}mermaid`nflowchart TD`n    A[开始] --> B[结束]`n${fence}`n`n图 1 处理流程"
        ExpectedRule = 'FIGURE_SHOULD_BE_CENTERED'
    },
    @{
        Name = '图题没有随图片居中失败'
        Text = "<div align=`"center`">`n`n![处理结果](https://example.com/result.png)`n`n</div>`n`n图 1 处理结果"
        ExpectedRule = 'VISUAL_CAPTION_SHOULD_BE_CENTERED'
    },
    @{
        Name = '默认表题没有随表格居中失败'
        Text = "表 1 第一轮结果`n`n<div align=`"center`">`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n</div>"
        ExpectedRule = 'VISUAL_CAPTION_SHOULD_BE_CENTERED'
    },
    @{
        Name = '出版文档表题没有随表格居中失败'
        Text = "表 1 第一轮结果`n`n<div align=`"center`">`n`n| 项目 | 结果 |`n|---|---|`n| 第一轮 | 通过 |`n`n</div>"
        CaptionStyle = 'Publication'
        ExpectedRule = 'VISUAL_CAPTION_SHOULD_BE_CENTERED'
    },
    @{
        Name = '同一汇总文档统一题注样式通过'
        Text = "## 1 案例汇总`n`n<div align=`"center`">`n`n表 1.1 第一组结果`n`n| 项目 | 结果 |`n|---|---|`n| 第一组 | 通过 |`n`n表 1.2 第二组结果`n`n| 项目 | 结果 |`n|---|---|`n| 第二组 | 通过 |`n`n</div>"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = 'Windows换行居中图片通过'
        Text = "<div align=`"center`">`r`n`r`n![处理结果](https://example.com/result.png)`r`n`r`n图 1 处理结果`r`n`r`n</div>"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = 'Windows换行技能元数据通过'
        Text = "---`r`nname: human-readable-technical-writing`r`ndescription: Create readable Chinese technical prose`r`n---`r`n`r`n# 人类可读技术写作`r`n`r`n读者先看到事实和原因，随后再判断结果"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = 'Windows换行流程图缺少图题失败'
        Text = ($fence + "mermaid`r`nflowchart TD`r`n    A[开始] --> B[结束]`r`n" + $fence)
        ExpectedRule = 'FIGURE_REQUIRES_NUMBERED_CAPTION'
    },
    @{
        Name = '图片编号跳号失败'
        Text = "![处理结果](https://example.com/result.png)`n`n图 2 处理结果"
        ExpectedRule = 'FIGURE_NUMBER_SEQUENCE_INVALID'
    },
    @{
        Name = '图片章节编号不匹配失败'
        Text = "## 2 结果`n`n![处理结果](https://example.com/result.png)`n`n图 1.1 处理结果"
        ExpectedRule = 'FIGURE_NUMBER_SECTION_MISMATCH'
    },
    @{
        Name = '章节内图片使用单一编号失败'
        Text = "## 2 结果`n`n![处理结果](https://example.com/result.png)`n`n图 1 处理结果"
        ExpectedRule = 'FIGURE_NUMBER_FORMAT_MUST_MATCH_SECTION'
    },
    @{
        Name = '图片零编号失败'
        Text = "## 1 结果`n`n![处理结果](https://example.com/result.png)`n`n图 0.1 处理结果"
        ExpectedRule = 'FIGURE_NUMBER_MUST_NOT_USE_ZERO'
    },
    @{
        Name = '图片零编号连字符失败'
        Text = "## 1 结果`n`n![处理结果](https://example.com/result.png)`n`n图 0-1 处理结果"
        ExpectedRule = 'FIGURE_NUMBER_MUST_NOT_USE_ZERO'
    },
    @{
        Name = '图片跨章节没有重新编号失败'
        Text = "## 1 第一章`n`n![第一章结果](https://example.com/one.png)`n`n图 1.1 第一章结果`n`n## 2 第二章`n`n![第二章结果](https://example.com/two.png)`n`n图 2.2 第二章结果"
        ExpectedRule = 'FIGURE_NUMBER_SEQUENCE_INVALID'
    },
    @{
        Name = '作者年份引用失败'
        Text = '现有规则要求先说明事实（Smith, 2024）'
        ExpectedRule = 'NON_IEEE_CITATION_STYLE'
    },
    @{
        Name = 'IEEE引用缺少文末条目失败'
        Text = '现有规则要求先说明事实 [1]'
        ExpectedRule = 'IEEE_CITATION_MISSING_REFERENCE'
    },
    @{
        Name = 'IEEE引用首次出现跳号失败'
        Text = "现有规则要求先说明事实 [2]`n`n## 1 参考文献`n`n[2] IEEE, Example, 2025. [Online]. Available: https://example.com"
        ExpectedRule = 'IEEE_CITATION_ORDER_INVALID'
    },
    @{
        Name = '双重否定失败'
        Text = '这个问题不能不处理'
        ExpectedRule = 'DOUBLE_NEGATIVE_SHOULD_BE_SIMPLIFIED'
    },
    @{
        Name = '不是而是否定先行失败'
        Text = '阻塞产品发布的不是本轮实现结果，而是真实硬件验证尚未完成'
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
    },
    @{
        Name = '并非而是否定先行失败'
        Text = '当前瓶颈并非服务器容量，而是审批记录缺少负责人'
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
    },
    @{
        Name = '不在于而在于否定先行失败'
        Text = '当前风险不在于切换速度，而在于回滚证据没有保存'
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
    },
    @{
        Name = '跨行否定先行失败'
        Text = "当前需要处理的不是服务器容量`n而是审批记录缺少负责人"
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
    },
    @{
        Name = '跨段真正问题否定先行失败'
        Text = "当前需要处理的并非服务器容量`n`n真正的问题是审批记录缺少负责人"
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
    },
    @{
        Name = '长文多章节否定先行复发失败'
        Text = "## 1 审批记录`n`n当前需要处理的不是服务器容量，而是审批记录缺少负责人`n`n## 2 回滚证据`n`n当前风险不在于切换速度，而在于回滚证据没有保存"
        ExpectedRule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
        ExpectedRuleCount = 2
    },
    @{
        Name = '逐字引用否定先行通过'
        Text = "> 当前需要处理的不是服务器容量，而是审批记录缺少负责人`n`n审批记录没有负责人，所以项目负责人需要先补齐责任信息"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '文档状态与后续补充失败'
        Text = '文档状态：第一部分已经形成真实截图、命令输出和智能体连接记录，后续章节将在同一时间线上继续补充'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '单独后续章节补充失败'
        Text = '后续章节将在同一时间线上继续补充'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '章节占位说明失败'
        Text = '本节先占位，稍后补充截图'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '跨行编辑过程说明失败'
        Text = "当前文档已经整理第一部分`n`n后续补充其余内容"
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '多章节编辑过程说明复发失败'
        Text = "## 1 第一部分`n`n后续章节继续补充`n`n## 2 第二部分`n`n本节先占位"
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
        ExpectedRuleCount = 2
    },
    @{
        Name = '逐字引用编辑过程说明通过'
        Text = "> 文档状态：第一部分已经形成真实截图，后续章节继续补充`n`n这句话只汇报写作进度，正式报告应当直接写明已经取得的证据"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '用户要求写作进度时通过'
        Text = '文档状态：第一部分已经形成真实截图，后续章节继续补充'
        AllowEditorialProcessNarrative = $true
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '证据范围正文通过'
        Text = "当前能够核实的证据包括真实截图、命令输出和智能体连接记录`n`n其余结论缺少对应证据，证据负责人补齐原始材料前不能写入正式结论"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '第二章下次再写失败'
        Text = '第一章已经整理完成，第二章等下一次再写'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '段落暂留空白失败'
        Text = '这一段暂留空白，等材料到了再填'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '报告以后添加内容失败'
        Text = '报告目前只写完截图部分，命令输出以后添加'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '正文下一轮继续失败'
        Text = '正文先放到这里，下一轮继续'
        ExpectedRule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
    },
    @{
        Name = '证据负责人补齐记录通过'
        Text = '命令输出缺少执行时间，证据负责人需要从服务器日志中补齐执行记录'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '正式报告更新任务通过'
        Text = '项目负责人需要在周五更新风险报告，并把审批结果发送给客户'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '简单键值拆行失败'
        Text = "项目 Vivado 冻结版本为：`n2024.1"
        ExpectedRule = 'SIMPLE_KEY_VALUE_SHOULD_STAY_INLINE'
    },
    @{
        Name = '冻结版本对象含糊失败'
        Text = '项目冻结版本为：2024.1'
        ExpectedRule = 'AMBIGUOUS_FROZEN_VERSION_OWNER'
    },
    @{
        Name = '为什么疑问句标题失败'
        Text = '## 1 为什么本项目禁止形式化验证'
        ExpectedRule = 'QUESTION_HEADING_SHOULD_BE_DECLARATIVE'
    },
    @{
        Name = '怎样疑问句标题失败'
        Text = '## 1 历史证据怎样独立保存'
        ExpectedRule = 'QUESTION_HEADING_SHOULD_BE_DECLARATIVE'
    },
    @{
        Name = '问号标题失败'
        Text = '## 1 本项目允许发布吗？'
        ExpectedRule = 'QUESTION_HEADING_SHOULD_BE_DECLARATIVE'
    }
)

$failures = [Collections.Generic.List[object]]::new()
$caseResults = [Collections.Generic.List[object]]::new()
foreach ($case in $cases) {
    # 旧题注参数继续传入以验证兼容性，全部文档仍统一要求表题在上
    $captionStyle = if ($case.ContainsKey('CaptionStyle')) { $case.CaptionStyle } else { 'Personal' }
    $allowQuestionHeadings = $case.ContainsKey('AllowQuestionHeadings') -and $case.AllowQuestionHeadings
    $allowEditorialProcessNarrative = $case.ContainsKey('AllowEditorialProcessNarrative') -and $case.AllowEditorialProcessNarrative
    $requiredTerms = if ($case.ContainsKey('RequiredTerms')) { @($case.RequiredTerms) } else { @() }
    $run = Invoke-Lint -Value $case.Text -CaptionStyle $captionStyle -AllowQuestionHeadings $allowQuestionHeadings -AllowEditorialProcessNarrative $allowEditorialProcessNarrative -RequiredTerms $requiredTerms
    if ($case.ContainsKey('ExpectedStatus') -and $case.ExpectedStatus -eq 'PASS') {
        $passed = $run.Result.status -eq 'PASS'
        $caseResults.Add([pscustomobject]@{
            name = $case.Name
            expected = 'PASS'
            actual = $run.Result.status
            rules = @($run.Result.issues | ForEach-Object { $_.rule })
            passed = $passed
        })
        if (-not $passed) {
            $failures.Add([pscustomobject]@{
                name = $case.Name
                expected = 'PASS'
                actual = $run.Result.status
                rules = @($run.Result.issues | ForEach-Object { $_.rule })
            })
        }
        continue
    }

    $actualRules = @($run.Result.issues | ForEach-Object { $_.rule })
    $expectedRuleCount = if ($case.ContainsKey('ExpectedRuleCount')) {
        [int]$case.ExpectedRuleCount
    }
    else {
        1
    }
    $actualRuleCount = @($actualRules | Where-Object { $_ -eq $case.ExpectedRule }).Count
    $passed = $actualRuleCount -ge $expectedRuleCount
    $caseResults.Add([pscustomobject]@{
        name = $case.Name
        expected = $case.ExpectedRule
        expected_rule_count = $expectedRuleCount
        actual_rule_count = $actualRuleCount
        actual = $run.Result.status
        rules = $actualRules
        passed = $passed
    })
    if (-not $passed) {
        $failures.Add([pscustomobject]@{
            name = $case.Name
            expected = $case.ExpectedRule
            expected_rule_count = $expectedRuleCount
            actual_rule_count = $actualRuleCount
            actual = $run.Result.status
            rules = $actualRules
        })
    }
}

$result = [pscustomobject]@{
    status = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
    case_count = $cases.Count
    failure_count = $failures.Count
    failures = @($failures)
    case_results = @($caseResults)
}

$result | ConvertTo-Json -Depth 6
if ($failures.Count -gt 0) {
    exit 1
}
exit 0
