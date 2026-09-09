"""Build twenty source-only candidate requests; private review notes stay separate.

Run with Python -B to avoid writing bytecode outside the four allowed files.
Only requests.jsonl is input to a writing agent. coverage.json and this builder
are evaluator-side artifacts, not prompt attachments. No model is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evals/candidate/two-layer"
RANGES = {"very_short": (1, 80), "short": (81, 250), "medium": (251, 700),
          "long": (701, 1500), "extended": (1501, 3000)}
ROUND = 20


# Evaluator-only targets grounded in references/explanation-framework.md.
# These map input opportunities, not observed answer quality or fixed wording.
EXPLANATION_TARGETS = {
    1: {
        4: "解释原始音频、收听副本、摘要的用途、使用时机和区别",
        5: "说明剪辑怎样破坏时间对应，背景噪声不能证明录音机故障",
        6: "用 OH-042 贯穿接收、核对、制作、交付和恢复演练",
        7: "就近说明未授权访谈、摘要不符和听辨待核分别阻挡什么",
        8: "交代各盘和目录的用途、操作输入、正常结果与失败核查",
        9: "区分四项登记状态及每项状态允许的交付动作",
        10: "说明 03:20、前后两秒、十二次中的两次各自归属",
        12: "完整覆盖五章并保留授权、摘要与时间位置的跨章依赖",
        13: "区分抽查、单项演练与全量验证，不补恢复时限",
    },
    2: {
        4: "说明工单、评估和报价如何使用，区分开缝与破洞",
        5: "解释居民同意、材料齐备、制作和复核的前后约束；迟延原因未知",
        6: "沿一件外套的四颗纽扣和一处开缝演示计价与工单流转",
        7: "解释不承接项目、待量取、追加费用和无加急的实际影响",
        8: "交代接待、量取、排队、复核、取件及查无凭条时的动作",
        9: "说明师傅、接待员和居民各自确认什么，以记录判断状态",
        10: "区分颗、处、件的单价与工时，并保持五张工单的状态总数",
        12: "完整覆盖六章，包括交班、未领衣物和返修未约定事项",
        13: "未记录的迟延原因和返修期限不能补造",
    },
    3: {
        5: "连接字号改变、重新分页、页码变化与同步正文位置的因果关系",
        6: "用同一段正文在不同字号设备上的情境示范，保持短回答规模",
        7: "区分页码不同与正文位置不同，不把前者直接判断为同步失败",
    },
    4: {
        4: "解释已预报、已入库和可领取的业务含义与判别依据，不强造英文",
        5: "连接编号通知、实物扫码、分配货架位与各阶段状态",
        7: "缺入库记录限制本票可支持的结论，不能据预报断言实物已到或未到",
        9: "以本票的实际记录判断当前状态对领取安排的影响",
        13: "明确缺的是实物扫码证据，不臆测包裹位置",
    },
    5: {
        4: "解释 client、server、payload、timeout 和 idempotency key 的作用及区别",
        5: "说明服务端保存与客户端收到回复不同步，为何超时不决定创建结果",
        6: "用同一笔捐赠演示保存、超时、同键同数据重试的完整过程",
        7: "说明同键改数据、保留窗口过期和收款不适用的例外",
        8: "说明何时复用键、何时先查登记簿，不补界面和重试节奏",
        10: "保留二十四小时窗口的单位、起作用范围与过期影响",
        13: "区分英文原文、用户提供的术语补充及帮助理解的示范",
    },
    6: {
        4: "解释延迟、离线回放与现场排练的用途和判别方式",
        5: "解释离线结果为何不能替代现场证据，六句偏慢的原因仍未知",
        6: "用本轮六十句数据走完达标比例与门槛的比较",
        7: "区分校对、安装、性能达标和试演获准的适用范围",
        9: "说明音频负责人、字幕员、舞台监督的依赖和下一项完成证据",
        10: "解释两秒、五十四除六十与百分之九十五门槛各自含义",
        13: "保留未做现场排练和未知迟延原因，不包装成确定诊断",
    },
    7: {
        4: "说明两种印法、一次性费用和制版改稿的区别",
        5: "连接定稿时间、交付所需时间与能否赶上活动的判断",
        6: "用本场二百四十张演示费用和交期比较，再区别下一场情境",
        7: "保留含税、不计运输、无加急、不能延期和改稿重收费条件",
        9: "按采购目标解释各方案何时合适及选择依据",
        10: "说明固定费用加单价乘数量的步骤、元和天的不同作用",
        13: "报价是所给合成材料，不冒充外部市场调查",
    },
    8: {
        4: "逐一说明 HTML、CSS、JavaScript、HTTP、Node.js、PostgreSQL 的当前用途",
        5: "连接页面提交、校验、照片上传、数据库保存、回复与审核公开",
        6: "用一次包含日期、地点、物种和照片的提交走完各层数据流",
        7: "解释草稿与公开、客户端与服务端校验、测试与正式环境的差异",
        8: "说明成功显示编号、失败保留表单和断网后核对草稿的操作依据",
        9: "交代每个技术栈对象为何存在、与前后对象怎样传递数据",
        10: "解释五 MB 与五百万字节的本项目换算范围",
        12: "按依赖组织长素材，保留后段测试环境与清理时限等限制",
        13: "不由技术名称推断正式部署、并发容量或清理时长",
    },
    9: {
        4: "解释宽高比和固定边的作用，区分比例与实际长度",
        5: "说明宽乘九除十六的原因，以及上下两边为何都要扣除",
        6: "用三点二米宽和两米布料逐步代入、计算、比较",
        7: "说明几何适配与亮度、镜头铺满是不同判断",
        10: "逐项说明 W、H、米、十六比九和零点一米边料的数据来源及结果含义",
        13: "明确缺投影距离、亮度和镜头参数所限制的结论",
    },
    10: {
        4: "说明函数、参数、set、列表、字段和返回值，不循环用陌生词定义",
        5: "解释按编号首次保留的机制，不猜重复是重发还是修改",
        6: "逐条走完三条订单，展示 seen 和 kept 的变化",
        7: "说明同编号不同数量、缺 id、无磁盘写入和原内容不变的影响",
        8: "交代输入记录需要 id，正常返回与 KeyError 的区别，不编执行结果",
        11: "保留原代码，为每个有效语句和示例记录提供可定位说明",
        13: "区分根据代码推演的结果与真实执行，业务修改关系仍未知",
    },
    11: {
        4: "解释 JSON、键值、数组、布尔值与 null 的含义和当前作用",
        5: "连接字段设置、重新载入、解析结果与实际轮播表现",
        6: "用当前 moon、mars、十五秒配置走完一轮观察",
        7: "就近区分 null、空字符串和 false，解释失败沿用旧配置的影响",
        8: "说明保存后重新载入及观察整轮的核对步骤，不造版本显示功能",
        10: "说明 interval_seconds 的秒单位和每页停留含义",
        11: "原样保留合法 JSON，每个字段在块外解释，块内不加注释",
        13: "沿用旧轮播不能证明新配置生效，版本号证据不可编造",
    },
    12: {
        4: "用自然语言区分分支判断、实线通道与虚线咨询关系",
        5: "解释票面标记如何决定候船分流，不能把咨询连线当通道",
        6: "从入口经查票走完一个具体票种的分流过程",
        7: "说明自行车车辆票、未知票种和围栏例外如何影响走法",
        8: "说明入口、查票点、服务台与候船区的下一动作和核对依据",
        11: "保留文本示意，逐项对应入口、箭头、菱形、A/B、服务台与注记；不计真实视觉识别",
        13: "仅依赖文字转录，不能补出开船时间、排队长度或无障碍坡道",
    },
    13: {
        4: "解释 seq、timeout 和轮询的含义与用途",
        5: "连接发送、保存、等待回复和屏幕轮询，说明现象不等于唯一根因",
        6: "按给定时间顺序走完四十一已保存而屏幕仍显示四十的过程",
        7: "保留共用时钟、禁用重试、未授权重置的条件和限制",
        8: "说明查看服务端版本、记录下次轮询，以及连续同步的恢复判据",
        9: "说明 client、server、display 的职责与状态证据区别",
        11: "保留五条日志，逐行说明时间、组件、动作和版本所能证明的内容",
        13: "指出缺回复、轮询与网络证据，不能断言网络或屏幕程序故障",
    },
    14: {
        5: "说明报姓名、领桌号、按号入座的衔接关系",
        6: "从首次到门口的情境示范入场过程，不重放失效通知",
        7: "解释查无名单先找接待员而不自行占座的分支",
        8: "交代现行时间地点、到场准备和可观察的入座依据",
        12: "只采用最终有效安排，旧三段结构、变更历史和自带围裙要求失效",
        13: "当前事实来自多轮用户更正，不编教室路线或报名界面",
    },
    15: {
        4: "说明总质量、皮重与净质量各是什么、怎样取得与区分",
        5: "解释净质量减法的原因，算术自洽不等于来源权威",
        6: "用甲的四百八十二克和三十二克走完核算，再对照乙的记录",
        7: "缺称量时刻与权威排序时不自行取最新、平均或选一个重量",
        8: "说明现在可登记的出处，以及复称所需原容器和新记录",
        10: "保留克单位和两份不同净质量，说明相减过程及适用条件",
        13: "保留来源冲突、原容器未确认及这些缺项对复核的影响",
    },
    16: {
        4: "解释等高线、海拔、比例尺在本图中的作用和区别",
        5: "连接相等高差、不同水平距离与缓陡判断的原因",
        6: "用东侧十二毫米和西侧四毫米对照同一段十米高差",
        7: "仅在同图等比例和同高差下比较，圈线不是可行走路线",
        10: "区分海拔米与纸面毫米，缺比例尺不能计算真实水平距离",
        11: "逐项对应文本中的三圈、高度与两侧间距；不计真实视觉识别",
        13: "只解释提供的文字示意，不推断道路、围栏和地面情况",
    },
    17: {
        4: "解释分母、回收率和满意比例各自统计什么",
        5: "说明不同回收数为何不能直接平均两组满意比例",
        6: "逐格取数，分别合计满意与有效回收，再计算总比例",
        7: "保持两组不重叠、每人一份、回收均有效和未回收意见未知的条件",
        10: "说明分子分母、总量与局部量、百分比的计算和代表范围",
        11: "保留原表，解释每列、每行和全部数据格的对应关系",
        13: "区分有效回收者与全体参加者，不把非随机反馈外推为全员意见",
    },
}


def attach_hidden_mappings(rows: list[dict], reviews: list[dict]) -> None:
    for index, (row, review) in enumerate(zip(rows, reviews), 1):
        if row["trigger_mode"] == "non_triggering_control":
            review["explanation_mapping"] = {}
            review["explanation_mapping_status"] = "not_applicable_non_triggering_control"
            review["explanation_mapping_note"] = "纯格式请求禁止追加解释，EXPL-001..014 不作为正文要求或正向解释覆盖"
        else:
            mapping = {
                1: "围绕当前请求解决读者的问题：" + row["request"],
                2: "按完全零基础处理，不凭读者身份或操作记录跳过必要解释；核对本案 prerequisite_checkpoints",
                3: "先补本案必要前提：" + "；".join(review["prerequisite_checkpoints"]),
                **EXPLANATION_TARGETS[index],
                14: "用本案 retelling_questions 和 transfer_questions 定位正文中支持理解与迁移的内容；不以模型自评代替证据",
            }
            review["explanation_mapping"] = {f"EXPL-{key:03d}": value for key, value in sorted(mapping.items())}
            review["explanation_mapping_status"] = "review_targets_not_verified_results"
        if "provided_diagram_text" in review["features"]:
            review["image_evidence_kind"] = "diagram_text_not_visual_input"
            review["image_evidence_note"] = "素材只有提供的文本示意或图中文字转录；仅覆盖文本示意解释，不证明真正视觉读图能力或视觉验证结果"


def digest(value: Any) -> str:
    # Same canonicalization as generate_agent_variability_cases.digest.
    raw = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def input_length(request: str, content: Any, references: list[dict]) -> int:
    raw = content if isinstance(content, str) else json.dumps(
        content, ensure_ascii=False, sort_keys=True)
    return len(request) + len(raw) + sum(len(ref["content"]) for ref in references)


def build_cases() -> tuple[list[dict], dict]:
    rows: list[dict] = []
    reviews: list[dict] = []

    def add(topic, request, content, *, facts, prerequisites, recall, transfer,
            operation="EXPLAIN", augmentation="TEACHING", genre="说明",
            task="explanation", mode="explicit", components=("TEXT",),
            material="text", terms=(), tags=(), references=(), features=(),
            output_contract=None):
        index = len(rows) + 1
        refs = [{"id": f"REF-TL-{index:03d}-{i}", "content": text}
                for i, text in enumerate(references, 1)]
        count = input_length(request, content, refs)
        length_class = next((key for key, (lo, hi) in RANGES.items()
                             if lo <= count <= hi), None)
        if length_class is None:
            raise ValueError(f"{topic}: input length {count} is outside schema")
        case_id = f"FWD-R{ROUND}-{index:03d}"
        rows.append({
            "case_id": case_id, "round": ROUND, "base_operation": operation,
            "augmentation": augmentation, "genre": genre,
            "audience": "zero_prior_knowledge", "content_task": task,
            "length_class": length_class, "input_char_count": count,
            "topic_id": f"TOPIC-R{ROUND}-{index:03d}",
            "core_terms": [topic, *terms], "trigger_mode": mode,
            "variation_tags": list(tags), "components": list(components),
            "request": request,
            "source": {"material_type": material, "content": content,
                       "sha256": digest(content)}, "references": refs,
        })
        review = {
            "case_id": case_id, "topic": topic, "features": list(features),
            "source_char_count": len(content) if isinstance(content, str) else None,
            "fact_checkpoints": facts, "prerequisite_checkpoints": prerequisites,
            "retelling_questions": recall, "transfer_questions": transfer,
        }
        if output_contract:
            review["output_contract"] = output_contract
        reviews.append(review)

    add("口述史录音数字归档",
        "把这份交接材料改写成给第一次参加档案工作的志愿者看的完整入门文章，保留各章节的信息，让他能接手一段录音并判断是否做对。",
        """第一章：为什么保存两种文件
