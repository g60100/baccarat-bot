# 이후 관리자 페이지를 위해서 1단계 데이터베이스 정리 / 2단계 텔레그램 봇에 데이터 로깅 기능 추가 완성
# 3단계 Flask로 관리자 웹페이지 만들기 / 4단계: 관리자 페이지 화면(HTML) 만들기 / 5단계: 서버에 함께 배포하기는 추가 예정
# 옆으로 행이 20칸이 넘어가면 다음 버튼 생성
# AI가 분석해 준 베팅이 맞으면 구슬 안쪽을 채워서 표시
# 젠트라 사용 순서
# 한글 글자 수정 적용
## 최종 기능 점검 리스트
# 1 & 2. 데이터베이스 및 로깅 기능: 포함됨
# 페이지 버튼 생성 (20칸 기준): 포함됨
# AI 추천 적중 시 구슬 채우기: 포함됨 / AI가 추천한 것이 맞으면 추천한 마지막 기존 구술에 색을 채우고(신규구술등록아님) / 틀렸으면 반대 구술을 안에 색이 없이 내려가는 줄은 내려가는 줄에, 안 내려가면 옆으로 등록해줘
# 안내 문구 및 한글 수정: 포함됨
# 오류 및 안정성: 점검 완료
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
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# --- 환경설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DB_FILE = "baccarat_stats.db"
COLS_PER_PAGE = 20

# --- 전역 변수 초기화 ---
client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}
user_locks = defaultdict(asyncio.Lock)


# --- 데이터베이스 관련 함수 ---
def get_db_conn():
    """안전한 SQLite 연결을 반환하는 함수 (WAL 모드 활성화)"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def safe_db_write(query, params=()):
    """DB 쓰기 작업을 재시도 로직과 함께 안전하게 실행하는 함수"""
    retries, delay = 5, 1
    for i in range(retries):
        try:
            with get_db_conn() as conn:
                conn.execute(query, params)
                return
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                time.sleep(delay * (i + 1))
            else:
                raise
    raise RuntimeError("DB write lock이 지속적으로 발생하여 작업을 중단합니다.")

def setup_database():
    """프로그램 시작 시 필요한 모든 DB 테이블을 생성하는 함수"""
    with get_db_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_seen TEXT, last_seen TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS activity (activity_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, timestamp TEXT, action TEXT, details TEXT)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS results_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            recommendation TEXT, outcome TEXT, created DATETIME)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reset_time DATETIME)"""
        )

def log_activity(user_id, action, details=""):
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_db_write(
        "INSERT INTO activity (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
        (user_id, dt, action, details),
    )

def log_result(user_id, recommendation, outcome):
    dt = datetime.datetime.now()
    safe_db_write(
        "INSERT INTO results_log (user_id, recommendation, outcome, created) VALUES (?, ?, ?, ?)",
        (user_id, recommendation, outcome, dt),
    )

def log_reset(user_id):
    dt = datetime.datetime.now()
    safe_db_write(
        "INSERT INTO resets (user_id, reset_time) VALUES (?, ?)", (user_id, dt)
    )

def get_feedback_stats(user_id):
    """초기화 시점 이후의 승/패 통계를 가져오는 함수"""
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT reset_time FROM resets WHERE user_id=? ORDER BY reset_time DESC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        last_reset = row[0] if row else None

        query = "SELECT outcome, COUNT(*) FROM results_log WHERE user_id=? "
        params = [user_id]
        if last_reset:
            query += "AND created >= ? "
            params.append(last_reset)
        query += "GROUP BY outcome"
        
        cursor.execute(query, tuple(params))
        
        stats = {"win": 0, "loss": 0}
        for outcome, count in cursor.fetchall():
            if outcome in ["win", "loss"]:
                stats[outcome] = count
    return stats


# --- 유틸리티 및 이미지 생성 함수 ---
def escape_markdown(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-.=|{}!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)

def _get_page_info(history):
    if not history:
        return -1, 1
    last_col = -1
    last_winner = None
    for winner in history:
        if winner == "T": continue
        if winner != last_winner:
            last_col += 1
        last_winner = winner
    total_cols = last_col + 1
    total_pages = math.ceil(total_cols / COLS_PER_PAGE) if COLS_PER_PAGE > 0 else 1
    return last_col, max(1, total_pages)

