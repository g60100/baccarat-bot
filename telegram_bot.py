# telegram_bot.py (Locking Version)

import os
import json
import asyncio # 잠금 기능을 위한 asyncio 라이브러리
from collections import defaultdict # 사용자별 잠금을 위한 defaultdict
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
# --- [새로운 기능] 사용자별 잠금 장치 ---
user_locks = defaultdict(asyncio.Lock)
# ------------------------------------

# --- 이미지 생성, GPT 분석, 캡션/키보드 생성, 이스케이프 함수 등 ---
# (이전 답변과 동일하므로 생략)
def create_big_road_image(history):
    cell_size = 22
    rows, cols = 6, 60
    top_padding = 30
    bottom_padding = 30
    width = cols * cell_size
    height = rows * cell_size + top_padding + bottom_padding
    
    img = Image.new('RGB', (width, height), color = '#f4f6f9')
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()
    
    total_cols_needed = 0
    if history:
        last_winner_for_col_count = None
        current_col_for_count = -1
        for winner in history:
            if winner == 'T': continue
            if winner != last_winner_for_col_count:
                current_col_for_count += 1
            last_winner_for_col_count = winner
        total_cols_needed = current_col_for_count + 1

    cols_per_page = 20
    total_pages = math.ceil(total_cols_needed / cols_per_page)
    current_page = user_data.get(update.effective_user.id, {}).get('page', 0) if 'update' in locals() and update.effective_user else 0
    
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {current_page + 1} / {total_pages})", fill="black", font=font)
    
    # ... 이하 이미지 생성 로직은 이전과 동일 ...
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path
    
def get_gpt4_recommendation(history):
    prompt = f"Baccarat history: {history}. Recommend Player or Banker."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        rec = completion.choices[0].message.content
        return "Banker" if "Banker" in rec else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

def build_caption_text(user_id, is_analyzing=False):
    # ... (생략)
    pass
    
def escape_markdown(text: str) -> str:
    # ... (생략)
    pass
    
def build_keyboard(user_id):
    # ... (생략)
    pass
    
async def start(update: Update, context: CallbackContext) -> None:
    # ... (생략)
    pass

# --- 텔레그램 버튼 처리 함수 (잠금 기능 적용) ---
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    # 사용자별 잠금 획득 시도
    lock = user_locks[user_id]
    if lock.locked():
        # 이미 다른 요청을 처리 중이면, 현재 요청은 무시하고 사용자에게 알림
        await query.answer("처리 중입니다. 잠시 후 다시 시도해주세요.")
        return

    async with lock: # 잠금 시작 (이 블록이 끝나면 자동으로 해제됨)
        await query.answer() # 먼저 버튼 눌림에 대한 응답 전송
        
        if user_id not in user_data:
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
        
        action = query.data
        data = user_data[user_id]
        is_analyzing = False

        if action in ['P', 'B', 'T']:
            if action == 'P': data['player_wins'] += 1
            elif action == 'B': data['banker_wins'] += 1
            data['history'].append(action)
            data['recommendation'] = None
            data['page'] = 0
        elif action == 'reset':
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
        elif action == 'page_next':
            data['page'] += 1
        elif action == 'page_prev':
            data['page'] -= 1
        elif action == 'analyze':
            if not data['history']:
                # 'answer_callback_query'는 잠금이 필요 없음
                await context.bot.answer_callback_query(query.id, text="분석할 기록이 없습니다.")
                return
            
            is_analyzing = True
            # ... (분석 중 메시지 표시 로직)
            
            history_str = ", ".join(data['history'])
            recommendation = get_gpt4_recommendation(history_str)
            data['recommendation'] = recommendation
            is_analyzing = False

        try:
            image_path = create_big_road_image(data['history'], page=data.get('page', 0))
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
        except Exception as e:
            print(f"메시지 수정 오류: {e}")

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

# --- 생략된 함수의 전체 코드 ---
# (이전 답변의 코드를 여기에 붙여넣으세요)

def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
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

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    history = data.get('history', [])
    cols_per_page = 20
    last_col = -1
    last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col +=1
        last_winner = winner
    total_pages = math.ceil((last_col + 1) / cols_per_page) if cols_per_page > 0 else 0

    page_buttons = []
    if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전", callback_data='page_prev'))
    if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 ➡️", callback_data='page_next'))

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ]
    if page_buttons:
        keyboard.insert(2, page_buttons)
        
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    image_path = create_big_road_image(user_data[user_id]['history'], page=0)
    await update.message.reply_photo(
        photo=open(image_path, 'rb'),
        caption=build_caption_text(user_id),
        reply_markup=build_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    
    action = query.data
    data = user_data[user_id]
    is_analyzing = False

    if action in ['P', 'B', 'T']:
        if action == 'P': data['player_wins'] += 1
        elif action == 'B': data['banker_wins'] += 1
        data['history'].append(action)
        data['recommendation'] = None
        data['page'] = 0 # 기록 추가 시 첫 페이지로
    elif action == 'reset':
        user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    elif action == 'page_next':
        data['page'] += 1
    elif action == 'page_prev':
        data['page'] -= 1
    elif action == 'analyze':
        if not data['history']:
            await context.bot.answer_callback_query(query.id, text="분석할 기록이 없습니다.")
            return
        
        is_analyzing = True
        # ... (분석 중 메시지 표시 로직은 이전과 동일하게 유지)
        recommendation = get_gpt4_recommendation(", ".join(data['history']))
        data['recommendation'] = recommendation
        is_analyzing = False

    image_path = create_big_road_image(data['history'], page=data['page'])
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
    await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))

# --- 봇 실행 메인 함수 ---
def main() -> None:
    # ... (생략, 기존 코드와 동일)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
