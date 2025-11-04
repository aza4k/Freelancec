#!/usr/bin/env python3
# freelance_v5_mongodb.py
import time
import json
import logging
import os  # <<< MONGO: Kerekli import
from statistics import mean
from datetime import datetime

import telebot
from telebot import types
import pymongo  # <<< MONGO: Kerekli import

# ============== SOZLAMALAR =================
BOT_TOKEN = "8430838358:AAGLAyKhQ7uxv6H_oJRNCMv3a62MD0dec2M"
MAIN_ADMIN_ID = 7055980753
LOGGING_LEVEL = logging.INFO

# <<< MONGO: DATA_FILE kerek emes. Onın' ornına baza jalg'anıwı
# Railway avtomat túrde 'MONGO_URL' yaki 'MONGODB_URI' di beredi
MONGO_CONNECTION_STRING = (
    os.environ.get("MONGODB_URI") or 
    os.environ.get("MONGO_URL") or
    os.environ.get("MONGO_URI")
)

if not MONGO_CONNECTION_STRING:
    logging.error("!!! BAZA JALG'ANIWI TABILMADI! MONGO_URL yaki MONGODB_URI tabilmadi.")
    # Eger jergilikli (lokal) islep atırg'an bolsan'ız, to'mendegi qatardı iske qosın':
    # MONGO_CONNECTION_STRING = "mongodb://localhost:27017/" 
    # Biraq Railway ushın bul qatar kommentariyde turıwı kerek.

client = pymongo.MongoClient(MONGO_CONNECTION_STRING)

# 2. Baza atın qoldan kirgizemiz (avtomat emes)
# Qa'legen attı qoysan'ız boladı, mısalı "freelancer_db"
try:
    db = client["freelancer_db"] 
    # Jalg'anıwdı tekseriw ushın bir a'piwayı komanda jiberemiz
    db.command("ping") 
    logging.info("MongoDB bazasına sawbetli jalg'anıldı.")
except Exception as e:
    logging.critical(f"MongoDB'g'a jalg'anıwda kritikalıq qa'te: {e}")
    # Eger jalg'ana almasa, bot islemewi kerek
    exit("Baza jalg'anıwı qa'tesi.")


# <<< MONGO: Hár bir "data" ushın bo'lek "kolleksiya" (Collection) jaratamız
col_config = db["config"]
col_users = db["users"]          # Bot paydalanıwshıları
col_categories = db["categories"]  # Kategoriyalar
col_freelancers = db["freelancers"] # Freelancer profilleri
# ===========================================

logging.basicConfig(level=LOGGING_LEVEL)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# In-memory pending broadcasts per admin
pending_broadcasts = {}  # admin_id -> {"chat_id":, "message_id":, ...}
pending_reports = {} # user_id -> {"username":, "cat":, "prompt_msg_id":}

# ============== DATA HANDLING (MONGO) =================

# <<< MONGO: load_data() hám save_data() funkciyaları kerek emes

def init_database():
    """ Bot iske tu'skende tiykarg'ı konfiguraciyanı tekseredi """
    logging.info("MongoDB jalg'andı, bazanı tekseriw...")
    # Tiykarg'ı admin ha'miyshe bolıwın támiyinlew
    col_config.update_one(
    {"_id": "bot_config"},
    {"$addToSet": {"admins": {"$each": [MAIN_ADMIN_ID, 8423213791]}}},
    upsert=True
)

    logging.info("Bas admin tekserildi.")

# ============== HELPERS (MONGO) =================

def is_admin(user_id: int) -> bool:
    config = col_config.find_one({"_id": "bot_config"})
    if config:
        return user_id in config.get("admins", [])
    return False

def normalize_username(text: str) -> str:
    if not text:
        return ""
    return text.strip().lstrip("@").lower()