# --- 빅로드 이미지 생성 ---
def create_big_road_image(user_id):
    data = user_data.get(user_id, {})
    history = data.get("history", [])
    page = data.get("page", 0)
    correct_indices = data.get("correct_indices", [])

    cell_size, rows, full_grid_cols = 22, 6, 120
    full_grid = [[""] * full_grid_cols for _ in range(rows)]
    last_positions = {}
    pb_history_index = -1
    col, row = -1, 0

    if history:
        last_winner = None
        for i, winner in enumerate(history):
            if winner == "T":
                if last_winner and last_winner in last_positions:
                    r_pos, c_pos = last_positions[last_winner]
                    if c_pos < full_grid_cols and full_grid[r_pos][c_pos]:
                        full_grid[r_pos][c_pos] += "T"
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
                is_correct = "C" if pb_history_index in correct_indices else ""
                full_grid[row][col] = winner + is_correct
                last_positions[winner] = (row, col)
            last_winner = winner

    start_col = page * COLS_PER_PAGE
    page_grid = [row[start_col : start_col + COLS_PER_PAGE] for row in full_grid]
    
    # [수정] 변수 선언을 여러 줄로 분리하여 UnboundLocalError 해결
    top_padding = 30
    width = COLS_PER_PAGE * cell_size
    height = rows * cell_size + top_padding
    
    img = Image.new("RGB", (width, height), color="#f4f6f9")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()

    _, total_pages = _get_page_info(history)
    draw.text((10, 5), f"ZENTRA AI - Big Road (Page {page + 1} / {total_pages})", fill="black", font=font)

    for r in range(rows):
        for c in range(COLS_PER_PAGE):
            x1, y1 = c * cell_size, r * cell_size + top_padding
            x2, y2 = (c + 1) * cell_size, (r + 1) * cell_size + top_padding
            draw.rectangle([(x1, y1), (x2, y2)], outline="lightgray")
            cell_data = page_grid[r][c]
            if cell_data:
                winner_char, is_correct = cell_data[0], "C" in cell_data
                color = "#3498db" if winner_char == "P" else "#e74c3c"
                ellipse_coords = [(x1 + 3, y1 + 3), (x2 - 3, y2 - 3)]
                if is_correct:
                    draw.ellipse(ellipse_coords, fill=color, outline=color, width=2)
                else:
                    draw.ellipse(ellipse_coords, outline=color, width=2)
                if "T" in cell_data:
                    draw.line([(x1 + 5, y1 + 5), (x2 - 5, y2 - 5)], fill="#2ecc71", width=2)
    
    image_path = f"baccarat_road_{user_id}.png"
    img.save(image_path)
    return image_path


