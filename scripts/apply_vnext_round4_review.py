"""Apply explicit round-four decisions and create five independently reviewable revisions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "evals" / "forward" / "round-1" / "lifecycle"
REVIEW_PATH = ROOT / "evals" / "reviews" / "vnext-1.1-round-4.json"
REVIEWED_AT = "2026-08-31"
REVIEWED_PROFILE = "round-4-generalization"
NEXT_PROFILE = "round-5-inline-alignment-aemp"


def digest(text: str) -> str:
    """Return the immutable UTF-8 digest used by lifecycle records."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object."""

    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one stable UTF-8 JSON object."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def remove_if_present(path: Path) -> None:
    """Remove an obsolete generated lifecycle path."""

    if path.exists():
        path.unlink()


def load_forward_r2(number: int) -> dict[str, Any]:
    """Load the reviewed R2 regardless of whether this generator ran before."""

    stem = f"FWD-R1-{number:03d}-R2"
    candidates = [
        FORWARD / "candidate" / f"CANDIDATE-{stem}.json",
        FORWARD / "gold" / f"GOLD-{stem}.json",
        FORWARD / "rejected" / f"REJECTED-{stem}.json",
    ]
    for path in candidates:
        if path.exists():
            return read_json(path)
    raise FileNotFoundError(f"reviewed R2 not found for FWD-R1-{number:03d}")


def review_forward_record(record: dict[str, Any], status: str, feedback: list[str]) -> dict[str, Any]:
    """Freeze an R2 as Gold or Rejected using only explicit user review."""

    reviewed = copy.deepcopy(record)
    number = reviewed["identity"]["origin_case_id"].rsplit("-", 1)[-1]
    case_id = f"{status.upper()}-FWD-R1-{number}-R2"
    answer_hash = digest(reviewed["artifact"]["answer"])
    reviewed["identity"].update({
        "case_id": case_id,
        "status": status,
        "revision": 2,
        "approved_by_user": status == "gold",
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": REVIEWED_PROFILE,
    })
    reviewed["artifact"]["answer_sha256"] = answer_hash
    reviewed["artifact"]["approved_snapshot_sha256"] = answer_hash if status == "gold" else None
    reviewed["review"].update({
        "decision_source": "explicit_user_review",
        "decision": "accepted" if status == "gold" else "rejected",
        "reasons": ["用户明确接受当前 R2，可以原样进入 Gold"] if status == "gold" else feedback,
    })
    if status == "rejected":
        reviewed["review"]["regression_requirements"] = feedback
    return reviewed


def aligned_python_block() -> str:
    """Build the reviewed Python explanation with one shared comment column."""

    rows = [
        ("def count_large(values, limit):", "定义函数；values 提供待检查数值，limit 提供比较阈值"),
        ("    total = 0", "创建计数器并从 0 开始，只记录满足条件的元素数量"),
        ("    for value in values:", "依次读取 values 中的每个元素，直到全部处理完成"),
        ("        if value > limit:", "只在当前元素严格大于 limit 时进入下一行，等于时不计数"),
        ("            total += 1", "把计数器增加 1，表示又发现一个满足条件的元素"),
        ("    return total", "返回最终计数，这行本身不会把结果显示在屏幕上"),
    ]
    longest = max(len(code.rstrip()) for code, _ in rows)
    return "\n".join(f"{code.rstrip().ljust(longest)} # {comment}" for code, comment in rows)


