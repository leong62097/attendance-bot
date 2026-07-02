from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.constants import ChatAction
from datetime import datetime, time
from zoneinfo import ZoneInfo
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
import json
import os
import traceback
import base64
import urllib.request
import urllib.error
import asyncio

BOT_TOKEN = os.getenv("BOT_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "leong62097/attendance-bot")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
DATA_FILE = os.getenv("DATA_FILE_PATH", "attendance_data.json")
HISTORY_FILE = os.getenv("HISTORY_FILE_PATH", "attendance_history.json")
TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# 如要限制管理员命令，可填 Telegram 用户ID，例如：{123456789}
# 目前留空 = 不限制
ADMIN_IDS = set()

DAY_SHIFT_START = time(6, 0, 0)
DAY_SHIFT_END = time(17, 59, 59)

# 外出与吃饭超时规则
OUTWORK_OVERTIME_SECONDS = 15 * 60
EAT_OVERTIME_SECONDS = 20 * 60
REMINDER_CHECK_INTERVAL = 30

STAFF_NAMES = [
    "二狗", "青柚", "小崔", "逍遥", "余果", "美鹅", "杰邓", "七月",
    "小玫", "颖杰", "卢卡", "瑞安", "雪美", "雪玲", "阿宝", "阿凯",
    "小鹿", "萌神", "小马", "不不", "路路", "十六", "阿旺", "十一",
    "小明", "小康", "维尼", "阿煌", "金兰", "小成", "丽小", "阿弟",
    "小迈", "柠柠", "文南", "里卡", "安妮", "欧迪", "小香", "杰伦",
    "娜婷", "十三", "小平", "路易斯", "胡萝卜", "鸡仔", "柒柒", "官成",
    "小水", "子龙", "小西", "明惠", "小雪", "梦瑶", "沈三", "唐勋",
    "小宁", "倪倪", "小鼠", "米儿", "丽莎", "小陶", "小媛", "麦子",
    "小杨", "怼怼", "白鹿", "西西", "浩哲", "小柳", "黄丽", "荆川",
    "怀宝", "卢雨", "玉玉", "小白", "月亮", "玲玲", "小草", "胜利",
    "啊宏", "宁宁", "阿森", "秀妍", "阿花", "李顺", "小漫", "小城",
    "美林", "清清", "燕子", "菠萝", "小依", "大球", "知夏", "琪琪",
    "苏苏", "小叶", "小月", "粉亿", "小青", "以沫", "星财", "小川"
]
STAFF_SET = set(STAFF_NAMES)


def now():
    return datetime.now(TIMEZONE)


def full(dt=None):
    if dt is None:
        dt = now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(text: str | None):
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=TIMEZONE)
    except Exception:
        return None


def sec_to_str(sec: int) -> str:
    if sec < 0:
        sec = 0
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}小时{m}分钟{s}秒"


def sec_to_short(sec: int) -> str:
    if sec < 0:
        sec = 0
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h}小时{m}分"


def diff(start_str: str, end_dt: datetime) -> int:
    start_dt = parse_dt(start_str)
    if not start_dt:
        return 0
    seconds = int((end_dt - start_dt).total_seconds())
    return max(seconds, 0)


def github_api_url(path: str) -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"


def github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "attendance-bot"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_get_file(path: str):
    url = github_api_url(path) + f"?ref={GITHUB_BRANCH}"
    req = urllib.request.Request(url, headers=github_headers(), method="GET")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data.get("content", "")
            sha = data.get("sha")
            if content:
                text = base64.b64decode(content).decode("utf-8")
            else:
                text = ""
            return text, sha
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    except Exception:
        raise


def github_put_file(path: str, text: str, sha: str | None = None):
    url = github_api_url(path)

    payload = {
        "message": f"update {path}",
        "content": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**github_headers(), "Content-Type": "application/json"},
        method="PUT"
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load():
    text, _ = github_get_file(DATA_FILE)
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data):
    _, sha = github_get_file(DATA_FILE)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    github_put_file(DATA_FILE, text, sha=sha)


def load_history():
    text, _ = github_get_file(HISTORY_FILE)
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(rows: list):
    _, sha = github_get_file(HISTORY_FILE)
    text = json.dumps(rows, ensure_ascii=False, indent=2)
    github_put_file(HISTORY_FILE, text, sha=sha)


