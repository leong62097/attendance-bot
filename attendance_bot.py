from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import traceback

BOT_TOKEN = "8189801715:AAEEupF_wChLaj6eidoLjmp_T3-2w1CmoH8"
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


def uid(update: Update) -> str:
    return str(update.effective_user.id)


def uname(update: Update) -> str:
    u = update.effective_user
    return u.first_name or u.full_name or "未知用户"


def ensure_user_record(data: dict, user_id: str, name: str) -> dict:
    """
    兼容旧数据，缺什么字段就补什么字段
    """
    if user_id not in data or not isinstance(data[user_id], dict):
        data[user_id] = {}

    record = data[user_id]

    record["name"] = name
    record["in"] = record.get("in")
    record["out"] = record.get("out")
    record["outwork_start"] = record.get("outwork_start")
    record["outwork_total"] = int(record.get("outwork_total", 0) or 0)
    record["eat_start"] = record.get("eat_start")
    record["eat_total"] = int(record.get("eat_total", 0) or 0)

    return record


async def send_reply(update: Update, text: str):
    await update.message.reply_text(text)


# =====================
# 上班 /in
# =====================
async def in_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    # 上班时开新班次
    data[user_id] = {
        "name": name,
        "in": full(),
        "out": None,
        "outwork_start": None,
        "outwork_total": 0,
        "eat_start": None,
        "eat_total": 0
    }

    save(data)
    await send_reply(update, f"{name} 上班 {full()}")


# =====================
# 下班 /out
# =====================
async def out_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await send_reply(update, f"{name} 下班 {full()}（未找到上班记录）")
        return

    record = ensure_user_record(data, user_id, name)

    if not record.get("in"):
        await send_reply(update, f"{name} 下班 {full()}（未找到上班记录）")
        return

    current_time = now()
    total_seconds = diff(record["in"], current_time)
    outwork_seconds = int(record.get("outwork_total", 0) or 0)
    eat_seconds = int(record.get("eat_total", 0) or 0)

    # 如果下班时还处于外出中，自动结算到当前时刻
    if record.get("outwork_start"):
        extra = diff(record["outwork_start"], current_time)
        outwork_seconds += extra
        record["outwork_total"] = outwork_seconds
        record["outwork_start"] = None

    # 如果下班时还处于吃饭中，自动结算到当前时刻
    if record.get("eat_start"):
        extra = diff(record["eat_start"], current_time)
        eat_seconds += extra
        record["eat_total"] = eat_seconds
        record["eat_start"] = None

    net_seconds = total_seconds - outwork_seconds - eat_seconds
    if net_seconds < 0:
        net_seconds = 0

    record["out"] = full(current_time)
    save(data)

    msg = (
        f"{name} 下班 {full(current_time)}\n"
        f"总工时 {sec_to_str(total_seconds)}\n"
        f"外出 {sec_to_str(outwork_seconds)}\n"
        f"吃饭 {sec_to_str(eat_seconds)}\n"
        f"净工时 {sec_to_str(net_seconds)}"
    )
    await send_reply(update, msg)


# =====================
# 外出 /outwork
# =====================
async def outwork_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await send_reply(update, f"{name} 外出 {full()}（未上班）")
        return

    record = ensure_user_record(data, user_id, name)

    if not record.get("in"):
        await send_reply(update, f"{name} 外出 {full()}（未上班）")
        return

    if record.get("outwork_start"):
        await send_reply(update, f"{name} 外出 {full()}（已有未结束的外出记录）")
        return

    record["outwork_start"] = full()
    save(data)

    await send_reply(update, f"{name} 外出 {full()}")


# =====================
# 外出回来 /back
# =====================
async def back_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await send_reply(update, f"{name} 回来 {full()}（未上班）")
        return

    record = ensure_user_record(data, user_id, name)

    if not record.get("outwork_start"):
        await send_reply(update, f"{name} 回来 {full()}（未找到外出记录）")
        return

    seconds = diff(record["outwork_start"], now())
    record["outwork_total"] = int(record.get("outwork_total", 0) or 0) + seconds
    record["outwork_start"] = None
    save(data)

    await send_reply(update, f"{name} 回来 {full()}（外出 {sec_to_str(seconds)}）")


# =====================
# 吃饭 /eat
# =====================
async def eat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await send_reply(update, f"{name} 吃饭 {full()}（未上班）")
        return

    record = ensure_user_record(data, user_id, name)

    if not record.get("in"):
        await send_reply(update, f"{name} 吃饭 {full()}（未上班）")
        return

    if record.get("eat_start"):
        await send_reply(update, f"{name} 吃饭 {full()}（已有未结束的吃饭记录）")
        return

    record["eat_start"] = full()
    save(data)

    await send_reply(update, f"{name} 吃饭 {full()}")


# =====================
# 吃饭回来 /eatback
# =====================
async def eatback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await send_reply(update, f"{name} 吃饭回 {full()}（未上班）")
        return

    record = ensure_user_record(data, user_id, name)

    if not record.get("eat_start"):
        await send_reply(update, f"{name} 吃饭回 {full()}（未找到吃饭记录）")
        return

    seconds = diff(record["eat_start"], now())
    record["eat_total"] = int(record.get("eat_total", 0) or 0) + seconds
    record["eat_start"] = None
    save(data)

    await send_reply(update, f"{name} 吃饭回 {full()}（吃饭 {sec_to_str(seconds)}）")


# =====================
# 当前状态 /today
# =====================
async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load()
    user_id = uid(update)
    name = uname(update)

    if user_id not in data:
        await update.message.reply_text("无当前班次记录")
        return

    record = ensure_user_record(data, user_id, name)

    in_time = record.get("in") or "无"
    out_time = record.get("out") or "未下班"
    outwork_total = int(record.get("outwork_total", 0) or 0)
    eat_total = int(record.get("eat_total", 0) or 0)

    outwork_status = "外出中" if record.get("outwork_start") else "无"
    eat_status = "吃饭中" if record.get("eat_start") else "无"

    msg = (
        f"{name} 当前班次\n"
        f"上班：{in_time}\n"
        f"下班：{out_time}\n"
        f"累计外出：{sec_to_str(outwork_total)}\n"
        f"累计吃饭：{sec_to_str(eat_total)}\n"
        f"当前外出状态：{outwork_status}\n"
        f"当前吃饭状态：{eat_status}"
    )
    await update.message.reply_text(msg)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("发生异常：")
    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("in", in_cmd))
    app.add_handler(CommandHandler("out", out_cmd))
    app.add_handler(CommandHandler("outwork", outwork_cmd))
    app.add_handler(CommandHandler("back", back_cmd))
    app.add_handler(CommandHandler("eat", eat_cmd))
    app.add_handler(CommandHandler("eatback", eatback_cmd))
    app.add_handler(CommandHandler("today", today_cmd))

    app.add_error_handler(error_handler)

    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
