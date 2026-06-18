# SONIK PAYMENT BOT - Stars Subscription Only
# Using pyTelegramBotAPI with sync MongoDB (pymongo)

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
import datetime
import random
import string
from pymongo import MongoClient

# ====================== DATABASE (SYNC) ======================
MONGO_URL = "mongodb://mongo:PLYxmxgNgAaBGpZsNtSfDdyOitMaQSfE@thomas.proxy.rlwy.net:42086"
DB_NAME = "sonik_bot"

mongo_client = MongoClient(MONGO_URL)
db = mongo_client[DB_NAME]

# Collections
users_col = db["users"]
star_orders_col = db["star_orders"]
stats_col = db["stats"]

# ====================== CONFIG ======================
BOT_TOKEN = '8991670803:AAEOu_4ZGyLFOAvtt-bjpxwPhEdNhj7pvhI'
MAIN_BOT_USERNAME = "shopify7bot"
ADMIN_ID = [1093032296, 7077116674]

STAR_PLANS = {
    "1h": {"name": "1 Hour", "hours": 1, "price": 30, "emoji": "⚡"},
    "12h": {"name": "12 Hours", "hours": 12, "price": 50, "emoji": "🔥"},
    "1d": {"name": "1 Day", "hours": 24, "price": 100, "emoji": "⭐"},
    "3d": {"name": "3 Days", "hours": 72, "price": 250, "emoji": "🌟"},
    "1w": {"name": "1 Week", "hours": 168, "price": 500, "emoji": "💎"},
}

# ====================== DATABASE FUNCTIONS ======================
def ensure_user(user_id):
    existing = users_col.find_one({"user_id": user_id})
    if not existing:
        users_col.insert_one({
            "user_id": user_id,
            "subscription_plan": None,
            "subscription_end": None,
            "subscription_hours": 0,
            "banned": False,
            "last_seen": datetime.datetime.utcnow(),
            "created_at": datetime.datetime.utcnow(),
            "plan": "Bronze"
        })

def is_banned_user(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("banned", False) if user else False

def get_user_subscription(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        ensure_user(user_id)
        user = users_col.find_one({"user_id": user_id})
    
    end = user.get("subscription_end")
    if end and datetime.datetime.utcnow() < end:
        remaining = (end - datetime.datetime.utcnow()).total_seconds() / 3600
        return {
            "plan": user.get("subscription_plan"),
            "end": end,
            "is_active": True,
            "remaining_hours": round(remaining, 2)
        }
    return {"plan": None, "end": None, "is_active": False, "remaining_hours": 0}

def set_user_subscription(user_id, plan, hours):
    expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=hours)
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"subscription_plan": plan, "subscription_end": expiry, "subscription_hours": hours, "plan": plan}},
        upsert=True
    )

def generate_order_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

def create_star_order(user_id, plan, hours, price_stars):
    order_id = generate_order_id()
    star_orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "plan": plan,
        "hours": hours,
        "price_stars": price_stars,
        "status": "pending",
        "created_at": datetime.datetime.utcnow()
    })
    return order_id

def get_star_order(order_id):
    return star_orders_col.find_one({"order_id": order_id})

def get_user_pending_order(user_id):
    return star_orders_col.find_one({"user_id": user_id, "status": "pending"})

def confirm_star_payment(order_id, telegram_payment_id, provider_payment_charge_id):
    order = get_star_order(order_id)
    if not order:
        return False
    star_orders_col.update_one(
        {"order_id": order_id},
        {"$set": {"status": "paid", "telegram_payment_id": telegram_payment_id, "paid_at": datetime.datetime.utcnow()}}
    )
    set_user_subscription(order["user_id"], order["plan"], order["hours"])
    
    stats_col.update_one(
        {"_id": "stars_earned"},
        {"$inc": {"total": order["price_stars"]}},
        upsert=True
    )
    return True

def init_db():
    try:
        users_col.create_index("user_id", unique=True)
        star_orders_col.create_index("order_id", unique=True)
        if stats_col.count_documents({"_id": "stars_earned"}) == 0:
            stats_col.insert_one({"_id": "stars_earned", "total": 0})
        print("✅ Database connected!")
    except Exception as e:
        print(f"⚠️ DB warning: {e}")

# ====================== SETUP ======================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# ====================== HANDLERS ======================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    ensure_user(uid)
    
    text = f"""⭐ <b>Sonik Payment Bot</b> ⭐
━━━━━━━━━━━━━━━━━
<b>Buy subscription with Telegram Stars</b>
━━━━━━━━━━━━━━━━━
Use /subscribe to see available plans
After payment, use @{MAIN_BOT_USERNAME} for checking

<b>Commands:</b>
/subscribe - Show plans
/myplan - Check your subscription"""
    
    bot.reply_to(message, text)

@bot.message_handler(commands=['subscribe'])
def subscribe(message):
    uid = message.from_user.id
    ensure_user(uid)
    
    if is_banned_user(uid):
        bot.reply_to(message, "❌ You are banned from using this bot.")
        return
    
    pending = get_user_pending_order(uid)
    if pending:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("❌ Cancel Pending Order", callback_data=f"cancel_order:{pending['order_id']}"))
        bot.reply_to(
            message,
            f"⚠️ <b>You have a pending order!</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"Order ID: <code>{pending['order_id']}</code>\n"
            f"Plan: {pending['plan']}\n"
            f"Price: {pending['price_stars']}⭐\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"Click cancel to remove it and try again.",
            reply_markup=keyboard
        )
        return
    
    text = f"""⭐ <b>Subscription Plans</b> ⭐
━━━━━━━━━━━━━━━━━
<b>Pay with Telegram Stars</b>
━━━━━━━━━━━━━━━━━"""
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for pid, plan in STAR_PLANS.items():
        buttons.append(InlineKeyboardButton(f"{plan['emoji']} {plan['name']} - {plan['price']}⭐", callback_data=f"plan:{pid}"))
    keyboard.add(*buttons)
    
    bot.reply_to(message, text, reply_markup=keyboard)

