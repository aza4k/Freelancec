#!/usr/bin/env python3
# freelance_v3_fixed.py
import time
import json
import logging
from statistics import mean
from datetime import datetime

import telebot
from telebot import types

# ============== SOZLAMALAR =================
BOT_TOKEN = "8121561887:AAEG6Jofl_qg2KKx_ZySMElf3j-bYuXn6GA"
MAIN_ADMIN_ID = 7055980753
DATA_FILE = "data.json"
LOGGING_LEVEL = logging.INFO
# ===========================================

logging.basicConfig(level=LOGGING_LEVEL)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# In-memory pending broadcasts per admin
pending_broadcasts = {}  # admin_id -> {"chat_id":, "message_id":, ...}

# ============== DATA HANDLING =================
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    # Ensure required keys exist
    if "categories" not in data:
        data["categories"] = {}
    if "freelancers" not in data:
        data["freelancers"] = {}
    if "admins" not in data:
        data["admins"] = []
    if "users" not in data:
        data["users"] = []
    return data

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.exception("save_data xatosi: %s", e)

data = load_data()

# Ensure MAIN_ADMIN_ID present
if MAIN_ADMIN_ID not in data["admins"]:
    data["admins"].append(MAIN_ADMIN_ID)
    save_data(data)

# ============== HELPERS =================

def is_admin(user_id: int) -> bool:
    return user_id in data["admins"]

def normalize_username(text: str) -> str:
    if not text:
        return ""
    return text.strip().lstrip("@").lower()

def render_stars(avg_rating: float) -> str:
    # Left-to-right filled stars (⭐) and empty (☆), 5 total
    if avg_rating is None:
        avg_rating = 0
    # use round to nearest integer; ensure within 0..5
    filled = int(round(avg_rating))
    filled = max(0, min(5, filled))
    return "⭐" * filled + "☆" * (5 - filled)

def rating_summary_for(username: str):
    fl = data["freelancers"].get(username, {})
    ratings = fl.get("ratings", {}) or {}
    # ratings stored as dict user_id -> int
    if isinstance(ratings, dict):
        try:
            values = list(map(int, ratings.values())) if ratings else []
        except Exception:
            # fallback: ignore malformed entries
            values = []
    else:
        try:
            values = list(map(int, ratings))
        except Exception:
            values = []
    if values:
        avg = mean(values)
        count = len(values)
    else:
        avg = 0.0
        count = 0
    return avg, count

def pretty_profile_text(username: str) -> str:
    fl = data["freelancers"].get(username)
    if not fl:
        return "❌ Freelancer topilmadi."
    avg, count = rating_summary_for(username)
    stars = render_stars(avg)
    first = fl.get("first_name", "None")
    last = fl.get("last_name", "")
    phone = fl.get("phone", "Noma'lum")
    added = fl.get("added_at", "")
    added_text = f"\n📅 Qosilg'an: {added}" if added else ""
    text = (
        f"👤 <b>{first} {last}</b>\n"
        f"🔹 <b>Username:</b> @{username}\n"
        f"📞 <b>Telefon:</b> {phone}\n"
        f"⭐ <b>Baxa (o'rtacha):</b> {stars} ({avg:.1f}/5) — <i>{count}</i>\n"
        f"{added_text}\n\n"
        "To'mendegi tu'ymeler arqali baxa berzen'iz boladi."
    )
    return text

def ensure_user_registered(user_id: int):
    if user_id not in data["users"]:
        data["users"].append(user_id)
        save_data(data)

# ============== KEYBOARDS =================

def main_reply_keyboard(user_id: int):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📋 Kategoriyalar")
    if is_admin(user_id):
        kb.row("⚙️ Admin panel")
    return kb

def admin_reply_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Kategoriya jaratiw", "🗑 Kategoriya o'shiriw ")
    kb.row("👤 Freelancer qosiw", "🗑 Freelancer o'shiriw")
    kb.row("📢 Hammege xabar jiberiw", "⬅️ Artqa")
    return kb

