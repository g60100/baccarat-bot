# telegram_bot.py (Final Version with Meta-Learning)

import os
import json
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
RESULTS_LOG_FILE = 'results_log.json' # AI의 추천 및 결과 기록 파일

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}

# --- 초기화 ---
if not os.path.exists(RESULTS_LOG_FILE):
    with open(RESULTS_LOG_FILE, 'w') as f:
        json.dump([], f)

# --- 데이터 로드 함수 ---
def load_results():
    try:
        with open(RESULTS_LOG_FILE, 'r') as f: return json.load(f)
    except: return []

# --- 이미지 생성 함수 ---
def create_big_road_image(history):
    cell_size = 22
    rows, cols = 6, 25
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
    draw.text((10, 5), "ZENTRA AI - Big Road", fill="black", font=font)

    for r in range(rows + 1):
        draw.line([(0, r * cell_size + top_padding), (width, r * cell_size + top_padding)], fill='lightgray')
    for c in range(cols + 1):
        draw.line([(c * cell_size, top_padding), (c * cell_size, height - bottom_padding)], fill='lightgray')

    if history:
        col, row = -1, 0
        last_winner = None
        last_bead_pos = None

        for winner in history:
            if winner == 'T':
                if last_bead_pos:
                    r_pos, c_pos = last_bead_pos
                    draw.line([(c_pos * cell_size + 5, r_pos * cell_size + 5 + top_padding), ((c_pos + 1) * cell_size - 5, (r_pos + 1) * cell_size - 5 + top_padding)], fill='#2ecc71', width=2)
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
                x1 = col * cell_size + 3
                y1 = row * cell_size + 3 + top_padding
                x2 = (col + 1) * cell_size - 3
                y2 = (row + 1) * cell_size - 3 + top_padding
                draw.ellipse([(x1, y1), (x2, y2)], outline=color, width=3)
                last_bead_pos = (row, col)
            
            last_winner = winner
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path

# --- GPT-4 분석 함수 (PC버전과 동일한 로직) ---
def get_gpt4_recommendation(game_history, ai_performance_history):
    performance_text = "아직 나의 추천 기록이 없습니다."
    if ai_performance_history:
        performance_text = "아래는 당신(AI)의 과거 추천 기록과 그 실제 결과입니다:\n"
        for i, record in enumerate(ai_performance_history[-10:]):
            outcome_text = '승리' if record.get('outcome') == 'win' else '패배'
            performance_text += f"{i+1}. 추천: {record.get('recommendation', 'N/A')}, 실제 결과: {outcome_text}\n"

    prompt = f"""
    당신은 세계 최고의 바카라 데이터 분석가이며, 자신의 과거 판단을 복기하여 전략을 수정하는 능력이 뛰어납니다.
    주어진 두 가지 데이터를 모두 입체적으로 분석하여 다음 베팅을 추천해야 합니다.

    [데이터 1: 현재 게임의 흐름]
    'P'는 플레이어 승, 'B'는 뱅커 승리를 의미합니다.
    {game_history}

    [데이터 2: 당신의 과거 추천 실적]
    {performance_text}

    이제 [데이터 1]의 게임 흐름과 [데이터 2]의 당신의 실적을 모두 고려하세요. 
    만약 당신의 추천이 계속 틀리고 있다면, 그 패턴을 깨는 새로운 추천을 해야 합니다.
    모든 것을 종합하여 다음 라운드에 가장 유리한 베팅(Player 또는 Banker)을 하나만 추천해주세요.
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 자신의 과거 실적을 복기하여 전략을 수정하는 지능적인 바카라 분석가입니다."},
                {"role": "user", "content": prompt}
            ]
        )
        recommendation = completion.choices[0].message.content
        return "Banker" if "Banker" in recommendation else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 캡션 및 키보드 생성 함수 ---
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

def build_keyboard(user_id):
    data = user_data.get(user_id, {})
    recommendation = data.get('recommendation', None)
    
    keyboard = [
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ]
    if recommendation:
        keyboard.append([
            InlineKeyboardButton("✅ 추천대로 승리", callback_data='feedback_win'),
            InlineKeyboardButton("❌ 추천대로 패배", callback_data='feedback_loss')
        ])
    return InlineKeyboardMarkup(keyboard)

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    image_path = create_big_road_image([])
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
        await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))

        ai_performance_history = load_results()
        history_str = ", ".join(data['history'])
        recommendation = get_gpt4_recommendation(history_str, ai_performance_history)
        data['recommendation'] = recommendation
        is_analyzing = False
    
    elif action in ['feedback_win', 'feedback_loss']:
        if data.get('recommendation'):
            outcome = 'win' if action == 'feedback_win' else 'loss'
            results = load_results()
            results.append({
                "recommendation": data['recommendation'],
                "outcome": outcome
            })
            with open(RESULTS_LOG_FILE, 'w') as f:
                json.dump(results, f, indent=2)
            
            await context.bot.answer_callback_query(query.id, text=f"피드백({outcome})을 학습했습니다!")
            data['recommendation'] = None
        else:
            await context.bot.answer_callback_query(query.id, text="피드백할 추천 결과가 없습니다.")

    image_path = create_big_road_image(data['history'])
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
    await query.edit_message_media(media=media, reply_markup=build_keyboard(user_id))

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
