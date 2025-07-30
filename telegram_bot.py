# telegram_bot.py (Final Enhanced Version)

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

if not os.path.exists(RESULTS_LOG_FILE):
    with open(RESULTS_LOG_FILE, 'w') as f: json.dump([], f)

# --- 데이터 로드 및 통계 함수 ---
def load_results():
    try:
        with open(RESULTS_LOG_FILE, 'r') as f: return json.load(f)
    except: return []

def get_feedback_stats():
    """AI 추천의 전체 승/패 통계를 계산합니다."""
    results = load_results()
    stats = {'win': 0, 'loss': 0}
    for record in results:
        if record.get('outcome') == 'win':
            stats['win'] += 1
        elif record.get('outcome') == 'loss':
            stats['loss'] += 1
    return stats

# --- [수정] GPT-4 분석 함수 (더욱 정교한 프롬프트) ---
def get_gpt4_recommendation(game_history, ai_performance_history):
    performance_text = "아직 나의 추천 기록이 없습니다."
    if ai_performance_history:
        performance_text = "아래는 당신(AI)의 과거 추천 기록과 그 실제 결과입니다:\n"
        for i, record in enumerate(ai_performance_history[-10:]):
            outcome_text = '승리' if record.get('outcome') == 'win' else '패배'
            performance_text += f"{i+1}. 추천: {record.get('recommendation', 'N/A')}, 실제 결과: {outcome_text}\n"

    prompt = f"""
    당신은 세계 최고의 바카라 데이터 분석가입니다. 당신의 임무는 주어진 데이터를 분석하여 가장 확률 높은 다음 베팅을 추천하는 것입니다.

    [분석 규칙]
    1. 먼저 게임 기록의 패턴(연속성, 전환 등)을 분석하고 그 이유를 간략히 서술합니다.
    2. 그 다음, 당신의 과거 추천 실적을 보고 현재 당신의 전략이 잘 맞고 있는지 평가합니다.
    3. 이 두 가지 분석을 종합하여, 최종 추천을 "추천:" 이라는 단어 뒤에 Player 또는 Banker 로만 결론내립니다.

    [데이터 1: 현재 게임의 흐름]
    {game_history}

    [데이터 2: 당신의 과거 추천 실적]
    {performance_text}
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a world-class Baccarat analyst who provides reasoning before the final recommendation."},
                {"role": "user", "content": prompt}
            ]
        )
        full_response = completion.choices[0].message.content
        # 답변에서 "추천:" 뒤의 단어만 추출
        if "추천:" in full_response:
            recommendation = full_response.split("추천:")[-1].strip()
            return "Banker" if "Banker" in recommendation else "Player"
        else: # 예외 처리
            return "Banker" if "Banker" in full_response else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 이미지/캡션/키보드 생성 함수 (UI 개선) ---
def create_big_road_image(user_id, history, page=0):
    # ... (생략, 이전 코드와 동일)
    pass 

def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    
    # 페이지 넘김 텍스트 생성
    history = data.get('history', [])
    page = data.get('page', 0)
    cols_per_page = 20
    last_col = -1; last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col +=1
        last_winner = winner
    total_pages = math.ceil((last_col + 1) / cols_per_page) if cols_per_page > 0 else 0
    
    page_text = ""
    if total_pages > 1:
        page_text = f"\n\n*{escape_markdown('⬅️ 이전')}* `( {page + 1} / {total_pages} )` *{escape_markdown('다음 ➡️')}*"

    rec_text = ""
    if is_analyzing: rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('GPT-4가 분석 중입니다...')}_"
    elif recommendation: rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅하세요.')}*"
    
    title = escape_markdown("ZENTRA AI 분석"); subtitle = escape_markdown("승리한 쪽의 버튼을 눌러 기록을 누적하세요.")
    player_title, banker_title = escape_markdown("플레이어"), escape_markdown("뱅커")
    
    return f"*{title}*\n{subtitle}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{page_text}{rec_text}"

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    recommendation = data.get('recommendation', None)
    feedback_stats = get_feedback_stats() # 승/패 통계 불러오기
    
    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ]
    if recommendation:
        keyboard.append([
            InlineKeyboardButton(f"✅ 추천대로 승리 ({feedback_stats['win']})", callback_data='feedback_win'),
            InlineKeyboardButton(f"❌ 추천대로 패배 ({feedback_stats['loss']})", callback_data='feedback_loss')
        ])
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 핸들러 및 메인 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    # ... (생략, 이전 코드와 동일)
    pass

async def button_callback(update: Update, context: CallbackContext) -> None:
    # ... (생략, 이전 코드와 동일)
    pass

def main() -> None:
    # ... (생략, 이전 코드와 동일)
    pass

if __name__ == "__main__":
    main()

# --- 생략된 함수의 전체 코드 ---
# (이전 답변의 완전한 코드를 여기에 붙여넣으세요)

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def create_big_road_image(user_id, history, page=0):
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
    start_col = page * cols_per_page; end_col = start_col + cols_per_page
    page_grid = [row[start_col:end_col] for row in full_grid]
    top_padding = 30; width = cols_per_page * cell_size; height = rows * cell_size + top_padding
    img = Image.new('RGB', (width, height), color='#f4f6f9')
    draw = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("arial.ttf", 16)
    except IOError: font = ImageFont.load_default()
    total_cols_needed = max(col + 1, 1) if 'col' in locals() else 1
    total_pages = math.ceil(total_cols_needed / cols_per_page)
    current_page = user_data.get(user_id, {}).get('page', 0)
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {current_page + 1} / {total_pages})", fill="black", font=font)
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
    image_path = "baccarat_road.png"; img.save(image_path)
    return image_path

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
    image_path = create_big_road_image(user_id, [], page=0)
    await update.message.reply_photo(photo=open(image_path, 'rb'), caption=build_caption_text(user_id), reply_markup=build_keyboard(user_id), parse_mode=ParseMode.MARKDOWN_V2)

async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lock = user_locks[user_id]
    if lock.locked(): await query.answer("처리 중입니다. 잠시 후 다시 시도해주세요."); return
    async with lock:
        await query.answer()
        if user_id not in user_data: user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0}
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
            image_path = create_big_road_image(user_id, data['history'], page=data.get('page', 0))
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=True), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
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
            image_path = create_big_road_image(user_id, data['history'], page=data.get('page', 0))
            media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
            await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
        except Exception as e: print(f"메시지 수정 오류: {e}")

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)
if __name__ == "__main__":
    main()