def cancel_inline_button(label="❌ Biykarlaw"):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(label, callback_data="cancel_action"))
    return kb

# ============== HANDLERS =================

@bot.message_handler(commands=["start"])
def cmd_start(message: types.Message):
    ensure_user_registered(message.from_user.id)
    save_data(data)
    kb = main_reply_keyboard(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "👋 <b>Freelancer botqa Xosh kelipsiz!</b>\n\n"
        "Kategoriyalardi ko‘riw ushin <b>📋 Kategoriyalar</b> tu'ymesin basin'.\n",
        reply_markup=kb,
    )

@bot.message_handler(func=lambda m: m.text == "📋 Kategoriyalar")
def show_categories(message: types.Message):
    ensure_user_registered(message.from_user.id)
    save_data(data)

    if not data["categories"]:
        bot.send_message(message.chat.id, "📭 <b>Kategoriyalar</b> ha'zirshe joq.")
        return

    kb = types.InlineKeyboardMarkup(row_width=2)
    sorted_cats = sorted(data["categories"].keys())
    for cat in sorted_cats:
        kb.add(types.InlineKeyboardButton(f"📂 {cat}", callback_data=f"cat:{cat}"))
    kb.add(types.InlineKeyboardButton("🏠 Menu", callback_data="back_to_main"))
    bot.send_message(message.chat.id, "<b>📋 Kategoriyalar</b>\nKerekli kategoriyani tanlan':", reply_markup=kb)

# ----- Category pressed: show available freelancers (sorted by avg desc) -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("cat:"))
def handle_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    cat = cat.strip()
    freelancers = data["categories"].get(cat, [])
    # Filter visible freelancers
    visible_list = [u for u in freelancers if data["freelancers"].get(u, {}).get("visible", True)]

    if not visible_list:
        bot.answer_callback_query(call.id, f"📭 Bul kategoriyada ha'zirshe freelancerlar joq.")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text=f"📂 <b>{cat}</b>\nHa'zirshe freelancer joq.", reply_markup=kb)
        except Exception:
            pass
        return

    # Sort by avg rating descending then by name
    def sort_key(u):
        avg, _ = rating_summary_for(u)
        # use negative avg for descending; tie-breaker username
        return (-avg, u)

    visible_list_sorted = sorted(visible_list, key=sort_key)

    kb = types.InlineKeyboardMarkup(row_width=2)
    for u in visible_list_sorted:
        fl = data["freelancers"].get(u, {})
        avg, count = rating_summary_for(u)
        stars = render_stars(avg)
        first = fl.get("first_name", u).strip()
        last = fl.get("last_name", "").strip()
        display_name = f"{first} {last}".strip()
        if len(display_name) > 24:
            display_name = display_name[:21] + "..."
        label = f"{display_name}\n{stars} ({avg:.1f})"
        # include category in callback so back goes to same category
        kb.add(types.InlineKeyboardButton(label, callback_data=f"profile:{u}:{cat}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
    # Edit message
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"📂 <b>{cat}</b> boyinsha freelancerlar:", reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, f"📂 <b>{cat}</b> boyinsha freelancerlar:", reply_markup=kb)

    bot.answer_callback_query(call.id)

# ----- Profile view -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("profile:"))
def handle_profile(call: types.CallbackQuery):
    # data = profile:username:category
    parts = call.data.split(":", 2)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Xatolik")
        return
    username = parts[1]
    cat = parts[2]

    profile_text = pretty_profile_text(username)
    avg, count = rating_summary_for(username)
    voter_id = str(call.from_user.id)
    already_voted = voter_id in data["freelancers"].get(username, {}).get("ratings", {})

    kb = types.InlineKeyboardMarkup(row_width=5)
    if not already_voted:
        for i in range(1, 6):
            kb.add(types.InlineKeyboardButton(f"{'⭐'*i}{'☆'*(5-i)}", callback_data=f"rate:{username}:{i}:{cat}"))
    else:
        kb.add(types.InlineKeyboardButton("✅ Siz baxalag'ansiz", callback_data="noop"))
    # back to same category
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data=f"back_to_cat:{cat}"))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=profile_text, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, profile_text, reply_markup=kb)
    bot.answer_callback_query(call.id)