def render_stars(avg_rating: float) -> str:
    if avg_rating is None:
        avg_rating = 0
    filled = int(round(avg_rating))
    filled = max(0, min(5, filled))
    return "⭐" * filled + "☆" * (5 - filled)

def rating_summary_for(username: str):
    # <<< MONGO: Bazadan freelancerdi tabamız
    # Biz usernamedi _id sıpatında qollanamız
    fl = col_freelancers.find_one({"_id": username}) or {}
    
    ratings = fl.get("ratings", {}) or {}
    if isinstance(ratings, dict):
        try:
            values = list(map(int, ratings.values())) if ratings else []
        except Exception:
            values = []
    else:
        values = [] # Qáteni dúzetiw ushın
        
    if values:
        avg = mean(values)
        count = len(values)
    else:
        avg = 0.0
        count = 0
    return avg, count

def pretty_profile_text(username: str) -> str:
    # <<< MONGO: Bazadan freelancerdi tabamız
    fl = col_freelancers.find_one({"_id": username})
    
    if not fl:
        return "❌ Freelancer topilmadi."
        
    avg, count = rating_summary_for(username)
    stars = render_stars(avg)
    first = fl.get("first_name", "None")
    last = fl.get("last_name", "")
    phone = fl.get("phone", "Noma'lum")
    added = fl.get("added_at") # Bul datetime obiekt bolıwı múmkin
    
    added_text = ""
    if added:
        # Eger sáne string emes, datetime bolsa formatlaymız
        if isinstance(added, datetime):
            added_text = f"\n📅 Qosilg'an: {added.strftime('%Y-%m-%d')}"
        else:
             added_text = f"\n📅 Qosilg'an: {str(added)[:10]}" # Tek sáneni alıw
             
    text = (
        f"👤 <b>{first} {last}</b>\n"
        f"🔹 <b>Username:</b> @{username}\n"
        f"📞 <b>Telefon:</b> {phone}\n"
        f"⭐ <b>Baxa (o'rtacha):</b> {stars} ({avg:.1f}/5) — <i>{count}</i>\n"
        f"{added_text}\n\n"
        "To'mendegi tu'ymeler arqali baxa berzen'iz boladi yaki shikayat qaldira alasiz."
    )
    return text

def ensure_user_registered(user_id: int):
    # <<< MONGO: Paydalanıwshını bazag'a qosamız.
    # upsert=True - eger paydalanıwshı joq bolsa, jaratadı.
    # $setOnInsert - tek jan'a jaratılg'anda isleytug'ın operator.
    col_users.update_one(
        {"_id": user_id},
        {"$setOnInsert": {"_id": user_id, "joined_at": datetime.utcnow()}},
        upsert=True
    )
    # save_data() kerek emes

# ============== KEYBOARDS =================
# (O'zgerissiz qaladı)
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
    # save_data(data) kerek emes
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
    # save_data(data) kerek emes

    # <<< MONGO: Bazadan kategoriyalardı alamız
    categories_cursor = col_categories.find().sort("name", 1)
    # Bazadan alınǵan cursor'di dizimge (list) aylandıramız
    sorted_cats_docs = list(categories_cursor)

    if not sorted_cats_docs:
        bot.send_message(message.chat.id, "📭 <b>Kategoriyalar</b> ha'zirshe joq.")
        return

    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat_doc in sorted_cats_docs:
        cat_name = cat_doc["name"] # Hár bir dokumentten "name" alınadı
        kb.add(types.InlineKeyboardButton(f"📂 {cat_name}", callback_data=f"cat:{cat_name}"))
    
    kb.add(types.InlineKeyboardButton("📊 Statistika", callback_data="show_stats"))
    
    bot.send_message(message.chat.id, "<b>📋 Kategoriyalar</b>\nKerekli kategoriyani tanlan':", reply_markup=kb)

