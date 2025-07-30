# telegram_bot.py (Final Stable Version)

import os
import json
import asyncio
import math
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

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
user_locks = defaultdict(asyncio.Lock)

# --- 초기화 ---
if not os.path.exists(RESULTS_LOG_FILE):
    with open(RESULTS_LOG_FILE, 'w') as f: json.dump([], f)

# --- 데이터 로드 및 통계 함수 ---
def load_results():
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

# --- Markdown V2 특수문자 이스케이프 함수 ---
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# --- 이미지 생성 함수 ---
def create_big_road_image(user_id, history):
    page = user_data.get(user_id, {}).get('page', 0)
    cell_size = 22; rows, cols_per_page = 6, 20
    full_grid_cols = 60
    full_grid = [[''] * full_grid_cols for _ in range(rows)]
    last_positions = {}
    if history:
        col, row, last_winner = -1, 0, None
        for i, winner in enumerate(history):
            if winner == 'T':
                if last_winner and last_winner in last_positions:
                    r, c = last_positions[last_winner]
                    if full_grid[r][c]: full_grid[r][c] += 'T'
                continue
            if winner != last_winner: col += 1; row = 0
            else: row += 1
            if row >= rows: col += 1; row = rows - 1
            if col < full_grid_cols: full_grid[row][col] = winner; last_positions[winner] = (row, col)
            last_winner = winner
    
    start_col = page * cols_per_page
    end_col = start_col + cols_per_page
    page_grid = [row[start_col:end_col] for row in full_grid]

    top_padding = 30
    width = cols_per_page * cell_size
    height = rows * cell_size + top_padding
    
    img = Image.new('RGB', (width, height), color='#f4f6f9')
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("arial.ttf", 16)
    except IOError: font = ImageFont.load_default()
    
    total_cols_needed = max(col + 1, 1) if 'col' in locals() else 1
    total_pages = math.ceil(total_cols_needed / cols_per_page)
    
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {page + 1} / {total_pages})", fill="black", font=font)
    
    for r in range(rows):
        for c in range(cols_per_page):
            x1, y1 = c * cell_size, r * cell_size + top_padding
            x2, y2 = (c + 1) * cell_size, (r + 1) * cell_size + top_padding
            draw.rectangle([(x1, y1), (x2, y2)], outline='lightgray')
            cell_data = page_grid[r][c]
            if cell_data:
                winner_char = cell_data[0]
                color = "#3498db" if winner_char == 'P' else "#e74c3c"
                draw.ellipse([(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)], outline=color, width=3)
                if 'T' in cell_data: draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill='#2ecc71', width=2)
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path

# --- GPT-4 분석 함수 ---
def get_gpt4_recommendation(game_history, ai_performance_history):
    performance_text = "기록 없음."
    if ai_performance_history:
        performance_text = "과거 추천 기록:\n"
        for i, record in enumerate(ai_performance_history[-5:]):
            outcome_text = '승리' if record.get('outcome') == 'win' else '패배'
            performance_text += f"{i+1}. 추천:{record.get('recommendation', 'N/A')}, 결과:{outcome_text}\n"

    prompt = f"Baccarat History: {game_history}. Your past performance: {performance_text}. Analyze both and recommend the next bet (Player or Banker)."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "You are an expert Baccarat analyst who self-corrects based on past performance. Respond with only 'Player' or 'Banker'."},{"role": "user", "content": prompt}])
        recommendation = completion.choices[0].message.content
        return "Banker" if "Banker" in recommendation else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 캡션 및 키보드 생성 함수 ---
def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    
    rec_text = ""
    if is_analyzing:
        rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('GPT-4가 분석 중입니다...')}_"
    elif recommendation:
        rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅하세요.')}*"
    
    title = escape_markdown("ZENTRA AI 분석"); subtitle = escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title, banker_title = escape_markdown("플레이어"), escape_markdown("뱅커")
    
    return f"*{title}*\n{subtitle}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}"

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    history = data.get('history', [])
    cols_per_page = 20
    last_col = -1; last_winner = None
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
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')]
    ]
    if page_buttons:
        keyboard.append(page_buttons)
    keyboard.append([InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')])
    
    if data.get('recommendation'):
        feedback_stats = get_feedback_stats()
        keyboard.append([
            InlineKeyboardButton(f"✅ 추천대로 승리 ({feedback_stats['win']})", callback_data='feedback_win'),
            InlineKeyboardButton(f"❌ 추천대로 패배 ({feedback_stats['loss']})", callback_data='feedback_loss')
        ])
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    image_path = create_big_road_image(user_id, [])
    await update.message.reply_photo(photo=open(image_path, 'rb'), caption=build_caption_text(user_id), reply_markup=build_keyboard(user_id), parse_mode=ParseMode.MARKDOWN_V2)

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lock = user_locks[user_id]
    if lock.locked(): await query.answer("처리 중입니다. 잠시 후 다시 시도해주세요."); return
    async with lock:
        await query.answer()
        
        if user_id not in user_data:
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
        
        action = query.data; data = user_data[user_id]; is_analyzing = False
        
        if action in ['P', 'B', 'T']:
            if action == 'P': data['player_wins'] += 1
            elif action == 'B': data['banker_wins'] += 1
            data['history'].append(action); data['recommendation'] = None; data['page'] = 0
        elif action == 'reset': user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
        elif action == 'page_next': data['page'] += 1
        elif action == 'page_prev': data['page'] -= 1
        elif action == 'analyze':
            if not data['history']: return
            is_analyzing = True
            image_path = create_big_road_image(user_id, data['history'])
            await query.edit_message_media(media=InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=True), parse_mode=ParseMode.MARKDOWN_V2), reply_markup=build_keyboard(user_id))
            
            ai_performance_history = load_results(); history_str = ", ".join(data['history'])
            recommendation = get_gpt4_recommendation(history_str, ai_performance_history)
            data['recommendation'] = recommendation; is_analyzing = False
        
        elif action in ['feedback_win', 'feedback_loss']:
            if data.get('recommendation'):
                outcome = 'win' if action == 'feedback_win' else 'loss'
                results = load_results(); results.append({"recommendation": data['recommendation'], "outcome": outcome})
                with open(RESULTS_LOG_FILE, 'w') as f: json.dump(results, f, indent=2)
                await context.bot.answer_callback_query(query.id, text=f"피드백({outcome})을 학습했습니다!")
                data['recommendation'] = None
            else: return

        try:
            image_path = create_big_road_image(user_id, data['history'])
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
        except Exception as e: print(f"메시지 수정 오류: {e}")

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
