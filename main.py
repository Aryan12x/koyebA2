import logging
import random
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ----------------------------- Logging Setup ----------------------------- #
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------- Health Server ----------------------------- #
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ----------------------------- Load Questions from JSON ----------------------------- #
def load_questions():
    try:
        with open('questions.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        valid_questions = []
        for q in data:
            if isinstance(q, dict) and "question" in q and "options" in q and isinstance(q["options"], list):
                valid_questions.append(q)
            else:
                logger.warning(f"Invalid question format skipped: {q}")
        logger.info(f"Loaded {len(valid_questions)} valid questions from JSON file.")
        return valid_questions
    except Exception as e:
        logger.error(f"Failed to load questions from JSON: {e}")
        return []

questions = load_questions()

# ------------------------- Persistent Chat Configuration ------------------------- #
CONFIG_FILE = 'chat_config.json'
chat_config = {}

def load_chat_config():
    global chat_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                chat_config = json.load(f)
            logger.info("Chat configuration loaded from file.")
        except Exception as e:
            logger.error(f"Failed to load chat config: {e}")
            chat_config = {}
    else:
        chat_config = {}

def save_chat_config():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(chat_config, f)
    except Exception as e:
        logger.error(f"Failed to save chat config: {e}")

def ensure_chat_config(chat_id: int):
    key = str(chat_id)
    if key not in chat_config:
        chat_config[key] = {
            "language": "English",
            "auto_delete": True,
            "auto_pin": False,
            "last_quiz_id": None,
            "active": True
        }
        save_chat_config()
    return chat_config[key]

# ----------------------------- Utility Functions ----------------------------- #
def get_random_question():
    return None if not questions else random.choice(questions)

def get_valid_random_question():
    if not questions:
        return None
    valid_questions = [q for q in questions if len(q['question'].split()) <= 100]
    if valid_questions:
        return random.choice(valid_questions)
    logger.warning("No valid questions with 100 words or less available.")
    return None

# ----------------------------- Permission Checks ----------------------------- #
def is_user_admin(update: Update, context: CallbackContext) -> bool:
    try:
        member = context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        logger.warning(f"Admin check failed: {e}")
        return False

def has_pin_permission(chat_id: int, context: CallbackContext) -> bool:
    try:
        bot_member = context.bot.get_chat_member(chat_id, context.bot.id)
        return hasattr(bot_member, 'can_pin_messages') and bot_member.can_pin_messages
    except Exception as e:
        logger.warning(f"Failed to check pin permission in chat {chat_id}: {e}")
        return False

def send_nonadmin_error(query, context: CallbackContext):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close")]])
    query.edit_message_text(text="You don't have admin right to perform this action.", reply_markup=keyboard)

# ----------------------------- Command Handlers ----------------------------- #
def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_first = update.effective_user.first_name
    if update.effective_chat.type in ["group", "supergroup"]:
        text = (
            f"Hi {user_first} !!\n\nThanks for starting me !!\n"
            "Chess quizzes will now be sent to this group.\n\n"
            "To change bot settings\nJust hit /settings"
        )
        keyboard = [[InlineKeyboardButton("Start Me", url="https://t.me/ThinkChessyBot")]]
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        cfg = ensure_chat_config(chat_id)
        cfg['active'] = True
        save_chat_config()
        schedule_quiz(context.job_queue, chat_id)
    else:
        welcome = (
            "♟️ Welcome to ThinkChessy Bot! 🧠\n"
            "Your ultimate Chess Quiz companion for group battles!\n\n"
            "👥 Add me to your group and I will send quizzes every 30 minutes."  
        )
        buttons = [
            [InlineKeyboardButton("➕ Add me to group", url="https://t.me/ThinkChessyBot?startgroup=true")],
            [InlineKeyboardButton("🔧 Support", url="https://t.me/ThinkChessySupport")],
            [InlineKeyboardButton("📝 About", callback_data="about")]
        ]
        update.message.reply_text(welcome, reply_markup=InlineKeyboardMarkup(buttons))

def settings(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ["group", "supergroup"]:
        update.message.reply_text("⚠️ This command is only for groups.")
        return
    chat_id = update.effective_chat.id
    cfg = ensure_chat_config(chat_id)
    text = (
        f"🔩 Setup Zone\n\n"
        f"🌐 Language : {cfg['language']}\n"
        f"🗑️ Auto-Delete : {'ON' if cfg['auto_delete'] else 'OFF'}\n"
        f"📌 Auto-Pin : {'ON' if cfg['auto_pin'] else 'OFF'}\n\n"
        "Select an option:"
    )
    kb = [
        [InlineKeyboardButton("🌐 Language", callback_data="change_language")],
        [InlineKeyboardButton("🗑️ Auto-Delete", callback_data="toggle_autodelete")],
        [InlineKeyboardButton("📌 Auto-Pin", callback_data="toggle_autopin")]
    ]
    update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

def about(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    text = (
        "🧠 About ThinkChessy Bot\n"
        "Auto chess quizzes every 30 minutes. Enjoy!"
    )
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="back_from_about")]]))