街区记忆小组录下居民讲述旧店铺的声音，希望以后既能重新编辑，也能让获准的研究者查找内容。录音机生成的 WAV 文件保存采样后的声音数据，是本项目的原始音频；MP3 文件是从它转换出来的较小收听副本。小文件便于传送，但转换会舍弃部分声音信息，不能由小文件还原原始质量。这里的 WAV 和 MP3 是文件格式名称，不是保密等级。志愿者没有重新录制居民讲话的权限，听不清的地方只能标为待核。
每个访谈有一个固定编号，例如 OH-042。编号对应一次访谈，不对应受访者的身份证明。同一人两次接受访谈会有两个编号。编号写进文件名和登记表，方便在不公开姓名的情况下把音频、文字和同意书关联起来。同意书另放在受限目录，不能随着收听副本一起发出。本批有十二次访谈，其中两次尚未取得对外收听授权，内部整理仍可继续。

第二章：接收时先确认什么
交接人会提供一张清单，列出编号、原始文件名、文件大小、录音时长及 SHA-256 值。SHA-256 是 Secure Hash Algorithm 256-bit 的常用写法，本项目把它算出的摘要当作文件内容的指纹；相同文件重复计算会得到相同值，内容改变通常会改变摘要。摘要相同用于核对传输前后是否一致，不证明讲话真实，也不证明已经获得授权。清单由交接人通过既定内部渠道提供，不能拿接收后自己生成的清单冒充交接依据。
接收盘只用于读取。先把清单中的原始文件复制到工作盘，再对工作盘副本计算摘要并逐项比对。文件名相同而摘要不同，记录该编号和两边摘要，暂停这一项的后续制作并请交接人复核；其他已核对项目可以继续。没有清单的文件进入待确认列表，不自动删掉。清单里有而盘上没有的文件记录为缺失，不能用同名 MP3 代替。复制完成的提示仅说明复制程序结束，不能代替摘要核对。

