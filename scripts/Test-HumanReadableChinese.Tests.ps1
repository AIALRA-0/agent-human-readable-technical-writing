[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$lintPath = Join-Path $PSScriptRoot 'Test-HumanReadableChinese.ps1'

function Invoke-Lint([string]$Value) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Value))
    $child = @"
`$text = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('$encoded'))
& '$lintPath' -Text `$text
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
        Text = '每100笔订单约有9笔没有按时足量交付；继续积压会增加投诉，因此今天需要介入'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '自然中文语序通过'
        Text = '芯片本轮实现验证已经完成'
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
        Text = "[![Quality checks](https://example.com/badge.svg)](https://example.com/checks)`n`n| 项目 | 内容 |`n|---|---|`n| 状态、原因和后果 | 原始证据 |"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '缩写映射通过'
        Text = 'DNS 域名系统（Domain Name System）负责把网站名称转换成网络地址；转换失败后，新网页无法找到服务器'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '内部名称映射通过'
        Text = '规定流程已经跑通，可以结束流程验证；原始记录中的 `FLOW_VALIDATED` 只证明流程完成，不代表产品发布'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '竖向流程图通过'
        Text = "流程图按照执行顺序从上到下排列：`n`n${fence}mermaid`n%% 从输入开始展示完整处理顺序`nflowchart TD`n    A[读取输入] --> B[检查内容]`n    B --> C[输出结果]`n${fence}`n`n竖向排列让阅读顺序和执行顺序保持一致"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '网络故障说明通过'
        Text = 'DNS 域名系统（Domain Name System）负责把网站名称转换成网络地址；这个转换暂时失败，所以新网页打不开；聊天软件仍在使用已经建立的连接，因此消息暂时还能发送'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '订单交付分析通过'
        Text = "OTIF 按时足量交付率（On Time In Full）统计订单是否按时并且数量完整地交付`n`n- 每100笔订单约有9笔没有同时满足这两个条件`n- 还有180笔订单尚未处理`n`n继续积压会增加逾期量和客户投诉，因此今天需要介入`n`n继续等待最容易扩大以下订单的客户损失：`n`n- 已经逾期的订单`n- 今天即将逾期的订单`n- 重要客户的订单`n- 因缺货而无法继续处理的订单`n`n这些订单最接近造成实际损失；先指定负责人和完成时间，再判断需要增加哪类资源：`n`n- 人员`n- 车辆`n- 库存"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '医疗结果说明通过'
        Text = 'eGFR 估算肾小球滤过率（Estimated Glomerular Filtration Rate）用于估计肾脏过滤血液的能力；这个数值低于正常范围，而且肌酐持续升高，所以肾功能可能正在下降；单次结果还会受到脱水和药物影响，因此医生需要结合复查结果再判断原因'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '还款能力分析通过'
        Text = "DSCR 偿债能力覆盖倍数（Debt Service Coverage Ratio）比较可用于还款的资金和需要偿还的本息`n`n漏扣下面任何一项支出都会高估还款能力：`n`n- 税款`n- 设备投入`n- 日常经营资金`n`n数据来源会影响计算结果的可信度，所以需要分开核对：`n`n- 如果来自过去的实际结果，需要核对下面三类记录：`n  - 银行流水`n  - 纳税记录`n  - 财务记录`n`n- 如果来自未来的预测，需要核对下面三项假设：`n  - 收入是否过于乐观`n  - 成本是否漏算`n  - 回款时间是否过早`n`n两类数据的证明能力不同，因此不能按照相同可信程度使用"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '芯片验证说明通过'
        Text = 'CDC 时钟区域跨越检查（Clock Domain Crossing）用于发现信号在不同时钟区域之间传递时可能出现的不稳定问题；检查结果没有发现问题，所以这部分流程可以通过；真实板卡尚未运行这些结果，因此流程通过不能替代产品发布'
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '制造质量说明通过'
        Text = '$C_{pk}$ 过程能力指数（Process Capability Index）比较生产波动和允许范围；当前数值下降说明产品更容易接近或越过规格边界；连续三批都出现相同趋势，所以先检查三类原因：' + "`n`n- 设备是否漂移`n- 原料是否变化`n- 测量是否存在误差`n`n这些检查能够判断变化来自生产过程还是测量过程，再决定是否暂停生产"
        ExpectedStatus = 'PASS'
    },
    @{
        Name = '数学公式排版通过'
        Text = '当 $x \geq 3$ 时，执行下一步'
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
        Name = '列表式代码缺少同行注释失败'
        Text = "命令如下：`n`n${fence}powershell`nGet-Process`nGet-Service # 查看系统服务及其状态`n${fence}"
        ExpectedRule = 'LIST_CODE_LINE_REQUIRES_INLINE_COMMENT'
    },
    @{
        Name = '段落式代码缺少开头注释失败'
        Text = "代码如下：`n`n${fence}csharp`n// 先处理资料缺失情况`nif (user.Profile is null)`n{`n    return ProfileResult.Missing();`n}`n`nreturn ProfileResult.Found(user.Profile.City);`n${fence}"
        ExpectedRule = 'CODE_PARAGRAPH_REQUIRES_LEADING_COMMENT'
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
    }
)

$failures = [Collections.Generic.List[object]]::new()
$caseResults = [Collections.Generic.List[object]]::new()
foreach ($case in $cases) {
    $run = Invoke-Lint -Value $case.Text
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
    $passed = $actualRules -contains $case.ExpectedRule
    $caseResults.Add([pscustomobject]@{
        name = $case.Name
        expected = $case.ExpectedRule
        actual = $run.Result.status
        rules = $actualRules
        passed = $passed
    })
    if (-not $passed) {
        $failures.Add([pscustomobject]@{
            name = $case.Name
            expected = $case.ExpectedRule
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