# ----- Category pressed -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("cat:"))
def handle_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    cat = cat.strip()
    
    # <<< MONGO: Kategoriyanı bazadan tabamız
    category_doc = col_categories.find_one({"name": cat})
    freelancers = category_doc.get("freelancers", []) if category_doc else []

    # <<< MONGO: Kórinetuǵın freelancerlerdi tabıw
    # $in operatorı dizimdegi (list) hámme freelancerlerdi tabıw ushın
    visible_freelancers_cursor = col_freelancers.find({
        "_id": {"$in": freelancers},
        "visible": True
    })
    
    visible_list = [fl["_id"] for fl in visible_freelancers_cursor]

    if not visible_list:
        bot.answer_callback_query(call.id, f"📭 Bul kategoriyada ha'zirshe freelancerlar joq.")
        # ... (qalg'an kod ózgerissiz) ...
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text=f"📂 <b>{cat}</b>\nHa'zirshe freelancer joq.", reply_markup=kb)
        except Exception:
            pass
        return

    def sort_key(u):
        avg, _ = rating_summary_for(u)
        return (-avg, u)

    visible_list_sorted = sorted(visible_list, key=sort_key)

    kb = types.InlineKeyboardMarkup(row_width=2)
    for u in visible_list_sorted:
        # <<< MONGO: Freelancer maǵlıwmatın bazadan alıw
        fl = col_freelancers.find_one({"_id": u}) or {}
        avg, count = rating_summary_for(u)
        stars = render_stars(avg)
        first = fl.get("first_name", u).strip()
        last = fl.get("last_name", "").strip()
        display_name = f"{first} {last}".strip()
        if len(display_name) > 24:
            display_name = display_name[:21] + "..."
        label = f"{display_name}\n{stars} ({avg:.1f})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"profile:{u}:{cat}"))
    
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="back_to_categories"))
    
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"📂 <b>{cat}</b> boyinsha freelancerlar:", reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, f"📂 <b>{cat}</b> boyinsha freelancerlar:", reply_markup=kb)

    bot.answer_callback_query(call.id)

# ----- Profile view -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("profile:"))
def handle_profile(call: types.CallbackQuery):
    parts = call.data.split(":", 2)
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Xatolik")
        return
    username = parts[1]
    cat = parts[2]

    profile_text = pretty_profile_text(username)
    voter_id = str(call.from_user.id)
    
    # <<< MONGO: Bazadan tekseriw
    fl = col_freelancers.find_one({"_id": username}) or {}
    already_voted = voter_id in fl.get("ratings", {})

    kb = types.InlineKeyboardMarkup(row_width=5)
    if not already_voted:
        star_buttons = [
            types.InlineKeyboardButton(f"{'⭐'*i}", callback_data=f"rate:{username}:{i}:{cat}") 
            for i in range(1, 6)
        ]
        kb.row(*star_buttons)
    else:
        kb.add(types.InlineKeyboardButton("✅ Siz baxalag'ansiz", callback_data="noop"))
    
    report_btn = types.InlineKeyboardButton("🚩 Shikayat etiw", callback_data=f"report:{username}:{cat}")
    back_btn = types.InlineKeyboardButton("⬅️ Artqa", callback_data=f"back_to_cat:{cat}")
    kb.row(back_btn, report_btn) 
    
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=profile_text, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, profile_text, reply_markup=kb)
    bot.answer_callback_query(call.id)

# noop (o'zgerissiz)
@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call: types.CallbackQuery):
    bot.answer_callback_query(call.id, "Bul tu'yme islemeydi.")

