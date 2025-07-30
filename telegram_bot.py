# telegram_bot.py (Final Complete Version)

import os
import json
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.constants import ParseMode
from PIL import Image, ImageDraw, ImageFont # 이미지 생성을 위한 Pillow 라이브러리

# --- 설정 ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
user_data = {}

# --- 이미지 생성 함수 ---
def create_big_road_image(history):
    cell_size = 22
    rows, cols = 6, 60
    width = cols * cell_size
    height = rows * cell_size
    
    img = Image.new('RGB', (width, height), color = '#f4f6f9')
    draw = ImageDraw.Draw(img)

    for r in range(rows + 1):
        draw.line([(0, r * cell_size), (width, r * cell_size)], fill='lightgray')
    for c in range(cols + 1):
        draw.line([(c * cell_size, 0), (c * cell_size, height)], fill='lightgray')

    if history:
        col, row = -1, 0
        last_winner = None
        last_bead_pos = None

        for winner in history:
            if winner == 'T':
                if last_bead_pos:
                    r, c = last_bead_pos
                    draw.line([(c * cell_size + 5, r * cell_size + 5), ((c+1) * cell_size - 5, (r+1) * cell_size - 5)], fill='#2ecc71', width=2)
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
                draw.ellipse([(col * cell_size + 3, row * cell_size + 3), ((col+1) * cell_size - 3, (r+1) * cell_size - 3)], outline=color, width=3)
                last_bead_pos = (row, col)
            
            last_winner = winner
    
    image_path = "baccarat_road.png"
    img.save(image_path)
    return image_path

# --- GPT-4 분석 함수 ---
def get_gpt4_recommendation(history):
    prompt = f"Baccarat history: {history}. Recommend Player or Banker."
    try:
        completion = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        rec = completion.choices[0].message.content
        return "Banker" if "Banker" in rec else "Player"
    except Exception as e:
        print(f"GPT-4 API Error: {e}")
        return "Banker"

# --- 캡션 구성 함수 ---
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

# --- 키보드 생성 함수 ---
def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 플레이어 승리", callback_data='P'), InlineKeyboardButton("🔴 뱅커 승리", callback_data='B')],
        [InlineKeyboardButton("🟢 타이 (Tie)", callback_data='T')],
        [InlineKeyboardButton("🔍 분석 후 베팅 추천", callback_data='analyze'), InlineKeyboardButton("🔄 초기화", callback_data='reset')]
    ])

# --- 텔레그램 명령어 및 버튼 처리 함수 ---
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'player_wins': 0, 'banker_wins': 0, 'history': [], 'recommendation': None}
    
    image_path = create_big_road_image([])
    await update.message.reply_photo(
        photo=open(image_path, 'rb'),
        caption=build_caption_text(user_id),
        reply_markup=build_keyboard(),
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
        await query.edit_message_media(media=media, reply_markup=build_keyboard())

        history_str = ", ".join(data['history'])
        recommendation = get_gpt4_recommendation(history_str)
        data['recommendation'] = recommendation
        is_analyzing = False

    image_path = create_big_road_image(data['history'])
    media = InputMediaPhoto(media=open(image_path, 'rb'), caption=build_caption_text(user_id, is_analyzing=is_analyzing), parse_mode=ParseMode.MARKDOWN_V2)
    await query.edit_message_media(media=media, reply_markup=build_keyboard())

# --- 봇 실행 메인 함수 ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    print("텔레그램 봇이 시작되었습니다...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
