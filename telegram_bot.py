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

# Perplexity 수정 요청 적용
# 수정/적용 요구 요약
# AI 자동분석 ON/OFF 토글 버튼 (수동 요청 버튼 옆)
# 기록 초기화시 빅로드+AI추천 승/패 카운터 동시 초기화
# 카운터는 DB에 누적 저장, 화면상에는 초기화~초기화 사이만 집계
# SQLite 동시접속 write lock 문제 최소화 (WAL 모드/timeout/retry)
# 최종 서비스 본(25년8월02일 최종수정)

import os
import asyncio
import math
import sqlite3
import datetime
import time
from collections import defaultdict
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# --- 환경설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DB_FILE = 'baccarat_stats.db'
COLS_PER_PAGE = 20

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
user_locks = defaultdict(asyncio.Lock)

# === SQLite: WAL 모드, write timeout/retry 래퍼 함수 ===
def get_db_conn():
    conn = sqlite3.connect(DB_FILE, timeout=10, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception as e:
        print(f"WAL mode set 실패: {e}")
    return conn

def safe_db_write(query, params=()):
    retries, delay = 3, 1
    for _ in range(retries):
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                time.sleep(delay)
            else:
                raise
    raise RuntimeError("DB write lock 지속됨")

# --- DB 테이블 생성 ---
def setup_database():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT, last_seen TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, timestamp TEXT, action TEXT, details TEXT)')
    cursor.execute('''CREATE TABLE IF NOT EXISTS results_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        recommendation TEXT, outcome TEXT, created DATETIME)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reset_time DATETIME)''')
    conn.commit()
    conn.close()

def log_activity(user_id, action, details=""):
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_db_write("INSERT INTO activity (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)", (user_id, dt, action, details))

def log_result(user_id, recommendation, outcome):
    dt = datetime.datetime.now()
    safe_db_write(
        "INSERT INTO results_log (user_id, recommendation, outcome, created) VALUES (?, ?, ?, ?)",
        (user_id, recommendation, outcome, dt)
    )

def log_reset(user_id):
    dt = datetime.datetime.now()
    safe_db_write("INSERT INTO resets (user_id, reset_time) VALUES (?, ?)", (user_id, dt))

def get_feedback_stats(user_id):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT reset_time FROM resets WHERE user_id=? ORDER BY reset_time DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    last_reset = row[0] if row else None

    if last_reset:
        cursor.execute("""SELECT outcome, COUNT(*) FROM results_log WHERE user_id=? AND created >= ? GROUP BY outcome""",
                       (user_id, last_reset))
    else:
        cursor.execute("SELECT outcome, COUNT(*) FROM results_log WHERE user_id=? GROUP BY outcome", (user_id,))
    stats = {'win': 0, 'loss': 0}
    for outcome, count in cursor.fetchall():
        if outcome == 'win': stats['win'] = count
        elif outcome == 'loss': stats['loss'] = count
    conn.close()
    return stats

# --- Markdown 이스케이프 ---
def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-.=|{}!'
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

# --- 빅로드 이미지 생성 ---
def create_big_road_image(user_id):
    data = user_data.get(user_id, {})
    history = data.get('history', [])
    page = data.get('page', 0)
    correct_indices = data.get('correct_indices', [])

    cell_size = 22
    rows = 6
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
                    if full_grid[r][c]:
                        full_grid[r][c] += 'T'
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
    start_col = page * COLS_PER_PAGE
    end_col = start_col + COLS_PER_PAGE
    page_grid = [row[start_col:end_col] for row in full_grid]
    top_padding = 30
    width = COLS_PER_PAGE * cell_size
    height = rows * cell_size + top_padding
    img = Image.new('RGB', (width, height), color='#f4f6f9')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()
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
                if 'T' in cell_data:
                    draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill='#2ecc71', width=2)
    image_path = f"/tmp/baccarat_road_{user_id}.png"
    img.save(image_path)
    return image_path

# --- GPT-4o 추천 ---
def get_gpt4_recommendation(game_history, ai_performance_history):
    performance_text = "아직 나의 추천 기록이 없습니다."
    if ai_performance_history:
        performance_text = "아래는 당신(AI)의 과거 추천 기록과 그 실제 결과입니다:\n"
        for i, record in enumerate(ai_performance_history[-10:]):
            outcome_text = '승리' if record.get('outcome') == 'win' else '패배'
            performance_text += f"{i+1}. 추천: {record.get('recommendation', 'N/A')}, 실제 결과: {outcome_text}\n"

    prompt = f"""
    당신은 세계 최고의 50년 경력의 바카라 데이터 분석가입니다...
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
        recommendation_part = ""
        if "추천:" in full_response:
            recommendation_part = full_response.split("추천:")[-1]
        else:
            recommendation_part = full_response
        if "Player" in recommendation_part or "플레이어" in recommendation_part:
            return "Player"
        elif "Banker" in recommendation_part or "뱅커" in recommendation_part:
            return "Banker"
        else:
            return "Banker"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return None

# --- Caption 빌드 ---
def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get('player_wins', 0), data.get('banker_wins', 0)
    recommendation = data.get('recommendation', None)
    feedback_stats = get_feedback_stats(user_id)
    guide_text = """