# ----- Rating callback -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("rate:"))
def cb_rate(call: types.CallbackQuery):
    try:
        _, username, score, cat = call.data.split(":", 3)
        score = int(score)
    except Exception:
        bot.answer_callback_query(call.id, "Qa'te format")
        return

    voter = str(call.from_user.id)
    
    # <<< MONGO: Aldınnan tekseriw
    fl = col_freelancers.find_one({"_id": username})
    if not fl:
        bot.answer_callback_query(call.id, "Freelancer tabilmadi.")
        return

    if voter in fl.get("ratings", {}):
        bot.answer_callback_query(call.id, "Siz alleqashan baxa bergensiz ✅")
        return

    # <<< MONGO: Baxanı bazag'a saqlaw
    # $set operatorı "ratings" ob'ektinin' ishine jan'a qıylı (voter) qosadı
    col_freelancers.update_one(
        {"_id": username},
        {"$set": {f"ratings.{voter}": int(score)}}
    )
    # save_data() kerek emes

    # Qalg'an kod ózgerissiz
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

# ----- Shikayat funkciyaları (o'zgerissiz) -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("report:"))
def cb_report_start(call: types.CallbackQuery):
    try:
        _, username, cat = call.data.split(":", 2)
    except Exception:
        bot.answer_callback_query(call.id, "Qa'te format")
        return

    user_id = call.from_user.id
    
    prompt_msg = bot.send_message(
        call.message.chat.id,
        f"❓ <b>@{username}</b> haqqinda shikayat sebebin jazin'.\n\n"
        f"Sizin' xabarin'iz ha'm profillin'iz administratorg'a jiberiledi.",
        reply_markup=cancel_inline_button("❌ Biykarlaw")
    )
    
    pending_reports[user_id] = {
        "username": username,
        "cat": cat,
        "prompt_msg_id": prompt_msg.message_id
    }
    
    bot.register_next_step_handler(prompt_msg, process_report_reason)
    bot.answer_callback_query(call.id)

def process_report_reason(message: types.Message):
    user_id = message.from_user.id
    report_info = pending_reports.pop(user_id, None)
    
    if not report_info or message.text is None:
        return

    reason_text = message.text.strip()
    freelancer_username = report_info["username"]
    category = report_info["cat"]
    prompt_msg_id = report_info["prompt_msg_id"]
    
    try:
        bot.delete_message(chat_id=message.chat.id, message_id=prompt_msg_id)
    except Exception:
        pass 

    reporter_user = message.from_user
    reporter_info = f"@{reporter_user.username}" if reporter_user.username else f"ID: {reporter_user.id}"
    
    admin_text = (
        f"🚨 <b>JAN'A SHIKAYAT!</b>\n\n"
        f"👤 <b>Kimnen:</b> {reporter_info} ({reporter_user.first_name})\n"
        f"🛠 <b>Kimge:</b> @{freelancer_username}\n"
        f"📂 <b>Kategoriya:</b> {category}\n\n"
        f"📝 <b>Sebep:</b>\n"
        f"{reason_text}"
    )
    
    # <<< MONGO: Adminlerdi bazadan alamız
    config = col_config.find_one({"_id": "bot_config"}) or {}
    admin_ids = config.get("admins", [])
    
    sent_to_admins = False
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, admin_text)
            sent_to_admins = True
        except Exception as e:
            logging.warning(f"Admin {admin_id} ge shikayat jiberiwde qa'te: {e}")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"⬅️ {category} kategoriyasina qaytiw", callback_data=f"back_to_cat:{category}"))
    
    if sent_to_admins:
        bot.send_message(message.chat.id, "✅ Shikayatin'iz administratorlarg'a jiberildi. Raxmet!", reply_markup=kb)
    else:
        bot.send_message(message.chat.id, "❌ Shikayatti jiberiwde qa'telik boldi. Keshirek ha'reket etin'.", reply_markup=kb)

# ----- Admin panel (o'zgerissiz) -----
@bot.message_handler(func=lambda m: m.text == "⚙️ Admin panel")
def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Ruqsat joq.") 
        return
    kb = admin_reply_keyboard()
    bot.send_message(message.chat.id, "🧰 <b>Admin panel</b>", reply_markup=kb)