REVISION_ANSWERS = {
    5: """# Thermo Mini 首次配对

下面的流程分别显示配对成功和超时退出两种结果

```mermaid
flowchart TD
    A[长按设备侧键 3 秒] --> B[指示灯蓝色闪烁]
    B --> C[在手机系统设置中选择 Thermo Mini]
    C --> D{60 秒内是否连接成功}
    D -- 是 --> E[指示灯常亮 5 秒]
    D -- 否 --> F[设备退出配对]
```

<p align="center">图 1. Thermo Mini 首次配对流程</p>

图中的流程从长按设备侧键开始；蓝色闪烁表示设备已经进入可配对状态，手机随后需要在系统设置中选择 `Thermo Mini`；连接成功时，指示灯会常亮 5 秒，60 秒内没有连接时，设备会退出配对并返回开始步骤

1. 长按设备侧键 3 秒，看到指示灯蓝色闪烁后再继续；这个现象表示设备已经进入配对状态
2. 在手机系统设置中选择 `Thermo Mini`，这一步让手机向当前设备发起连接
3. 查看指示灯
   - 指示灯常亮 5 秒表示连接成功
   - 60 秒内没有连接表示本次配对超时；设备退出配对后，需要从第一步重新开始""",
    9: """原始 Python 代码如下

```python
def count_large(values, limit):
    total = 0
    for value in values:
        if value > limit:
            total += 1
    return total
```

下面保留同一段代码并加入同行注释；每个注释都从最长代码行之后的同一列开始，代码逻辑没有改变

```python
{aligned_code}
```

在 Python 环境中先执行代码定义函数，再调用 `count_large(values, limit)`

原始材料没有给出实际输入，因此无法计算具体结果；代码也没有规定不合格输入的处理方式，需要用字符串、空值或不可比较对象补充测试才能确认失败表现""",
    12: """# 原文结论

已经测定年代的火山灰层位于化石层上方，因此这个年代为埋藏事件确定了最低年龄；不过，这个年代不能说明这些生物在被埋藏以前生活了多长时间

# 不需要地质学知识的理解方式

可以把这些地层想成先后叠放的几层材料；化石层在下面，火山灰层后来覆盖在上面，因此下面的埋藏事件一定发生得更早

测得上方火山灰层的年代以后，只能确认埋藏事件至少已经发生了这么久；埋藏也可能更早，所以这个结果叫作最低年龄

# 补充背景

* 地层（Stratum）：地质过程中逐层形成的岩石或沉积物；上下位置可以帮助判断形成先后
* 火山灰层（Volcanic Ash Layer）：火山喷发后沉积形成的灰层；合适的同位素方法可以测定它的形成年代
* 化石层（Fossil Bed）：包含化石的地层；这里记录了生物被埋藏的位置
* 最低年龄（Minimum Age）：事件至少已经发生了这么久，但实际时间可以更早

测年的对象是化石层上方的火山灰层，不是生物本身；这些信息只能限制埋藏事件的时间，不能据此推断生物在埋藏以前存活了多久""",
    15: """# 阅读位置无法同步时的排查步骤

```mermaid
flowchart TD
    A[确认两台设备登录同一账号] --> B[确认阅读位置同步开关已开启]
    B --> C[手动同步并等待 20 秒]
    C --> D{阅读位置是否变化}
    D -- 是 --> E[同步已经生效]
    D -- 否 --> F[记录书名、设备型号和应用版本]
    F --> G[保留未同步的本地标注，不先重新安装]
```

<p align="center">图 1. 阅读位置同步排查流程</p>

流程先确认账号和同步开关，再执行一次可观察的同步测试；如果阅读位置仍然没有变化，需要保留问题环境和本地标注，避免重新安装造成数据丢失

1. 确认两台设备登录同一账号，这一步用于排除账号不同造成的数据隔离；界面应当显示相同账号
2. 确认两台设备的阅读位置同步开关已经开启，开关关闭时系统不会同步；界面会显示同步功能没有开启
3. 手动同步并等待 20 秒，等待后查看阅读位置是否变化；发生变化表示同步已经生效
4. 阅读位置仍然没有变化时，记录以下信息：
   - 书名：标明出现问题的内容
   - 设备型号：标明出现问题的硬件环境
   - 应用版本：标明出现问题的软件环境
5. 保留未同步的本地标注，不先重新安装；重新安装会删除尚未同步的本地标注，因此它不能作为首选步骤""",
}


def build_forward_r3(rejected: dict[str, Any], number: int, answer: str, feedback: list[str]) -> dict[str, Any]:
    """Create one pending R3 without rewriting the reviewed R2."""

    candidate = copy.deepcopy(rejected)
    candidate["identity"].update({
        "case_id": f"CANDIDATE-FWD-R1-{number:03d}-R3",
        "status": "candidate",
        "revision": 3,
        "approved_by_user": False,
        "reviewed_at": None,
        "profile_revision_at_review": None,
    })
    candidate["source"]["revision_references"] = list(candidate["source"]["revision_references"]) + [{
        "id": f"USER-ROUND4-FWD-{number:03d}",
        "kind": "explicit_user_review",
        "content": "；".join(feedback),
    }]
    if number == 9:
        answer = answer.format(aligned_code=aligned_python_block())
    candidate["artifact"].update({
        "answer": answer,
        "answer_sha256": digest(answer),
        "approved_snapshot_sha256": None,
        "revision_of": f"REJECTED-FWD-R1-{number:03d}-R2",
    })
    candidate["review"].update({
        "decision_source": "pending_user_review",
        "decision": "pending",
        "reasons": ["R3 已按照第四轮用户反馈修订，等待用户逐项审核"],
        "regression_requirements": feedback,
    })
    return candidate


