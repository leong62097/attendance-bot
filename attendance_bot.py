from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.constants import ChatAction
from datetime import datetime
from zoneinfo import ZoneInfo
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from flask import Flask
from threading import Thread
import html
import json
import os
import traceback

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "attendance_data.json"
TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")

# Web 面板配置
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

# 如要限制管理员命令，可填 Telegram 用户ID，例如：{123456789}
# 目前留空 = 不限制
ADMIN_IDS = set()

STAFF_NAMES = [
    "小鑫", "阿强", "小财", "二狗", "青柚", "小崔", "逍遥", "余果", "阿良", "小凡",
    "美鹅", "杰邓", "实惠", "关智", "靖茹", "七月", "小玫", "颖杰", "卢卡", "瑞安",
    "雪美", "雪玲", "阿宝", "阿凯", "小鹿", "萌神", "小马", "不不", "路路", "小猪",
    "不留", "十六", "阿旺", "M16", "大和", "十一", "小明", "小康", "小E", "维尼",
    "阿煌", "金兰", "小成", "丽小", "阿弟", "小迈", "杨浩", "柠柠", "文南", "小布",
    "里卡", "安妮", "欧迪", "小香", "杰伦", "娜婷", "十三", "小平", "路易斯", "胡萝卜",
    "可可", "鸡仔", "柒柒", "官成", "小水", "子龙", "小西", "明惠", "小雪", "佳佳",
    "梦瑶", "苏苏", "沈三", "唐勋", "小宁", "珠珠", "倪倪", "小鼠", "米儿", "丽莎",
    "凯文", "小陶", "小媛", "麦子", "小杨", "怼怼", "白鹿", "西西", "浩哲", "小柳",
    "阿伟", "大风", "黄丽", "容丽", "荆川", "怀宝", "卢雨", "玉玉", "林希", "丽丽",
    "小白", "月亮", "金金", "贵天", "通邦", "何江", "土豆", "玲玲", "杰克", "黑狼"
]
STAFF_SET = set(STAFF_NAMES)

web_app = Flask(__name__)


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


def load():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def ensure_record(data: dict, key: str, name: str) -> dict:
    if key not in data or not isinstance(data[key], dict):
        data[key] = {}

    record = data[key]
    record["name"] = name
    record["in"] = record.get("in")
    record["out"] = record.get("out")
    record["outwork_start"] = record.get("outwork_start")
    record["outwork_total"] = int(record.get("outwork_total", 0) or 0)
    record["eat_start"] = record.get("eat_start")
    record["eat_total"] = int(record.get("eat_total", 0) or 0)
    record["handover_to"] = record.get("handover_to")
    record["remark"] = record.get("remark")
    return record


def reset_for_new_shift(record: dict, name: str, current: str):
    record["name"] = name
    record["in"] = current
    record["out"] = None
    record["outwork_start"] = None
    record["outwork_total"] = 0
    record["eat_start"] = None
    record["eat_total"] = 0
    record["handover_to"] = None
    record["remark"] = None


def clear_temp_fields(record: dict):
    record["handover_to"] = None
    record["remark"] = None


async def send_reply(update: Update, text: str):
    if update.message:
        await update.message.reply_text(text)


def parse_command_args(context: ContextTypes.DEFAULT_TYPE):
    """
    支持：
    /in 小鑫
    /today 小鑫
    /outwork 小鑫
    /outwork 小鑫 小小
    /outwork 小鑫 | 上厕所
    /outwork 小鑫 小小 | 上厕所
    /eat 小鑫 小小 | 吃饭
    """
    raw = " ".join(context.args).strip()
    if not raw:
        return None, None, None

    remark = None
    left = raw

    if "|" in raw:
        left, remark = raw.split("|", 1)
        left = left.strip()
        remark = remark.strip() or None

    parts = left.split()
    if not parts:
        return None, None, remark

    name = parts[0].strip() if len(parts) >= 1 else None
    handover_to = parts[1].strip() if len(parts) >= 2 else None

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

    # 未下班 = 当前班次
    if not out_dt:
        return True

    # 只要上班或下班日期是今天，就视为今天相关记录
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

    return True, ""