第三章：整理文字与时间位置
转写稿是把声音内容写成文字的文档，本项目允许语气词保留，不把方言改成另一种说法。时间标记采用从该音频开头起算的分和秒，例如 03:20 表示三分二十秒处，不是当天钟表时间。先完整听一遍确认说话人和段落，再在话题变化处加入时间标记。每段标记回放时应落在该段首句附近；复核允许的偏差是前后两秒。超过这个范围需要重新定位，不通过增删讲话内容来迁就时间。
自动转写只能作为草稿，机器可能把人名写成常见词，也可能漏掉重叠讲话。听不清的片段写上起止位置与“听辨待核”，由另一位志愿者复听。两人仍听不清时保留这一状态，不根据街区常识猜出一个名字。说话人代号使用访谈内的甲、乙；材料没有提供代号与真实姓名的对应表。本批有一段背景收音机声较响，只确认影响听辨，没有证据判断录音机故障。

第四章：制作收听副本
摘要核对成功后，从工作盘中的原始音频制作 MP3。转换工具的预设由管理员提供，志愿者不自行调高音量或剪去停顿。制作后核对开头、一个中间位置与结尾是否能播放，登记副本时长；若副本少了结尾，重新制作并保留失败记录。抽查播放覆盖这些位置，不等于逐秒确认全片没有噪声。转写稿中的时间位置以原始音频为准，所以剪去停顿会破坏文字和声音之间的对应关系。
文件采用 OH-042_master.wav、OH-042_listen.mp3 和 OH-042_transcript.txt 这样的命名，扩展名用来区分格式。把扩展名改成 mp3 并不会完成转换。修改转写稿时另记修订日期和修改人，不能覆盖清单中的原始音频。若原始文件名与约定不同，在登记表记录对应关系，完成核对以后才给工作副本使用约定名称；接收盘上的文件维持原样。

第五章：交付与后续核查
登记表按访谈逐行记录摘要核对、转写复听、收听副本播放检查和授权状态。这四项分别记录，不能用一个“完成”代替。负责整理的人提交记录，另一位志愿者签署复核日期。只有取得对外收听授权且副本检查通过的访谈，才进入研究者可见目录；文字仍有听辨待核的地方时，随稿保留标记。研究者可见目录不含同意书和原始录音。
当天工作结束后，管理员把原始音频、转写稿和登记表复制到第二块独立保存的盘，次日再做一次可读取检查。两份放在同一块盘的文件会同时受该盘损坏影响，因此不算这里要求的两处保存。恢复演练只取一项已授权访谈，从第二块盘复制到空工作目录，检查摘要并打开转写稿。演练成功表示该项在当时能够恢复，不代表其他项目都已逐项验证。遇到文件读不出时保留错误提示、编号和操作时间，联系管理员；材料没有承诺恢复时限。""",
        operation="TRANSFORM", genre="多章节入门文章", task="tutorial",
        terms=("WAV", "MP3", "SHA-256"), tags=("distributed_condition", "negation_exception"),
        features=("multi_section_article", "long_source", "prerequisite_chain", "unknown_cause"),
        facts=["十二次访谈中两次未获对外收听授权，内部整理可继续", "时间标记允许前后两秒偏差", "摘要、复听、播放检查、授权是四项不同状态", "背景声影响听辨不证明录音机故障", "恢复演练只验证一个访谈"],
        prerequisites=["原始音频与收听副本各自用途", "文件格式、编号、摘要与授权的区别", "转写时间位置为何依赖未经剪辑的音频", "独立保存与恢复演练的关系"],
        recall=["收到一项访谈后，各项证据分别支持哪一步交付？"],
        transfer=["副本能播放但交接摘要不同，能否发给研究者？依据是什么？", "两份文件放在同一块盘，能否满足两处保存？"])

    add("旧衣修补合作社工单流转",
        "请把这份试营业手册整理成新接待员能独立使用的中文长文。读者从未接触修补业务，既要明白流程，也要知道遇到例外时如何判断；各章事实都要保留。",
        """第一章：接待台的任务