= Zentra ChetGPT-4o AI 분석기 사용 순서 =
1. 게임결과 마지막 결과를 "수동기록"으로 기록
2. 1번 수동기록 끝나면 "자동분석 OFF"를 클릭...
3. 게임결과 AI추천 맞으면 'AI추천"승"시'를 클릭
   게임결과 AI추천 틀리면 'AI추천"패"시'를 클릭
4. 이후부터 3번 항목만 반복, "타이"시 타이 클릭
5. 새롭게 하기 위해서는 "기록 초기화" 클릭
6. AI분석 OFF하면 "AI분석수동요청"클릭시 AI분석
7. AI는 참고용이며 수익을 보장하지 않습니다. 
"""
    rec_text = ""
    if is_analyzing:
        rec_text = f"\n\n👇 *ChetGPT-4o AI분석 추천 참조* 👇\n_{escape_markdown('ChetGPT-4o AI가 다음 베팅을 분석중입니다...')}_"
    elif recommendation:
        rec_text = f"\n\n👇 *ChetGPT-4o AI분석 추천 참조* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅참조하세요.')}*"
    title = escape_markdown("ZENTRA가 개발한 ChetGPT-4o AI 분석으로 베팅에 참조하세요.")
    subtitle = escape_markdown("베팅의 결정과 베팅의 결과는 본인에게 있습니다.")
    player_title, banker_title = escape_markdown("플레이어 총 횟수"), escape_markdown("뱅커 총 횟수")
    win_count = feedback_stats.get('win', 0)
    loss_count = feedback_stats.get('loss', 0)
    return (f"*{title}*\n{subtitle}\n\n{escape_markdown(guide_text)}\n\n"
            f"*{player_title}: {player_wins}* ┃ *{banker_title}: {banker_wins}*{rec_text}\n\n"
            f"✅ AI추천\"승\" 클릭: {win_count} ┃ ❌ AI추천\"패\" 클릭: {loss_count}")

# --- 히스토리/페이지 정보 ---
def _get_page_info(history):
    if not history:
        return -1, 1
    last_col = -1
    last_winner = None
    for winner in history:
        if winner == 'T': continue
        if winner != last_winner: last_col += 1
        last_winner = winner
    total_cols = last_col + 1
    total_pages = math.ceil(total_cols / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 1
    return last_col, max(1, total_pages)

# --- 키보드 빌드 ---
def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page = data.get('page', 0)
    history = data.get('history', [])
    last_col, total_pages = _get_page_info(history)
    page_buttons = []
    if total_pages > 1:
        if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전", callback_data='page_prev'))
        if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 ➡️", callback_data='page_next'))

    auto_analysis = data.get('auto_analysis_enabled', False)  # 기본 OFF
    toggle_text = "🔔 자동분석 ON 상태" if auto_analysis else "🔕 자동분석 OFF 상태"

    keyboard = [
        [InlineKeyboardButton("🔵 플레이어(수동 기록)", callback_data='P'),
         InlineKeyboardButton("🔴 뱅커 (수동 기록)", callback_data='B')],
        [InlineKeyboardButton(toggle_text, callback_data='toggle_auto_analysis'),
         InlineKeyboardButton("🟢 타이 (수동 기록)", callback_data='T')],
    ]
    if page_buttons:
        keyboard.append(page_buttons)

    keyboard.append([
        InlineKeyboardButton("🔍 AI분석 수동 요청", callback_data='analyze'),
        InlineKeyboardButton("🔄 기록 초기화", callback_data='reset')
    ])

    if data.get('recommendation'):
        feedback_stats = get_feedback_stats(user_id)
        keyboard.append([
            InlineKeyboardButton(f'✅ AI추천 "승" 클릭 ({feedback_stats["win"]})', callback_data='feedback_win'),
            InlineKeyboardButton(f'❌ AI추천 "패" 클릭 ({feedback_stats["loss"]})', callback_data='feedback_loss')
        ])

    return InlineKeyboardMarkup(keyboard)

# --- start 커맨드 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    log_activity(user_id, "start")
    user_data[user_id] = {
        'player_wins': 0, 'banker_wins': 0, 'history': [],
        'recommendation': None, 'page': 0, 'correct_indices': [],
        'auto_analysis_enabled': False  # 기본 OFF
    }
    image_path = create_big_road_image(user_id)
    await update.message.reply_photo(
        photo=open(image_path, 'rb'),
        caption=build_caption_text(user_id),
        reply_markup=build_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN_V2
    )

# --- 버튼 콜백 ---
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lock = user_locks[user_id]

    try:
        await query.answer()
    except Exception as e:
        print(f"query.answer() error: {e}")

    if lock.locked():
        await query.answer("처리 중입니다...")
        return

    async with lock:
        if user_id not in user_data:
            user_data[user_id] = {
                'player_wins': 0, 'banker_wins': 0, 'history': [],
                'recommendation': None, 'page': 0, 'correct_indices': [],
                'auto_analysis_enabled': False
            }

        data = user_data[user_id]
        action = query.data
        log_activity(user_id, "button_click", action)

        should_analyze = False
        update_ui_only = False

        if action in ['P', 'B', 'T']:
            data['history'].append(action)
            if action == 'P':
                data['player_wins'] += 1
            elif action == 'B':
                data['banker_wins'] += 1
            data['recommendation'] = None
            data['recommendation_info'] = None
            auto_analysis = data.get('auto_analysis_enabled', False)

            update_ui_only = True  # 빅로드는 항상 즉시 갱신

            if action in ['P', 'B'] and auto_analysis:
                should_analyze = True  # 자동분석 ON일 때 즉시 분석

        elif action == 'reset':
            user_data[user_id] = {
                'player_wins': 0, 'banker_wins': 0, 'history': [],
                'recommendation': None, 'page': 0, 'correct_indices': [],
                'auto_analysis_enabled': False  # 초기화 시 OFF로
            }
            log_reset(user_id)
            update_ui_only = True

        elif action in ['page_next', 'page_prev']:
            if action == 'page_next':
                data['page'] += 1
            else:
                data['page'] = max(0, data['page'] - 1)
            update_ui_only = True

        elif action == 'analyze':
            if not data['history']:
                await context.bot.answer_callback_query(query.id, text="기록이 없어 분석할 수 없습니다.")
                return
            # 한번만 AI 분석 실행(자동분석 토글 상태와 무관)
            should_analyze = True

        elif action == 'toggle_auto_analysis':
            current_state = data.get('auto_analysis_enabled', False)
            new_state = not current_state
            data['auto_analysis_enabled'] = new_state
    if new_state:  # ON
        if data.get('history'):
            should_analyze = True
        else:
            update_ui_only = True
    else:  # OFF
        data['recommendation'] = None
        data['recommendation_info'] = None
        update_ui_only = True

        elif action == 'feedback_win':
            rec_info = data.get('recommendation_info')
            if not rec_info:
                await context.bot.answer_callback_query(query.id, text="피드백할 추천 결과가 없습니다.")
               return
            recommendation = rec_info['bet_on']  # "Player" 또는 "Banker"
            result_to_add = 'P' if recommendation == "Player" else 'B'
            data['history'].append(result_to_add)
            if result_to_add == 'P':
                data['player_wins'] += 1
            elif result_to_add == 'B':
                data['banker_wins'] += 1
           pb_history = [h for h in data['history'] if h != 'T']
           data.setdefault('correct_indices', []).append(len(pb_history) - 1)
           log_activity(user_id, "feedback", f"{recommendation}:win")
           log_result(user_id, recommendation, "win")
           should_analyze = True  # AI 재분석 트리거

        elif action == 'feedback_loss':
            rec_info = data.get('recommendation_info')
            if not rec_info:
                await context.bot.answer_callback_query(query.id, text="피드백할 추천 결과가 없습니다.")
                return
            recommendation = rec_info['bet_on']
            opposite_result = 'P' if recommendation == "Banker" else 'B'
            data['history'].append(opposite_result)
            if opposite_result == 'P':
                data['player_wins'] += 1
            elif opposite_result == 'B':
                data['banker_wins'] += 1
            log_activity(user_id, "feedback", f"{recommendation}:loss")
            log_result(user_id, recommendation, "loss")
            should_analyze = True

        # --- 분석 및 UI 업데이트 ---
        if should_analyze:
            last_col, total_pages = _get_page_info(data['history'])
            data['page'] = max(0, total_pages - 1)
            image_path = create_big_road_image(user_id)
            try:
                await query.edit_message_media(
                    media=InputMediaPhoto(media=open(image_path, 'rb'),
                                          caption=build_caption_text(user_id, is_analyzing=True),
                                          parse_mode=ParseMode.MARKDOWN_V2),
                    reply_markup=build_keyboard(user_id)
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"분석 중 표시 오류: {e}")

            conn = get_db_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT recommendation, outcome FROM results_log WHERE user_id=?", (user_id,))
            records = [{'recommendation': r[0], 'outcome': r[1]} for r in cursor.fetchall()]
            conn.close()

            history_str = ", ".join(data['history'])
            new_recommendation = get_gpt4_recommendation(history_str, records)
            data['recommendation'] = new_recommendation
            data['recommendation_info'] = {'bet_on': new_recommendation,
                                           'at_round': len([h for h in data['history'] if h != 'T'])}

        if update_ui_only or should_analyze:
            try:
                image_path = create_big_road_image(user_id)
                await query.edit_message_media(
                    media=InputMediaPhoto(media=open(image_path, 'rb'),
                                          caption=build_caption_text(user_id, is_analyzing=False),
                                          parse_mode=ParseMode.MARKDOWN_V2),
                    reply_markup=build_keyboard(user_id)
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    print(f"메시지 수정 오류: {e}")

# --- 메인 ---
def main() -> None:
    setup_database()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