# noop for disabled buttons
@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call: types.CallbackQuery):
    bot.answer_callback_query(call.id, "Bul tu'yme islemeydi.")

# ----- Rating callback -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("rate:"))
def cb_rate(call: types.CallbackQuery):
    # data: rate:username:score:category
    try:
        _, username, score, cat = call.data.split(":", 3)
        score = int(score)
    except Exception:
        bot.answer_callback_query(call.id, "Qa'te format")
        return

    voter = str(call.from_user.id)
    fl = data["freelancers"].get(username)
    if not fl:
        bot.answer_callback_query(call.id, "Freelancer tabilmadi.")
        return

    if voter in fl.get("ratings", {}):
        bot.answer_callback_query(call.id, "Siz alleqashsn baxx bergensiz ✅")
        return

    # Save rating as int
    fl.setdefault("ratings", {})[voter] = int(score)
    save_data(data)

    # Update profile message: show confirmation and back button (back to that category)
    avg, count = rating_summary_for(username)
    stars = render_stars(avg)

    text = (
        f"✅ Raxmet! Siz <b>@{username}</b> ushin <b>{score}⭐</b> baxa berdiniz.\n\n"
        f"📊 Ha'zirgi ortasha baxa: {stars} ({avg:.1f}/5) — {count} dawis"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data=f"back_to_cat:{cat}"))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=text, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb)
    bot.answer_callback_query(call.id, "Baxan'iz qabil qilindi ✅")

# ----- Admin panel -----
@bot.message_handler(func=lambda m: m.text == "⚙️ Admin panel")
def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Suck my dick.")
        return
    kb = admin_reply_keyboard()
    bot.send_message(message.chat.id, "🧰 <b>Admin panel</b>\nWTF?", reply_markup=kb)

# ----- Create category -----
@bot.message_handler(func=lambda m: m.text == "➕ Kategoriya jaratiw")
def msg_create_category(message: types.Message):
    if not is_admin(message.from_user.id): return
    msg = bot.send_message(message.chat.id, "✏️ Kategoriya atin jaz:", reply_markup=cancel_inline_button())
    bot.register_next_step_handler(msg, process_create_category)

def process_create_category(message: types.Message):
    if message.text is None or message.text.strip().lower() == "cancel_action":
        bot.send_message(message.chat.id, "❌ Niykar etildi.")
        return
    cat = message.text.strip()
    if cat in data["categories"]:
        bot.send_message(message.chat.id, "⚠️ Bul kategoriya uje barg'o")
        return
    data["categories"][cat] = []
    save_data(data)
    bot.send_message(message.chat.id, f"✅ <b>{cat}</b> kategoriya jaratildi")

# ----- Delete category (with full deletion confirmation) -----
@bot.message_handler(func=lambda m: m.text == "🗑 Kategoriya o'shiriw")
def msg_delete_category(message: types.Message):
    if not is_admin(message.from_user.id): return
    if not data["categories"]:
        bot.send_message(message.chat.id, "📭 Kategoriya joq.")
        return
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat in sorted(data["categories"].keys()):
        kb.add(types.InlineKeyboardButton(f"🗑 {cat}", callback_data=f"delcat:{cat}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qayssin o'shireyin(butunlay)?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("delcat:"))
def cb_delcat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Awa, o'shireber", callback_data=f"confirm_delcat:{cat}"))
    kb.add(types.InlineKeyboardButton("❌ O'shirme", callback_data="admin_back"))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=f"⚠️ <b>{cat}</b> kategoriyani <u>toliq</u> o'shirebereynba?\n",
                          reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("confirm_delcat:"))
def cb_confirm_delcat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    users_in_cat = data["categories"].pop(cat, [])
    # Keep freelancer profiles, just removed from this category
    # (If you want to remove category reference from profiles, implement here)
    save_data(data)
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=f"✅ <b>{cat}</b> kategoriyasi joq boldi.")
    bot.answer_callback_query(call.id)

