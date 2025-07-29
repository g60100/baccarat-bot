# telegram_bot.py 수정

import os # os 라이브러리 추가
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# --- 설정 ---
# 코드에서 직접 키를 읽는 대신, 서버의 환경 변수에서 키를 읽어옴
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# ... (이후 코드는 동일) ...

# 사용자별 게임 기록을 저장할 딕셔너리
user_histories = {}

# --- GPT-4 분석 함수 (기존과 동일) ---
def get_gpt4_recommendation(history):
    prompt = f"""
    당신은 세계 최고의 바카라 패턴 분석가입니다. 과거 게임 기록의 순서와 흐름을 보고, 가장 확률 높은 다음 베팅을 추천해야 합니다.
    플레이어(Player) 또는 뱅커(Banker) 중 하나로만 간결하게 답변해주세요.
    기록: {history}
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 데이터와 패턴에만 근거하여 분석하는 최고의 바카라 전략가입니다."},
                {"role": "user", "content": prompt}
            ]
        )
        recommendation = completion.choices[0].message.content
        return "Banker" if "Banker" in recommendation else "Player"
    except Exception as e:
        print(f"GPT-4 API 호출 오류: {e}")
        return "Banker"

# --- 텔레그램 명령어 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    """/start 명령어 처리: 사용자에게 시작 메시지와 버튼을 보냅니다."""
    user_id = update.message.from_user.id
    user_histories[user_id] = []  # 사용자 기록 초기화

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 실행", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "바카라 분석을 시작합니다.\n"
        "아래 버튼을 눌러 게임 결과를 기록하고 '분석 실행'을 누르세요.",
        reply_markup=reply_markup
    )

async def button(update: Update, context: CallbackContext) -> None:
    """버튼 클릭 처리"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # 사용자 기록 초기화
    if user_id not in user_histories:
        user_histories[user_id] = []

    # 버튼 데이터에 따라 기능 수행
    if query.data in ['P', 'B', 'T']:
        user_histories[user_id].append(query.data)
        history_str = ", ".join(user_histories[user_id])
        await query.edit_message_text(text=f"기록됨: {query.data}\n현재 기록: {history_str if history_str else '없음'}", reply_markup=query.message.reply_markup)
    
    elif query.data == 'reset':
        user_histories[user_id] = []
        await query.edit_message_text(text="기록이 초기화되었습니다. 다시 시작하세요.", reply_markup=query.message.reply_markup)

    elif query.data == 'analyze':
        history = user_histories.get(user_id, [])
        if not history:
            await context.bot.send_message(chat_id=user_id, text="분석할 기록이 없습니다. 먼저 결과를 기록해주세요.")
            return

        await context.bot.send_message(chat_id=user_id, text="GPT-4가 분석 중입니다...")
        history_str = ", ".join(history)
        recommendation = get_gpt4_recommendation(history_str)
        await context.bot.send_message(chat_id=user_id, text=f"🤖 AI 추천: **{recommendation}**에 베팅하세요.")

# --- 봇 실행 메인 함수 ---
def main() -> None:
    """봇을 시작합니다."""
    # 봇이 시작되기 전에, 쌓여있는 메시지를 모두 지우도록 설정 추가
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))

    # 봇 실행 (메시지를 계속 확인)
    print("텔레그램 봇이 시작되었습니다...")
    # drop_pending_updates=True 옵션을 추가하여 오래된 메시지를 무시
    application.run_polling(drop_pending_updates=True)

async def post_init(application: Application) -> None:
    """봇 초기화 시 오래된 업데이트를 정리하는 함수"""
    await application.bot.delete_webhook(drop_pending_updates=True)

if __name__ == "__main__":
    main()
