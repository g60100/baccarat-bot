# telegram_bot.py (Final Version 2)

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

# --- 화면(메시지) 구성 함수 (수정됨) ---
def build_message_text(user_id, is_analyzing=False):
    """현재 상태를 기반으로 텔레그램 메시지 전체 내용을 생성합니다."""
    data = user_data.get(user_id, {})
    player_wins = data.get('player_wins', 0)
    banker_wins = data.get('banker_wins', 0)
    history = data.get('history', [])
    recommendation = data.get('recommendation', None)

    # Big Road 기록판 생성 (60열)
    grid = [['▪️'] * 60 for _ in range(6)]
    if history:
        col, row = -1, 0
        last_winner = None
        last_bead_pos = None

        for winner in history:
            if winner == 'T':
                if last_bead_pos:
                    r, c = last_bead_pos
                    if grid[r][c] == '🔴': grid[r][c] = '㊙️'
                    elif grid[r][c] == '🔵': grid[r][c] = '㊗️'
                continue

            if winner != last_winner:
                col += 1
                row = 0
            else:
                row += 1
            
            if row >= 6:
                col += 1
                row = 5

            if col < 60:
                grid[row][col] = '🔵' if winner == 'P' else '🔴'
                last_bead_pos = (row, col)
            
            last_winner = winner

    big_road_text = "\n".join(["".join(r) for r in grid])

    # AI 추천 결과 텍스트 (수정됨)
    rec_text = "\n\n👇 *AI 추천* 👇\n"
    if is_analyzing:
        rec_text += escape_markdown("GPT-4가 분석 중입니다...")
    elif recommendation:
        if recommendation == "Banker":
            rec_text += f"🔴 *{escape_markdown('뱅커에 베팅하세요.')}*"
        else: # Player
            rec_text += f"🔵 *{escape_markdown('플레이어에 베팅하세요.')}*"
    else:
        rec_text = "" # 분석 전에는 AI 추천 섹션 숨김

    # 일반 텍스트 부분 이스케이프 처리
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
            await context.bot.answer_callback_query(query.id, text="분석할 기록이 없습니다. 먼저 결과를 기록해주세요.")
            return
        
        # 분석 중 메시지로 화면 업데이트
        await query.edit_message_text(# telegram_bot.py (Image Generation Version)

import os
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont # 이미지 생성을 위한 Pillow 라이브러리

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}

# --- [새로운 기능] Big Road 이미지를 생성하는 함수 ---
def create_big_road_image(history):
    cell_size = 22
    rows, cols = 6, 60
    width = cols * cell_size
    height = rows * cell_size
    
    # 이미지 생성 및 그리드 라인 그리기
    img = Image.new('RGB', (width, height), color = '#f4f6f9')
    draw = ImageDraw.Draw(img)

    for r in range(rows + 1):
        draw.line([(0, r * cell_size), (width, r * cell_size)], fill='lightgray')
    for c in range(cols + 1):
        draw.line([(c * cell_size, 0), (c * cell_size, height)], fill='lightgray')

    # 기록을 이미지에 그리기
    if history:
        col, row = -1, 0
        last_winner = None
        last_bead_pos = None

        for winner in history:
            if winner == 'T':
                if last_bead_pos:
                    r, c = last_bead_pos
                    draw.line([(c * cell_size + 5, r * cell_size + 5), ((c+1) * cell_size - 5, (r+1) * cell_size - 5)], fill='#2ecc71', width=2)
                continue

            if winner != last_winner:
                col += 1
                row = 0
            else:
                row += 1
            
            if row >= rows:
                col += 1
                row = rows - 1

            if col < cols:
                color = "#3498db" if winner == 'P' else "#e74c3c"
                draw.ellipse([(col * cell_size + 3, row * cell_size + 3), ((col+1) * cell_size - 3, (r+1) * cell_size - 3)], outline=color, width=3)
                last_bead_pos = (row, col)
            
            last_winner = winner
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path

# --- GPT-4 분석 함수 (기존과 동일) ---
def get_gpt4_recommendation(history):
    prompt = f"Baccarat history: {history}. Recommend Player or Banker."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        rec = completion.choices[0].message.content
        return "Banker" if "Banker" in rec else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 화면(캡션) 구성 함수 ---
def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins = data.get('player_wins', 0)
    banker_wins = data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)

    rec_text = ""
    if is_analyzing:
        rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('GPT-4가 분석 중입니다...')}_"
    elif recommendation:
        rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅하세요.')}*"
    
    title = escape_markdown("ZENTRA AI 분석")
    subtitle = escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title = escape_markdown("플레이어")
    banker_title = escape_markdown("뱅커")
    
    return f"*{title}*\n{subtitle}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}"

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ])

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    image_path = create_big_road_image([])
    await update.message.reply_photo(
        photo=open(image_path, 'rb'),
        caption=build_caption_text(user_id),
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
    is_analyzing = False

    if action in ['P', 'B', 'T']:
        if action == 'P': data['player_wins'] += 1
        elif action == 'B': data['banker_wins'] += 1
        data['history'].append(action)
        data['recommendation'] = None
    elif action == 'reset':
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    elif action == 'analyze':
        if not data['history']:
            await context.bot.answer_callback_query(query.id, text="분석할 기록이 없습니다.")
            return
        
        is_analyzing = True
        image_path = create_big_road_image(data['history'])
        media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=True), parse_mode=ParseMode.MARKDOWN_V2)
        await query.edit_message_media(media=media, reply_markup=build_keyboard())

        history_str = ", ".join(data['history'])
        recommendation = get_gpt4_recommendation(history_str)
        data['recommendation'] = recommendation
        is_analyzing = False

    image_path = create_big_road_image(data['history'])
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
    await query.edit_message_media(media=media, reply_markup=build_keyboard())

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    main()