def back_from_about(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    settings(update, context)

def change_language(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not is_user_admin(update, context): return send_nonadmin_error(query, context)
    query.answer()
    chat_id = update.effective_chat.id
    cfg = ensure_chat_config(chat_id)
    kb = [
        [InlineKeyboardButton("English", callback_data="lang_English")],
        [InlineKeyboardButton("Hindi", callback_data="lang_Hindi")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_to_settings")]
    ]
    query.edit_message_text(f"Select language (current: {cfg['language']})", reply_markup=InlineKeyboardMarkup(kb))

def toggle_autodelete(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not is_user_admin(update, context): return send_nonadmin_error(query, context)
    query.answer()
    chat_id = update.effective_chat.id
    cfg = ensure_chat_config(chat_id)
    status = not cfg['auto_delete']
    cfg['auto_delete'] = status
    save_chat_config()
    query.edit_message_text(f"Auto-Delete set to {'ON' if status else 'OFF'}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="back_to_settings")]]))

def toggle_autopin(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if not is_user_admin(update, context): return send_nonadmin_error(query, context)
    query.answer()
    chat_id = update.effective_chat.id
    cfg = ensure_chat_config(chat_id)
    status = not cfg['auto_pin']
    if status and not has_pin_permission(chat_id, context):
        return query.edit_message_text("Grant pin permission first", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close")]]))
    cfg['auto_pin'] = status
    save_chat_config()
    query.edit_message_text(f"Auto-Pin set to {'ON' if status else 'OFF'}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="back_to_settings")]]))

def back_to_settings(update: Update, context: CallbackContext) -> None:
    settings(update, context)

def language_selection(update: Update, context: CallbackContext) -> None:
    # same as change_language callback for lang_
    return change_language(update, context)

def autodelete_selection(update: Update, context: CallbackContext) -> None:
    return toggle_autodelete(update, context)

def autopin_selection(update: Update, context: CallbackContext) -> None:
    return toggle_autopin(update, context)

def close_message(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    try: query.message.delete()
    except: pass

# ----------------------------- Quiz Poll ----------------------------- #
def send_quiz(context: CallbackContext) -> None:
    job = context.job
    chat_id = job.context
    cfg = ensure_chat_config(chat_id)
    q = get_valid_random_question()
    if not q: return
    opts = [opt if len(opt)<=100 else opt[:100] for opt in q['options']]
    correct = {'A':0,'B':1,'C':2,'D':3}.get(q.get('answer','A').upper(),0)
    if cfg['auto_delete'] and cfg.get('last_quiz_id'):
        try: context.bot.delete_message(chat_id, cfg['last_quiz_id'])
        except: pass
    poll = context.bot.send_poll(chat_id, q['question'], opts, type='quiz', correct_option_id=correct, is_anonymous=False)
    cfg['last_quiz_id'] = poll.message_id
    save_chat_config()
    if cfg['auto_pin']:
        try: context.bot.pin_chat_message(chat_id, poll.message_id, disable_notification=True)
        except: cfg['auto_pin']=False; save_chat_config()

def schedule_quiz(job_queue, chat_id: int) -> None:
    for job in job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    job_queue.run_repeating(send_quiz,interval=1800,first=0,context=chat_id,name=str(chat_id))

def new_chat_member(update: Update, context: CallbackContext) -> None:
    for m in update.message.new_chat_members:
        if m.username == context.bot.username:
            chat_id = update.effective_chat.id
            ensure_chat_config(chat_id)
            update.message.reply_text("Bot added to group! Starting quizzes.")
            schedule_quiz(context.job_queue, chat_id)

def error_handler(update, context: CallbackContext) -> None:
    logger.error("Exception handling update", exc_info=context.error)

# ----------------------------- Main ----------------------------- #
def main() -> None:
    load_chat_config()
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        logger.error("Bot token not found! Exiting.")
        return
    updater = Updater(TOKEN,use_context=True)
    dp = updater.dispatcher
    # Register handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("settings", settings))
    dp.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    dp.add_handler(CallbackQueryHandler(back_from_about, pattern="^back_from_about$"))
    dp.add_handler(CallbackQueryHandler(change_language, pattern="^change_language$"))
    dp.add_handler(CallbackQueryHandler(toggle_autodelete, pattern="^toggle_autodelete$"))
    dp.add_handler(CallbackQueryHandler(toggle_autopin, pattern="^toggle_autopin$"))
    dp.add_handler(CallbackQueryHandler(back_to_settings, pattern="^back_to_settings$"))
    dp.add_handler(CallbackQueryHandler(language_selection, pattern="^lang_"))
    dp.add_handler(CallbackQueryHandler(autodelete_selection, pattern="^autodelete_"))
    dp.add_handler(CallbackQueryHandler(autopin_selection, pattern="^autopin_"))
    dp.add_handler(CallbackQueryHandler(close_message, pattern="^close$"))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_chat_member))
    dp.add_error_handler(error_handler)
    # Schedule any existing chats
    for cid in list(chat_config.keys()):
        try: schedule_quiz(updater.job_queue, int(cid))
        except: pass
    # Start
    updater.start_polling()
    logger.info("Bot started polling.")
    updater.idle()

if __name__ == '__main__':
    start_health_server()
    main()