# ----- Add freelancer flow: choose category -> username -> first -> last -> phone -----
@bot.message_handler(func=lambda m: m.text == "👤 Freelancer qosiw")
def msg_add_freelancer(message: types.Message):
    if not is_admin(message.from_user.id): return
    if not data["categories"]:
        bot.send_message(message.chat.id, "⚠️ Kategoriya jarat.")
        return
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat in sorted(data["categories"].keys()):
        kb.add(types.InlineKeyboardButton(cat, callback_data=f"addf_cat:{cat}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qaysi kategoriya ushin freelancer qosamiz?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("addf_cat:"))
def cb_addf_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    msg = bot.send_message(call.message.chat.id, "🆔 Freelancerdin' @username in kirgiz (ma'seln @thedurev):", reply_markup=cancel_inline_button())
    bot.register_next_step_handler(msg, lambda m: addf_username_step(m, cat))
    bot.answer_callback_query(call.id)

def addf_username_step(message: types.Message, category: str):
    username_raw = message.text.strip()
    username = normalize_username(username_raw)
    if not username:
        bot.send_message(message.chat.id, "❌ Qate user biykarlandi")
        return
    bot.send_message(message.chat.id, "📛 Ati:")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_firstname_step(m, category, username))

def addf_firstname_step(message: types.Message, category: str, username: str):
    first = message.text.strip()
    if not first:
        bot.send_message(message.chat.id, "❌ Qate at, biykarlandi")
        return
    bot.send_message(message.chat.id, "📝 Familyasi:")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_lastname_step(m, category, username, first))

def addf_lastname_step(message: types.Message, category: str, username: str, first: str):
    last = message.text.strip() or ""
    bot.send_message(message.chat.id, "📞 Telefon nomer (+998912618831):")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_phone_step(m, category, username, first, last))

def addf_phone_step(message: types.Message, category: str, username: str, first: str, last: str):
    phone = message.text.strip()
    if not phone or len(phone) < 6:
        bot.send_message(message.chat.id, "⚠️ Telefon nomer qate.")
        return
    if username not in data["freelancers"]:
        data["freelancers"][username] = {
            "first_name": first,
            "last_name": last,
            "phone": phone,
            "ratings": {},
            "visible": True,
            "added_at": datetime.utcnow().isoformat()
        }
    else:
        data["freelancers"][username].update({
            "first_name": first,
            "last_name": last,
            "phone": phone,
            "visible": True
        })
    if username not in data["categories"].get(category, []):
        data["categories"][category].append(username)
    save_data(data)
    bot.send_message(message.chat.id, f"✅ <b>@{username}</b> qosildi ham <b>{category}</b> ga jalg'andi.")

