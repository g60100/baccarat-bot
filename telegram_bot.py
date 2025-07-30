# telegram_bot.py (New Version)

import os
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# 사용자별 데이터를 저장할 딕셔너리
# 이제 승리 횟수, 기록, 추천 결과를 모두 관리합니다.
user_data = {}

# --- GPT-4 분석 함수 (기존과 동일) ---
def get_gpt4_recommendation(history):
    # ... (이전과 동일한 GPT-4 호출 로직)
    prompt = f"Baccarat game history: {history}. 'P' is Player win, 'B' is Banker win. Analyze the pattern and recommend the next bet. Answer with only 'Player' or 'Banker'."
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert Baccarat pattern analyst."},
                {"role": "user", "content": prompt}
            ]
        )
        recommendation = completion.choices[0].message.content
        return "Banker" if "Banker" in recommendation else "Player"
    except Exception as e:
        print(f"GPT-4 API 호출 오류: {e}")
        return "Banker"

# --- 화면(메시지) 구성 함수 ---
def build_message_text(user_id):
    """현재 상태를 기반으로 텔레그램 메시지 전체 내용을 생성합니다."""
    data = user_data.get(user_id, {})
    player_wins = data.get('player_wins', 0)
    banker_wins = data.get('banker_wins', 0)
    history = data.get('history', [])
    recommendation = data.get('recommendation', None)

    # Big Road 기록판 생성 (최대 6행 12열 예시)
    grid = [['⚪️'] * 12 for _ in range(6)]
    if history:
        col, row, last_winner = -1, 0, None
        for winner in history:
            if winner == 'T': continue # 타이는 Big Road에 직접 표시하지 않음
            if winner != last_winner:
                col += 1
                row = 0
            else:
                row += 1
            if col < 12 and row < 6:
                grid[row][col] = '🔵' if winner == 'P' else '🔴'
            last_winner = winner
    
    big_road_text = "\n".join(["".join(row) for row in grid])

    # 추천 결과 텍스트
    rec_text = ""
    if recommendation:
        rec_text = f"\n\n👇 *AI 추천* 👇\n*{recommendation}에 베팅하세요*"

    # 전체 메시지 조합
    return f"""*ZENTRA AI 분석*
승리한 쪽의 버튼을 눌러 기록을 누적하세요.

*플레이어: {player_wins}* |  *뱅커: {banker_wins}*
---
*전체 기록 (Big Road)*
`{big_road_text}`{rec_text}
"""

def build_keyboard():
    """텔레그램 인라인 키보드를 생성합니다."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔵 플레이어(Player) 승리 입력", callback_data='P'), InlineKeyboardButton(f"🔴 뱅커(Banker) 승리 입력", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ])

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    """/start 명령어: 봇을 초기화하고 첫 화면을 보냅니다."""
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    await update.message.reply_text(
        build_message_text(user_id),
        reply_markup=build_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def button_callback(update: Update, context: CallbackContext) -> None:
    """모든 버튼 클릭을 처리합니다."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # 사용자 데이터 초기화
    if user_id not in user_data:
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    action = query.data
    data = user_data[user_id]

    if action == 'P':
        data['player_wins'] += 1
        data['history'].append('P')
        data['recommendation'] = None # 추천 결과 초기화
    elif action == 'B':
        data['banker_wins'] += 1
        data['history'].append('B')
        data['recommendation'] = None # 추천 결과 초기화
    elif action == 'T':
        data['history'].append('T')
        data['recommendation'] = None # 추천 결과 초기화
    elif action == 'reset':
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    elif action == 'analyze':
        if not data['history']:
            await context.bot.send_message(chat_id=user_id, text="분석할 기록이 없습니다. 먼저 결과를 기록해주세요.")
            return
        
        await context.bot.send_message(chat_id=user_id, text="GPT-4가 분석 중입니다...")
        history_str = ", ".join(data['history'])
        recommendation = get_gpt4_recommendation(history_str)
        data['recommendation'] = recommendation

    # 메시지 수정으로 화면 업데이트
    await query.edit_message_text(
        text=build_message_text(user_id),
        reply_markup=build_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling()

if __name__ == "__main__":
    main()