针线合作社承接居民旧衣修补，试营业期间只做纽扣补缀、直线开缝修补和裤脚改短。皮衣、羽绒填充层和需要整片换里的衣物不在本轮范围内。接待员的工作是确认需求、登记现状和安排评估，不能代表师傅承诺任何破损都能恢复成新衣。居民送来一件衣物不等于已经同意开工；衣物由合作社暂存，也不等于费用已经支付。
工单是一张围绕单件衣物的记录，号码印在取件凭条和衣物挂签上。一个人送两件衣服，需要两张工单，避免其中一件完工时把另一件也标为已取走。表格包含物品描述、原有破损、居民希望的结果、评估结论、报价、同意状态、负责师傅、计划日期与交付记录。联系电话仅在内页供接待员使用，对外展示的进度板只有工单号和状态。

第二章：接收和评估
接待员先与居民一起看衣物，记录污渍、磨损和缺件位置；需要拍照时先询问是否同意，不拍照也可用文字登记。裤脚改短需要居民穿着计划搭配的鞋确认位置，再以可移除记号标示。居民不能当场试穿时，接待员只能记录期望长度，工单停在待量取，不能把居民随口估计的数字直接交给师傅裁剪。衣物上原有装饰可能限制可改长度，要由师傅评估。
评估是师傅判断现有面料和破损是否适合本轮服务的过程。开缝指原来缝合的接缝松开，破洞指面料本身缺失，两者处理不同；直线接缝重新缝合在服务范围内，补整块缺失面料不在本轮范围内。评估结果写为可做、需另议或不承接。需另议表示还缺材料选择或效果确认，并非居民已经同意更高费用。师傅不在时收件可暂存到次日，但工单只能写待评估。

第三章：报价与同意
试营业内部价目为纽扣补缀每颗三元、直线开缝每处八元、裤脚改短每件二十元。纽扣由居民提供，价格只含人工；缺纽扣时先待材料，不把别的衣物上的纽扣拆来使用。一张衣物工单有多项服务时逐项相加。举例材料是同一件外套补四颗纽扣并修一处直线开缝，两项都在师傅确认范围内。报价后由居民确认服务项目和总额，同意时间记到工单，才可进入排队。
如果师傅开工前发现另一处开缝，先暂停新增部分并联系居民；原来同意的项目能够独立完成时可继续，不能默认为居民接受追加费用。居民拒绝新增项目时记录不做及可见影响，不能把拒绝写成欠款。报价在同意前可重新核对，但同意后若要变更金额，需要再次确认，不能用更新进度板代替沟通。试营业不收加急费，也不承诺插队当天完工。

第四章：排队与制作
排队表按确认同意的时间排序，待材料和待量取工单不占正在制作的位置。每日可安排的工作量由师傅在晨会确认，接待员根据剩余位置给计划日期；计划日期是安排目标，不是无条件的交付保证。当天师傅只有三处直线开缝的可用工时，接待员不能把一件包含四处开缝的衣物按一件普通工单塞进剩余位置。件数和服务处数是不同的计量对象。
开工时师傅取下排队标记，登记开始时间，核对衣物挂签与工单号。缝制完后保留修补部位可见，交给另一位师傅复核；复核查看线头、接缝是否牢靠以及是否做了获准项目。发现返工则写回制作中并记录原因，不能在居民端继续显示待取件。这里只有已检查的项目可以记为通过，没有逐件复核记录就不能笼统声称这一批质量全部合格。

第五章：通知、领取和费用
复核通过后接待员核对联系电话，发送取件通知并登记发送时间。通知已发送只表示接待台完成联络动作，居民可能还没看到；只有居民回复确认时才记录已联系。领取时凭条号码与挂签一致，居民现场查看修补部位，再记录验收和付款。遗失凭条可由接待员根据内页电话与衣物描述核对，普通志愿者不能仅凭进度板上的号码放行衣物。
付款登记包含实收金额、支付方式和接待员，收款与取件状态分别保存。居民对效果有异议时转师傅现场核对，工单保留已付或未付的真实状态，不能为了结束流程把异议改为已验收。试营业未制定统一返修天数，现场接待员不能自行承诺长期免费返修。未领衣物放在对应编号格中，每周核对一次；材料没有授权丢弃超期未领衣物。