@bot.message_handler(commands=['myplan'])
def myplan(message):
    uid = message.from_user.id
    ensure_user(uid)
    
    if uid in ADMIN_ID:
        bot.reply_to(message, f"👑 <b>Admin</b>\nNo subscription needed")
        return
    
    sub = get_user_subscription(uid)
    
    if sub["is_active"]:
        remaining = sub["remaining_hours"]
        remaining_str = f"{int(remaining * 60)} minutes" if remaining < 1 else f"{remaining:.1f} hours"
        end_str = sub['end'].strftime('%Y-%m-%d %H:%M:%S') if sub['end'] else 'N/A'
        bot.reply_to(
            message,
            f"""✅ <b>Your Subscription</b> ✅
━━━━━━━━━━━━━━━━━
<b>Status:</b> Active
<b>Plan:</b> {sub['plan']}
<b>Remaining:</b> {remaining_str}
<b>Expires:</b> {end_str}
━━━━━━━━━━━━━━━━━
Use @{MAIN_BOT_USERNAME} to start checking"""
        )
    else:
        bot.reply_to(message, "❌ <b>No Active Subscription</b>\nUse /subscribe to buy a plan")

# ====================== CALLBACKS ======================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.from_user.id
    data = call.data
    
    if data.startswith("cancel_order:"):
        order_id = data.split(":")[1]
        order = get_star_order(order_id)
        
        if not order:
            bot.edit_message_text("Order not found!", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        
        if order["user_id"] != uid:
            bot.answer_callback_query(call.id, "Not your order!", show_alert=True)
            return
        
        if order["status"] != "pending":
            bot.answer_callback_query(call.id, "Order already processed!", show_alert=True)
            return
        
        star_orders_col.update_one({"order_id": order_id}, {"$set": {"status": "cancelled"}})
        bot.answer_callback_query(call.id, "Order cancelled! You can now subscribe again.", show_alert=True)
        
        text = f"""⭐ <b>Subscription Plans</b> ⭐
━━━━━━━━━━━━━━━━━
<b>Pay with Telegram Stars</b>
━━━━━━━━━━━━━━━━━"""
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        buttons = []
        for pid, plan in STAR_PLANS.items():
            buttons.append(InlineKeyboardButton(f"{plan['emoji']} {plan['name']} - {plan['price']}⭐", callback_data=f"plan:{pid}"))
        keyboard.add(*buttons)
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=keyboard)
        return
    
    if data.startswith("plan:"):
        plan_id = data.split(":")[1]
        plan = STAR_PLANS[plan_id]
        
        if is_banned_user(uid):
            bot.answer_callback_query(call.id, "You are banned!", show_alert=True)
            return
        
        pending = get_user_pending_order(uid)
        if pending:
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("❌ Cancel Pending Order", callback_data=f"cancel_order:{pending['order_id']}"))
            bot.edit_message_text(
                f"⚠️ <b>You have a pending order!</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"Order ID: <code>{pending['order_id']}</code>\n"
                f"Plan: {pending['plan']}\n"
                f"Price: {pending['price_stars']}⭐\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"Click cancel to remove it and try again.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard
            )
            bot.answer_callback_query(call.id)
            return
        
        order_id = create_star_order(uid, plan_id, plan["hours"], plan["price"])
        
        bot.answer_callback_query(call.id, f"Opening payment for {plan['name']}...")
        
        try:
            bot.send_invoice(
                chat_id=uid,
                title=f"Sonik - {plan['name']}",
                description=f"Subscription: {plan['name']} for {plan['hours']} hours",
                invoice_payload=order_id,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=plan['name'], amount=plan['price'])],
                start_parameter=str(order_id),
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                send_phone_number_to_provider=False,
                send_email_to_provider=False,
                is_flexible=False
            )
        except Exception as e:
            print(f"Invoice error for {uid}: {e}")
            bot.answer_callback_query(call.id, f"Payment error: {str(e)[:50]}", show_alert=True)

# ====================== PRE-CHECKOUT ======================
@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)

# ====================== SUCCESSFUL PAYMENT ======================
@bot.message_handler(content_types=['successful_payment'])
def successful_payment(message):
    payment = message.successful_payment
    order_id = payment.invoice_payload
    telegram_payment_id = payment.telegram_payment_charge_id
    provider_payment_id = payment.provider_payment_charge_id
    uid = message.from_user.id
    
    result = confirm_star_payment(order_id, telegram_payment_id, provider_payment_id)
    
    if result:
        order = get_star_order(order_id)
        if order:
            plan = STAR_PLANS[order['plan']]
            bot.reply_to(
                message,
                f"""✅ <b>Payment Successful!</b> ✅
━━━━━━━━━━━━━━━━━
⭐ <b>Plan:</b> {plan['emoji']} {plan['name']}
⏱ <b>Duration:</b> {plan['hours']} hours
━━━━━━━━━━━━━━━━━
<b>Now you can use the main bot:</b>
👉 @{MAIN_BOT_USERNAME}
Type /start to begin"""
            )
            
            for admin in ADMIN_ID:
                try:
                    bot.send_message(admin, f"💰 User {order['user_id']} bought {plan['name']} for {plan['price']}⭐")
                except:
                    pass

# ====================== MAIN ======================
if __name__ == "__main__":
    init_db()
    print("Starting Payment Bot...")
    print("✅ Payment Bot (@Stars838bot) started!")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)