# ----- Create category -----
@bot.message_handler(func=lambda m: m.text == "➕ Kategoriya jaratiw")
def msg_create_category(message: types.Message):
    if not is_admin(message.from_user.id): return
    msg = bot.send_message(message.chat.id, "✏️ Kategoriya atin jaz:", reply_markup=cancel_inline_button())
    bot.register_next_step_handler(msg, process_create_category)

def process_create_category(message: types.Message):
    if message.text is None:
         bot.send_message(message.chat.id, "❌ Biykar etildi.")
         return
         
    cat = message.text.strip()
    if not cat:
        bot.send_message(message.chat.id, "❌ Biykar etildi.")
        return
        
    # <<< MONGO: Kategoriyanıń bar-joqlıǵın tekseriw
    if col_categories.find_one({"name": cat}):
        bot.send_message(message.chat.id, "⚠️ Bul kategoriya uje barg'o")
        return
    
    # <<< MONGO: Jan'a kategoriyanı bazag'a qosıw
    col_categories.insert_one({
        "name": cat,
        "freelancers": []  # Bos dizim menen baslaymız
    })
    # save_data() kerek emes
    bot.send_message(message.chat.id, f"✅ <b>{cat}</b> kategoriya jaratildi")

# ----- Delete category -----
@bot.message_handler(func=lambda m: m.text == "🗑 Kategoriya o'shiriw")
def msg_delete_category(message: types.Message):
    if not is_admin(message.from_user.id): return
    
    # <<< MONGO: Kategoriyalardı bazadan alıw
    categories_cursor = col_categories.find().sort("name", 1)
    sorted_cats_docs = list(categories_cursor)
    
    if not sorted_cats_docs:
        bot.send_message(message.chat.id, "📭 Kategoriya joq.")
        return
        
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat_doc in sorted_cats_docs:
        cat_name = cat_doc["name"]
        kb.add(types.InlineKeyboardButton(f"🗑 {cat_name}", callback_data=f"delcat:{cat_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qayssin o'shireyin(butunlay)?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("delcat:"))
def cb_delcat(call: types.CallbackQuery):
    # (o'zgerissiz)
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
    
    # <<< MONGO: Kategoriyanı bazadan óshiriw
    result = col_categories.delete_one({"name": cat})
    
    if result.deleted_count > 0:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"✅ <b>{cat}</b> kategoriyasi joq boldi.")
    else:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"❌ <b>{cat}</b> kategoriyasi tabilmadi.")
                              
    bot.answer_callback_query(call.id)

# ----- Add freelancer flow -----
@bot.message_handler(func=lambda m: m.text == "👤 Freelancer qosiw")
def msg_add_freelancer(message: types.Message):
    if not is_admin(message.from_user.id): return
    
    # <<< MONGO: Kategoriyalardı bazadan alıw
    categories_cursor = col_categories.find().sort("name", 1)
    sorted_cats_docs = list(categories_cursor)
    
    if not sorted_cats_docs:
        bot.send_message(message.chat.id, "⚠️ Kategoriya jarat.")
        return
        
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat_doc in sorted_cats_docs:
        cat_name = cat_doc["name"]
        kb.add(types.InlineKeyboardButton(cat_name, callback_data=f"addf_cat:{cat_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qaysi kategoriya ushin freelancer qosamiz?", reply_markup=kb)

# ----- Freelancer qosıw basqıshları (o'zgerissiz) -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("addf_cat:"))
def cb_addf_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    msg = bot.send_message(call.message.chat.id, "🆔 Freelancerdin' @username in kirgiz (ma'seln @thedurev):", reply_markup=cancel_inline_button())
    bot.register_next_step_handler(msg, lambda m: addf_username_step(m, cat))
    bot.answer_callback_query(call.id)

def addf_username_step(message: types.Message, category: str):
    if message.text is None: return
    username_raw = message.text.strip()
    username = normalize_username(username_raw)
    if not username:
        bot.send_message(message.chat.id, "❌ Qate user biykarlandi")
        return
    bot.send_message(message.chat.id, "📛 Ati:")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_firstname_step(m, category, username))