# ----- Remove freelancer from category (but keep profile) -----
@bot.message_handler(func=lambda m: m.text == "🗑 Freelancer o'shiriw")
def msg_remove_freelancer(message: types.Message):
    if not is_admin(message.from_user.id): return
    if not data["categories"]:
        bot.send_message(message.chat.id, "📭 Kategoriyalar joqqo.")
        return
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat in sorted(data["categories"].keys()):
        kb.add(types.InlineKeyboardButton(cat, callback_data=f"remf_cat:{cat}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qaysisinan o'shiremiz?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("remf_cat:"))
def cb_remf_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    freelancers = data["categories"].get(cat, [])
    if not freelancers:
        bot.answer_callback_query(call.id, "Bul kategoriyada freelancerlar joq.")
        return
    kb = types.InlineKeyboardMarkup(row_width=1)
    for u in freelancers:
        fl = data["freelancers"].get(u, {})
        name = f"{fl.get('first_name','')} {fl.get('last_name','')}".strip() or u
        kb.add(types.InlineKeyboardButton(f"❌ @{u} — {name}", callback_data=f"remove_from_cat:{cat}:{u}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text=f"🗑 <b>{cat}</b> dan qaysisin o'shiresen'?", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("remove_from_cat:"))
def cb_remove_from_cat(call: types.CallbackQuery):
    try:
        _, cat, username = call.data.split(":", 2)
    except Exception:
        bot.answer_callback_query(call.id, "Qatelik")
        return
    if username in data["categories"].get(cat, []):
        data["categories"][cat].remove(username)
        if username in data["freelancers"]:
            data["freelancers"][username]["visible"] = False
        save_data(data)
        bot.answer_callback_query(call.id, f"@{username} {cat} dan o‘shirildi ✅", show_alert=False)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"🗑 @{username} {cat} dan o‘shirildi (profil saxlanadi).")
    else:
        bot.answer_callback_query(call.id, "Tabilmadi")

# ----- Admin broadcast flows (unchanged) -----
@bot.message_handler(func=lambda m: m.text == "📢 Ha'mmege xabar")
def msg_broadcast_start(message: types.Message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Suck my dick.")
        return
    kb = cancel_inline_button("❌ Biykarlaw")
    msg = bot.send_message(message.chat.id, "✉️ Xabardi jiber\n"
                                            "Biykarlaw ushin knopkani bas!!!.", reply_markup=kb)
    bot.register_next_step_handler(msg, lambda m: confirm_broadcast_prepare(m, message.from_user.id))

def confirm_broadcast_prepare(message: types.Message, admin_id: int):
    pending_broadcasts[admin_id] = {
        "chat_id": message.chat.id,
        "message_id": message.message_id
    }
    if message.content_type == "text":
        preview = message.text
    else:
        preview = f"<i>{message.content_type} message</i>"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Jiberiw", callback_data=f"broadcast_send:{admin_id}"))
    kb.add(types.InlineKeyboardButton("❌ Biykarlaw", callback_data=f"broadcast_cancel:{admin_id}"))
    bot.send_message(message.chat.id, f"📥 <b>Preview</b>: {preview}\n\n⚠️ Ha'mmege jiberilsinba", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("broadcast_cancel:"))
def cb_broadcast_cancel(call: types.CallbackQuery):
    _, admin_id_str = call.data.split(":", 1)
    try:
        admin_id = int(admin_id_str)
    except:
        bot.answer_callback_query(call.id, "Qate")
        return
    if admin_id in pending_broadcasts:
        pending_broadcasts.pop(admin_id, None)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text="❌ Xabar jiberiw biykarlandi")
        bot.answer_callback_query(call.id, "Biykarlandi")
    else:
        bot.answer_callback_query(call.id, "Biykarlawga tayin material tabilmadi")

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("broadcast_send:"))
def cb_broadcast_send(call: types.CallbackQuery):
    _, admin_id_str = call.data.split(":", 1)
    try:
        admin_id = int(admin_id_str)
    except:
        bot.answer_callback_query(call.id, "Qate")
        return
    info = pending_broadcasts.get(admin_id)
    if not info:
        bot.answer_callback_query(call.id, "Aldinnan jiberilgen xabar tabilmadi.")
        return

    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                          text="📤 Jiberiw baslanbaqta ku'tin'...")

    from_chat = info["chat_id"]
    message_id = info["message_id"]

    users = list(data.get("users", []))
    total = len(users)
    sent = 0
    failed = 0

    for idx, uid in enumerate(users, start=1):
        try:
            bot.copy_message(uid, from_chat, message_id)
            sent += 1
        except Exception as e:
            logging.warning("JIberiwde qate %s -> %s: %s", uid, e, type(e))
            failed += 1
        if idx % 25 == 0 or idx == total:
            try:
                bot.send_message(call.message.chat.id, f"📤 Progress: {idx}/{total} — jiberildi: {sent}, qate: {failed}")
            except Exception:
                pass
        time.sleep(0.12)

    pending_broadcasts.pop(admin_id, None)
    bot.send_message(call.message.chat.id, f"✅ Tamamlandi \nJiberildi: {sent}\nQa'telikler: {failed}")
    bot.answer_callback_query(call.id)

# ----- Cancel generic handler -----
@bot.callback_query_handler(func=lambda c: c.data == "cancel_action")
def cb_cancel_action(call: types.CallbackQuery):
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Amal bekor qilindi.")
    except Exception:
        pass
    bot.answer_callback_query(call.id, "Amal bekor qilindi")

# ----- Navigation helpers (improved) -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("back_to_cat:"))
def cb_back_to_cat(call: types.CallbackQuery):
    # return to category listing for given category
    try:
        _, cat = call.data.split(":", 1)
    except:
        cat = None
    if not cat:
        # fallback to categories list
        cb_navigation_simple(call, "back_to_categories")
        return
    # Recreate category view (simulate pressing the category)
    freelancers = data["categories"].get(cat, [])
    visible_list = [u for u in freelancers if data["freelancers"].get(u, {}).get("visible", True)]
    if not visible_list:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text=f"📂 <b>{cat}</b>\nHa'zirshe freelancerlar joq.", reply_markup=kb)
        except Exception:
            pass
        bot.answer_callback_query(call.id)
        return

    visible_list_sorted = sorted(visible_list, key=lambda u: (-rating_summary_for(u)[0], u))
    kb = types.InlineKeyboardMarkup(row_width=2)
    for u in visible_list_sorted:
        fl = data["freelancers"].get(u, {})
        avg, count = rating_summary_for(u)
        stars = render_stars(avg)
        first = fl.get("first_name", u)
        last = fl.get("last_name", "")
        display = f"{first} {last}".strip() or u
        label = f"{display}\n{stars} ({avg:.1f})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"profile:{u}:{cat}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"📂 <b>{cat}</b> boyinsha freelancerlar:", reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, f"📂 <b>{cat}</b> bo‘yicha freelancerlar (eng yuqori baho avval):", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data in ["back_to_main", "back_to_categories", "admin_back"])