def is_admin(update: Update) -> bool:
    if not ADMIN_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in ADMIN_IDS)


async def require_admin(update: Update) -> bool:
    if is_admin(update):
        return True
    await send_reply(update, "❌ 你没有权限使用此命令")
    return False


def key_by_name(chat_id: int, name: str) -> str:
    return f"{chat_id}_{name}"


def validate_name(name: str) -> tuple[bool, str]:
    if not name:
        return False, "❌ 名字不存在，请检查！"
    if name not in STAFF_SET:
        return False, "❌ 名字不存在，请检查！"
    return True, ""


def determine_shift_type(dt: datetime, manual_shift: str | None = None) -> str:
    if manual_shift == "转":
        return "转班"

    t = dt.time()
    if DAY_SHIFT_START <= t <= DAY_SHIFT_END:
        return "白班"
    return "夜班"


def normalize_shift_input(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if text == "转":
        return "转"
    return None


def get_shift_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def ensure_record(data: dict, key: str, name: str) -> dict:
    if key not in data or not isinstance(data[key], dict):
        data[key] = {}

    record = data[key]
    record["name"] = name
    record["in"] = record.get("in")
    record["out"] = record.get("out")
    record["outwork_start"] = record.get("outwork_start")
    record["outwork_total"] = int(record.get("outwork_total", 0) or 0)
    record["outwork_count"] = int(record.get("outwork_count", 0) or 0)
    record["eat_start"] = record.get("eat_start")
    record["eat_total"] = int(record.get("eat_total", 0) or 0)
    record["eat_count"] = int(record.get("eat_count", 0) or 0)
    record["handover_to"] = record.get("handover_to")
    record["remark"] = record.get("remark")
    record["shift_type"] = record.get("shift_type")
    record["shift_date"] = record.get("shift_date")
    # 保留旧字段名，避免旧数据失效；实际含义改为“外出超时”
    record["toilet_overtime"] = int(record.get("toilet_overtime", 0) or 0)
    record["eat_overtime"] = int(record.get("eat_overtime", 0) or 0)
    record["toilet_reminded"] = bool(record.get("toilet_reminded", False))
    record["eat_reminded"] = bool(record.get("eat_reminded", False))
    return record


def reset_for_new_shift(record: dict, name: str, current: str, shift_type: str, shift_date: str):
    record["name"] = name
    record["in"] = current
    record["out"] = None
    record["outwork_start"] = None
    record["outwork_total"] = 0
    record["outwork_count"] = 0
    record["eat_start"] = None
    record["eat_total"] = 0
    record["eat_count"] = 0
    record["handover_to"] = None
    record["remark"] = None
    record["shift_type"] = shift_type
    record["shift_date"] = shift_date
    record["toilet_overtime"] = 0
    record["eat_overtime"] = 0
    record["toilet_reminded"] = False
    record["eat_reminded"] = False


def clear_temp_fields(record: dict):
    record["handover_to"] = None
    record["remark"] = None


def append_history(chat_id: int, record: dict, out_time: str, net_seconds: int):
    history = load_history()
    history.append({
        "chat_id": chat_id,
        "name": record.get("name") or "",
        "shift_type": record.get("shift_type") or "",
        "shift_date": record.get("shift_date") or "",
        "in": record.get("in") or "",
        "out": out_time,
        "outwork_total": int(record.get("outwork_total", 0) or 0),
        "eat_total": int(record.get("eat_total", 0) or 0),
        "net_seconds": int(net_seconds or 0),
        "outwork_count": int(record.get("outwork_count", 0) or 0),
        "eat_count": int(record.get("eat_count", 0) or 0),
        "toilet_overtime": int(record.get("toilet_overtime", 0) or 0),
        "eat_overtime": int(record.get("eat_overtime", 0) or 0),
    })
    save_history(history)


async def send_reply(update: Update, text: str):
    if update.message:
        await update.message.reply_text(text)


def parse_command_args(context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        return None, None, None

    name = None
    handover_to = None
    remark = None

    if len(args) == 1:
        name = args[0].strip()
    elif len(args) == 2:
        name = args[0].strip()
        remark = args[1].strip()
    else:
        name = args[0].strip()
        handover_to = args[1].strip()
        remark = " ".join(args[2:]).strip() or None

    return name, handover_to, remark


def get_status(record: dict) -> str:
    if not record.get("in"):
        return "none"
    if record.get("out"):
        return "off"
    if record.get("outwork_start"):
        return "outwork"
    if record.get("eat_start"):
        return "eat"
    return "working"


def is_record_current(record: dict, current_time: datetime) -> bool:
    in_dt = parse_dt(record.get("in"))
    out_dt = parse_dt(record.get("out"))

    if not in_dt:
        return False

    if not out_dt:
        return True

    today = current_time.date()
    return in_dt.date() == today or out_dt.date() == today


def calc_current_totals(record: dict, current_time: datetime):
    in_time = record.get("in")
    if not in_time:
        return {
            "total_seconds": 0,
            "outwork_seconds": 0,
            "eat_seconds": 0,
            "net_seconds": 0,
        }

    if record.get("out"):
        end_time = parse_dt(record["out"]) or current_time
    else:
        end_time = current_time

    total_seconds = diff(in_time, end_time)
    outwork_seconds = int(record.get("outwork_total", 0) or 0)
    eat_seconds = int(record.get("eat_total", 0) or 0)

    if record.get("outwork_start") and not record.get("out"):
        outwork_seconds += diff(record["outwork_start"], current_time)

    if record.get("eat_start") and not record.get("out"):
        eat_seconds += diff(record["eat_start"], current_time)

    net_seconds = total_seconds - outwork_seconds - eat_seconds
    if net_seconds < 0:
        net_seconds = 0

    return {
        "total_seconds": total_seconds,
        "outwork_seconds": outwork_seconds,
        "eat_seconds": eat_seconds,
        "net_seconds": net_seconds,
    }


def working_msg(name: str, in_time: str) -> str:
    return (
        f"{name}已在上班中\n"
        f"上班时间：{in_time}\n"
        f"如需结束班次，请先使用 /out {name}"
    )


def outwork_msg(name: str, outwork_time: str, handover_to: str | None = None, remark: str | None = None) -> str:
    msg = (
        f"{name}已在外出中\n"
        f"外出时间：{outwork_time}\n"
    )
    if handover_to:
        msg += f"当前工作已临时交接给：{handover_to}\n"
    if remark:
        msg += f"备注：{remark}\n"
    msg += (
        f"如需返回上班，请先使用 /back {name}\n"
        f"如需结束班次，请先使用 /out {name}"
    )
    return msg


def eat_msg(name: str, eat_time: str, handover_to: str | None = None, remark: str | None = None) -> str:
    msg = (
        f"{name}已在吃饭中\n"
        f"吃饭时间：{eat_time}\n"
    )
    if handover_to:
        msg += f"当前工作已临时交接给：{handover_to}\n"
    if remark:
        msg += f"备注：{remark}\n"
    msg += (
        f"如需返回上班，请先使用 /eatback {name}\n"
        f"如需结束班次，请先使用 /out {name}"
    )
    return msg


def off_msg(name: str, out_time: str) -> str:
    return (
        f"{name}当前班次已结束\n"
        f"下班时间：{out_time}\n"
        f"如需开始新班次，请使用 /in {name}"
    )


def get_todayall_rows(chat_id: int):
    data = load()
    current_time = now()
    rows = []

    for name in STAFF_NAMES:
        key = key_by_name(chat_id, name)
        record = data.get(key)

        if not record or not isinstance(record, dict) or not is_record_current(record, current_time):
            rows.append({
                "name": name,
                "status": "未打卡",
                "in_time": "",
                "out_time": "",
                "handover_to": "",
                "remark": "",
                "shift_type": "",
                "net_seconds": 0,
                "outwork_seconds": 0,
                "eat_seconds": 0,
            })
            continue

        record = ensure_record(data, key, name)
        totals = calc_current_totals(record, current_time)
        status_key = get_status(record)

        status_map = {
            "working": "上班中",
            "outwork": "外出中",
            "eat": "吃饭中",
            "off": "已下班",
            "none": "未打卡"
        }

        status_text = status_map.get(status_key, "未知")
        handover_to = record.get("handover_to") or ""
        remark = record.get("remark") or ""

        if status_text not in ("外出中", "吃饭中"):
            handover_to = ""

        if status_text != "外出中":
            remark = ""

        rows.append({
            "name": name,
            "status": status_text,
            "in_time": record.get("in") or "",
            "out_time": record.get("out") or "",
            "handover_to": handover_to,
            "remark": remark,
            "shift_type": record.get("shift_type") or "",
            "net_seconds": totals["net_seconds"],
            "outwork_seconds": totals["outwork_seconds"],
            "eat_seconds": totals["eat_seconds"],
        })

    return rows


def is_handover_target_available(chat_id: int, data: dict, handover_to: str) -> tuple[bool, str]:
    valid, msg = validate_name(handover_to)
    if not valid:
        return False, msg

    key = key_by_name(chat_id, handover_to)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not record.get("in"):
        return False, f"❌ 临时代接人 {handover_to} 当前未在上班中，无法交接"

    if not is_record_current(record, now()):
        return False, f"❌ 临时代接人 {handover_to} 当前未在上班中，无法交接"

    status = get_status(record)
    if status != "working":
        if status == "outwork":
            return False, f"❌ 临时代接人 {handover_to} 当前正在外出中，无法交接"
        if status == "eat":
            return False, f"❌ 临时代接人 {handover_to} 当前正在吃饭中，无法交接"
        if status == "off":
            return False, f"❌ 临时代接人 {handover_to} 当前班次已结束，无法交接"
        return False, f"❌ 临时代接人 {handover_to} 当前状态异常，无法交接"

    # 代接人如果正在替别人代岗，也不能再被交接
    covering, covering_msg = is_covering_for_others(chat_id, data, handover_to)
    if covering:
        return False, f"❌ 临时代接人 {handover_to} 当前正在代接他人工作，无法再次交接"

    return True, ""


def is_covering_for_others(chat_id: int, data: dict, name: str) -> tuple[bool, str]:
    current_time = now()

    for other_name in STAFF_NAMES:
        if other_name == name:
            continue

        other_key = key_by_name(chat_id, other_name)
        other_record = data.get(other_key)

        if not other_record or not isinstance(other_record, dict):
            continue

        if not is_record_current(other_record, current_time):
            continue

        status = get_status(other_record)
        if status not in ("outwork", "eat"):
            continue

        if other_record.get("handover_to") == name:
            return True, f"❌ {name} 当前正在代接 {other_name} 的工作，暂时不能外出、吃饭或下班"

    return False, ""


async def reminder_loop(application):
    while True:
        try:
            data = load()
            current_time = now()
            changed = False

            for key, raw_record in list(data.items()):
                if not isinstance(raw_record, dict):
                    continue

                record = ensure_record(data, key, raw_record.get("name") or "")

                if not is_record_current(record, current_time):
                    continue

                name = record.get("name") or ""

                try:
                    chat_id = int(str(key).split("_", 1)[0])
                except Exception:
                    continue

                # 只要是外出，一律超过15分钟提醒
                if record.get("outwork_start"):
                    passed = diff(record["outwork_start"], current_time)
                    if passed >= OUTWORK_OVERTIME_SECONDS and not record.get("toilet_reminded", False):
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ 提醒：{name} 外出已超过15分钟，请尽快确认"
                        )
                        record["toilet_reminded"] = True
                        changed = True

                if record.get("eat_start"):
                    passed = diff(record["eat_start"], current_time)
                    if passed >= EAT_OVERTIME_SECONDS and not record.get("eat_reminded", False):
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ 提醒：{name} 吃饭已超过20分钟，请尽快确认"
                        )
                        record["eat_reminded"] = True
                        changed = True

            if changed:
                save(data)

        except asyncio.CancelledError:
            break
        except Exception:
            print("自动提醒循环异常：")
            traceback.print_exc()

        await asyncio.sleep(REMINDER_CHECK_INTERVAL)