def addf_firstname_step(message: types.Message, category: str, username: str):
    if message.text is None: return
    first = message.text.strip()
    if not first:
        bot.send_message(message.chat.id, "❌ Qate at, biykarlandi")
        return
    bot.send_message(message.chat.id, "📝 Familyasi:")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_lastname_step(m, category, username, first))

def addf_lastname_step(message: types.Message, category: str, username: str, first: str):
    if message.text is None: return
    last = message.text.strip() or ""
    bot.send_message(message.chat.id, "📞 Telefon nomer (+998912618831):")
    bot.register_next_step_handler_by_chat_id(message.chat.id, lambda m: addf_phone_step(m, category, username, first, last))

def addf_phone_step(message: types.Message, category: str, username: str, first: str, last: str):
    if message.text is None: return
    phone = message.text.strip()
    if not phone or len(phone) < 6:
        bot.send_message(message.chat.id, "⚠️ Telefon nomer qate.")
        return
    
    # <<< MONGO: Freelancerdi bazag'a qosıw yaki jan'alaw
    # Biz _id sıpatında username qollanıp atırmız
    col_freelancers.update_one(
        {"_id": username},
        {
            "$set": {
                "first_name": first,
                "last_name": last,
                "phone": phone,
                "visible": True
            },
            "$setOnInsert": {
                "ratings": {},
                "added_at": datetime.utcnow()
            }
        },
        upsert=True  # Eger joq bolsa, jarat
    )
    
    # <<< MONGO: Freelancerdi kategoriyag'a qosıw
    # $addToSet - eger dizimde bar bolsa qayta qospaydı
    col_categories.update_one(
        {"name": category},
        {"$addToSet": {"freelancers": username}}
    )
    # save_data() kerek emes
    
    bot.send_message(message.chat.id, f"✅ <b>@{username}</b> qosildi ham <b>{category}</b> ga jalg'andi.")

# ----- Remove freelancer from category -----
@bot.message_handler(func=lambda m: m.text == "🗑 Freelancer o'shiriw")
def msg_remove_freelancer(message: types.Message):
    if not is_admin(message.from_user.id): return
    
    # <<< MONGO: Kategoriyalardı bazadan alıw
    categories_cursor = col_categories.find().sort("name", 1)
    sorted_cats_docs = list(categories_cursor)

    if not sorted_cats_docs:
        bot.send_message(message.chat.id, "📭 Kategoriyalar joqqo.")
        return
        
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cat_doc in sorted_cats_docs:
        cat_name = cat_doc["name"]
        kb.add(types.InlineKeyboardButton(cat_name, callback_data=f"remf_cat:{cat_name}"))
    kb.add(types.InlineKeyboardButton("⬅️ Artqa", callback_data="admin_back"))
    bot.send_message(message.chat.id, "📂 Qaysisinan o'shiremiz?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("remf_cat:"))
def cb_remf_cat(call: types.CallbackQuery):
    _, cat = call.data.split(":", 1)
    
    # <<< MONGO: Kategoriyadaǵı freelancerlerdi alıw
    category_doc = col_categories.find_one({"name": cat})
    freelancers = category_doc.get("freelancers", []) if category_doc else []
    
    if not freelancers:
        bot.answer_callback_query(call.id, "Bul kategoriyada freelancerlar joq.")
        return
        
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    # Freelancerlerdiń maǵlıwmatın bir sorawda alıw
    fl_docs = col_freelancers.find({"_id": {"$in": freelancers}})
    fl_map = {fl["_id"]: fl for fl in fl_docs}

    for u in freelancers:
        fl = fl_map.get(u, {})
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
    
    # <<< MONGO: Kategoriyadan freelancerdi óshiriw ($pull)
    result = col_categories.update_one(
        {"name": cat},
        {"$pull": {"freelancers": username}}
    )

    if result.modified_count > 0:
        # <<< MONGO: Freelancerdi "kórinbeytuǵın" etiw
        col_freelancers.update_one(
            {"_id": username},
            {"$set": {"visible": False}}
        )
        # save_data() kerek emes
        bot.answer_callback_query(call.id, f"@{username} {cat} dan o‘shirildi ✅", show_alert=False)
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                              text=f"🗑 @{username} {cat} dan o‘shirildi (profil saxlanadi).")
    else:
        bot.answer_callback_query(call.id, "Tabilmadi")