第六章：交班与例外记录
晚班交给早班三张清单：仍待居民确认的项目、已同意但受材料阻挡的项目、已复核且未领取的项目。各条写明工单号、下一动作和负责的人，而不是只写“跟进”。例如待纽扣工单由接待员联系居民补齐材料，收到后先核对数量再恢复排队；居民改变颜色选择，需要回到材料确认，不由师傅自行选相近颜色。
当前试点记录有五张工单，其中两张正在制作、一张待居民同意、一张待纽扣、一张已复核待领取。进度板上的四种状态反映不同阻碍，不能把五张都计作正在生产。昨日一张工单计划日期顺延，但交班记录只有顺延结果，没有迟延原因；接班员先找负责师傅核对，不能断言是居民迟送材料。交班完成以接班人能按号码找到衣物、确认当前状态并接手下一动作为准。""",
        operation="TRANSFORM", genre="多章节业务手册", task="operation",
        terms=("工单", "开缝", "报价"), tags=("numeric_scope", "distributed_condition", "negation_exception"),
        features=("multi_section_article", "long_source", "exceptions", "unknown_cause"),
        facts=["仅三类服务，缺失面料的破洞不等于开缝", "报价单价为每颗三元、每处八元、每件二十元", "试点五张工单分为二、一、一、一", "通知发送、回复、付款、取件状态独立", "没有统一返修天数或迟延原因"],
        prerequisites=["工单与服务项目的计数差异", "评估、报价、同意如何依次约束开工", "待材料与排队的区别", "可观察记录如何支持状态判断"],
        recall=["一件衣物从送达到取件需要哪些确认，谁完成这些确认？"],
        transfer=["四颗纽扣加一处开缝该如何计价？", "通知发出但居民未回复，应如何区分联络状态？"])

    add("电子书阅读进度同步", "给我妈回一句她看得懂的话：为什么换设备后页码不同？",
        "电子书按字号重新分页；同步保存的是正文位置。两台设备字号不同，正文位置相同也可能显示不同页码。",
        mode="implicit", augmentation="EXPLANATORY", genre="短回答", features=("short_answer", "implicit"),
        facts=["分页随字号变化，同步保存正文位置"], prerequisites=["正文位置与屏幕页码并非同一对象"],
        recall=["为什么页码不同仍可能同步成功？"], transfer=["把字号调大后怎样判断是否还在同一段？"])

    add("包裹代收点扫码状态", "这张小票写的是到了还是没到？",
        "小票：已预报。代收点约定：已预报表示商家传来包裹编号；已入库表示站点实物扫码；可领取表示已分配货架位。本票无入库记录。",
        mode="implicit", augmentation="EXPLANATORY", genre="小票解读", features=("implicit", "status_distinction"),
        facts=["本票只有预报，无入库记录"], prerequisites=["数字通知、实物接收、上架是不同步骤"],
        recall=["已预报能证明什么？"], transfer=["如果变为已入库却未分配货架，能否直接按可领取处理？"])

    add("捐赠收据接口重试", "把英文说明完整翻译成我这个第一次接触接口的人能看懂的中文，原文的例外也要讲清楚。",
        """A receipt request may time out after the server has committed the receipt. A timeout alone does not tell the client whether creation succeeded. Reuse the same idempotency key when retrying the same donation. Within the 24-hour retention window, this service returns the stored result for the same key and payload. A changed payload with that key is rejected. After expiry, check the receipt ledger before attempting another creation. This rule applies to receipt creation, not to donation collection. No retry schedule is specified here.""",
        operation="TRANSLATE", augmentation="EXPLANATORY", genre="解释性翻译",
        terms=("idempotency key", "payload", "timeout"), tags=("negation_exception", "numeric_scope"),
        references=("本接口说明补充：client 是发送请求的程序，server 是接收并处理请求的程序；payload 是本次提交的业务数据。commit 表示结果已保存；timeout 表示等待超过客户端设定时间。idempotency 指重复同一操作不会额外产生新的业务结果，本服务用请求中的 idempotency key 识别同一次捐赠的收据请求。receipt ledger 是已创建收据的登记簿。",),
        features=("explanatory_translation", "causal_chain", "exceptions"),
        facts=["超时不决定是否创建成功", "相同键和数据在二十四小时窗口返回已存结果", "同键不同数据拒绝", "过期先查登记簿，仅收据创建适用，未指定重试节奏"],
        prerequisites=["请求、服务端保存和客户端收到回复的时间关系", "同一业务与同一数据如何识别"],
        recall=["为什么超时后不能直接换键再创建？"], transfer=["相同键却改了金额会怎样？窗口过期后第一步做什么？"])

    add("剧场实时字幕试点", "把记录整理成给不懂技术的剧场经理看的项目状态说明，让他知道现在能安排什么、还要等什么。",
        """周二验收记录：字幕是把台词转成投影文字，延迟从演员说完到该句最后一字出现计时。离线回放使用事先录好的声音；现场排练会加入真实麦克风和环境声。离线样本共 60 句，其中 54 句延迟不超过 2 s，6 句超过 2 s；本轮目标是至少 95% 的句子不超过 2 s。文字校对已完成，现场排练尚未做。音频负责人周四提供现场录音，字幕员收到后先测延迟，再由舞台监督确认是否安排观众试演。投影幕安装完毕不代表字幕延迟达标。那 6 句延迟偏高的原因还没有排查记录。""",
        operation="GENERATE", genre="项目状态", task="status", terms=("延迟", "离线回放"),
        tags=("numeric_scope",), features=("project_status", "unknown_cause", "numeric_consistency"),
        facts=["六十句中五十四句达标，目标百分之九十五", "文字校对已完成，现场排练未做", "周四先提供录音再测量，舞台监督决定试演", "六句慢的原因未知"],
        prerequisites=["达标比例的分子分母", "离线回放与现场排练的证据差异"],
        recall=["哪些完成项不能证明可以试演？"], transfer=["保持六十句样本，要达到目标至少需几句达标？"])

    add("种子交换会说明卡印制", "我们要选说明卡的印法。请给完全没做过印刷采购的组织者写一份选择建议，比较费用、时间和适用条件。",
        """交换会需要 240 张说明卡，两种报价都按合格卡片计费且已含税，不计运输。甲是数码印刷，开机费 40 元，每张 0.80 元，确认稿件后 1 天交付；乙是胶印，制版费 180 元，每张 0.25 元，确认后 3 天交付。开机或制版费每次订单只收一次。数码印刷直接读取电子稿；这里的胶印先制作固定版面，改稿要重新制版并再收 180 元。稿件尚待植物名称复核，最晚会前 2 天才能确认；活动不能延期。两家均不提供加急。采购员还问下一场若需 800 张、能提前 5 天定稿时是否要重新比较。""",
        operation="GENERATE", genre="方案选择", task="decision", terms=("数码印刷", "胶印", "制版费"),
        tags=("numeric_scope", "distributed_condition"), features=("decision", "numeric_consistency"),
        facts=["二百四十张，甲固定四十元每张零点八元，乙固定一百八十元每张零点二五元", "可用两天，甲一天乙三天，均无加急", "乙改稿另收制版费", "下一场八百张可提前五天定稿是另一情境"],
        prerequisites=["固定成本与按张计费如何相加", "费用和可交付时间必须共同判断"],
        recall=["本次选择受哪项约束决定？"], transfer=["八百张且五天准备期时两种方案总费如何变化？"])

    add("昆虫观察网站技术栈", "我只会用浏览器。请依据团队笔记讲明白这个网站每一层为什么存在，以及我点一次提交之后会发生什么。",
        """项目要让自然观察社记录在何处看到哪种昆虫。页面只收观察日期、地点代号、物种名称和一张照片，不收精确住址。地点代号是社团维护的区域名称，不是卫星定位坐标。草稿只有填写人能看见，管理员核对物种后才公开；公开状态并不保证物种永远不会被修订。