# --- AI 및 UI 관련 함수 ---
def get_gpt4_recommendation(user_id, game_history):
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT recommendation, outcome FROM results_log WHERE user_id=?", (user_id,))
        ai_performance_history = [{"recommendation": r[0], "outcome": r[1]} for r in cursor.fetchall()]

    performance_text = "기록된 추천 실적이 없습니다."
    if ai_performance_history:
        performance_text = "아래는 당신(AI)의 과거 추천 기록과 그 실제 결과입니다:\n"
        for i, record in enumerate(ai_performance_history[-10:]):
            outcome_text = "승리" if record.get("outcome") == "win" else "패배"
            performance_text += f"{i+1}. 추천: {record.get('recommendation', 'N/A')}, 실제 결과: {outcome_text}\n"
    
    # [수정] 사용자님의 경험을 AI에게 지시하는 프롬프트 항목 추가
    prompt = f"""
    당신은 세계 최고의 50년 경력의 바카라 데이터 분석가입니다. 당신의 임무는 주어진 데이터를 분석하여 가장 확률 높은 다음 베팅을 추천하는 것입니다.

    [데이터 1: 현재 게임의 흐름]
    {game_history}

    [데이터 2: 당신의 과거 추천 실적]
    {performance_text}

    [데이터 3: 베팅 전략 추가 지침 (사용자 경험)]
    1. 단순히 마지막 결과를 따라가는 추천은 절대 지양한다.
    2. 플레이어든 뱅커든, 한쪽의 결과가 5번 이상 연속되면(장줄), 반대 결과가 나올 확률을 더 높게 고려한다.
    3. 플레이어와 뱅커가 번갈아 나오는 전환(일명 '퐁당' 또는 'chop') 패턴이 나타나는지 주의 깊게 살핀다.
    4. 전체적인 흐름을 보고, 연속(streak) 패턴과 전환(chop) 패턴 중 현재 어떤 패턴이 더 우세한지 판단하여 추천한다.

    [분석 및 추천]
    위 3가지 데이터와 지침을 종합적으로 분석하여, 최종 추천을 "추천:" 이라는 단어 뒤에 Player 또는 Banker 로만 결론내려주십시오.
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a world-class Baccarat analyst with 50 years of experience who provides deep strategic reasoning."},
                {"role": "user", "content": prompt},
            ],
        )
        response = completion.choices[0].message.content
        part = response.split("추천:")[-1] if "추천:" in response else response
        
        if "Player" in part or "플레이어" in part: return "Player"
        if "Banker" in part or "뱅커" in part: return "Banker"
        return "Banker" # 명확한 단어가 없으면 기본값으로 Banker 반환
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return None

def build_caption_text(user_id, is_analyzing=False):
    data = user_data.get(user_id, {})
    player_wins, banker_wins = data.get("player_wins", 0), data.get("banker_wins", 0)
    recommendation = data.get("recommendation", None)
    feedback_stats = get_feedback_stats(user_id)
    guide_text = "...\n(처음 시작 시 P나 B를 선택 후 '자동분석시작'을 클릭하세요.)\n..."
    
    rec_text = ""
    if is_analyzing:
        rec_text = f"\n\n👇 *AI 추천* 👇\n_{escape_markdown('AI가 분석 중입니다...')}_"
    elif recommendation:
        rec_text = f"\n\n👇 *AI 추천* 👇\n{'🔴' if recommendation == 'Banker' else '🔵'} *{escape_markdown(recommendation + '에 베팅참조하세요.')}*"
    
    title = escape_markdown("ZENTRA 개발 Chet GPT-4o AI 분석기")
    subtitle = escape_markdown("베팅 결정과 결과의 책임은 본인에게 있습니다.")
    win_count, loss_count = feedback_stats.get("win", 0), feedback_stats.get("loss", 0)
    
    return (
        f"*{title}*\n{subtitle}\n\n{escape_markdown(guide_text)}\n\n"
        f"*플레이어: {player_wins}* ┃ *뱅커: {banker_wins}*{rec_text}\n\n"
        f'✅ AI "승": {win_count} ┃ ❌ AI "패": {loss_count}'
    )

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    page, history = data.get("page", 0), data.get("history", [])
    _, total_pages = _get_page_info(history)
    auto_analysis = data.get("auto_analysis_enabled", True)
    
    page_buttons = []
    if total_pages > 1:
        if page > 0: page_buttons.append(InlineKeyboardButton("⬅️ 이전", callback_data="page_prev"))
        if page < total_pages - 1: page_buttons.append(InlineKeyboardButton("다음 ➡️", callback_data="page_next"))

    keyboard = [
        [InlineKeyboardButton("🔵 P", callback_data="P"), InlineKeyboardButton("🔴 B", callback_data="B")],
        [InlineKeyboardButton("🔔 자동분석중 ON" if auto_analysis else "🔕 자동 분석 OFF", callback_data="toggle_auto_analysis"),
         InlineKeyboardButton("🟢 T", callback_data="T")],
    ]
    if page_buttons: keyboard.append(page_buttons)
    keyboard.append([
        InlineKeyboardButton("🔍자동 분석 시작", callback_data="analyze"),
        InlineKeyboardButton("🔄기록 초기화", callback_data="reset"),
    ])

    if data.get("recommendation"):
        stats = get_feedback_stats(user_id)
        keyboard.append([
            InlineKeyboardButton(f'✅AI 분석 승({stats["win"]})', callback_data="feedback_win"),
            InlineKeyboardButton(f'❌AI 분석 패({stats["loss"]})', callback_data="feedback_loss"),
        ])
    return InlineKeyboardMarkup(keyboard)


# --- 텔레그램 핸들러 ---
async def update_message(context, query, user_id, is_analyzing=False):
    """메시지(사진, 캡션, 키보드)를 업데이트하는 헬퍼 함수"""
    try:
        image_path = create_big_road_image(user_id)
        media = InputMediaPhoto(
            media=open(image_path, "rb"),
            caption=build_caption_text(user_id, is_analyzing=is_analyzing),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))
    except Exception as e:
        if "Message is not modified" not in str(e):
            print(f"메시지 업데이트 오류: {e}")

async def run_analysis(user_id):
    """AI 분석을 실행하고 user_data를 업데이트하는 함수"""
    data = user_data.get(user_id)
    if not data: return
    
    history_str = ", ".join(data.get("history", []))
    new_recommendation = get_gpt4_recommendation(user_id, history_str)
    
    if new_recommendation:
        data["recommendation"] = new_recommendation
        data["recommendation_info"] = {
            "bet_on": new_recommendation,
            "at_round": len([h for h in data.get("history", []) if h != "T"]),
        }

async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    log_activity(user.id, "start")
    # [수정] auto_analysis_enabled의 기본값을 False로 변경
    user_data[user.id] = {
        "player_wins": 0, "banker_wins": 0, "history": [], "recommendation": None,
        "page": 0, "correct_indices": [], "auto_analysis_enabled": False,
    }
    image_path = create_big_road_image(user.id)
    await update.message.reply_photo(
        photo=open(image_path, "rb"),
        caption=build_caption_text(user.id),
        reply_markup=build_keyboard(user.id),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

# --- 버튼 콜백 ---
async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    lock = user_locks[user_id]
    if lock.locked():
        return

    async with lock:
        if user_id not in user_data:
            user_data[user_id] = {
                "player_wins": 0, "banker_wins": 0, "history": [], "recommendation": None,
                "page": 0, "correct_indices": [], "auto_analysis_enabled": False,
            }

        data = user_data[user_id]
        action = query.data
        log_activity(user_id, "button_click", action)

        should_analyze = False
        update_ui_only = False

        if action in ["P", "B", "T"]:
            data["history"].append(action)
            if action == "P": data["player_wins"] += 1
            elif action == "B": data["banker_wins"] += 1
            data["recommendation"] = None
            if action in ["P", "B"] and data.get("auto_analysis_enabled", False):
                should_analyze = True
            else:
                update_ui_only = True
        
        elif action in ["feedback_win", "feedback_loss"]:
            rec_info = data.get("recommendation_info")
            if not rec_info: return
            
            recommendation = rec_info["bet_on"]
            outcome = "win" if action == "feedback_win" else "loss"
            log_result(user_id, recommendation, outcome)

            if outcome == "win":
                result_to_add = "P" if recommendation == "Player" else "B"
                pb_history = [h for h in data["history"] if h != "T"]
                data.setdefault("correct_indices", []).append(len(pb_history))
            else:
                result_to_add = "P" if recommendation == "Banker" else "B"
            
            data["history"].append(result_to_add)
            if result_to_add == "P": data["player_wins"] += 1
            else: data["banker_wins"] += 1
            should_analyze = True

        elif action == "reset":
            log_reset(user_id)
            user_data[user_id].update({
                "player_wins": 0, "banker_wins": 0, "history": [], "recommendation": None,
                "page": 0, "correct_indices": [], "auto_analysis_enabled": False,
            })
            update_ui_only = True
            
        elif action == "toggle_auto_analysis":
            data["auto_analysis_enabled"] = not data.get("auto_analysis_enabled", False)
            if not data["auto_analysis_enabled"]:
                 data["recommendation"] = None
                 data["recommendation_info"] = None
            update_ui_only = True

        elif action in ["page_next", "page_prev"]:
            if action == "page_next": data["page"] += 1
            else: data["page"] = max(0, data["page"] - 1)
            update_ui_only = True

        elif action == "analyze":
            if not data["history"]: return
            # [수정] 수동 분석 요청 시, 자동 분석을 ON으로 변경
            data["auto_analysis_enabled"] = True
            should_analyze = True
        
        if action in ["P", "B", "T", "feedback_win", "feedback_loss"]:
             _, total_pages = _get_page_info(data["history"])
             data["page"] = max(0, total_pages - 1)

        # --- UI 업데이트 및 분석 실행 ---
        if should_analyze:
            await update_message(context, query, user_id, is_analyzing=True)
            await run_analysis(user_id)
            await update_message(context, query, user_id, is_analyzing=False)
        elif update_ui_only:
            await update_message(context, query, user_id, is_analyzing=False)

# --- 메인 실행 ---
def main() -> None:
    if not all([OPENAI_API_KEY, TELEGRAM_BOT_TOKEN]):
        print("ERROR: 환경변수 OPENAI_API_KEY, TELEGRAM_BOT_TOKEN 설정이 필요합니다.")
        return
    
    setup_database()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()