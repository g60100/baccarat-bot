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

# --- [DB] 데이터베이스 설정 함수 ---
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
    except Exception as e:
        print(f"DB Log Error: {e}")
    finally:
        conn.close()

# --- 데이터 로드 및 통계 함수 ---
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

# --- Markdown V2 특수문자 이스케이프 함수 ---
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# --- 이미지 생성 함수 ---
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
            
            if winner != last_winner:
                col += 1
                row = 0
            else:
                row += 1
            
            if row >= rows:
                col += 1
                row = rows - 1

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

# --- GPT-4 분석 함수 ---
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
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "You are a world-class Baccarat analyst."},{"role": "user", "content": prompt}])
        full_response = completion.choices[0].message.content
        if "추천:" in full_response:
            recommendation = full_response.split("추천:")[-1].strip()
            return "Banker" if "Banker" in recommendation else "Player"
        else:
            return "Banker" if "Banker" in full_response else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 캡션 및 키보드 생성 함수 ---
def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    
    guide_text = """
= Zentra ChetGPT-4o AI 분석기 사용 순서 =
1. 실제 게임결과를 '수동 기록' 클릭과 시작합니다.
2. 1번 수동입력하면 AI가 자동으로 분석을 시작합니다.
3. 실제 게임결과 AI추천이 맞으면 "AI추천승리"를 클릭
   실제 게임결과 AI추천이 틀리면 "AI추천패비"를 클릭
   (AI분석 평가를 하면 다음 분석을 즉시 시작한다.)
4. 이후부터 3번 항목만 반복하며, 타이시 타이 클릭한다.
5. 기록을 지우고 새롭게 하기위해서는 "기록초기화" 클릭
6. Zentra AI는 참고용이며 수익을 보장하지 않습니다. 
"""

    rec_text = ""
    if is_analyzing: rec_text = f"\n\n👇 *AI 추천 참조* 👇\n_{escape_markdown('ChetGPT-4o AI가 다음 베팅을 자동으로 분석중입니다...')}_"
    elif recommendation: rec_text = f"\n\n👇 *AI 추천 참조* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅참조하세요.')}*"
    
    title = escape_markdown("ZENTRA가 개발한한 ChetGPT-4o AI 분석으로 베팅에 참조하세요."); 
    subtitle = escape_markdown("결정과 결과의 책임은 본인에게 있습니다.")
    player_title, banker_title = escape_markdown("플레이어 총 횟수"), escape_markdown("뱅커 총 횟수")
    
    return f"*{title}*\n{subtitle}\n\n{escape_markdown(guide_text)}\n\n*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}"

def _get_page_info(history):
    """히스토리를 기반으로 마지막 열과 전체 페이지 수를 계산하는 헬퍼 함수"""
    last_col = -1
    last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col += 1
        last_winner = winner
    
    total_pages = math.ceil((last_col + 1) / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 1
    # total_pages는 최소 1이 되어야 합니다.
    total_pages = max(1, total_pages)
    
    return last_col, total_pages

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    history = data.get('history', [])
    
    # 새로운 헬퍼 함수를 사용하여 페이지 정보 계산
    last_col, total_pages = _get_page_info(history)
    
    page_buttons = []
    if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전 이동", callback_data='page_prev'))
    if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 이동 ➡️", callback_data='page_next'))

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 (수동 기록)", callback_data='P'), InlineKeyboardButton("🔴 뱅커 (수동 기록)", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (수동 기록)", callback_data='T')]
    ]
    if page_buttons:
        keyboard.append(page_buttons)
    keyboard.append([InlineKeyboardButton("🔍 ChetGPT-4o AI 분석수동요청", callback_data='analyze'), InlineKeyboardButton("🔄 기록 초기화", callback_data='reset')])
    
    if data.get('recommendation'):
        feedback_stats = get_feedback_stats()
        keyboard.append([
            InlineKeyboardButton(f"✅ AI추천 "승"시 클릭  ({feedback_stats['win']})", callback_data='feedback_win'),
            InlineKeyboardButton(f"❌ AI추천 "패"시 클릭 ({feedback_stats['loss']})", callback_data='feedback_loss')
        ])
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    log_activity(user_id, "start")
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
    image_path = create_big_road_image(user_id)
    await update.message.reply_photo(photo=open(image_path, 'rb'), caption=build_caption_text(user_id), reply_markup=build_keyboard(user_id), parse_mode=ParseMode.MARKDOWN_V2)