浏览器里的 HTML（HyperText Markup Language）描述表单、按钮和图片等页面结构，CSS（Cascading Style Sheets）控制颜色与排版，JavaScript 处理点击和提示。三者都在用户看到的页面中发挥作用。浏览器可以先发现必填项空缺，但别人可以绕过页面直接发送数据，所以服务端仍要复核。
浏览器通过 HTTP（Hypertext Transfer Protocol）提交请求。请求包含要执行的动作、目标地址和表单内容；服务器返回状态及结果。本站 POST /observations 用于新建观察，GET /observations/{id} 用于读取指定观察。花括号中的 id 表示实际编号需要填在该位置，不是原样发送花括号。路径相同不代表动作相同，方法也参与区分。
Node.js 是运行服务端 JavaScript 的运行环境，在本项目中接收请求并执行处理逻辑。它检查登录状态、必填项和照片大小；本站照片上限为 5 MB，这里的 MB 按 1,000,000 字节计算。只在浏览器隐藏管理员按钮不能代替服务端核对权限。有效请求进入保存步骤，无效请求返回对应错误，页面显示错误后保留未提交的表单内容。
PostgreSQL 是这里保存结构化记录的关系数据库，每条观察有唯一编号，记录日期、地点、物种、照片地址和审核状态。照片二进制内容放在对象存储中；对象存储按名称保存文件内容，数据库只记它的地址。这样看见数据库有一行，不足以证明照片能读取。照片上传失败时本次流程不创建观察行；数据库保存失败但照片已上传时，后台清理未被记录引用的照片。
一次正常提交先检查字段，再上传照片，最后保存观察行，收到保存成功的回复后页面才显示观察编号。断网发生在保存之后、回复之前时，页面可能不知道结果；当前版本没有自动重试，成员可以到自己的草稿列表核对。管理员另行审核后将草稿变为公开，这不是提交按钮自动完成的步骤。
测试环境使用虚构观察，正式环境用于成员的真实记录，两处数据库和照片空间独立。演示中出现编号只证明测试环境能走完那一次流程。当前仅有测试环境的成功记录，正式环境没有部署记录。团队尚未测量同时在线人数的上限，也没有说明照片后台清理要多久，不能由技术栈名称推算这两个值。""",
        genre="技术栈说明", terms=("HTML", "CSS", "JavaScript", "HTTP", "Node.js", "PostgreSQL"),
        tags=("mixed_format", "distributed_condition"), features=("technology_stack", "prerequisite_chain", "long_source"),
        facts=["服务端也校验字段和权限", "照片限五百万字节", "照片先上传，观察行后保存", "保存回复后显示编号，审核之后才公开", "只有测试环境证据，无并发上限或清理时限"],
        prerequisites=["页面结构、样式和行为的分工", "请求方法与路径", "运行环境、数据库、对象存储之间的关系", "保存成功与收到回复不同"],
        recall=["点击提交后各层分别处理什么数据？"], transfer=["数据库有记录但照片打不开，应沿哪条关系检查？"])

    add("露天电影银幕尺寸计算", "我没学过这些公式。请解释给活动志愿者听，算出这块银幕需要多高，并展示代入和单位。",
        """画面宽高比为 16:9，表示宽和高按相同单位比较时的比值，不是十六米乘九米。银幕可用宽度 W = 3.2 m，保持原比例的高度 H = W × 9 / 16。布料总高 2.0 m，上下各留 0.1 m 固定边，固定边不显示画面。这里仅比较几何尺寸；材料未给投影距离、亮度和镜头参数，不能判断现场画面是否明亮或投影机能否铺满。""",
        terms=("宽高比", "W", "H"), tags=("numeric_scope",), features=("formula_with_units", "numeric_consistency"),
        facts=["宽三点二米，十六比九", "总高两米，上下各零点一米", "只比较几何尺寸"],
        prerequisites=["比例不带固定长度", "同单位计算及两侧边料扣除"],
        recall=["为什么乘九再除十六？"], transfer=["如果可用宽度变为四米而布料不变，还能保持完整比例吗？"])

    add("手工皂订单去重代码", "请保留这段 Python 代码，再教一个第一次看代码的店员读懂每一步；用给定订单演示，说明这段代码能发现什么、不能发现什么。",
        """def unique_orders(orders):
    seen = set()
    kept = []
    for order in orders:
        if order["id"] not in seen:
            seen.add(order["id"])
            kept.append(order)
    return kept

示例输入：[{"id": "S-7", "bars": 2}, {"id": "S-7", "bars": 5}, {"id": "S-8", "bars": 1}]
本店 id 是订单编号，bars 是皂块数。orders 是按收到顺序排列的记录列表，每条记录包含这两个字段。set 保存不重复的值，列表保存顺序，字典按字段名取值。seen 记录见过的编号，kept 保存保留的记录。重复编号可能是重发，也可能是修改，材料没有记录修改关系。此函数只返回新列表，不写磁盘，不修改原订单内容；缺少 id 字段会产生 KeyError。""",
        material="code", components=("TEXT", "CODE"), terms=("Python", "set", "KeyError"),
        tags=("mixed_format", "negation_exception"), features=("code_explanation", "unknown_cause"),
        facts=["输入三条，S-7 两次且数量不同", "按首次出现保留，不合并数量", "不写磁盘，不改原记录，缺 id 报错", "不能确认重复原因"],
        prerequisites=["函数、参数、循环、集合、列表、字段和返回值", "记录标识与业务版本的区别"],
        recall=["seen 和 kept 分别解决什么问题？"], transfer=["若第二条代表修改，为什么这段代码不够用？"])

    add("天文展台轮播配置", "原样保留 JSON 代码块，块内不能加注释；在块外向第一次接触配置文件的展台管理员解释每个字段，说明如何核对生效。",
        '{"interval_seconds":15,"shuffle":false,"slides":["moon","mars"],"caption":null}',
        material="code", components=("TEXT", "CODE"), terms=("JSON", "null", "false"),
        references=("该展台用 JSON（JavaScript Object Notation）读取配置，键名必须保留。interval_seconds 是每页停留秒数；shuffle 为 false 时按 slides 的数组顺序轮播，true 才随机。caption 为 null 表示沿用各页原题注，空字符串才隐藏题注。管理员保存后点击重新载入；解析失败显示配置错误并继续旧轮播。观察完整一轮才能核对次序，本设备没有显示配置版本的功能。",),
        features=("strict_json_no_comments", "code_explanation"), tags=("mixed_format",),
        facts=["十五秒，moon 在 mars 前，shuffle 为 false", "null 沿用题注，空字符串隐藏", "失败继续旧轮播"],
        prerequisites=["键值、数组、布尔值、null 与文本的区别", "保存与重新载入不是同一动作"],
        recall=["如何从实际轮播判断顺序设置是否生效？"], transfer=["要隐藏题注，为什么不能只把 null 留在那里？"],
        output_contract={"embedded_json": "verbatim", "comments_allowed": False, "explanation_location": "outside_code_block"})

    add("渡口候船区分流示意", "第一次来这儿，这个牌子怎么走？",
        """现场指示牌文字转录，不附照片：
