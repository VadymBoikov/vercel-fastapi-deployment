import os
from datetime import datetime, timedelta, timezone
import stripe
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from supabase import create_client
import logging
from warnings import filterwarnings
from telegram.warnings import PTBUserWarning
import dotenv
dotenv.load_dotenv('.env')


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

NAME, BUTTON = range(2)

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
stripe.api_key = os.getenv("STRIPE_API_KEY")

price_15_euro = 'price_1PXkvYKdmVvRSiVymFPRUye5'
price_30_euro = 'price_1PXkvYKdmVvRSiVymFPRUye5'

url = os.getenv('WEBHOOK_URL')
success_url = os.path.join(url, 'success_payment')
cancel_url = os.path.join(url,'cancel_payment')
# cancel_url = 'https://stripe-telegram-bot-d351cbcba525.herokuapp.com/cancel_payment'

async def start_to_name(update: Update, context: CallbackContext):
    logger.info(f"Received /start command from user: {update.message.from_user.id}")
    response = supabase.table("profiles").upsert({"tg_user_id": update.message.from_user.id}).execute()
    await update.message.reply_text('Hello! What is your name?')
    return NAME

async def name_to_payment(update: Update, context: CallbackContext):
    logger.info(f"User {update.message.from_user.id} provided name: {update.message.text}")
    response = supabase.table("profiles").upsert({"tg_user_id": update.message.from_user.id, 'user_name': update.message.text}).execute()
    keyboard = [
        [InlineKeyboardButton("Підписка на 15 євро", callback_data='subscribe_15')],
        [InlineKeyboardButton("Підписка на 30 євро", callback_data='subscribe_30')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Оберіть план підписки:', reply_markup=reply_markup)
    return BUTTON

async def button(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    logger.info(f"User {query.from_user.id} selected subscription plan: {query.data}")
    price_id = price_15_euro if query.data == 'subscribe_15' else price_30_euro
    expires_at = int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
    telegram_user_id = query.from_user.id
    telegram_username = query.from_user.username
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{'price': price_id, 'quantity': 1}],
        mode='subscription',
        success_url=success_url,
        cancel_url=cancel_url,
        expires_at=expires_at,
        currency="eur",
        allow_promotion_codes=True,
        metadata={'telegram_user_id': str(telegram_user_id), 'telegram_username': telegram_username}
    )
    context.user_data['checkout_session_id'] = session.id
    await query.edit_message_text(text=f"Перейдіть за посиланням для завершення оплати: {session.url}")

async def cancel(update: Update, context) -> int:
    await update.message.reply_text("Okay, you can come back later :)")
    return ConversationHandler.END

def main():
    application = (Application.builder().updater(None).token(os.getenv("BOT_TOKEN"))
                   #.read_timeout(7).get_updates_read_timeout(42)
                   .build())
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_to_name)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_to_payment)],
            BUTTON: [CallbackQueryHandler(button)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    # application.updater = None
    return application

application = main()
