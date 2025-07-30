# telegram_bot.py (Final Corrected Version)

import os
import json
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# 사용자별 데이터를 저장할 딕셔너리
user_data = {}

# --- [새로운 기능] Markdown V2 특수문자 이스케이프 함수 ---
def escape_markdown(text: str) -> str:
    """Telegram Markdown V2의 모든 특수문자를 이스케이프합니다."""
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)
# ---------------------------------------------------------

# --- GPT-4 분석 함수 (기존과 동일) ---
def get_gpt4_recommendation(history):
    prompt = f"Baccarat game history: {history}. 'P' is Player win, 'B' is Banker win, 'T' is Tie. Analyze the pattern and recommend the next bet. Answer with only 'Player' or 'Banker'."
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

# --- 화면(메시지) 구성 함수 (이스케이프 기능 적용) ---
def build_message_text(user_id):
    """현재 상태를 기반으로 텔레그램 메시지 전체 내용을 생성합니다."""
    data = user_data.get(user_id, {})
    player_wins = data.get('player_wins', 0)
    banker_wins = data.get('banker_wins', 0)
    history = data.get('history', [])
    recommendation = data.get('recommendation', None)

    # Big Road 기록판 생성 (60열)
    grid = [['▪️'] * 60 for _ in range(6)]
    if history:
        col, row, last_winner_pos = -1, 0, None
        last_pb_index = -1
        # 마지막 P/B 위치를 찾기 위해 history 인덱스 추적
        for i, winner in enumerate(history):
            if winner in ['P', 'B']:
                last_pb_index = i
        
        for i, winner in enumerate(history):
            if winner == 'T':
                if last_winner_pos:
                    r, c = last_winner_pos
                    if grid[r][c] == '🔴': grid[r][c] = '㊙️'
                    elif grid[r][c] == '🔵': grid[r][c] = '㊗️'
                continue

            # 승자 변경 로직 수정
            prev_winner = history[last_pb_index] if last_pb_index != -1 and i > 0 else None
            
            if winner != prev_winner or i == 0 or history[i-1] == 'T':
                 # 첫번째이거나, 이전 승자가 타이였거나, 이전 P/B와 다를 때
                col += 1
                row = 0
            else:
                row += 1
            
            if row >= 6:
                col += 1
                row = 5

            if col < 60 and row < 6:
                grid[row][col] = '🔵' if winner == 'P' else '🔴'
                last_winner_pos = {'row': row, 'col': col}
                last_pb_index = i

    big_road_text = "\n".join(["".join(r) for r in grid])

    # AI 추천 결과 텍스트
    rec_text = ""
    if recommendation:
        if recommendation == "Banker":
            rec_text = f"\n\n👇 *AI 추천* 👇\n🔴 *{escape_markdown('뱅커에 베팅하세요.')}*"
        else: # Player
            rec_text = f"\n\n👇 *AI 추천* 👇\n🔵 *{escape_markdown('플레이어에 베팅하세요.')}*"

    # [수정] 일반 텍스트 부분에 escape_markdown 함수 적용
    title = escape_markdown("ZENTRA AI 분석")
    subtitle = escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title = escape_markdown("플레이어")
    banker_title = escape_markdown("뱅커")
    history_title = escape_markdown("전체 기록 (Big Road)")
    
    return f"""*{title}*
{subtitle}

*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*
\-\-\-
*{history_title}*
`{big_road_text}`{rec_text}
"""

def build_keyboard():
    """텔레그램 인라인 키보드를 생성합니다."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔵 플레이어(Player) 승리", callback_data='P'), InlineKeyboardButton(f"🔴 뱅커(Banker) 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ])

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    await update.message.reply_text(
        build_message_text(user_id),
        reply_markup=build_keyboard(),
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    action = query.data
    data = user_data[user_id]

    if action in ['P', 'B', 'T']:
        if action == 'P': data['player_wins'] += 1
        elif action == 'B': data['banker_wins'] += 1
        data['history'].append(action)
        data['recommendation'] = None
    elif action == 'reset':
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    elif action == 'analyze':
        if not data['history']:
            await context.bot.send_message(chat_id=user_id, text=escape_markdown("분석할 기록이 없습니다. 먼저 결과를 기록해주세요."))
            return
        
        await context.bot.send_message(chat_id=user_id, text=escape_markdown("GPT-4가 분석 중입니다..."))
        history_str = ", ".join(data['history'])
        recommendation = get_gpt4_recommendation(history_str)
        data['recommendation'] = recommendation

    try:
        await query.edit_message_text(
            text=build_message_text(user_id),
            reply_markup=build_keyboard(),
            parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as e:
        print(f"메시지 수정 오류: {e}")

# --- 봇 실행 메인 함수 (기존과 동일) ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    main()