[入口] → [查验船票] → ◇票面有车辆标记？
                         ├─是→ [车辆候船道 A]
                         └─否→ [步行候船区 B]
[服务台] 位于查验船票左侧，虚线连接到查验点。
牌下注记：实线箭头为乘客前进方向；虚线表示可向服务台咨询，不是通道。A 与 B 之间有围栏，不可横穿。自行车也属于车辆票；不确定票种时先到服务台。牌子没有开船时间、实时排队长度或无障碍坡道信息。""",
        mode="implicit", material="image", components=("TEXT", "IMAGE"),
        terms=("车辆票", "实线箭头", "虚线"), tags=("mixed_format", "negation_exception"),
        features=("implicit", "provided_diagram_text", "visual_evidence_boundary"),
        facts=["有车辆标记去 A，否则去 B，自行车属车辆票", "虚线是咨询关系，围栏不可穿越", "未显示时刻和坡道"],
        prerequisites=["判断菱形如何分支", "通道方向与咨询关系区别"],
        recall=["从入口到候船区的判断顺序是什么？"], transfer=["推自行车且不清楚票种时，能否直接走 B？"])

    add("桌游积分屏断更日志", "积分屏卡住了，主持人很着急。请按这些日志写一段他能看懂的现场说明，包括已知情况、下一步怎么查和怎样确认恢复。",
        """10:04:00 score-client sent update seq=41
10:04:01 score-server saved seq=41
10:04:02 score-client timeout seq=41
10:04:10 display showing seq=40
10:04:12 score-client retry disabled
以上来自同一台演示电脑，各程序共用系统时钟。seq 是递增的比分版本号；client 发更新，server 保存比分，display 单独轮询读取。timeout 表示客户端在等待回复时超过期限，不表示服务器一定没保存。现场只采集了这些日志，没有服务端回复日志、屏幕轮询日志或网络抓包。允许操作：查看服务端当前版本，记录屏幕下一次轮询结果；没有授权重置比分。恢复标准是屏幕显示服务端当前版本，并在下一次合法加分后再次同步。""",
        genre="故障现场说明", task="status", terms=("seq", "timeout", "轮询"),
        tags=("noisy_input", "urgency_or_emotion"), features=("logs", "unknown_cause", "observable_recovery"),
        facts=["服务端存四十一，屏幕显示四十", "客户端超时，自动重试禁用", "无轮询和回复日志，未授权重置"],
        prerequisites=["发送、保存、回执、屏幕读取各阶段", "版本号用于比对状态"],
        recall=["为什么客户端超时和服务端保存并不矛盾？"], transfer=["屏幕跳到四十一但下一次加分不动，是否达到恢复标准？"])

    add("陶艺体验课改期通知", "根据下面的沟通记录，写一份直接发给首次报名者的最终通知，让他们知道现在该怎么做。",
        [
            {"role": "user", "content": "原安排：周六上午在一号教室上陶艺体验课，请带围裙，提前二十分钟到场。通知用三段，附上所有改动历史。"},
            {"role": "user", "content": "更正：改到周日下午两点，地点换二号教室。围裙由教室提供，报名者不用带。提前到场改为十分钟。"},
            {"role": "user", "content": "最终要求：旧通知尚未发出，所以不写改动历史，也不用三段；只写现行安排和首次入场步骤。门口先报报名姓名，领取桌号，按桌号入座。名单没找到就找入口接待员核对，先别自行占座。课程时长九十分钟。"},
        ], material="multi_turn", operation="GENERATE", genre="最终通知", task="operation",
        tags=("correction_turn",), terms=("桌号",), features=("multi_turn_superseded",),
        facts=["周日下午两点，二号教室，提前十分钟，九十分钟", "不用带围裙", "取消三段和变更历史要求", "报姓名、领桌号、入座，查无名单找接待"],
        prerequisites=["桌号连接报名核对与座位分配"],
        recall=["新学员到门口以后依次做什么？"], transfer=["名单里查不到名字时，能否先坐空位？"])

    add("岩石标本称量记录冲突", "帮第一次做标本登记的同学整理两份记录，说明哪些能录入、哪些需要复核。保留来源差异，不替我们选一个重量。",
        """标本编号 R-18。来源甲为周一电子秤打印条：总质量 482 g，容器皮重 32 g，净质量 450 g。来源乙为周一手抄登记页：R-18 净质量 480 g，旁注“已去盒”，没有对应打印条编号。总质量含容器；皮重是空容器质量；净质量按总质量减皮重计算。两份记录都没有称量时刻，无法确定哪次较晚，现场也未指定权威来源。可以先登记编号及两份读数和出处；管理人明早找原容器重称，记录时间、皮重和新打印条编号。原容器是否仍在尚未确认。""",
        task="audit", genre="冲突记录说明", terms=("总质量", "皮重", "净质量"),
        tags=("conflicting_sources", "numeric_scope"), features=("conflicting_sources", "numeric_consistency"),
        facts=["甲四百八十二减三十二等于四百五十克", "乙记四百八十克且称已去盒", "缺时间和权威排序，原容器未确认"],
        prerequisites=["净质量计算与来源可信度是两种判断", "复称需要容器和可追查记录"],
        recall=["甲的算术自洽能不能排除乙？"], transfer=["原容器丢失后，能否拿另一只盒子的皮重修正旧数据？"])

    add("公园等高线草图", "这张草图怎么看，东坡和西坡哪边更缓？",
        """提供的等高线示意文字：同一张等比例平面图上，从中心向外三圈封闭线分别标注 80 m、70 m、60 m；东侧相邻线的纸面间距均为 12 mm，西侧均为 4 mm。等高线连接相同海拔的位置；相邻线高差相同时，水平距离更长意味着同样高差分摊在更长路程上。纸上距离只能按本图比例比较，本图未标比例尺。线圈不是步行路线，也没有显示道路、围栏或路面状况。""",
        mode="implicit", material="image", components=("TEXT", "IMAGE"), terms=("等高线", "海拔", "比例尺"),
        features=("implicit", "provided_diagram_text", "visual_evidence_boundary", "formula_reasoning"),
        facts=["由内向外八十、七十、六十米", "东间距十二毫米，西四毫米", "无比例尺和道路信息"],
        prerequisites=["高差与水平距离共同决定坡度", "平面图的圈线不是路径"],
        recall=["为什么线较疏的一侧更缓？"], transfer=["若两幅图比例尺不同，还能只凭纸上间距比较坡度吗？"])

    add("读书会反馈满意比例", "给没学过统计的组织者解读这张表，保留表格，说明总满意比例怎么算，以及这份结果能代表谁。",
        """| 组别 | 已参加人数 | 回收问卷数 | 满意问卷数 |
