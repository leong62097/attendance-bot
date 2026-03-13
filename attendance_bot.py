from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import traceback

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "attendance_data.json"

TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")


def now():
    return datetime.now(TIMEZONE)


def full(dt=None):
    if dt is None:
        dt = now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def sec_to_str(sec: int) -> str:
    if sec < 0:
        sec = 0
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}小时{m}分钟{s}秒"


def diff(start_str: str, end_dt: datetime) -> int:
    start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
    start_dt = start_dt.replace(tzinfo=TIMEZONE)
    seconds = int((end_dt - start_dt).total_seconds())
    return max(seconds, 0)


def load():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except Exception:
        return {}


def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def key_by_name(update: Update, name: str) -> str:
    return f"{update.effective_chat.id}_{name}"


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
    return record


def get_names_from_args(context: ContextTypes.DEFAULT_TYPE):
    """
    支持：
    /in 小鑫
    /outwork 小鑫
    /outwork 小鑫 小小
    /eat 小鑫 小小
    """
    if not context.args:
        return None, None

    if len(context.args) == 1:
        name = context.args[0].strip()
        return (name if name else None), None

    name = context.args[0].strip()
    handover_to = " ".join(context.args[1:]).strip()

    return (name if name else None), (handover_to if handover_to else None)


async def send_reply(update: Update, text: str):
    if update.message:
        await update.message.reply_text(text)


def working_msg(name: str, in_time: str) -> str:
    return (
        f"{name}已在上班中\n"
        f"上班时间：{in_time}\n"
        f"如需结束班次，请先使用 /out {name}"
    )


def outwork_msg(name: str, outwork_time: str, handover_to: str | None = None) -> str:
    msg = (
        f"{name}已在外出中\n"
        f"外出时间：{outwork_time}\n"
    )
    if handover_to:
        msg += f"当前工作已临时交接给：{handover_to}\n"
    msg += (
        f"如需返回上班，请先使用 /back {name}\n"
        f"如需结束班次，请先使用 /out {name}"
    )
    return msg


def eat_msg(name: str, eat_time: str, handover_to: str | None = None) -> str:
    msg = (
        f"{name}已在吃饭中\n"
        f"吃饭时间：{eat_time}\n"
    )
    if handover_to:
        msg += f"当前工作已临时交接给：{handover_to}\n"
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


def calc_current_totals(record: dict, current_time: datetime):
    in_time = record.get("in")
    if not in_time:
        return {
            "total_seconds": 0,
            "outwork_seconds": 0,
            "eat_seconds": 0,
            "net_seconds": 0,
        }

    total_seconds = diff(in_time, current_time)
    outwork_seconds = int(record.get("outwork_total", 0) or 0)
    eat_seconds = int(record.get("eat_total", 0) or 0)

    if record.get("outwork_start"):
        outwork_seconds += diff(record["outwork_start"], current_time)

    if record.get("eat_start"):
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


def get_status(record: dict) -> str:
    if record.get("out"):
        return "off"
    if record.get("outwork_start"):
        return "outwork"
    if record.get("eat_start"):
        return "eat"
    if record.get("in"):
        return "working"
    return "none"


def is_handover_target_available(update: Update, data: dict, handover_to: str) -> tuple[bool, str]:
    key = key_by_name(update, handover_to)
    record = data.get(key)

    if not record or not isinstance(record, dict) or not record.get("in"):
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
    name, extra = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/in 名字\n例如：/in 小鑫")
        return

    data = load()
    key = key_by_name(update, name)
    record = data.get(key)

    if record and isinstance(record, dict):
        if record.get("out") and not record.get("outwork_start") and not record.get("eat_start"):
            pass
        elif record.get("outwork_start"):
            await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to")))
            return
        elif record.get("eat_start"):
            await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to")))
            return
        elif record.get("in") and not record.get("out"):
            await send_reply(update, working_msg(name, record["in"]))
            return

    current = full()
    data[key] = {
        "name": name,
        "in": current,
        "out": None,
        "outwork_start": None,
        "outwork_total": 0,
        "eat_start": None,
        "eat_total": 0,
        "handover_to": None,
    }
    save(data)
    await send_reply(update, f"{name} 上班 {current}")


