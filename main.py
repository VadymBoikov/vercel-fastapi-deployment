import os
import logging
from fastapi import FastAPI, Request, Response
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from supabase import create_client
from telegram import Update
from bot import application
from contextlib import asynccontextmanager
import stripe
import dotenv
dotenv.load_dotenv('.env')

# Ініціалізація FastAPI додатку
app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ініціалізація Stripe API
stripe.api_key = os.getenv('STRIPE_API_KEY')


# Ініціалізація Supabase клієнта
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')
supabase = create_client(url, key)

endpoint_url = os.getenv('WEBHOOK_URL')
stripe_secret = os.getenv('STRIPE_SECRET')

# Налаштування шаблонів Jinja2
templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Функція управління життєвим циклом додатку FastAPI.
    Налаштовує веб-хук для Telegram бота.
    """
    webhook_info = await application.bot.getWebhookInfo()
    webhook_url = os.path.join(endpoint_url, "telegram-webhook")
    
    if webhook_info.url != webhook_url:
        await application.bot.setWebhook(webhook_url, max_connections=30)
    async with application:
        await application.start()
        yield
        await application.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/success_payment", response_class=HTMLResponse)
async def success_payment(request: Request):
    """
    Обробник для успішної сторінки оплати.
    """
    return templates.TemplateResponse("success_payment.html", {"request": request})
    
@app.get("/cancel_payment", response_class=HTMLResponse)
async def cancel_payment(request: Request):
    """
    Обробник для сторінки скасування оплати.
    """
    return templates.TemplateResponse("cancel_payment.html", {"request": request})

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """
    Обробник веб-хуків Stripe для обробки подій оплати.
    """
    payload = await request.body()
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, stripe_secret)
        logger.info('Webhook event received: %s', event['type'])
    except ValueError as e:
        logger.error('Invalid payload: %s', str(e))
        return Response(content='Invalid payload', status_code=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error('Invalid signature: %s', str(e))
        return Response(content='Invalid signature', status_code=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_session(session)

    return Response(content='', status_code=200)

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """
    Обробник веб-хуків Telegram для обробки оновлень.
    """
    update = Update.de_json(await request.json(), application.bot)
    logger.info(f"Received update: {update}")
    await application.process_update(update)
    return Response(content="OK", status_code=200)

html = f"""
<!DOCTYPE html>
<html>
    <head>
        <title>FastAPI on Vercel</title>
        <link rel="icon" href="/static/favicon.ico" type="image/x-icon" />
    </head>
    <body>
        <div class="bg-gray-200 p-4 rounded-lg shadow-lg">
            <h1>Hello from FastAPI</h1>
            <ul>
                <li><a href="/docs">/docs</a></li>
                <li><a href="/redoc">/redoc</a></li>
            </ul>
            <p>Powered by <a href="https://vercel.com" target="_blank">Vercel</a></p>
        </div>
    </body>
</html>
"""

@app.get("/")
async def root():
    return HTMLResponse(html)

def update_supabase(payment_session, customer_id: str, customer_username: str, discount_percent: str, email: str):
    """
    Оновлює базу даних Supabase інформацією про оплату.
    """
    payment_id = payment_session['id']
    payment_status = payment_session['payment_status']
    payment_amount = payment_session['amount_total']
    payment_currency = payment_session['currency']
    data = {
        "customer_telegram_id": customer_id,
        "customer_telegram_username": customer_username,
        "payment_id": payment_id,
        "payment_status": payment_status,
        "payment_amount": payment_amount,
        "payment_currency": payment_currency,
        "discount_percent": discount_percent,
        "email": email,
    }
    try:
        supabase.table("payments").upsert(data).execute()
        logger.info('Payment data updated in Supabase: %s', data)
    except Exception as e:
        logger.error('Error updating Supabase: %s', str(e))

def handle_checkout_session(session):
    """
    Обробляє завершені сесії оплати Stripe.
    """
    customer_telegram_id = session['metadata'].get('telegram_user_id')
    customer_telegram_username = session['metadata'].get('telegram_username')
    discount_percent = None
    if session['total_details'] and session['total_details']['amount_discount']:
        discount_percent = int((session['total_details']['amount_discount'] / session['amount_subtotal']) * 100)
    email = session.get('customer_email')
    if not email and 'customer_details' in session and 'email' in session['customer_details']:
        email = session['customer_details']['email']
    update_supabase(session, customer_telegram_id, customer_telegram_username, discount_percent, email)

if __name__ == '__main__':
    import uvicorn
    # Запуск FastAPI додатку з uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))