|---|---:|---:|---:|
| 上午组 | 40 | 10 | 8 |
| 下午组 | 60 | 30 | 18 |
每人最多交一张问卷，两组人员不重叠。满意只计选择“满意”的有效问卷；其余有效问卷选择“一般”或“不满意”，没有进一步分类。回收问卷均有效。未回收者的意见未知。本次“总满意比例”的分母约定为回收的有效问卷数，不是参加人数。没有随机抽样，也没有未回收者访谈。""",
        material="table", components=("TEXT", "TABLE"), terms=("分母", "回收率", "满意比例"),
        tags=("numeric_scope",), features=("table", "numeric_consistency", "sampling_boundary"),
        facts=["参加人数四十与六十，回收十与三十，满意八与十八", "分母是有效回收问卷，未回收意见未知", "两组无重叠"],
        prerequisites=["人数、回收问卷和满意问卷的包含关系", "不同分母的比例不能直接平均"],
        recall=["总满意比例的分子分母各来自哪些格子？"], transfer=["如果下午只回收十份，能否仍沿用原来的总比例？"])

    add("烘焙计时秒数函数", "只原样返回纯 Python 代码，不加注释、说明或 Markdown 围栏。",
        "def to_seconds(minutes, seconds):\n    return minutes * 60 + seconds\n",
        operation="FORMAT_ONLY", augmentation="NONE", mode="non_triggering_control",
        material="code", components=("CODE",), genre="纯代码", task="reference", terms=("Python",),
        features=("non_triggering_control", "pure_code"), facts=["源代码逐字保留"], prerequisites=[], recall=[], transfer=[],
        output_contract={"kind": "python", "verbatim": True, "explanation_allowed": False, "fences_allowed": False})

    add("唱片清单机器交换", "仅原样输出纯 JSON，不加注释、解释或代码围栏。",
        '{"records":[{"title":"Harbor","rpm":33}],"checked":false}',
        operation="FORMAT_ONLY", augmentation="NONE", mode="non_triggering_control",
        material="code", components=("CODE",), genre="纯JSON", task="reference", terms=("JSON",),
        features=("non_triggering_control", "pure_json", "strict_json_no_comments"), facts=["保留 false 和三十三的数值类型"], prerequisites=[], recall=[], transfer=[],
        output_contract={"kind": "json", "verbatim": True, "explanation_allowed": False, "fences_allowed": False})

    add("打字机色带库存数", "仅复制这个整数，不加单位或解释。", "27",
        operation="FORMAT_ONLY", augmentation="NONE", mode="non_triggering_control",
        genre="纯数字", task="reference", terms=("整数",),
        features=("non_triggering_control", "pure_number"), facts=["整数二十七"], prerequisites=[], recall=[], transfer=[],
        output_contract={"kind": "integer", "verbatim": True, "explanation_allowed": False, "fences_allowed": False})

    attach_hidden_mappings(rows, reviews)
    coverage = {
        "suite": "two-layer", "status": "candidate", "case_count": len(rows),
        "provenance": "New synthetic, realistic materials; no external publications or model answers used.",
        "visibility": {"writer_input": "requests.jsonl only",
                       "evaluator_only": ["coverage.json", "scripts/build_two_layer_cases.py", "tests/test_two_layer_cases.py"],
                       "delivery": "Provide only request, source.content and references content; keep routing labels and review notes out of the writing prompt."},
        "review_objective": {"format_layer": "遵守当前有效格式要求，含纯格式不触发边界",
                             "explanation_layer": "完全零基础读者能理解任务目的、必要前提、对象与作用、因果、操作时机和区分依据，并用具体示范判断可观察的成功或失败；不要求统一句式或百科堆积",
                             "framework": "references/explanation-framework.md",
                             "framework_ids": [f"EXPL-{i:03d}" for i in range(1, 15)],
                             "mapping_status": "Per-case hidden review targets mapped to the completed framework; no model or visual validation claimed.",
                             "mapping_scope": "Focused case-specific mappings, not an exhaustive waiver of unmapped rules; pure-format controls do not activate the explanation layer."},
        "length_measurement": "len(request) + len(source text or json.dumps(content, ensure_ascii=False, sort_keys=True)) + sum(len(reference.content)); Python Unicode characters",
        "length_distribution": dict(Counter(row["length_class"] for row in rows)),
        "length_requirements": {
            "balanced_five_bins_required": False,
            "note": "本轮记录真实长度分布，不沿用旧计划五档各四项的配额；多章节长文章按原始素材字符数单独记录，不与 schema 的 length_class 标签混用",
            "multi_section_articles": [
                {"case_id": review["case_id"], "source_char_count": review["source_char_count"]}
                for review in reviews if "multi_section_article" in review["features"]
            ],
        },
        "trigger_distribution": dict(Counter(row["trigger_mode"] for row in rows)),
        "cases": reviews,
    }
    return rows, coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-only", action="store_true",
                        help="Refresh hidden coverage without writing requests; require existing requests to match.")
    args = parser.parse_args()
    rows, coverage = build_cases()
    schema = json.loads((ROOT / "contracts/forward-request.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for row in rows:
        validator.validate(row)
    if args.coverage_only:
        existing_rows = [json.loads(line) for line in
                         (OUTPUT / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        if existing_rows != rows:
            raise ValueError("Existing requests differ; coverage-only mode will not change request or source data")
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "requests.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8", newline="\n")
    (OUTPUT / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "cases": len(rows), "output": str(OUTPUT),
                      "lengths": coverage["length_distribution"],
                      "triggers": coverage["trigger_distribution"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