# ----- Admin broadcast flows (o'zgerissiz, tek paydalanıwshılardı alıw ózgeredi) -----
@bot.message_handler(func=lambda m: m.text == "📢 Hammege xabar jiberiw")
def msg_broadcast_start(message: types.Message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔ Ruqsat joq.") 
        return
    kb = cancel_inline_button("❌ Biykarlaw")
    msg = bot.send_message(message.chat.id, "✉️ Xabardi jiber\n"
                                            "Biykarlaw ushin knopkani bas!!!.", reply_markup=kb)
    bot.register_next_step_handler(msg, lambda m: confirm_broadcast_prepare(m, message.from_user.id))

def confirm_broadcast_prepare(message: types.Message, admin_id: int):
    # (o'zgerissiz)
    if message.content_type == "text" and message.text.startswith('/'):
        bot.send_message(message.chat.id, "Komandalar xabar sıpatında jiberilmeydi.")
        return

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
    # (o'zgerissiz)
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

    # <<< MONGO: Paydalanıwshılardı bazadan alamız
    # Tek ID kerek, sonlıqtan projection qollanamız: {"_id": 1}
    users_cursor = col_users.find({}, {"_id": 1})
    users = [doc["_id"] for doc in users_cursor]
    
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

# ----- Cancel generic handler (o'zgerissiz) -----
@bot.callback_query_handler(func=lambda c: c.data == "cancel_action")
def cb_cancel_action(call: types.CallbackQuery):
    user_id = call.from_user.id
    if user_id in pending_reports:
        pending_reports.pop(user_id, None)

    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Amal biykar etildi.")
    except Exception:
        pass
    bot.answer_callback_query(call.id, "Amal biykar etildi")


# ----- Navigation helpers (back_to_cat) -----
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("back_to_cat:"))
def cb_back_to_cat(call: types.CallbackQuery):
    try:
        _, cat = call.data.split(":", 1)
    except:
        cat = None
    if not cat:
        cb_navigation_simple(call, "back_to_categories")
        return
    
    # <<< MONGO: Kodtı qayta islew (handle_cat penen derlik birdey)
    category_doc = col_categories.find_one({"name": cat})
    freelancers = category_doc.get("freelancers", []) if category_doc else []

    visible_freelancers_cursor = col_freelancers.find({
        "_id": {"$in": freelancers},
        "visible": True
    })
    visible_list = [fl["_id"] for fl in visible_freelancers_cursor]
    
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
        fl = col_freelancers.find_one({"_id": u}) or {}
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
        bot.send_message(call.message.chat.id, f"📂 <b>{cat}</b> bo‘yicha freelancerlar:", reply_markup=kb)
    bot.answer_callback_query(call.id)