# [최종] 모든 오류를 수정한 button_callback 함수
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lock = user_locks[user_id]

    if lock.locked():
        await query.answer("처리 중입니다...")
        return
        
    async with lock:
        await query.answer()
        if user_id not in user_data:
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
        
        data = user_data[user_id]
        action = query.data
        log_activity(user_id, "button_click", action)

        should_analyze = False
        update_ui_only = False

        if action in ['P', 'B', 'T']:
            data['history'].append(action)
            if action == 'P': data['player_wins'] += 1
            elif action == 'B': data['banker_wins'] += 1
            data['recommendation'] = None
            data['recommendation_info'] = None
            should_analyze = True

        elif action == 'reset':
            user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None, 'page': 0, 'correct_indices': []}
            update_ui_only = True

        elif action in ['page_next', 'page_prev']:
            if action == 'page_next': data['page'] += 1
            else: data['page'] = max(0, data['page'] - 1)
            update_ui_only = True

        elif action == 'analyze':
            if not data['history']:
                await context.bot.answer_callback_query(query.id, text="기록이 없어 분석할 수 없습니다.")
                return
            should_analyze = True

        elif action == 'feedback_win':
            rec_info = data.get('recommendation_info')
            if not rec_info:
                await context.bot.answer_callback_query(query.id, text="피드백할 추천 결과가 없습니다.")
                return

            recommendation = rec_info['bet_on'] # "Player" 또는 "Banker"
            result_to_add = 'P' if recommendation == "Player" else 'B'
            data['history'].append(result_to_add)

            if result_to_add == 'P': data['player_wins'] += 1
            elif result_to_add == 'B': data['banker_wins'] += 1
            
            pb_history = [h for h in data['history'] if h != 'T']
            data.setdefault('correct_indices', []).append(len(pb_history) - 1)
            log_activity(user_id, "feedback", f"{recommendation}:win")
            results = load_results(); results.append({"recommendation": recommendation, "outcome": "win"})
            with open(RESULTS_LOG_FILE, 'w') as f: json.dump(results, f, indent=2)
            should_analyze = True
        
        elif action == 'feedback_loss':
            rec_info = data.get('recommendation_info')
            if not rec_info:
                await context.bot.answer_callback_query(query.id, text="피드백할 추천 결과가 없습니다.")
                return
            
            recommendation = rec_info['bet_on'] # "Player" 또는 "Banker"
            opposite_result = 'P' if recommendation == "Banker" else 'B'
            data['history'].append(opposite_result)
            
            if opposite_result == 'P': data['player_wins'] += 1
            elif opposite_result == 'B': data['banker_wins'] += 1

            log_activity(user_id, "feedback", f"{recommendation}:loss")
            results = load_results(); results.append({"recommendation": recommendation, "outcome": "loss"})
            with open(RESULTS_LOG_FILE, 'w') as f: json.dump(results, f, indent=2)
            should_analyze = True

        # --- 통합 분석 및 UI 업데이트 로직 ---
        if should_analyze:
            # 새로운 헬퍼 함수를 사용하여 페이지 정보 계산
            last_col, total_pages = _get_page_info(data['history'])
            # 마지막 페이지로 자동 이동
            data['page'] = max(0, total_pages - 1)

            image_path = create_big_road_image(user_id)
            try:
                await query.edit_message_media(
                    media=InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=True), parse_mode=ParseMode.MARKDOWN_V2),
                    reply_markup=build_keyboard(user_id)
                )
            except Exception as e:
                if "Message is not modified" not in str(e): print(f"분석 중 표시 오류: {e}")

            ai_performance_history = load_results()
            history_str = ", ".join(data['history'])
            new_recommendation = get_gpt4_recommendation(history_str, ai_performance_history)
            data['recommendation'] = new_recommendation
            data['recommendation_info'] = {'bet_on': new_recommendation, 'at_round': len([h for h in data['history'] if h != 'T'])}

        if update_ui_only or should_analyze:
            try:
                image_path = create_big_road_image(user_id)
                await query.edit_message_media(
                    media=InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=False), parse_mode=ParseMode.MARKDOWN_V2),
                    reply_markup=build_keyboard(user_id)
                )
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