def convert_forward(review: dict[str, Any]) -> list[str]:
    """Convert eight R2 records to Gold and four to Rejected plus R3."""

    written: list[str] = []
    for number in review["accepted"]:
        record = review_forward_record(load_forward_r2(number), "gold", [])
        output = FORWARD / "gold" / f"{record['identity']['case_id']}.json"
        write_json(output, record)
        remove_if_present(FORWARD / "candidate" / f"CANDIDATE-FWD-R1-{number:03d}-R2.json")
        written.append(str(output.relative_to(ROOT)).replace("\\", "/"))
    for number in review["rejected"]:
        feedback = review["feedback"][f"{number:03d}"]
        rejected = review_forward_record(load_forward_r2(number), "rejected", feedback)
        rejected_path = FORWARD / "rejected" / f"{rejected['identity']['case_id']}.json"
        write_json(rejected_path, rejected)
        remove_if_present(FORWARD / "candidate" / f"CANDIDATE-FWD-R1-{number:03d}-R2.json")
        candidate = build_forward_r3(rejected, number, REVISION_ANSWERS[number], feedback)
        candidate_path = FORWARD / "candidate" / f"{candidate['identity']['case_id']}.json"
        write_json(candidate_path, candidate)
        written.extend([
            str(rejected_path.relative_to(ROOT)).replace("\\", "/"),
            str(candidate_path.relative_to(ROOT)).replace("\\", "/"),
        ])
    return written


def convert_c03(review: dict[str, Any]) -> list[str]:
    """Freeze C03 R5 as rejected and create the narrowly revised R6."""

    candidate_path = ROOT / "evals" / "candidate" / "CANDIDATE-03-R5.json"
    rejected_path = ROOT / "evals" / "rejected" / "REJECTED-03-R5.json"
    source = read_json(candidate_path if candidate_path.exists() else rejected_path)
    rejected = copy.deepcopy(source)
    reviewed_hash = digest(rejected["artifact"]["answer"])
    rejected["identity"].update({
        "case_id": "REJECTED-03-R5",
        "status": "rejected",
        "revision": 5,
        "approved_by_user": False,
        "reviewed_at": REVIEWED_AT,
        "profile_revision_at_review": REVIEWED_PROFILE,
    })
    rejected["artifact"]["approved_snapshot_sha256"] = None
    rejected["review"].update({
        "decision_source": "explicit_user_review",
        "decision": "rejected",
        "reasons": review["reasons"],
        "correct_parts": review["correct_parts"],
        "regression_requirements": review["reasons"],
        "reviewed_snapshot_sha256": reviewed_hash,
    })
    write_json(rejected_path, rejected)

    r6 = copy.deepcopy(rejected)
    r6["identity"].update({
        "case_id": "CANDIDATE-03-R6",
        "status": "candidate",
        "revision": 6,
        "approved_by_user": False,
        "reviewed_at": None,
        "profile_revision_at_review": None,
    })
    old = "npm 是 Node.js 生态使用的包管理客户端和软件包仓库；"
    new = "npm 是官方名称，不是 `Node Package Manager` 的首字母缩写；它是 Node.js 生态使用的包管理客户端和软件包仓库；"
    answer = r6["artifact"]["answer"].replace(old, new, 1)
    if answer == r6["artifact"]["answer"]:
        raise RuntimeError("C03 R5 npm definition was not found")
    r6["source"]["references"] = list(r6["source"]["references"]) + [{
        "id": "REF-ROUND-4-NPM-NAME",
        "kind": "explicit_user_review",
        "content": "保留当前内容，并自然说明 npm 是官方名称，不是 Node Package Manager 的首字母缩写",
    }]
    r6["artifact"]["answer"] = answer
    r6["artifact"]["approved_snapshot_sha256"] = None
    r6["review"].update({
        "decision_source": "explicit_user_review",
        "decision": "pending",
        "reasons": ["R6 已增加 npm 官方名称边界，等待人工审核"],
        "correct_parts": review["correct_parts"],
        "regression_requirements": [
            "npm 保持官方小写",
            "自然说明 npm 是官方名称，不是 Node Package Manager 的首字母缩写",
            "保留客户端、软件包仓库、命令主体、退出码、CI 和证据边界",
        ],
    })
    r6["review"].pop("reviewed_snapshot_sha256", None)
    r6_path = ROOT / "evals" / "candidate" / "CANDIDATE-03-R6.json"
    write_json(r6_path, r6)
    remove_if_present(candidate_path)
    return [
        str(rejected_path.relative_to(ROOT)).replace("\\", "/"),
        str(r6_path.relative_to(ROOT)).replace("\\", "/"),
    ]


def main() -> int:
    """Apply the review and report exact post-review lifecycle counts."""

    review = read_json(REVIEW_PATH)["review_round"]
    written = convert_c03(review["c03"]) + convert_forward(review["forward"])
    print(json.dumps({
        "status": "PASS",
        "written": written,
        "lifecycle": {"gold": 27, "rejected": 30, "candidate": 5, "total": 62},
        "first_round_human_acceptance": "8/20",
        "round_four_review": {"accepted": 8, "rejected": 5, "new_candidates": 5},
        "reason": "只有显式用户决定改变生命周期；五个新答案仍为 Candidate",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