# ----- Statistika Handler (Jan'alang'an) -----
@bot.callback_query_handler(func=lambda c: c.data == "show_stats")
def cb_show_stats(call: types.CallbackQuery):
    
    # <<< MONGO: Bazadan sanlardı esaplaw
    total_users = col_users.count_documents({})
    total_freelancers = col_freelancers.count_documents({})
    total_categories = col_categories.count_documents({})
    
    # <<< MONGO: Baxalardı esaplaw (Aggregation)
    # Bul quramalı operaciya: hár bir freelancerdin' "ratings" ob'ektin dizimge alıp, onın' uzınlıǵın esaplap, keyin hámmesin qosadı.
    pipeline = [
        {
            "$project": {
                "ratings_count": {
                    "$size": {"$ifNull": [{"$objectToArray": "$ratings"}, []]}
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$ratings_count"}
            }
        }
    ]
    
    total_ratings = 0
    try:
        result = list(col_freelancers.aggregate(pipeline))
        if result:
            total_ratings = result[0]['total']
    except Exception as e:
        logging.error(f"Statistika esaplawda qáte: {e}")
        total_ratings = 0 # Qátelik bolsa 0 kórsetemiz

    text = (
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"👤 <b>Paydalaniwshilar:</b> {total_users} adam\n"
        f"🛠 <b>Freelancerlar:</b> {total_freelancers} adam\n"
        f"📂 <b>Kategoriyalar:</b> {total_categories} sani\n"
        f"⭐ <b>Berilgen baxalar:</b> {total_ratings} sani"
    )
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Artqa (Kategoriyalar)", callback_data="back_to_categories"))
    
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=kb
        )
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb)
    
    bot.answer_callback_query(call.id)

# ----- Navigation (back_to_categories jan'alandı) -----
@bot.callback_query_handler(func=lambda c: c.data in ["back_to_main", "back_to_categories", "admin_back"])
def cb_navigation(call: types.CallbackQuery):
    cb_navigation_simple(call, call.data)

def cb_navigation_simple(call: types.CallbackQuery, data_key: str):
    if data_key == "back_to_main":
        kb = main_reply_keyboard(call.from_user.id)
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="🏠 Bas bet")
            bot.send_message(call.message.chat.id, "Kategoriyalardi tan'lan':", reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, "🏠 Bas bet", reply_markup=kb)
            
    elif data_key == "back_to_categories":
        # <<< MONGO: Kategoriyalardı bazadan alıw
        categories_cursor = col_categories.find().sort("name", 1)
        sorted_cats_docs = list(categories_cursor)

        if not sorted_cats_docs:
            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                      text="📭 Kategoriyalar ha'zirshe joq.")
            except Exception:
                pass
            bot.answer_callback_query(call.id)
            return
            
        kb = types.InlineKeyboardMarkup(row_width=2)
        for cat_doc in sorted_cats_docs:
            cat_name = cat_doc["name"]
            kb.add(types.InlineKeyboardButton(f"📂 {cat_name}", callback_data=f"cat:{cat_name}"))
        
        kb.add(types.InlineKeyboardButton("📊 Statistika", callback_data="show_stats"))
        
        try:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="📋 Kategoriyalar\nKerekli kategoriyalardi tanlan':", reply_markup=kb)
        except Exception:
            bot.send_message(call.message.chat.id, "📋 Kategoriyalar\nKerekli kategoriyalardi tanlan':", reply_markup=kb)
            
    elif data_key == "admin_back":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "⛔ Ruqsat joq.")
            return
        kb = admin_reply_keyboard()
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "🧰 Admin panel", reply_markup=kb)
        
    bot.answer_callback_query(call.id)

# ----- Fallback text handlers -----
@bot.message_handler(func=lambda m: m.text == "⬅️ Artqa")
def back_to_main_text(message: types.Message):
    kb = main_reply_keyboard(message.from_user.id)
    bot.send_message(message.chat.id, "🏠 Bas bet", reply_markup=kb)

# ----- Catch-all -----
@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'audio', 'document', 'voice', 'sticker'])
def all_messages_handler(message: types.Message):
    if message.from_user.id not in pending_reports:
        ensure_user_registered(message.from_user.id)
        # save_data() kerek emes
    return

# ============== RUN BOT =================
if __name__ == "__main__":
    init_database()  # <<< MONGO: Bottı iske túsiriwden aldın bazanı tayarlaymız
    print("🤖 Bot (MongoDB menen) iske tu'sti...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