async def post_init(application):
    application.bot_data["reminder_loop_task"] = asyncio.create_task(reminder_loop(application))
    print("自动提醒循环已启动")


async def post_shutdown(application):
    task = application.bot_data.get("reminder_loop_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def in_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await send_reply(update, "❌ 格式错误\n格式：\n/in 名字\n/in 名字 转")
        return

    name = args[0].strip()
    shift_override = None

    if len(args) >= 2:
        shift_override = normalize_shift_input(args[1])
        if not shift_override:
            await send_reply(update, "❌ 上班仅支持：\n/in 名字\n/in 名字 转")
            return

    if len(args) > 2:
        await send_reply(update, "❌ 上班仅支持：\n/in 名字\n/in 名字 转")
        return

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if record and isinstance(record, dict):
        if is_record_current(record, now()):
            if record.get("outwork_start"):
                await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to"), record.get("remark")))
                return
            if record.get("eat_start"):
                await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to"), record.get("remark")))
                return
            if record.get("in") and not record.get("out"):
                await send_reply(update, working_msg(name, record["in"]))
                return

    current_dt = now()
    current = full(current_dt)
    shift_type = determine_shift_type(current_dt, shift_override)
    shift_date = get_shift_date(current_dt)

    data[key] = {}
    reset_for_new_shift(data[key], name, current, shift_type, shift_date)
    save(data)

    await send_reply(update, f"{name} 上班 {current}\n班次：{shift_type}")


async def out_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, _, _ = parse_command_args(context)
    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not record.get("in") or not is_record_current(record, now()):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行下班打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    covering, covering_msg = is_covering_for_others(chat_id, data, name)
    if covering:
        await send_reply(update, covering_msg)
        return

    current_time = now()
    total_seconds = diff(record["in"], current_time)
    outwork_seconds = int(record.get("outwork_total", 0) or 0)
    eat_seconds = int(record.get("eat_total", 0) or 0)

    if record.get("outwork_start"):
        extra_out = diff(record["outwork_start"], current_time)
        outwork_seconds += extra_out
        record["outwork_total"] = outwork_seconds

        # 不再看备注，只要外出超过15分钟就算超时
        if extra_out > OUTWORK_OVERTIME_SECONDS:
            record["toilet_overtime"] = int(record.get("toilet_overtime", 0) or 0) + 1

        record["outwork_start"] = None
        record["toilet_reminded"] = False

    if record.get("eat_start"):
        extra_eat = diff(record["eat_start"], current_time)
        eat_seconds += extra_eat
        record["eat_total"] = eat_seconds

        if extra_eat > EAT_OVERTIME_SECONDS:
            record["eat_overtime"] = int(record.get("eat_overtime", 0) or 0) + 1

        record["eat_start"] = None
        record["eat_reminded"] = False

    net_seconds = total_seconds - outwork_seconds - eat_seconds
    if net_seconds < 0:
        net_seconds = 0

    out_text = full(current_time)
    record["out"] = out_text
    clear_temp_fields(record)

    append_history(chat_id, record, out_text, net_seconds)
    save(data)

    msg = (
        f"{name} 下班 {record['out']}\n"
        f"班次：{record.get('shift_type') or '未设置'}\n"
        f"总工时 {sec_to_str(total_seconds)}\n"
        f"外出 {sec_to_str(outwork_seconds)}（{int(record.get('outwork_count', 0) or 0)}次）\n"
        f"吃饭 {sec_to_str(eat_seconds)}（{int(record.get('eat_count', 0) or 0)}次）\n"
        f"净工时 {sec_to_str(net_seconds)}\n"
        f"外出超时 {int(record.get('toilet_overtime', 0) or 0)}次\n"
        f"吃饭超时 {int(record.get('eat_overtime', 0) or 0)}次"
    )
    await send_reply(update, msg)


async def outwork_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, handover_to, remark = parse_command_args(context)

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    if handover_to and handover_to == name:
        await send_reply(update, "❌ 临时代接人不能与本人相同")
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not record.get("in") or not is_record_current(record, now()):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行外出打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if record.get("outwork_start"):
        await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to"), record.get("remark")))
        return

    if record.get("eat_start"):
        await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to"), record.get("remark")))
        return

    covering, covering_msg = is_covering_for_others(chat_id, data, name)
    if covering:
        await send_reply(update, covering_msg)
        return

    if handover_to:
        ok, reason = is_handover_target_available(chat_id, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["outwork_start"] = full()
    record["handover_to"] = handover_to
    record["remark"] = remark
    record["outwork_count"] = int(record.get("outwork_count", 0) or 0) + 1
    record["toilet_reminded"] = False
    save(data)

    reply = f"{name} 外出 {record['outwork_start']}"
    if handover_to:
        reply += f"\n当前工作已临时交接给：{handover_to}"
    if remark:
        reply += f"\n备注：{remark}"

    await send_reply(update, reply)


async def back_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, _, _ = parse_command_args(context)

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not record.get("outwork_start"):
        await send_reply(update, f"{name}当前不在外出中")
        return

    record = ensure_record(data, key, name)

    current_time = now()
    seconds = diff(record["outwork_start"], current_time)

    record["outwork_total"] = int(record.get("outwork_total", 0) or 0) + seconds
    record["outwork_start"] = None
    record["toilet_reminded"] = False

    # 不再看备注，只要外出超过15分钟就算超时
    overtime_hit = seconds > OUTWORK_OVERTIME_SECONDS
    if overtime_hit:
        record["toilet_overtime"] = int(record.get("toilet_overtime", 0) or 0) + 1

    clear_temp_fields(record)
    save(data)

    reply = (
        f"{name} 外出回来 {full(current_time)}\n"
        f"本次外出 {sec_to_str(seconds)}"
    )

    if overtime_hit:
        reply += "\n⚠️ 警告：本次外出超过15分钟"

    await send_reply(update, reply)


async def eat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if not args:
        await send_reply(
            update,
            "❌ 格式错误\n"
            "格式：\n"
            "/eat 名字\n"
            "/eat 名字 临时代接人"
        )
        return

    name = args[0].strip()
    handover_to = args[1].strip() if len(args) >= 2 else None

    if len(args) > 2:
        await send_reply(
            update,
            "❌ 吃饭无需填写备注\n"
            "格式：\n"
            "/eat 名字\n"
            "/eat 名字 临时代接人"
        )
        return

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    if handover_to and handover_to == name:
        await send_reply(update, "❌ 临时代接人不能与本人相同")
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not record.get("in") or not is_record_current(record, now()):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行吃饭打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if record.get("eat_start"):
        await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to"), record.get("remark")))
        return

    if record.get("outwork_start"):
        await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to"), record.get("remark")))
        return

    covering, covering_msg = is_covering_for_others(chat_id, data, name)
    if covering:
        await send_reply(update, covering_msg)
        return

    if handover_to:
        ok, reason = is_handover_target_available(chat_id, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["eat_start"] = full()
    record["handover_to"] = handover_to
    record["remark"] = None
    record["eat_count"] = int(record.get("eat_count", 0) or 0) + 1
    record["eat_reminded"] = False
    save(data)

    reply = f"{name} 吃饭 {record['eat_start']}"
    if handover_to:
        reply += f"\n当前工作已临时交接给：{handover_to}"

    await send_reply(update, reply)


async def eatback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, _, _ = parse_command_args(context)

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not record.get("eat_start"):
        await send_reply(update, f"{name}当前不在吃饭中")
        return

    record = ensure_record(data, key, name)

    current_time = now()
    seconds = diff(record["eat_start"], current_time)

    record["eat_total"] = int(record.get("eat_total", 0) or 0) + seconds
    record["eat_start"] = None
    record["eat_reminded"] = False

    overtime_hit = seconds > EAT_OVERTIME_SECONDS
    if overtime_hit:
        record["eat_overtime"] = int(record.get("eat_overtime", 0) or 0) + 1

    clear_temp_fields(record)
    save(data)

    reply = (
        f"{name} 吃饭回 {full(current_time)}\n"
        f"本次吃饭 {sec_to_str(seconds)}"
    )

    if overtime_hit:
        reply += "\n⚠️ 警告：吃饭超过20分钟"

    await send_reply(update, reply)


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, _, _ = parse_command_args(context)
    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    data = load()
    chat_id = update.effective_chat.id
    key = key_by_name(chat_id, name)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not is_record_current(record, now()):
        await send_reply(update, f"{name} 无当前班次记录")
        return

    record = ensure_record(data, key, name)
    if not record.get("in"):
        await send_reply(update, f"{name} 无当前班次记录")
        return

    current_time = now()
    totals = calc_current_totals(record, current_time)

    if record.get("out"):
        status = "已下班"
    elif record.get("outwork_start"):
        status = "外出中"
    elif record.get("eat_start"):
        status = "吃饭中"
    else:
        status = "上班中"

    reply = (
        f"{name} 当前班次\n"
        f"当前状态：{status}\n"
        f"班次：{record.get('shift_type') or '未设置'}\n"
        f"班次日期：{record.get('shift_date') or '未设置'}\n"
        f"上班时间：{record.get('in') or '无'}\n"
        f"下班时间：{record.get('out') or '未下班'}\n"
    )

    if status in ("外出中", "吃饭中") and record.get("handover_to"):
        reply += f"临时代接：{record.get('handover_to')}\n"

    if status == "外出中" and record.get("remark"):
        reply += f"备注：{record.get('remark')}\n"

    reply += (
        f"累计外出：{sec_to_str(totals['outwork_seconds'])}（{int(record.get('outwork_count', 0) or 0)}次）\n"
        f"累计吃饭：{sec_to_str(totals['eat_seconds'])}（{int(record.get('eat_count', 0) or 0)}次）\n"
        f"外出超时：{int(record.get('toilet_overtime', 0) or 0)}次\n"
        f"吃饭超时：{int(record.get('eat_overtime', 0) or 0)}次\n"
        f"当前净工时：{sec_to_str(totals['net_seconds'])}"
    )
    await send_reply(update, reply)


async def todayall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    chat_id = update.effective_chat.id
    rows = get_todayall_rows(chat_id)

    lines = ["全部人员当前状态\n"]
    for row in rows:
        line = f"{row['name']} {row['status']}"
        if row["shift_type"]:
            line += f"（{row['shift_type']}）"
        if row["status"] != "未打卡":
            line += f" | 净工时：{sec_to_short(row['net_seconds'])}"
        if row["status"] in ("外出中", "吃饭中") and row["handover_to"]:
            line += f" | 临时代接：{row['handover_to']}"
        if row["status"] == "外出中" and row["remark"]:
            line += f" | 备注：{row['remark']}"
        lines.append(line)

    await send_reply(update, "\n".join(lines))


def build_report_lines(chat_id: int, shift_date: str, shift_type: str) -> list[str]:
    history = load_history()
    rows = [
        row for row in history
        if isinstance(row, dict)
        and str(row.get("chat_id")) == str(chat_id)
        and row.get("shift_date") == shift_date
        and row.get("shift_type") == shift_type
    ]

    if shift_type == "白班":
        range_text = f"{shift_date} 06:00 - {shift_date} 17:59"
    elif shift_type == "夜班":
        range_text = f"{shift_date} 18:00 - 次日 05:59"
    else:
        range_text = f"{shift_date} 转班"

    lines = [
        f"{shift_date} {shift_type}日报",
        f"统计区间：{range_text}",
        f"完结班次：{len(rows)}",
        ""
    ]

    if not rows:
        lines.append("暂无已下班记录")
        return lines

    total_net = sum(int(r.get("net_seconds", 0) or 0) for r in rows)
    total_outwork = sum(int(r.get("outwork_total", 0) or 0) for r in rows)
    total_eat = sum(int(r.get("eat_total", 0) or 0) for r in rows)
    total_outwork_count = sum(int(r.get("outwork_count", 0) or 0) for r in rows)
    total_eat_count = sum(int(r.get("eat_count", 0) or 0) for r in rows)
    total_outwork_overtime = sum(int(r.get("toilet_overtime", 0) or 0) for r in rows)
    total_eat_overtime = sum(int(r.get("eat_overtime", 0) or 0) for r in rows)

    lines.extend([
        f"净工时合计：{sec_to_str(total_net)}",
        f"外出合计：{sec_to_str(total_outwork)}（{total_outwork_count}次）",
        f"吃饭合计：{sec_to_str(total_eat)}（{total_eat_count}次）",
        f"外出超时：{total_outwork_overtime}次",
        f"吃饭超时：{total_eat_overtime}次",
        "",
        "人员明细："
    ])

    rows.sort(key=lambda x: x.get("in") or "")
    for r in rows:
        lines.append(
            f"{r.get('name', '')} "
            f"{r.get('in', '')[11:16]}→{r.get('out', '')[11:16]} "
            f"净{sec_to_short(int(r.get('net_seconds', 0) or 0))} "
            f"| 外出{int(r.get('outwork_count', 0) or 0)}次 "
            f"| 吃饭{int(r.get('eat_count', 0) or 0)}次 "
            f"| 外出超时{int(r.get('toilet_overtime', 0) or 0)}次 "
            f"| 吃饭超时{int(r.get('eat_overtime', 0) or 0)}次"
        )

    return lines


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    args = context.args
    if len(args) != 1 or args[0] not in ("白班", "夜班", "转班"):
        await send_reply(
            update,
            "❌ 格式错误\n"
            "格式：\n"
            "/report 白班\n"
            "/report 夜班\n"
            "/report 转班"
        )
        return

    shift_type = args[0]
    shift_date = get_shift_date(now())
    chat_id = update.effective_chat.id
    lines = build_report_lines(chat_id, shift_date, shift_type)
    await send_reply(update, "\n".join(lines))


async def reportall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    shift_date = get_shift_date(now())
    chat_id = update.effective_chat.id

    parts = []
    for shift_type in ("白班", "夜班", "转班"):
        parts.append("\n".join(build_report_lines(chat_id, shift_date, shift_type)))

    await send_reply(update, "\n\n".join(parts))


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update):
        return

    if update.message:
        await update.message.chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)

    chat_id = update.effective_chat.id
    rows = get_todayall_rows(chat_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "考勤状态"

    headers = ["姓名", "班次", "状态", "上班时间", "下班时间", "临时代接", "备注", "净工时", "累计外出", "累计吃饭"]
    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        ws.append([
            row["name"],
            row["shift_type"],
            row["status"],
            row["in_time"],
            row["out_time"],
            row["handover_to"],
            row["remark"],
            sec_to_str(row["net_seconds"]),
            sec_to_str(row["outwork_seconds"]),
            sec_to_str(row["eat_seconds"]),
        ])

    widths = {
        "A": 12, "B": 10, "C": 12, "D": 22, "E": 22, "F": 14,
        "G": 20, "H": 16, "I": 16, "J": 16
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    os.makedirs("exports", exist_ok=True)
    filename = f"exports/attendance_{chat_id}_{now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(filename)

    with open(filename, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=os.path.basename(filename),
            caption="考勤导出完成"
        )

    if BASE_URL:
        await send_reply(update, f"Web 面板地址：{BASE_URL}/")
    else:
        await send_reply(update, "当前未设置 BASE_URL，Web 面板默认地址为你的 Render 域名 /")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = (
        "打卡命令说明\n\n"
        "/in 名字  上班（自动识别白/夜班）\n"
        "/in 名字 转  转班上班\n"
        "/out 名字  下班\n"
        "/outwork 名字  外出\n"
        "/outwork 名字 备注  外出\n"
        "/outwork 名字 临时代接人 备注  外出并临时交接\n"
        "/back 名字  外出回来\n"
        "/eat 名字  吃饭\n"
        "/eat 名字 临时代接人  吃饭并临时交接\n"
        "/eatback 名字  吃饭回\n"
        "/today 名字  查看当前班次\n"
        "/todayall  查看全部人员状态\n"
        "/report 白班  查看当天白班日报\n"
        "/report 夜班  查看当天夜班日报\n"
        "/report 转班  查看当天转班日报\n"
        "/reportall  查看当天全部班次日报\n"
        "/export  导出 Excel\n\n"
        "白夜班规则：\n"
        "06:00–17:59 = 白班\n"
        "18:00–05:59 = 夜班\n"
        "转班必须手动写：/in 名字 转\n\n"
        "超时规则：\n"
        "外出超过15分钟 = 提醒/警告\n"
        "吃饭超过20分钟 = 提醒/警告\n\n"
        "示例：\n"
        "/in 小鑫\n"
        "/in 小鑫 转\n"
        "/outwork 小鑫\n"
        "/outwork 小鑫 拿快递\n"
        "/outwork 小鑫 小明 拿快递\n"
        "/back 小鑫\n"
        "/eat 小鑫\n"
        "/eat 小鑫 小明\n"
        "/eatback 小鑫\n"
        "/today 小鑫\n"
        "/todayall\n"
        "/report 白班\n"
        "/reportall\n"
        "/export"
    )
    await send_reply(update, reply)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("发生异常：")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("in", in_cmd))
    app.add_handler(CommandHandler("out", out_cmd))
    app.add_handler(CommandHandler("outwork", outwork_cmd))
    app.add_handler(CommandHandler("back", back_cmd))
    app.add_handler(CommandHandler("eat", eat_cmd))
    app.add_handler(CommandHandler("eatback", eatback_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("todayall", todayall_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("reportall", reportall_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_error_handler(error_handler)

    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
