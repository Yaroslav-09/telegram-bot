import os
import sqlite3
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
 
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
 
TOKEN      = os.getenv("BOT_TOKEN")
ADMIN_ID   = os.getenv("ADMIN_CHAT_ID", "")          # заповниться автоматично при першому /start
DB_PATH    = "/data/rent.db" if os.path.exists("/data") else "rent.db"
 
# ── База даних ────────────────────────────────────────────────────────────────
 
def db():
    return sqlite3.connect(DB_PATH)
 
def init_db():
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER, amount INTEGER,
                date TEXT, month INTEGER, year INTEGER
            );
            CREATE TABLE IF NOT EXISTS fund (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT, amount INTEGER, date TEXT, note TEXT DEFAULT ''
            );
        """)
        defaults = {
            "t0_name": "Жилець 1",  "t0_amount": "14000", "t0_day": "5",
            "t1_name": "Жилець 2",  "t1_amount": "14000", "t1_day": "10",
            "t2_name": "Жилець 3",  "t2_amount": "12000", "t2_day": "15",
            "rent": "28800",
            "notify_hour": "9",
            "chat_id": ADMIN_ID,
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (k, v))
 
def cfg(key, default=""):
    with db() as c:
        row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return row[0] if row else default
 
def set_cfg(key, value):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, str(value)))
 
def tenants():
    return [
        {"id": i, "name": cfg(f"t{i}_name"), "amount": int(cfg(f"t{i}_amount", 0)), "day": int(cfg(f"t{i}_day", 1))}
        for i in range(3)
    ]
 
def paid_month(tid, month=None, year=None):
    now = datetime.now()
    month = month or now.month
    year  = year  or now.year
    with db() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE tenant_id=? AND month=? AND year=?",
            (tid, month, year)
        ).fetchone()
    return row[0]
 
def add_payment(tid, amount):
    now = datetime.now()
    with db() as c:
        c.execute(
            "INSERT INTO payments (tenant_id,amount,date,month,year) VALUES (?,?,?,?,?)",
            (tid, amount, now.strftime("%d.%m.%Y"), now.month, now.year)
        )
 
def last_payments(tid, n=5):
    with db() as c:
        return c.execute(
            "SELECT amount, date FROM payments WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
            (tid, n)
        ).fetchall()
 
def fund_balance():
    with db() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='in' THEN amount ELSE -amount END),0) FROM fund"
        ).fetchone()
    return row[0]
 
def add_fund(type_, amount, note=""):
    with db() as c:
        c.execute(
            "INSERT INTO fund (type,amount,date,note) VALUES (?,?,?,?)",
            (type_, amount, datetime.now().strftime("%d.%m.%Y"), note)
        )
 
def last_fund(n=7):
    with db() as c:
        return c.execute(
            "SELECT type, amount, date, note FROM fund ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
 
# ── Клавіатури ────────────────────────────────────────────────────────────────
 
def main_kb():
    rows = []
    for t in tenants():
        paid = paid_month(t["id"])
        icon = "✅" if paid >= t["amount"] else ("⏳" if paid > 0 else "❌")
        rows.append([InlineKeyboardButton(
            f"{icon}  {t['name']}  —  {t['amount']:,} ₴",
            callback_data=f"t:{t['id']}"
        )])
    rows.append([InlineKeyboardButton("💰  Фонд", callback_data="fund")])
    rows.append([InlineKeyboardButton("📊  Підсумок місяця", callback_data="summary")])
    return InlineKeyboardMarkup(rows)
 
def tenant_kb(tid):
    t = tenants()[tid]
    paid      = paid_month(tid)
    remaining = t["amount"] - paid
    buttons   = []
 
    # Якщо не сплачено — кнопка "записати всю суму"
    if remaining > 0:
        buttons.append([InlineKeyboardButton(
            f"✅  Записати {remaining:,} ₴  (вся сума)", callback_data=f"pay_full:{tid}"
        )])
        buttons.append([InlineKeyboardButton(
            "✏️  Ввести іншу суму", callback_data=f"pay_custom:{tid}"
        )])
    else:
        buttons.append([InlineKeyboardButton("✏️  Додати ще оплату", callback_data=f"pay_custom:{tid}")])
 
    buttons.append([InlineKeyboardButton("📋  Останні оплати", callback_data=f"hist:{tid}")])
    buttons.append([InlineKeyboardButton("◀️  Назад", callback_data="main")])
    return InlineKeyboardMarkup(buttons)
 
def fund_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Поклав гроші у фонд",  callback_data="fund:in")],
        [InlineKeyboardButton("➖  Взяв гроші з фонду",   callback_data="fund:out")],
        [InlineKeyboardButton("📋  Останні операції",      callback_data="fund:hist")],
        [InlineKeyboardButton("◀️  Назад",                 callback_data="main")],
    ])
 
def back_kb(to="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️  Назад", callback_data=to)]])
 
# ── Допоміжні функції ─────────────────────────────────────────────────────────
 
def tenant_text(tid):
    t    = tenants()[tid]
    paid = paid_month(tid)
    rem  = t["amount"] - paid
    if rem <= 0:
        status = "✅ Повністю сплачено цього місяця!"
    elif paid > 0:
        status = f"⏳ Сплачено: *{paid:,} ₴*  |  Залишок: *{rem:,} ₴*"
    else:
        status = f"❌ Ще не платив цього місяця"
    return (
        f"👤 *{t['name']}*\n"
        f"Щомісяця: {t['amount']:,} ₴  |  Платіжний день: {t['day']}-е\n\n"
        f"{status}"
    )
 
# ── Обробники ─────────────────────────────────────────────────────────────────
 
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    if not cfg("chat_id"):
        set_cfg("chat_id", cid)
    await update.message.reply_text(
        "🏠 *Облік оренди*\n\nОберіть жильця або розділ:",
        parse_mode="Markdown",
        reply_markup=main_kb()
    )
 
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()
 
    # ── Головне меню ──
    if data == "main":
        await q.edit_message_text(
            "🏠 *Облік оренди*\n\nОберіть жильця або розділ:",
            parse_mode="Markdown", reply_markup=main_kb()
        )
 
    # ── Жилець ──
    elif data.startswith("t:"):
        tid = int(data[2:])
        await q.edit_message_text(tenant_text(tid), parse_mode="Markdown", reply_markup=tenant_kb(tid))
 
    # ── Записати всю суму одним кліком ──
    elif data.startswith("pay_full:"):
        tid       = int(data[9:])
        t         = tenants()[tid]
        paid      = paid_month(tid)
        remaining = t["amount"] - paid
        add_payment(tid, remaining)
        await q.edit_message_text(
            f"✅ *Записано {remaining:,} ₴* від {t['name']}\n"
            f"Сплачено цього місяця: *{t['amount']:,} ₴* — повністю! 🎉",
            parse_mode="Markdown", reply_markup=back_kb()
        )
 
    # ── Ввести довільну суму ──
    elif data.startswith("pay_custom:"):
        tid = int(data[11:])
        t   = tenants()[tid]
        ctx.user_data["state"]      = "pay"
        ctx.user_data["pay_tenant"] = tid
        rem = t["amount"] - paid_month(tid)
        await q.edit_message_text(
            f"✏️ *{t['name']}* — введіть суму оплати:\n_(залишок: {rem:,} ₴)_",
            parse_mode="Markdown",
            reply_markup=back_kb(f"t:{tid}")
        )
 
    # ── Історія оплат жильця ──
    elif data.startswith("hist:"):
        tid  = int(data[5:])
        t    = tenants()[tid]
        rows = last_payments(tid)
        if rows:
            lines = "\n".join(f"• {r[1]}  —  *{r[0]:,} ₴*" for r in rows)
            text  = f"📋 *Останні оплати — {t['name']}*\n\n{lines}"
        else:
            text = f"📋 *{t['name']}*\nОплат ще не зафіксовано."
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb(f"t:{tid}"))
 
    # ── Фонд ──
    elif data == "fund":
        bal  = fund_balance()
        text = f"💰 *Фонд*\n\nПоточний баланс: *{bal:,} ₴*"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=fund_kb())
 
    elif data == "fund:in":
        ctx.user_data["state"] = "fund_in"
        await q.edit_message_text(
            "➕ Введіть суму, яку *кладете* у фонд:",
            parse_mode="Markdown", reply_markup=back_kb("fund")
        )
 
    elif data == "fund:out":
        ctx.user_data["state"] = "fund_out"
        bal = fund_balance()
        await q.edit_message_text(
            f"➖ Введіть суму, яку *берете* з фонду:\n_Баланс зараз: {bal:,} ₴_",
            parse_mode="Markdown", reply_markup=back_kb("fund")
        )
 
    elif data == "fund:hist":
        rows = last_fund()
        if rows:
            lines = "\n".join(
                f"{'➕' if r[0]=='in' else '➖'}  {r[2]}  —  *{r[1]:,} ₴*"
                + (f"  _{r[3]}_" if r[3] else "")
                for r in rows
            )
            text = f"📋 *Операції фонду*\n\n{lines}\n\n💰 Баланс: *{fund_balance():,} ₴*"
        else:
            text = "📋 Операцій ще не було."
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb("fund"))
 
    # ── Підсумок ──
    elif data == "summary":
        now    = datetime.now()
        ts     = tenants()
        total  = sum(paid_month(t["id"]) for t in ts)
        needed = sum(t["amount"] for t in ts)
        rent   = int(cfg("rent", 0))
        lines  = []
        for t in ts:
            paid = paid_month(t["id"])
            if paid >= t["amount"]:
                lines.append(f"✅ *{t['name']}*: {paid:,} ₴")
            elif paid > 0:
                lines.append(f"⏳ *{t['name']}*: {paid:,} / {t['amount']:,} ₴")
            else:
                lines.append(f"❌ *{t['name']}*: не платив")
 
        profit = total - rent
        text = (
            f"📊 *Підсумок — {now.strftime('%B %Y')}*\n\n"
            + "\n".join(lines)
            + f"\n\n💵 Зібрано: *{total:,} ₴* з {needed:,} ₴"
            + f"\n🏠 Аренда: *{rent:,} ₴*"
            + (f"\n✅ Прибуток: *+{profit:,} ₴*" if profit >= 0 else f"\n⚠️ Не вистачає: *{abs(profit):,} ₴*")
            + f"\n💰 Фонд: *{fund_balance():,} ₴*"
        )
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb())
 
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state")
    text  = update.message.text.strip()
 
    # ── Оплата жильця ──
    if state == "pay":
        tid = ctx.user_data["pay_tenant"]
        t   = tenants()[tid]
        try:
            amount = int(text.replace(" ", "").replace(",", "").replace("₴", ""))
        except ValueError:
            await update.message.reply_text("❌ Введіть просто число, наприклад: *14000*", parse_mode="Markdown")
            return
        add_payment(tid, amount)
        ctx.user_data["state"] = None
        paid = paid_month(tid)
        msg  = f"✅ Записано *{amount:,} ₴* від {t['name']}\nСплачено цього місяця: *{paid:,} ₴*"
        if paid >= t["amount"]:
            msg += "\n🎉 Повністю сплачено!"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_kb())
 
    # ── Фонд ──
    elif state in ("fund_in", "fund_out"):
        try:
            amount = int(text.replace(" ", "").replace(",", "").replace("₴", ""))
        except ValueError:
            await update.message.reply_text("❌ Введіть просто число, наприклад: *5000*", parse_mode="Markdown")
            return
        type_  = "in" if state == "fund_in" else "out"
        if type_ == "out" and amount > fund_balance():
            await update.message.reply_text(
                f"❌ У фонді лише *{fund_balance():,} ₴*", parse_mode="Markdown"
            )
            return
        add_fund(type_, amount)
        ctx.user_data["state"] = None
        icon = "➕" if type_ == "in" else "➖"
        word = "Покладено" if type_ == "in" else "Знято"
        await update.message.reply_text(
            f"{icon} *{word}: {amount:,} ₴*\n💰 Баланс фонду: *{fund_balance():,} ₴*",
            parse_mode="Markdown", reply_markup=main_kb()
        )
 
    else:
        await update.message.reply_text("Оберіть дію:", reply_markup=main_kb())
 
# ── Щоденне сповіщення ────────────────────────────────────────────────────────
 
async def daily_notify(app: Application):
    cid   = cfg("chat_id")
    today = datetime.now().day
    if not cid:
        return
    for t in tenants():
        if t["day"] == today:
            paid = paid_month(t["id"])
            if paid < t["amount"]:
                rem = t["amount"] - paid
                msg = (
                    f"🔔 *Нагадування*\n\n"
                    f"Сьогодні *{t['name']}* повинен заплатити *{rem:,} ₴*"
                )
                if paid > 0:
                    msg += f"\n_(вже сплачено: {paid:,} ₴)_"
                await app.bot.send_message(chat_id=int(cid), text=msg, parse_mode="Markdown")
 
# ── Health-check сервер для Render ────────────────────────────────────────────
 
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, *a): pass
 
def _run_health():
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", 8080))), _Health).serve_forever()
 
# ── Запуск ────────────────────────────────────────────────────────────────────
 
def main():
    init_db()
    threading.Thread(target=_run_health, daemon=True).start()
 
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
 
    hour = int(cfg("notify_hour", "9"))
    sched = AsyncIOScheduler(timezone="Europe/Kyiv")
    sched.add_job(daily_notify, "cron", hour=hour, minute=0, args=[app])
    sched.start()
 
    log.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)
 
if __name__ == "__main__":
    main()