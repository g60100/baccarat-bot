# 이후 관리자 페이지를 위해서 1단계 데이터베이스 정리 / 2단계 텔레그램 봇에 데이터 로깅 기능 추가 완성
# 3단계 Flask로 관리자 웹페이지 만들기 / 4단계: 관리자 페이지 화면(HTML) 만들기 / 5단계: 서버에 함께 배포하기는 추가 예정
# 옆으로 행이 20칸이 넘어가면 다음 버튼 생성
# AI가 분석해 준 베팅이 맞으면 구슬 안쪽을 채워서 표시
# 젠트라 사용 순서
# 한글 글자 수정 적용
## 최종 기능 점검 리스트
# 1 & 2. 데이터베이스 및 로깅 기능: ✅ 포함됨
# 페이지 버튼 생성 (20칸 기준): ✅ 포함됨
# AI 추천 적중 시 구슬 채우기: ✅ 포함됨 / AI가 추천한 것이 맞으면 추천한 마지막 기존 구술에 색을 채우고(신규구술등록아님) / 틀렸으면 반대 구술을 안에 색이 없이 내려가는 줄은 내려가는 줄에, 안 내려가면 옆으로 등록해줘
# 안내 문구 및 한글 수정: ✅ 포함됨
# 오류 및 안정성: ✅ 점검 완료
# 최종 서비스 본(25년7월31일 최종수정)
 
# telegram_bot.py (Final Corrected Workflow Version)

import os
import json
import asyncio
import math
import sqlite3
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
RESULTS_LOG_FILE = 'results_log.json' 
DB_FILE = 'baccarat_stats.db' 
COLS_PER_PAGE = 20

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
user_locks = defaultdict(asyncio.Lock)

# --- [DB] 및 기본 헬퍼 함수들 ---
def setup_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT, last_seen TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, timestamp TEXT, action TEXT, details TEXT)')
    conn.commit()
    conn.close()

def log_activity(user_id, action, details=""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        cursor.execute("INSERT INTO activity (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)", (user_id, timestamp, action, details))
        conn.commit()
    except Exception as e: print(f"DB Log Error: {e}")
    finally: conn.close()

def load_results():
    if not os.path.exists(RESULTS_LOG_FILE):
        with open(RESULTS_LOG_FILE, 'w') as f: json.dump([], f)
    try:
        with open(RESULTS_LOG_FILE, 'r') as f: return json.load(f)
    except: return []

def get_feedback_stats():
    results = load_results()
    stats = {'win': 0, 'loss': 0}
    for record in results:
        if record.get('outcome') == 'win': stats['win'] += 1
        elif record.get('outcome') == 'loss': stats['loss'] += 1
    return stats

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def create_big_road_image(user_id):
    data = user_data.get(user_id, {})
    history = data.get('history', [])
    page = data.get('page', 0)
    correct_indices = data.get('correct_indices', [])
    
    cell_size = 22; rows = 6
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
    
    start_col = page * COLS_PER_PAGE; end_col = start_col + COLS_PER_PAGE
    page_grid = [row[start_col:end_col] for row in full_grid]
    top_padding = 30; width = COLS_PER_PAGE * cell_size; height = rows * cell_size + top_padding
    img = Image.new('RGB', (width, height), color='#f4f6f9')
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("arial.ttf", 16)
    except IOError: font = ImageFont.load_default()
    
    total_cols_needed = max(col + 1, 1) if 'col' in locals() else 1
    total_pages = math.ceil(total_cols_needed / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 1
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {page + 1} / {total_pages})", fill="black", font=font)
    
    for r in range(rows):
        for c in range(COLS_PER_PAGE):
            x1, y1 = c * cell_size, r * cell_size + top_padding
            x2, y2 = (c + 1) * cell_size, (r + 1) * cell_size + top_padding
            draw.rectangle([(x1, y1), (x2, y2)], outline='lightgray')
            cell_data = page_grid[r][c]
            if cell_data:
                winner_char = cell_data[0]
                is_correct_prediction = 'C' in cell_data
                color = "#3498db" if winner_char == 'P' else "#e74c3c"
                if is_correct_prediction:
                    draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], fill=color, outline=color, width=2)
                else:
                    draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], outline=color, width=2)
                if 'T' in cell_data: draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill='#2ecc71', width=2)
    
    image_path = "baccarat_road.png"; img.save(image_path)
    return image_path

