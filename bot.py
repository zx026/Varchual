#!/usr/bin/env python3
# bot.py
import json
import sqlite3
import requests
import qrcode
import os
from io import BytesIO
from datetime import datetime

from aiogram import Bot, Dispatcher, types, executor

# ========== CONFIG ==========
BOT_TOKEN = "8330533753:AAG_2Fn5deWSVIx1euC-LshE4JNmSA9Jtgs"
API_KEY_5SIM = "a4ac091e88004e00ba43894f854a789d"
ADMIN_ID = 7875650103  # replace with your Telegram ID (int)
UPI_ID = "yourbharatpeid@upi"
BUSINESS_NAME = "Akotp"
BASE_5SIM = "https://5sim.net/v1/"

# Minimum top-up amount (enforced)
MIN_TOPUP = 20

# payments.json path (simulated feed / webhook should write here)
PAYMENTS_FILE = "payments.json"

# Ensure payments file exists
if not os.path.exists(PAYMENTS_FILE):
    with open(PAYMENTS_FILE, "w") as f:
        json.dump([], f)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ========== DATABASE ==========
DB_FILE = "bot.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS prices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT,
    service TEXT,
    price REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    order_id TEXT,
    phone TEXT,
    country TEXT,
    service TEXT,
    cost_price REAL,
    sell_price REAL,
    status TEXT,
    created_at TEXT
)
""")
conn.commit()

# helper: get or create user
def ensure_user(tg_id):
    cur.execute("SELECT tg_id FROM users WHERE tg_id=?", (tg_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users(tg_id, balance, is_admin, created_at) VALUES(?,?,?,?)",
                    (tg_id, 0.0, 1 if tg_id == ADMIN_ID else 0, datetime.utcnow().isoformat()))
        conn.commit()

# ========== KEYBOARDS ==========
main_menu = types.InlineKeyboardMarkup(inline_keyboard=[
    [types.InlineKeyboardButton("📱 Buy Number", callback_data="buy_num")],
    [types.InlineKeyboardButton("💰 Add Balance", callback_data="add_balance")],
    [types.InlineKeyboardButton("🧾 My Orders", callback_data="my_orders"),
     types.InlineKeyboardButton("👤 Profile", callback_data="profile")]
])

amount_menu = types.InlineKeyboardMarkup(inline_keyboard=[
    [types.InlineKeyboardButton("₹50", callback_data="amt_50"),
     types.InlineKeyboardButton("₹100", callback_data="amt_100")],
    [types.InlineKeyboardButton("₹200", callback_data="amt_200")],
    [types.InlineKeyboardButton("✏ Custom Amount", callback_data="amt_custom")],
    [types.InlineKeyboardButton("⬅ Back", callback_data="back_main")]
])

verify_button = types.InlineKeyboardMarkup(inline_keyboard=[
    [types.InlineKeyboardButton("✔ I Have Paid (Verify Payment)", callback_data="verify_payment")],
    [types.InlineKeyboardButton("⬅ Back", callback_data="back_main")]
])

# ========== UTIL FUNCTIONS ==========
def generate_upi_link(amount):
    # returns upi link and in-memory QR bytes
    upi_link = f"upi://pay?pa={UPI_ID}&pn={BUSINESS_NAME}&am={amount}&cu=INR"
    img = qrcode.make(upi_link)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return upi_link, bio

def read_payments():
    with open(PAYMENTS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return []

def write_payments(data):
    with open(PAYMENTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def verify_payment(amount, tg_id=None):
    """
    Look for any SUCCESS payment with matching amount and used==false.
    If found, mark used and return True.
    """
    payments = read_payments()
    for p in payments:
        try:
            amt = float(p.get("amount", 0))
        except:
            continue
        if p.get("status") == "SUCCESS" and (not p.get("used", False)) and abs(amt - float(amount)) < 0.001:
            # Optionally match to tg_id via 'from' or memo if available
            p["used"] = True
            p["credited_to"] = tg_id
            p["credited_at"] = datetime.utcnow().isoformat()
            write_payments(payments)
            return True
    return False

def api_5sim_get(path):
    headers = {"Authorization": f"Bearer {API_KEY_5SIM}"}
    url = BASE_5SIM.rstrip("/") + "/" + path.lstrip("/")
    r = requests.get(url, headers=headers, timeout=30)
    return r.json() if r.ok else {"error": "request_failed", "status_code": r.status_code, "text": r.text}

# ========== HANDLERS ==========
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    ensure_user(msg.from_user.id)
    await msg.answer(f"Welcome, {msg.from_user.first_name}!\nUse the menu below:", reply_markup=main_menu)

@dp.callback_query_handler(lambda c: c.data == "back_main")
async def back_main(cb: types.CallbackQuery):
    await cb.message.edit_text("Main Menu", reply_markup=main_menu)

# Add Balance flow
@dp.callback_query_handler(lambda c: c.data == "add_balance")
async def cb_add_balance(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("Choose amount to add (min ₹20):", reply_markup=amount_menu)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("amt_"))
async def cb_amount_select(cb: types.CallbackQuery):
    await cb.answer()
    key = cb.data.split("_",1)[1]
    if key == "custom":
        await cb.message.edit_text("Send custom amount (number). Minimum ₹20.\nExample: `25`", parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("⬅ Back", callback_data="back_main")]]))
        # we will capture next message as custom amount via message handler
        return
    amount = int(key)
    if amount < MIN_TOPUP:
        await cb.message.answer(f"❌ Minimum top-up is ₹{MIN_TOPUP}.")
        return
    # store temp selection in-memory (simple dict). For production use persistent store.
    if "user_temp" not in globals():
        globals()["user_temp"] = {}
    globals()["user_temp"][cb.from_user.id] = amount

    upi_link, qr_bio = generate_upi_link(amount)
    caption = f"💰 Pay ₹{amount}\n\nUPI ID: `{UPI_ID}`\nTap link (if supported):\n{upi_link}\n\nAfter paying, press *I Have Paid (Verify Payment)*."
    await cb.message.answer_photo(photo=qr_bio, caption=caption, parse_mode="Markdown", reply_markup=verify_button)

@dp.message_handler(lambda m: m.text and m.text.isdigit())
async def handle_custom_amount(msg: types.Message):
    # Called when user sends a plain number for custom amount
    amount = float(msg.text.strip())
    if amount < MIN_TOPUP:
        await msg.reply(f"❌ Minimum top-up is ₹{MIN_TOPUP}. Please send amount ≥ ₹{MIN_TOPUP}.")
        return
    if "user_temp" not in globals():
        globals()["user_temp"] = {}
    globals()["user_temp"][msg.from_user.id] = amount
    upi_link, qr_bio = generate_upi_link(amount)
    caption = f"💰 Pay ₹{amount}\n\nUPI ID: `{UPI_ID}`\nTap link (if supported):\n{upi_link}\n\nAfter paying, press *I Have Paid (Verify Payment)*."
    await msg.answer_photo(photo=qr_bio, caption=caption, parse_mode="Markdown", reply_markup=verify_button)

@dp.callback_query_handler(lambda c: c.data == "verify_payment")
async def cb_verify_payment(cb: types.CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    ensure_user(uid)
    amount = globals().get("user_temp", {}).get(uid)
    if amount is None:
        await cb.message.answer("No pending amount found. Please choose amount again.")
        return
    # Try to verify via payments.json
    ok = verify_payment(amount, tg_id=uid)
    if ok:
        # credit user
        cur.execute("SELECT balance FROM users WHERE tg_id=?", (uid,))
        row = cur.fetchone()
        bal = row[0] if row else 0.0
        new_bal = bal + float(amount)
        cur.execute("UPDATE users SET balance=? WHERE tg_id=?", (new_bal, uid))
        conn.commit()
        # remove temp
        globals()["user_temp"].pop(uid, None)
        await cb.message.answer(f"✅ Payment verified. ₹{amount} added to your balance.\nCurrent Balance: ₹{new_bal}")
    else:
        await cb.message.answer("❌ Payment not found yet. Ensure you paid using the shown UPI ID/QR. If paid, wait a few seconds and press Verify again. (This demo uses `payments.json` as feed.)")

# Profile / My Orders
@dp.callback_query_handler(lambda c: c.data == "profile")
async def cb_profile(cb: types.CallbackQuery):
    ensure_user(cb.from_user.id)
    cur.execute("SELECT balance FROM users WHERE tg_id=?", (cb.from_user.id,))
    bal = cur.fetchone()[0]
    await cb.message.edit_text(f"👤 {cb.from_user.full_name}\n💰 Balance: ₹{bal}", reply_markup=main_menu)

@dp.callback_query_handler(lambda c: c.data == "my_orders")
async def cb_my_orders(cb: types.CallbackQuery):
    uid = cb.from_user.id
    rows = cur.execute("SELECT id, phone, service, sell_price, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
    if not rows:
        await cb.message.answer("No orders found.", reply_markup=main_menu)
        return
    text = "Your last orders:\n\n"
    for r in rows:
        text += f"Order#{r[0]} | {r[2]} | {r[1]} | ₹{r[3]} | {r[4]}\n"
    await cb.message.answer(text, reply_markup=main_menu)

# Buy Number
@dp.callback_query_handler(lambda c: c.data == "buy_num")
async def cb_buy_num(cb: types.CallbackQuery):
    # Simple flow: ask service and country inline (for demo we use India + telegram)
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton("Telegram (India)", callback_data="buy_india_telegram")],
        [types.InlineKeyboardButton("WhatsApp (India)", callback_data="buy_india_whatsapp")],
        [types.InlineKeyboardButton("⬅ Back", callback_data="back_main")]
    ])
    await cb.message.edit_text("Choose service / country:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("buy_"))
async def cb_buy_confirm(cb: types.CallbackQuery):
    await cb.answer()
    parts = cb.data.split("_")
    if len(parts) < 3:
        await cb.message.answer("Invalid selection.")
        return
    country = parts[1]
    service = parts[2]
    uid = cb.from_user.id
    ensure_user(uid)
    # check price
    cur.execute("SELECT price FROM prices WHERE country=? AND service=?", (country, service))
    row = cur.fetchone()
    sell_price = row[0] if row else 15.0  # default price
    # check balance
    cur.execute("SELECT balance FROM users WHERE tg_id=?", (uid,))
    bal = cur.fetchone()[0]
    if bal < sell_price:
        await cb.message.answer(f"❌ Insufficient balance. Price ₹{sell_price}. Your balance ₹{bal}. Please add balance.", reply_markup=main_menu)
        return
    # call 5sim buy (demo)
    resp = api_5sim_get(f"user/buy/activation/{country}/{service}")
    if resp.get("error"):
        await cb.message.answer(f"❌ 5SIM error: {resp}", reply_markup=main_menu)
        return
    # expected fields: id, phone, price
    order_id = resp.get("id") or resp.get("request_id") or f"local_{int(datetime.utcnow().timestamp())}"
    phone = resp.get("phone") or resp.get("number") or "UNKNOWN"
    cost_price = float(resp.get("price", 0) or 0)
    # deduct sell_price
    new_bal = bal - sell_price
    cur.execute("UPDATE users SET balance=? WHERE tg_id=?", (new_bal, uid))
    cur.execute("""INSERT INTO orders(user_id, order_id, phone, country, service, cost_price, sell_price, status, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (uid, order_id, phone, country, service, cost_price, sell_price, "active", datetime.utcnow().isoformat()))
    conn.commit()
    await cb.message.answer(f"✅ Number bought!\nNumber: `{phone}`\nOrder ID: `{order_id}`\nPrice charged: ₹{sell_price}\nCurrent Balance: ₹{new_bal}\n\nWhen OTP arrives, use `/otp {order_id}` to check.", parse_mode="Markdown")