async def in_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, _, _ = parse_command_args(context)
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

    current = full()
    data[key] = {}
    reset_for_new_shift(data[key], name, current)
    save(data)
    await send_reply(update, f"{name} 上班 {current}")


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

    current_time = now()
    total_seconds = diff(record["in"], current_time)
    outwork_seconds = int(record.get("outwork_total", 0) or 0)
    eat_seconds = int(record.get("eat_total", 0) or 0)

    if record.get("outwork_start"):
        extra_out = diff(record["outwork_start"], current_time)
        outwork_seconds += extra_out
        record["outwork_total"] = outwork_seconds
        record["outwork_start"] = None

    if record.get("eat_start"):
        extra_eat = diff(record["eat_start"], current_time)
        eat_seconds += extra_eat
        record["eat_total"] = eat_seconds
        record["eat_start"] = None

    net_seconds = total_seconds - outwork_seconds - eat_seconds
    if net_seconds < 0:
        net_seconds = 0

    record["out"] = full(current_time)
    record["handover_to"] = None
    record["remark"] = None
    save(data)

    msg = (
        f"{name} 下班 {record['out']}\n"
        f"总工时 {sec_to_str(total_seconds)}\n"
        f"外出 {sec_to_str(outwork_seconds)}\n"
        f"吃饭 {sec_to_str(eat_seconds)}\n"
        f"净工时 {sec_to_str(net_seconds)}"
    )
    await send_reply(update, msg)


