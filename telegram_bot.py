# telegram_bot.py (Pagination Version)

import os
import json
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont
import math

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}

# --- [새로운 기능] Big Road 이미지를 페이지별로 생성하는 함수 ---
def create_big_road_image(history, page=0):
    cell_size = 22
    rows = 6
    cols_per_page = 20 # 한 페이지에 보여줄 열의 수
    
    # 전체 논리적 그리드 생성
    full_grid_cols = 60
    full_grid = [[''] * full_grid_cols for _ in range(rows)]
    last_positions = {} # 타이(Tie) 처리를 위해 마지막 구슬 위치 저장

    if history:
        col, row = -1, 0
        last_winner = None
        for i, winner in enumerate(history):
            if winner == 'T':
                if last_winner and last_winner in last_positions:
                    r, c = last_positions[last_winner]
                    if full_grid[r][c]:
                        full_grid[r][c] += 'T' # 타이 정보 추가
                continue

            if winner != last_winner:
                col += 1
                row = 0
            else:
                row += 1
            
            if row >= rows:
                col += 1
                row = rows - 1

            if col < full_grid_cols:
                full_grid[row][col] = winner
                last_positions[winner] = (row, col)
            
            last_winner = winner

    # 현재 페이지에 해당하는 부분만 잘라내기
    start_col = page * cols_per_page
    end_col = start_col + cols_per_page
    page_grid = [row[start_col:end_col] for row in full_grid]

    # 이미지 생성
    top_padding = 30
    width = cols_per_page * cell_size
    height = rows * cell_size + top_padding
    
    img = Image.new('RGB', (width, height), color = '#f4f6f9')
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()
    
    total_cols = max(col + 1, 1) if 'col' in locals() else 1
    total_pages = math.ceil(total_cols / cols_per_page)
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {page + 1} / {total_pages})", fill="black", font=font)
    
    # 그리드 그리기
    for r in range(rows):
        for c in range(cols_per_page):
            x1, y1 = c * cell_size, r * cell_size + top_padding
            x2, y2 = (c+1) * cell_size, (r+1) * cell_size + top_padding
            draw.rectangle([(x1, y1), (x2, y2)], outline='lightgray')
            
            cell_data = page_grid[r][c]
            if cell_data:
                winner_char = cell_data[0]
                color = "#3498db" if winner_char == 'P' else "#e74c3c"
                draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], outline=color, width=3)
                if 'T' in cell_data:
                    draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill='#2ecc71', width=2)
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path

# --- GPT-4 분석 함수 (기존과 동일) ---
def get_gpt4_recommendation(history):
    # ... (생략, 기존 코드와 동일)
    prompt = f"Baccarat history: {history}. Recommend Player or Banker."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        rec = completion.choices[0].message.content
        return "Banker" if "Banker" in rec else "Player"
    except Exception as e: return "Banker"

# --- 캡션 및 키보드 생성 함수 (페이지 넘김 버튼 추가) ---
def build_caption_text(user_id, is_analyzing=False):
    # ... (생략, 기존 코드와 동일)
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    rec_text = ""
    if is_analyzing: rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('GPT-4가 분석 중입니다...')}_"
    elif recommendation: rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅하세요.')}*"
    title, subtitle = escape_markdown("ZENTRA AI 분석"), escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title, banker_title = escape_markdown("플레이어"), escape_markdown("뱅커")
    return f"*{title}*\n{subtitle}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}"

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    # 전체 페이지 수 계산
    history = data.get('history', [])
    cols_per_page = 20
    last_col = -1
    last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col +=1
        last_winner = winner
    total_pages = math.ceil((last_col + 1) / cols_per_page)

    # 페이지 넘김 버튼 생성
    page_buttons = []
    if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전", callback_data='page_prev'))
    if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 ➡️", callback_data='page_next'))

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        page_buttons, # 페이지 버튼 행 추가
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 명령어 및 버튼 처리 함수 (페이지 넘김 로직 추가) ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    image_path = create_big_road_image([], page=0)
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