# OTP check
@dp.message_handler(lambda m: m.text and m.text.startswith("/otp"))
async def msg_check_otp(msg: types.Message):
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply("Usage: /otp <order_id>")
        return
    oid = parts[1]
    resp = api_5sim_get(f"user/check/{oid}")
    await msg.reply(f"5SIM response:\n`{json.dumps(resp, indent=2)}`", parse_mode="Markdown")

# ========== ADMIN COMMANDS ==========
@dp.message_handler(commands=["admin"])
async def cmd_admin(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.reply("No access.")
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Users List", "Set Price")
    kb.add("Add Balance", "Remove Balance")
    kb.add("Show Payments JSON")
    await msg.reply("Admin panel:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "Users List")
async def admin_users(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    rows = cur.execute("SELECT tg_id, balance, created_at FROM users ORDER BY created_at DESC LIMIT 100").fetchall()
    text = "Users:\n"
    for r in rows:
        text += f"{r[0]} | ₹{r[1]} | created {r[2]}\n"
    await m.reply(text)

@dp.message_handler(lambda m: m.text == "Set Price")
async def admin_set_price(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    await m.reply("Format: price <country> <service> <amount>\nExample: price india telegram 25")

@dp.message_handler(lambda m: m.text and m.text.startswith("price "))
async def admin_set_price_do(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, country, service, amount = m.text.split()
        amount = float(amount)
        cur.execute("INSERT OR REPLACE INTO prices(country, service, price) VALUES(?,?,?)", (country, service, amount))
        conn.commit()
        await m.reply("Price set.")
    except Exception as e:
        await m.reply("Invalid format.")

@dp.message_handler(lambda m: m.text and m.text.startswith("add "))
async def admin_add_balance(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, user, amt = m.text.split()
        user = int(user)
        amt = float(amt)
        ensure_user(user)
        cur.execute("UPDATE users SET balance = balance + ? WHERE tg_id=?", (amt, user))
        conn.commit()
        await m.reply(f"Added ₹{amt} to {user}.")
    except Exception as e:
        await m.reply("Format: add <tg_id> <amount>")

@dp.message_handler(lambda m: m.text and m.text.startswith("remove "))
async def admin_remove_balance(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, user, amt = m.text.split()
        user = int(user)
        amt = float(amt)
        ensure_user(user)
        cur.execute("UPDATE users SET balance = balance - ? WHERE tg_id=?", (amt, user))
        conn.commit()
        await m.reply(f"Removed ₹{amt} from {user}.")
    except Exception as e:
        await m.reply("Format: remove <tg_id> <amount>")

@dp.message_handler(lambda m: m.text == "Show Payments JSON")
async def admin_show_payments(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    payments = read_payments()
    await m.reply(f"Payments feed ({len(payments)} entries). Use server/webhook to append here.")

# ========== START ==========
if __name__ == "__main__":
    print("Bot starting...")
    executor.start_polling(dp, skip_updates=True)