def cb_navigation(call: types.CallbackQuery):
    cb_navigation_simple(call, call.data)

def cb_navigation_simple(call: types.CallbackQuery, data_key: str):
    if data_key == "back_to_main":
        kb = main_reply_keyboard(call.from_user.id)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="🏠 Menu", reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, "🏠 Menu", reply_markup=kb)
    elif data_key == "back_to_categories":
        if not data["categories"]:
            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                      text="📭 Kategoriyalar mavjud emas.")
            except Exception:
                pass
            bot.answer_callback_query(call.id)
            return
        kb = types.InlineKeyboardMarkup(row_width=2)
        for cat in sorted(data["categories"].keys()):
            kb.add(types.InlineKeyboardButton(f"📂 {cat}", callback_data=f"cat:{cat}"))
        kb.add(types.InlineKeyboardButton("🏠 Menu", callback_data="back_to_main"))
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="📋 Kategoriyalar\nKerekli kategoriyalardi tanlan':", reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, "📋 Kategoriyalar\nKerekli kategoriyalardi tanlan':", reply_markup=kb)
    elif data_key == "admin_back":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Suck my dick")
            return
        kb = admin_reply_keyboard()
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="🧰 Admin panel", reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, "🧰 Admin panel", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ----- Fallback text handlers: Orqaga etc. -----
@bot.message_handler(func=lambda m: m.text == "⬅️ Artqa")
def back_to_main_text(message: types.Message):
    kb = main_reply_keyboard(message.from_user.id)
    bot.send_message(message.chat.id, "🏠 Menu", reply_markup=kb)

# ----- Catch-all for conservation of users list on any message -----
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker'])
def all_messages_handler(message: types.Message):
    ensure_user_registered(message.from_user.id)
    save_data(data)
    return

# ============== RUN BOT =================
if __name__ == "__main__":
    print("🤖 Bot ishga tushdi...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