async def out_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, extra = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/out 名字\n例如：/out 小鑫")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行下班打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if not record.get("in"):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行下班打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

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
    name, handover_to = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/outwork 名字 [临时代接人]\n例如：/outwork 小鑫\n例如：/outwork 小鑫 小小")
        return

    if handover_to and handover_to == name:
        await send_reply(update, "❌ 临时代接人不能与本人相同")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行外出打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if not record.get("in"):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行外出打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if record.get("outwork_start"):
        await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to")))
        return

    if record.get("eat_start"):
        await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to")))
        return

    if handover_to:
        ok, reason = is_handover_target_available(update, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["outwork_start"] = full()
    record["handover_to"] = handover_to
    save(data)

    msg = f"{name} 外出 {record['outwork_start']}"
    if handover_to:
        msg += f"\n当前工作已临时交接给：{handover_to}"
    await send_reply(update, msg)


async def back_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, extra = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/back 名字\n例如：/back 小鑫")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
        await send_reply(
            update,
            f"{name}当前不在外出中\n"
            f"无法进行返回打卡\n"
            f"如需外出，请先使用 /outwork {name}"
        )
        return

    record = ensure_record(data, key, name)

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if not record.get("outwork_start"):
        if record.get("eat_start"):
            await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to")))
            return

        if record.get("in"):
            await send_reply(
                update,
                f"{name}当前不在外出中\n"
                f"无法进行返回打卡\n"
                f"如需外出，请先使用 /outwork {name}"
            )
            return

        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    current_time = now()
    seconds = diff(record["outwork_start"], current_time)
    handover_to = record.get("handover_to")

    record["outwork_total"] = int(record.get("outwork_total", 0) or 0) + seconds
    record["outwork_start"] = None
    record["handover_to"] = None
    save(data)

    msg = (
        f"{name} 外出回来 {full(current_time)}\n"
        f"本次外出 {sec_to_str(seconds)}"
    )
    if handover_to:
        msg += "\n已恢复本人岗位"
    await send_reply(update, msg)


async def eat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, handover_to = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/eat 名字 [临时代接人]\n例如：/eat 小鑫\n例如：/eat 小鑫 小小")
        return

    if handover_to and handover_to == name:
        await send_reply(update, "❌ 临时代接人不能与本人相同")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行吃饭打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    record = ensure_record(data, key, name)

    if not record.get("in"):
        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"无法进行吃饭打卡\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if record.get("eat_start"):
        await send_reply(update, eat_msg(name, record["eat_start"], record.get("handover_to")))
        return

    if record.get("outwork_start"):
        await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to")))
        return

    if handover_to:
        ok, reason = is_handover_target_available(update, data, handover_to)
        if not ok:
            await send_reply(update, reason)
            return

    record["eat_start"] = full()
    record["handover_to"] = handover_to
    save(data)

    msg = f"{name} 吃饭 {record['eat_start']}"
    if handover_to:
        msg += f"\n当前工作已临时交接给：{handover_to}"
    await send_reply(update, msg)


async def eatback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, extra = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/eatback 名字\n例如：/eatback 小鑫")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
        await send_reply(
            update,
            f"{name}当前不在吃饭中\n"
            f"无法进行返回打卡\n"
            f"如需吃饭，请先使用 /eat {name}"
        )
        return

    record = ensure_record(data, key, name)

    if record.get("out"):
        await send_reply(update, off_msg(name, record["out"]))
        return

    if not record.get("eat_start"):
        if record.get("outwork_start"):
            await send_reply(update, outwork_msg(name, record["outwork_start"], record.get("handover_to")))
            return

        if record.get("in"):
            await send_reply(
                update,
                f"{name}当前不在吃饭中\n"
                f"无法进行返回打卡\n"
                f"如需吃饭，请先使用 /eat {name}"
            )
            return

        await send_reply(
            update,
            f"{name}当前未在上班中\n"
            f"如需开始班次，请先使用 /in {name}"
        )
        return

    current_time = now()
    seconds = diff(record["eat_start"], current_time)
    handover_to = record.get("handover_to")

    record["eat_total"] = int(record.get("eat_total", 0) or 0) + seconds
    record["eat_start"] = None
    record["handover_to"] = None
    save(data)

    msg = (
        f"{name} 吃饭回 {full(current_time)}\n"
        f"本次吃饭 {sec_to_str(seconds)}"
    )
    if handover_to:
        msg += "\n已恢复本人岗位"
    await send_reply(update, msg)


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, extra = get_names_from_args(context)
    if not name:
        await send_reply(update, "用法：/today 名字\n例如：/today 小鑫")
        return

    data = load()
    key = key_by_name(update, name)

    if key not in data:
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

    msg = (
        f"{name} 当前班次\n"
        f"当前状态：{status}\n"
        f"上班时间：{record.get('in') or '无'}\n"
        f"下班时间：{record.get('out') or '未下班'}\n"
    )

    if record.get("handover_to") and not record.get("out"):
        msg += f"临时代接：{record.get('handover_to')}\n"

    msg += (
        f"累计外出：{sec_to_str(totals['outwork_seconds'])}\n"
        f"累计吃饭：{sec_to_str(totals['eat_seconds'])}\n"
        f"当前净工时：{sec_to_str(totals['net_seconds'])}"
    )
    await send_reply(update, msg)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "打卡命令说明\n\n"
        "/in 名字  上班\n"
        "/out 名字  下班\n"
        "/outwork 名字  外出\n"
        "/outwork 名字 临时代接人  外出并临时交接\n"
        "/back 名字  外出回来\n"
        "/eat 名字  吃饭\n"
        "/eat 名字 临时代接人  吃饭并临时交接\n"
        "/eatback 名字  吃饭回\n"
        "/today 名字  查看当前班次\n\n"
        "例如：\n"
        "/in 小鑫\n"
        "/in 小小\n"
        "/outwork 小鑫\n"
        "/outwork 小鑫 小小\n"
        "/back 小鑫\n"
        "/eat 小鑫\n"
        "/eat 小鑫 小小\n"
        "/eatback 小鑫\n"
        "/out 小鑫\n"
        "/today 小鑫"
    )
    await send_reply(update, msg)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("发生异常：")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("in", in_cmd))
    app.add_handler(CommandHandler("out", out_cmd))
    app.add_handler(CommandHandler("outwork", outwork_cmd))
    app.add_handler(CommandHandler("back", back_cmd))
    app.add_handler(CommandHandler("eat", eat_cmd))
    app.add_handler(CommandHandler("eatback", eatback_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_error_handler(error_handler)

    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
