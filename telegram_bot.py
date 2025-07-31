# telegram_bot.py (Database Logging Version)

import os
import json
import asyncio
import math
import sqlite3 # 데이터베이스를 위한 라이브러리
import datetime
from collections import defaultdict
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DB_FILE = 'baccarat_stats.db' # 데이터베이스 파일 이름

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
user_locks = defaultdict(asyncio.Lock)

# --- [새로운 기능] 데이터베이스 설정 함수 ---
def setup_database():
    """프로그램 시작 시 데이터베이스와 테이블을 생성합니다."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 사용자 정보 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    ''')
    # 활동 기록 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity (
            activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT,
            action TEXT,
            details TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- [새로운 기능] 데이터베이스 기록 함수 ---
def log_activity(user_id, action, details=""):
    """사용자의 활동을 데이터베이스에 기록합니다."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO activity (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
                   (user_id, timestamp, action, details))
    conn.commit()
    conn.close()

# --- 기존 헬퍼 함수들 ---
# (create_big_road_image, get_gpt4_recommendation 등은 이전과 동일)

# --- 텔레그램 명령어 및 버튼 처리 함수 (DB 기록 추가) ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name
    
    # --- DB 기록 로직 ---
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not user:
        cursor.execute("INSERT INTO users (user_id, username, first_seen, last_seen) VALUES (?, ?, ?, ?)",
                       (user_id, username, now, now))
    else:
        cursor.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now, user_id))
    conn.commit()
    conn.close()
    log_activity(user_id, "start")
    # --- 여기까지 ---

    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
    image_path = create_big_road_image(user_id)
    await update.message.reply_photo(photo=open(image_path, 'rb'), caption=build_caption_text(user_id), reply_markup=build_keyboard(user_id), parse_mode=ParseMode.MARKDOWN_V2)

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lock = user_locks[user_id]
    if lock.locked(): await query.answer("처리 중입니다..."); return
    async with lock:
        await query.answer()
        if user_id not in user_data: 
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
        
        action = query.data; data = user_data[user_id]; is_analyzing = False
        
        # 모든 버튼 클릭을 DB에 기록
        log_activity(user_id, "button_click", action)

        if action in ['P', 'B', 'T']:
            if action == 'P': data['player_wins'] += 1
            elif action == 'B': data['banker_wins'] += 1
            data['history'].append(action); data['recommendation'] = None
            
            # 페이지 유지 로직
            history = data['history']
            cols_per_page = 30
            last_col = -1; last_winner = None
            for winner in history:
                if winner == 'T': continue
                if winner != last_winner: last_col +=1
                last_winner = winner
            total_pages = math.ceil((last_col + 1) / cols_per_page) if cols_per_page > 0 else 0
            data['page'] = max(0, total_pages - 1)

        elif action == 'reset': 
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
        
        # ... 이하 button_callback 함수의 나머지 부분은 이전과 동일 ...

        try:
            image_path = create_big_road_image(user_id)
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
        except Exception as e: print(f"메시지 수정 오류: {e}")

# --- 봇 실행 메인 함수 (DB 설정 추가) ---
def main() -> None:
    # 프로그램 시작 시 DB 파일과 테이블이 있는지 확인하고 없으면 생성
    setup_database()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

# --- 생략된 함수의 전체 코드 ---
# (이전 답변의 완전한 코드를 여기에 붙여넣으세요: get_feedback_stats, get_gpt4_recommendation, create_big_road_image, build_caption_text, build_keyboard, escape_markdown 등)

def get_feedback_stats():
    # ...
    pass

# telegram_bot.py 파일에 이 함수를 추가하세요.

def create_big_road_image(user_id):
    data = user_data.get(user_id, {})
    history = data.get('history', [])
    page = data.get('page', 0)
    correct_indices = data.get('correct_indices', [])
    
    cell_size = 22; rows, cols_per_page = 6, 30
    full_grid_cols = 120
    full_grid = [[''] * full_grid_cols for _ in range(rows)]
    last_positions = {}
    
    pb_history_index = -1
    if history:
        col, row, last_winner = -1, 0, None
        for i, winner in enumerate(history):
            if winner == 'T':
                if last_winner and last_winner in last_positions:
                    r, c = last_positions[last_winner]
                    if full_grid[r][c]: full_grid[r][c] += 'T'
                continue
            pb_history_index += 1
            if winner != last_winner: col += 1; row = 0
            else: row += 1
            if row >= rows: col += 1; row = rows - 1
            if col < full_grid_cols: 
                is_correct = 'C' if pb_history_index in correct_indices else ''
                full_grid[row][col] = winner + is_correct
                last_positions[winner] = (row, col)
            last_winner = winner
    
    start_col = page * cols_per_page; end_col = start_col + cols_per_page
    page_grid = [row[start_col:end_col] for row in full_grid]
    top_padding = 30; width = cols_per_page * cell_size; height = rows * cell_size + top_padding
    img = Image.new('RGB', (width, height), color='#f4f6f9')
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("arial.ttf", 16)
    except IOError: font = ImageFont.load_default()
    
    total_cols_needed = max(col + 1, 1) if 'col' in locals() else 1
    total_pages = math.ceil(total_cols_needed / cols_per_page) if cols_per_page > 0 else 1
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {page + 1} / {total_pages})", fill="black", font=font)
    
    for r in range(rows):
        for c in range(cols_per_page):
            x1, y1 = c * cell_size, r * cell_size + top_padding
            x2, y2 = (c + 1) * cell_size, (r + 1) * cell_size + top_padding
            draw.rectangle([(x1, y1), (x2, y2)], outline='lightgray')
            cell_data = page_grid[r][c]
            if cell_data:
                winner_char = cell_data[0]
                is_correct_prediction = 'C' in cell_data
                color = "#3498db" if winner_char == 'P' else "#e74c3c"
                if is_correct_prediction:
                    draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], fill=color, outline=color, width=3)
                else:
                    draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], outline=color, width=3)
                if 'T' in cell_data: draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill='#2ecc71', width=2)
    
    image_path = "baccarat_road.png"; img.save(image_path)
    return image_path
def get_gpt4_recommendation(game_history, ai_performance_history):
    # ...
    pass

# ... etc ...