async def outwork_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, handover_to, remark = parse_command_args(context)

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    if not remark:
        await send_reply(
            update,
            "❌ 外出必须填写备注\n"
            "格式：\n"
            "/outwork 名字 | 备注\n"
            "/outwork 名字 临时代接人 | 备注"
        )
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

    if handover_to:
        ok, reason = is_handover_target_available(chat_id, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["outwork_start"] = full()
    record["handover_to"] = handover_to
    record["remark"] = remark
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

    current_time = now()

    seconds = diff(record["outwork_start"], current_time)
    remark_text = (record.get("remark") or "").lower()

    record["outwork_total"] = int(record.get("outwork_total", 0) or 0) + seconds
    record["outwork_start"] = None
    clear_temp_fields(record)

    save(data)

    reply = (
        f"{name} 外出回来 {full(current_time)}\n"
        f"本次外出 {sec_to_str(seconds)}"
    )

    if any(x in remark_text for x in ["厕所", "上厕所", "洗手间", "wc"]) and seconds > 15 * 60:
        reply += "\n⚠️ 警告：本次厕所外出超过15分钟"

    await send_reply(update, reply)


async def eat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, handover_to, remark = parse_command_args(context)

    valid, msg = validate_name(name)
    if not valid:
        await send_reply(update, msg)
        return

    if remark:
        await send_reply(
            update,
            "❌ 吃饭无需填写备注\n"
            "格式：\n"
            "/eat 名字\n"
            "/eat 名字 临时代接人"
        )
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

    if handover_to:
        ok, reason = is_handover_target_available(chat_id, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["eat_start"] = full()
    record["handover_to"] = handover_to
    record["remark"] = None
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

    current_time = now()

    seconds = diff(record["eat_start"], current_time)

    record["eat_total"] = int(record.get("eat_total", 0) or 0) + seconds
    record["eat_start"] = None
    clear_temp_fields(record)

    save(data)

    reply = (
        f"{name} 吃饭回 {full(current_time)}\n"
        f"本次吃饭 {sec_to_str(seconds)}"
    )

    if seconds > 20 * 60:
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
        f"上班时间：{record.get('in') or '无'}\n"
        f"下班时间：{record.get('out') or '未下班'}\n"
    )

    if record.get("handover_to") and not record.get("out"):
        reply += f"临时代接：{record.get('handover_to')}\n"

    if record.get("remark") and not record.get("out"):
        reply += f"备注：{record.get('remark')}\n"

    reply += (
        f"累计外出：{sec_to_str(totals['outwork_seconds'])}\n"
        f"累计吃饭：{sec_to_str(totals['eat_seconds'])}\n"
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
        if row["status"] != "未打卡":
            line += f" | 净工时：{sec_to_short(row['net_seconds'])}"
        if row["status"] in ("外出中", "吃饭中") and row["handover_to"]:
            line += f" | 临时代接：{row['handover_to']}"
        if row["status"] == "外出中" and row["remark"]:
            line += f" | 备注：{row['remark']}"
        lines.append(line)

    await send_reply(update, "\n".join(lines))


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

    headers = ["姓名", "状态", "上班时间", "下班时间", "临时代接", "备注", "净工时", "累计外出", "累计吃饭"]
    ws.append(headers)

    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        ws.append([
            row["name"],
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
        "A": 12, "B": 12, "C": 22, "D": 22, "E": 14,
        "F": 20, "G": 16, "H": 16, "I": 16
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


async def web_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if BASE_URL:
        await send_reply(update, f"Web 面板地址：{BASE_URL}/")
    else:
        await send_reply(update, "当前未设置 BASE_URL，Web 面板默认地址为你的 Render 域名 /")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = (
        "打卡命令说明\n\n"
        "/in 名字  上班\n"
        "/out 名字  下班\n"
        "/outwork 名字 | 备注  外出\n"
        "/outwork 名字 临时代接人 | 备注  外出并临时交接\n"
        "/back 名字  外出回来\n"
        "/eat 名字  吃饭\n"
        "/eat 名字 临时代接人  吃饭并临时交接\n"
        "/eatback 名字  吃饭回\n"
        "/today 名字  查看当前班次\n"
        "/todayall  查看全部人员状态\n"
        "/export  导出 Excel\n"
        "/web  查看 Web 面板地址\n\n"
        "示例：\n"
        "/in 小鑫\n"
        "/outwork 小鑫 | wc\n"
        "/outwork 小鑫 小小 | 拿快递\n"
        "/back 小鑫\n"
        "/eat 小鑫\n"
        "/eat 小鑫 小小\n"
        "/eatback 小鑫\n"
        "/today 小鑫\n"
        "/todayall\n"
        "/export"
    )
    await send_reply(update, reply)


def build_web_html():
    data = load()
    current_time = now()

    chat_ids = sorted({
        int(k.split("_", 1)[0])
        for k in data.keys()
        if "_" in k and k.split("_", 1)[0].lstrip("-").isdigit()
    })

    if not chat_ids:
        body = "<p>暂无数据</p>"
    else:
        sections = []
        for chat_id in chat_ids:
            rows = get_todayall_rows(chat_id)
            html_rows = []
            for row in rows:
                html_rows.append(
                    "<tr>"
                    f"<td>{html.escape(row['name'])}</td>"
                    f"<td>{html.escape(row['status'])}</td>"
                    f"<td>{html.escape(row['in_time'])}</td>"
                    f"<td>{html.escape(row['out_time'])}</td>"
                    f"<td>{html.escape(row['handover_to'])}</td>"
                    f"<td>{html.escape(row['remark'])}</td>"
                    f"<td>{html.escape(sec_to_short(row['net_seconds']))}</td>"
                    f"<td>{html.escape(sec_to_short(row['outwork_seconds']))}</td>"
                    f"<td>{html.escape(sec_to_short(row['eat_seconds']))}</td>"
                    "</tr>"
                )

            section = f"""
            <h2>群组：{chat_id}</h2>
            <table>
                <thead>
                    <tr>
                        <th>姓名</th>
                        <th>状态</th>
                        <th>上班时间</th>
                        <th>下班时间</th>
                        <th>临时代接</th>
                        <th>备注</th>
                        <th>净工时</th>
                        <th>累计外出</th>
                        <th>累计吃饭</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(html_rows)}
                </tbody>
            </table>
            """
            sections.append(section)

        body = "".join(sections)

    return f"""
    <!doctype html>
    <html lang="zh-CN">
    <head>
        <meta charset="utf-8">
        <title>考勤面板</title>
        <style>
            body {{
                font-family: Arial, "Microsoft YaHei", sans-serif;
                background: #f7f7f7;
                color: #222;
                padding: 20px;
            }}
            h1, h2 {{
                margin: 0 0 16px 0;
            }}
            .time {{
                margin-bottom: 20px;
                color: #666;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: #fff;
                margin-bottom: 28px;
            }}
            th, td {{
                border: 1px solid #ddd;
                padding: 8px 10px;
                text-align: left;
                font-size: 14px;
            }}
            th {{
                background: #f0f0f0;
            }}
            tr:nth-child(even) {{
                background: #fafafa;
            }}
        </style>
    </head>
    <body>
        <h1>考勤 Web 面板</h1>
        <div class="time">当前时间：{html.escape(full(current_time))}</div>
        {body}
    </body>
    </html>
    """


@web_app.route("/")
def web_index():
    return build_web_html()


@web_app.route("/health")
def health():
    return "ok"


def run_web():
    web_app.run(host="0.0.0.0", port=PORT)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("发生异常：")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    # 启动 Web 面板
    web_thread = Thread(target=run_web, daemon=True)
    web_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("in", in_cmd))
    app.add_handler(CommandHandler("out", out_cmd))
    app.add_handler(CommandHandler("outwork", outwork_cmd))
    app.add_handler(CommandHandler("back", back_cmd))
    app.add_handler(CommandHandler("eat", eat_cmd))
    app.add_handler(CommandHandler("eatback", eatback_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("todayall", todayall_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("web", web_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_error_handler(error_handler)

    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()