def get_gpt4_recommendation(game_history, ai_performance_history):
    performance_text = "기록 없음."
    if ai_performance_history:
        performance_text = "과거 추천 기록:\n"
        for i, record in enumerate(ai_performance_history[-5:]):
            outcome_text = '승리' if record.get('outcome') == 'win' else '패배'
            performance_text += f"{i+1}. 추천:{record.get('recommendation', 'N/A')}, 결과:{outcome_text}\n"

    prompt = f"Baccarat History: {game_history}. Your past performance: {performance_text}. Analyze both and recommend the next bet (Player or Banker). Conclude with '추천:' followed by only 'Player' or 'Banker'."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "You are an expert Baccarat analyst who self-corrects based on past performance."},{"role": "user", "content": prompt}])
        full_response = completion.choices[0].message.content
        if "추천:" in full_response:
            recommendation = full_response.split("추천:")[-1].strip()
            return "Banker" if "Banker" in recommendation else "Player"
        else:
            return "Banker" if "Banker" in full_response else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    
    rec_text = ""
    if is_analyzing: rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('GPT-4가 분석 중입니다...')}_"
    elif recommendation: rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅하세요.')}*"
    
    title = escape_markdown("ZENTRA AI 분석"); subtitle = escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title, banker_title = escape_markdown("플레이어 횟수"), escape_markdown("뱅커 횟수")
    
    return f"*{title}*\n{subtitle}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}"

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    history = data.get('history', [])
    
    last_col = -1; last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col +=1
        last_winner = winner
    total_pages = math.ceil((last_col + 1) / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 0
    
    page_buttons = []
    if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전", callback_data='page_prev'))
    if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 ➡️", callback_data='page_next'))

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리 기록", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리 기록", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')]
    ]
    if page_buttons:
        keyboard.append(page_buttons)
    keyboard.append([InlineKeyboardButton("🔍 분석 후 베팅 추천 요청", callback_data='analyze'), InlineKeyboardButton("🔄 기록 초기화", callback_data='reset')])
    
    if data.get('recommendation'):
        feedback_stats = get_feedback_stats()
        keyboard.append([
            InlineKeyboardButton(f"✅ 추천대로 승리 횟수 ({feedback_stats['win']})", callback_data='feedback_win'),
            InlineKeyboardButton(f"❌ 추천대로 패배 횟수 ({feedback_stats['loss']})", callback_data='feedback_loss')
        ])
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 명령어 및 버튼 처리 함수 (로직 전면 수정) ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name
    
    log_activity(user_id, "start")

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
        
        log_activity(user_id, "button_click", action)

        if action in ['P', 'B', 'T']:
            if action == 'P': data['player_wins'] += 1
            elif action == 'B': data['banker_wins'] += 1
            data['history'].append(action)
            data['recommendation'] = None
            data['recommendation_info'] = None
            
        elif action == 'reset': 
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
        elif action == 'page_next': data['page'] += 1
        elif action == 'page_prev': data['page'] -= 1
        elif action == 'analyze':
            if not data['history']: return
            is_analyzing = True
            image_path = create_big_road_image(user_id)
            await query.edit_message_media(media=InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=True), parse_mode=ParseMode.MARKDOWN_V2), reply_markup=build_keyboard(user_id))
            
            ai_performance_history = load_results(); history_str = ", ".join(data['history'])
            recommendation = get_gpt4_recommendation(history_str, ai_performance_history)
            data['recommendation'] = recommendation
            data['recommendation_info'] = {'bet_on': recommendation, 'at_round': len([h for h in data['history'] if h != 'T'])}
            is_analyzing = False
        
        elif action == 'feedback_win':
            if data.get('recommendation_info'):
                rec_info = data['recommendation_info']
                outcome = 'win'
                actual_winner = rec_info['bet_on']
                
                data['history'].append(actual_winner)
                if actual_winner == 'P': data['player_wins'] += 1
                else: data['banker_wins'] += 1
                
                pb_history_len = len([h for h in data['history'] if h != 'T'])
                data.setdefault('correct_indices', []).append(pb_history_len - 1)
                
                log_activity(user_id, "feedback", f"{actual_winner}:{outcome}")
                results = load_results(); results.append({"recommendation": actual_winner, "outcome": outcome})
                with open(RESULTS_LOG_FILE, 'w') as f: json.dump(results, f, indent=2)

                await context.bot.answer_callback_query(query.id, text=f"피드백(승리) 및 다음 결과({actual_winner})를 기록했습니다!")
                data['recommendation'] = None
                data['recommendation_info'] = None
            else: return

        elif action == 'feedback_loss':
            if data.get('recommendation_info'):
                rec_info = data['recommendation_info']
                outcome = 'loss'

                actual_winner = 'P' if rec_info['bet_on'] == 'B' else 'B'
                data['history'].append(actual_winner)
                if actual_winner == 'P': data['player_wins'] += 1
                else: data['banker_wins'] += 1
                
                log_activity(user_id, "feedback", f"{rec_info['bet_on']}:{outcome}")
                results = load_results(); results.append({"recommendation": rec_info['bet_on'], "outcome": outcome})
                with open(RESULTS_LOG_FILE, 'w') as f: json.dump(results, f, indent=2)

                await context.bot.answer_callback_query(query.id, text=f"피드백(패배) 및 실제 결과({actual_winner})를 기록했습니다.")
                data['recommendation'] = None
                data['recommendation_info'] = None
            else: return

        if action not in ['page_next', 'page_prev']:
            history = data['history']
            last_col = -1; last_winner = None
            for winner in history:
                if winner == 'T': continue
                if winner != last_winner: last_col +=1
                last_winner = winner
            total_pages = math.ceil((last_col + 1) / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 0
            data['page'] = max(0, total_pages - 1)

        try:
            image_path = create_big_road_image(user_id)
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
        except Exception as e:
            if "Message is not modified" not in str(e):
                print(f"메시지 수정 오류: {e}")

# --- 봇 실행 메인 함수 ---
def main() -> None:
    setup_database()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
