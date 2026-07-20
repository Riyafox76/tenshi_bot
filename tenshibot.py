import logging
import sqlite3
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageOps
import io
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8658625238:AAGIfOAz3cuVBUNrjvOinFK_2QGpoiVihvk"
ADMIN_ID = 5145527096

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class CreatePack(StatesGroup):
    waiting_for_images = State()
    waiting_for_pack_name = State()
    waiting_for_emoji_images = State()
    waiting_for_emoji_pack_name = State()
    waiting_for_palette = State()
    waiting_for_preview = State()

# ========== БАЗА ЭМОДЗИ-КОНВЕРТАЦИИ ==========
LETTER_TO_EMOJI = {
    'a': '🇦', 'b': '🇧', 'c': '🇨', 'd': '🇩', 'e': '🇪',
    'f': '🇫', 'g': '🇬', 'h': '🇭', 'i': '🇮', 'j': '🇯',
    'k': '🇰', 'l': '🇱', 'm': '🇲', 'n': '🇳', 'o': '🇴',
    'p': '🇵', 'q': '🇶', 'r': '🇷', 's': '🇸', 't': '🇹',
    'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽', 'y': '🇾', 'z': '🇿'
}

TEXT_TO_EMOJI = {
    ':heart:': '❤️', ':fire:': '🔥', ':cat:': '🐱', ':dog:': '🐶',
    ':star:': '⭐', ':rainbow:': '🌈', ':unicorn:': '🦄', ':rocket:': '🚀',
    ':sparkles:': '✨', ':thumbsup:': '👍', ':smile:': '😊', ':laugh:': '😂',
    ':love:': '🥰', ':cool:': '😎', ':cry:': '😢', ':angry:': '😡',
    ':surprised:': '😮', ':sleep:': '😴', ':pray:': '🙏'
}

FONT_STYLES = {
    '𝒽ℯ𝓁𝓁ℴ': 'математический',
    '𝕙𝕖𝕝𝕝𝕠': 'двойной',
    'ᕼᗴᒪᒪᗝ': 'канадский',
    'ʜᴇʟʟᴏ': 'капитель',
    '🅷🅴🅻🅻🅾': 'кружочки'
}

DESIGN_TIPS = {
    'синий': '💡 К синему отлично подходят:\n• Оранжевый (#FFA500) — для контраста\n• Белый (#FFFFFF) — для чистоты\n• Желтый (#FFD700) — для теплоты\n• Фиолетовый (#8B00FF) — для глубины',
    'красный': '💡 К красному отлично подходят:\n• Белый — для контраста\n• Черный — для строгости\n• Золотой — для роскоши',
    'зеленый': '💡 К зеленому отлично подходят:\n• Белый — для свежести\n• Коричневый — для натуральности\n• Желтый — для яркости',
    'черный': '💡 К черному отлично подходят:\n• Белый — классика\n• Золотой — роскошь\n• Красный — акцент',
    'белый': '💡 К белому отлично подходят:\n• Любой цвет! Но особенно:\n• Черный — контраст\n• Золотой — элегантность\n• Пастельные тона — нежность'
}

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('packs.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pack_name TEXT UNIQUE,
            pack_link TEXT,
            sticker_count INTEGER,
            created_at TEXT,
            creator_id INTEGER,
            pack_type TEXT DEFAULT 'sticker'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_stickers (
            user_id INTEGER,
            file_id TEXT,
            position INTEGER,
            pack_type TEXT DEFAULT 'sticker'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return user_id == ADMIN_ID

def convert_to_sticker(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    width, height = img.size
    new_size = min(width, height)
    left = (width - new_size) / 2
    top = (height - new_size) / 2
    right = (width + new_size) / 2
    bottom = (height + new_size) / 2
    img = img.crop((left, top, right, bottom))
    
    img = img.resize((512, 512), Image.Resampling.LANCZOS)
    
    output = io.BytesIO()
    img.save(output, format='webp', quality=95)
    output.seek(0)
    return output.getvalue()

def get_pack_link(pack_name, pack_type='sticker'):
    if pack_type == 'emoji':
        return f"https://t.me/addemojiset/{pack_name}"
    return f"https://t.me/addstickers/{pack_name}"

def text_to_emoji(text):
    text = text.lower().strip()
    
    if text in TEXT_TO_EMOJI:
        return TEXT_TO_EMOJI[text]
    
    result = []
    for char in text:
        if char in LETTER_TO_EMOJI:
            result.append(LETTER_TO_EMOJI[char])
        elif char == ' ':
            result.append('  ')
        else:
            result.append(char)
    
    return ' '.join(result) if result else '❓ Неизвестный текст'

def get_font_variants(text):
    """Превращает текст в разные стили"""
    variants = []
    
    # Математический стиль
    math_map = {'a':'𝒶','b':'𝒷','c':'𝒸','d':'𝒹','e':'ℯ','f':'𝒻','g':'ℊ','h':'𝒽','i':'𝒾','j':'𝒿','k':'𝓀','l':'𝓁','m':'𝓂','n':'𝓃','o':'ℴ','p':'𝓅','q':'𝓆','r':'𝓇','s':'𝓈','t':'𝓉','u':'𝓊','v':'𝓋','w':'𝓌','x':'𝓍','y':'𝓎','z':'𝓏'}
    math_text = ''.join([math_map.get(c, c) for c in text.lower()])
    variants.append(math_text)
    
    # Двойной стиль
    double_map = {'a':'𝕒','b':'𝕓','c':'𝕔','d':'𝕕','e':'𝕖','f':'𝕗','g':'𝕘','h':'𝕙','i':'𝕚','j':'𝕛','k':'𝕜','l':'𝕝','m':'𝕞','n':'𝕟','o':'𝕠','p':'𝕡','q':'𝕢','r':'𝕣','s':'𝕤','t':'𝕥','u':'𝕦','v':'𝕧','w':'𝕨','x':'𝕩','y':'𝕪','z':'𝕫'}
    double_text = ''.join([double_map.get(c, c) for c in text.lower()])
    variants.append(double_text)
    
    # Капитель (верхний регистр)
    cap_text = text.upper()
    variants.append(cap_text)
    
    # Кружочки
    circle_map = {'a':'🅐','b':'🅑','c':'🅒','d':'🅓','e':'🅔','f':'🅕','g':'🅖','h':'🅗','i':'🅘','j':'🅙','k':'🅚','l':'🅛','m':'🅜','n':'🅝','o':'🅞','p':'🅟','q':'🅠','r':'🅡','s':'🅢','t':'🅣','u':'🅤','v':'🅥','w':'🅦','x':'🅧','y':'🅨','z':'🅩'}
    circle_text = ''.join([circle_map.get(c, c) for c in text.lower()])
    variants.append(circle_text)
    
    return variants

def extract_colors(image_bytes, num_colors=5):
    """Вырезает главные цвета из картинки"""
    img = Image.open(io.BytesIO(image_bytes))
    
    # Уменьшаем для скорости
    img = img.resize((100, 100))
    img = img.convert('RGB')
    
    # Получаем цвета
    pixels = list(img.getdata())
    
    # Простой алгоритм кластеризации
    colors = []
    for pixel in pixels:
        if len(colors) < num_colors:
            colors.append(pixel)
        else:
            # Ищем ближайший цвет
            min_dist = float('inf')
            min_idx = 0
            for i, c in enumerate(colors):
                dist = sum((pixel[j] - c[j])**2 for j in range(3))
                if dist < min_dist:
                    min_dist = dist
                    min_idx = i
            # Если далеко от всех — заменяем самый старый
            if min_dist > 10000:
                colors[min_idx] = pixel
    
    # Конвертируем в HEX
    hex_colors = []
    for r, g, b in colors:
        hex_color = f"#{r:02x}{g:02x}{b:02x}".upper()
        hex_colors.append((hex_color, r, g, b))
    
    return hex_colors

def create_preview(image_bytes):
    """Создает превью стикера в кружочке"""
    img = Image.open(io.BytesIO(image_bytes))
    
    # Приводим к квадрату
    size = min(img.size)
    left = (img.width - size) // 2
    top = (img.height - size) // 2
    img = img.crop((left, top, left + size, top + size))
    img = img.resize((400, 400))
    
    # Создаем фон
    preview = Image.new('RGBA', (500, 500), (50, 50, 50, 255))
    
    # Делаем круглую маску
    mask = Image.new('L', (400, 400), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, 400, 400), fill=255)
    
    # Применяем маску
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Вставляем в центр фона
    preview.paste(img, (50, 50), mask)
    
    output = io.BytesIO()
    preview.save(output, format='png')
    output.seek(0)
    return output

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "🎨 Привет, Создатель!\n\n"
            "📦 **Стикеры и эмодзи:**\n"
            "/newpack - Создать пак стикеров\n"
            "/newemoji - Создать пак эмодзи\n"
            "/get [название] - Получить пак\n"
            "/list - Мои паки\n"
            "/delete [название] - Удалить пак\n"
            "/stats - Статистика\n\n"
            "🎨 **Дизайн-инструменты:**\n"
            "/palette - Вырезать цвета из картинки\n"
            "/preview - Показать стикер в кружке\n"
            "/font [текст] - Красивые шрифты\n"
            "/ask [вопрос] - Советы по дизайну\n\n"
            "📝 **Текст:**\n"
            "/maketext [текст] - Текст в эмодзи"
        )
    else:
        await message.answer(
            "👋 Привет!\n\n"
            "Я бот для стикеров, эмодзи и дизайна.\n"
            "Используй /get [название] чтобы получить пак."
        )

@dp.message(Command("palette"))
async def palette_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    await state.set_state(CreatePack.waiting_for_palette)
    await message.answer("🖼️ Кинь мне картинку, и я вырежу из неё 5 главных цветов!")

@dp.message(CreatePack.waiting_for_palette)
async def handle_palette(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if not message.photo and not message.document:
        await message.answer("❌ Кинь картинку!")
        return
    
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
        
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_data = file_bytes.read()
        
        colors = extract_colors(file_data)
        
        # Формируем ответ
        response = "🎨 **Твоя палитра:**\n\n"
        for hex_color, r, g, b in colors:
            response += f"{hex_color} 🎨 RGB({r}, {g}, {b})\n"
        
        # Добавляем цветные квадратики
        for hex_color, _, _, _ in colors:
            response += f"`{hex_color}` "
        
        await message.answer(response, parse_mode="Markdown")
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("preview"))
async def preview_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    await state.set_state(CreatePack.waiting_for_preview)
    await message.answer("🖼️ Кинь мне картинку или стикер, и я покажу, как он выглядит в чате!")

@dp.message(CreatePack.waiting_for_preview)
async def handle_preview(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if not message.photo and not message.document and not message.sticker:
        await message.answer("❌ Кинь картинку или стикер!")
        return
    
    try:
        if message.sticker:
            file_id = message.sticker.file_id
        elif message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
        
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_data = file_bytes.read()
        
        preview_bytes = create_preview(file_data)
        
        await message.answer_photo(
            types.BufferedInputFile(preview_bytes.getvalue(), filename="preview.png"),
            caption="🖼️ Вот как будет выглядеть твой стикер в чате!"
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("font"))
async def font_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    text = message.text.replace('/font', '').strip()
    if not text:
        await message.answer("📝 Напиши текст после команды:\n/font hello")
        return
    
    variants = get_font_variants(text)
    
    response = "✨ **Красивые стили:**\n\n"
    for i, variant in enumerate(variants):
        style_name = ["Математический", "Двойной", "Капитель", "Кружочки"][i] if i < 4 else "Стиль"
        response += f"**{style_name}:** {variant}\n"
    
    await message.answer(response, parse_mode="Markdown")

@dp.message(Command("ask"))
async def ask_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    question = message.text.replace('/ask', '').strip()
    if not question:
        await message.answer(
            "❓ Напиши вопрос после команды:\n"
            "/ask какой цвет подойдет к синему?\n\n"
            "Я знаю про цвета: синий, красный, зеленый, черный, белый"
        )
        return
    
    # Ищем ключевые слова
    response = None
    for color in DESIGN_TIPS:
        if color in question.lower():
            response = DESIGN_TIPS[color]
            break
    
    if response:
        await message.answer(response)
    else:
        await message.answer(
            "🤔 Я пока знаю советы только про цвета.\n"
            "Попробуй спросить про: синий, красный, зеленый, черный, белый.\n\n"
            "Пример: /ask какой цвет подойдет к синему?"
        )

@dp.message(Command("maketext"))
async def make_text_emoji(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    text = message.text.replace('/maketext', '').strip()
    if not text:
        await message.answer(
            "📝 Напиши текст после команды:\n"
            "/maketext hello\n"
            "Или эмодзи-код:\n"
            "/maketext :heart:"
        )
        return
    
    result = text_to_emoji(text)
    await message.answer(f"✨ {result}")

@dp.message(Command("newemoji"))
async def new_emoji(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет прав создавать эмодзи.")
        return
    
    await state.set_state(CreatePack.waiting_for_emoji_images)
    await state.update_data(pack_type='emoji')
    await message.answer(
        "📸 Отправляй мне картинки для эмодзи (PNG с прозрачным фоном).\n"
        "Каждую картинку по отдельности.\n"
        "Когда закончишь, напиши /done"
    )

@dp.message(Command("newpack"))
async def new_pack(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У тебя нет прав создавать паки.")
        return
    
    await state.set_state(CreatePack.waiting_for_images)
    await state.update_data(pack_type='sticker')
    await message.answer(
        "📸 Отправляй мне картинки (PNG или JPG).\n"
        "Каждую картинку по отдельности.\n"
        "Когда закончишь, напиши /done"
    )

@dp.message(CreatePack.waiting_for_images)
async def handle_image(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text and message.text.lower() == '/done':
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM temp_stickers WHERE user_id = ?', (message.from_user.id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        if count == 0:
            await message.answer("❌ Ты не отправил ни одной картинки!")
            return
        
        await state.set_state(CreatePack.waiting_for_pack_name)
        await message.answer("📝 Придумай название для пака (латиницей, без пробелов, например: my_cool_pack):")
        return
    
    if not message.photo and not message.document:
        await message.answer("❌ Отправь картинку (фото или файл)")
        return
    
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
        
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_data = file_bytes.read()
        
        sticker_data = convert_to_sticker(file_data)
        
        temp_file = f"temp_{message.from_user.id}_{datetime.now().timestamp()}.webp"
        with open(temp_file, 'wb') as f:
            f.write(sticker_data)
        
        with open(temp_file, 'rb') as f:
            uploaded = await bot.upload_sticker_file(
                user_id=message.from_user.id,
                sticker=FSInputFile(temp_file),
                sticker_format="static"
            )
        
        os.remove(temp_file)
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO temp_stickers (user_id, file_id, position, pack_type)
            VALUES (?, ?, ?, ?)
        ''', (message.from_user.id, uploaded.file_id, 0, 'sticker'))
        conn.commit()
        conn.close()
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM temp_stickers WHERE user_id = ?', (message.from_user.id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        await message.answer(f"✅ Картинка #{count} сохранена! Отправляй следующую или напиши /done")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(CreatePack.waiting_for_emoji_images)
async def handle_emoji_image(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text and message.text.lower() == '/done':
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM temp_stickers WHERE user_id = ? AND pack_type = "emoji"', (message.from_user.id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        if count == 0:
            await message.answer("❌ Ты не отправил ни одной картинки для эмодзи!")
            return
        
        await state.set_state(CreatePack.waiting_for_emoji_pack_name)
        await message.answer("📝 Придумай название для эмодзи-пака (латиницей, без пробелов, например: my_cool_emojis):")
        return
    
    if not message.photo and not message.document:
        await message.answer("❌ Отправь картинку (фото или файл)")
        return
    
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
        else:
            file_id = message.document.file_id
        
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_data = file_bytes.read()
        
        sticker_data = convert_to_sticker(file_data)
        
        temp_file = f"temp_{message.from_user.id}_{datetime.now().timestamp()}.webp"
        with open(temp_file, 'wb') as f:
            f.write(sticker_data)
        
        with open(temp_file, 'rb') as f:
            uploaded = await bot.upload_sticker_file(
                user_id=message.from_user.id,
                sticker=FSInputFile(temp_file),
                sticker_format="static"
            )
        
        os.remove(temp_file)
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO temp_stickers (user_id, file_id, position, pack_type)
            VALUES (?, ?, ?, ?)
        ''', (message.from_user.id, uploaded.file_id, 0, 'emoji'))
        conn.commit()
        conn.close()
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM temp_stickers WHERE user_id = ? AND pack_type = "emoji"', (message.from_user.id,))
        count = cursor.fetchone()[0]
        conn.close()
        
        await message.answer(f"✅ Эмодзи #{count} сохранено! Отправляй следующее или напиши /done")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(CreatePack.waiting_for_pack_name)
async def handle_pack_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    pack_name = message.text.strip()
    
    if not pack_name or ' ' in pack_name:
        await message.answer("❌ Название должно быть без пробелов! Попробуй снова:")
        return
    
    try:
        data = await state.get_data()
        pack_type = data.get('pack_type', 'sticker')
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT file_id FROM temp_stickers WHERE user_id = ? ORDER BY position', (message.from_user.id,))
        stickers = cursor.fetchall()
        
        if len(stickers) < 3:
            await message.answer("❌ Нужно минимум 3 элемента для пака!")
            conn.close()
            await state.clear()
            return
        
        sticker_inputs = []
        for i, (file_id,) in enumerate(stickers):
            sticker_inputs.append(
                types.InputSticker(
                    sticker=file_id,
                    format="static",
                    emoji_list=["🎨"]
                )
            )
        
        pack_title = f"{'Emoji' if pack_type == 'emoji' else 'Pack'} by {message.from_user.first_name or 'Designer'}"
        
        if pack_type == 'emoji':
            await bot.create_new_emoji_sticker_set(
                user_id=message.from_user.id,
                name=pack_name,
                title=pack_title,
                stickers=sticker_inputs
            )
        else:
            await bot.create_new_sticker_set(
                user_id=message.from_user.id,
                name=pack_name,
                title=pack_title,
                stickers=sticker_inputs
            )
        
        pack_link = get_pack_link(pack_name, pack_type)
        cursor.execute('''
            INSERT INTO packs (pack_name, pack_link, sticker_count, created_at, creator_id, pack_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (pack_name, pack_link, len(stickers), datetime.now().isoformat(), message.from_user.id, pack_type))
        
        cursor.execute('DELETE FROM temp_stickers WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        conn.close()
        
        await message.answer(
            f"🎉 {'Эмодзи-пак' if pack_type == 'emoji' else 'Пак'} создан!\n\n"
            f"📦 Название: {pack_name}\n"
            f"📊 Элементов: {len(stickers)}\n"
            f"🔗 Ссылка: {pack_link}\n\n"
            f"Теперь другие могут получить его по команде:\n"
            f"/get {pack_name}"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании пака: {str(e)}")
    
    await state.clear()

@dp.message(CreatePack.waiting_for_emoji_pack_name)
async def handle_emoji_pack_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    pack_name = message.text.strip()
    
    if not pack_name or ' ' in pack_name:
        await message.answer("❌ Название должно быть без пробелов! Попробуй снова:")
        return
    
    try:
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT file_id FROM temp_stickers WHERE user_id = ? AND pack_type = "emoji" ORDER BY position', (message.from_user.id,))
        stickers = cursor.fetchall()
        
        if len(stickers) < 3:
            await message.answer("❌ Нужно минимум 3 эмодзи для пака!")
            conn.close()
            await state.clear()
            return
        
        sticker_inputs = []
        for i, (file_id,) in enumerate(stickers):
            sticker_inputs.append(
                types.InputSticker(
                    sticker=file_id,
                    format="static",
                    emoji_list=["🎨"]
                )
            )
        
        pack_title = f"Emoji by {message.from_user.first_name or 'Designer'}"
        
        await bot.create_new_emoji_sticker_set(
            user_id=message.from_user.id,
            name=pack_name,
            title=pack_title,
            stickers=sticker_inputs
        )
        
        pack_link = get_pack_link(pack_name, 'emoji')
        cursor.execute('''
            INSERT INTO packs (pack_name, pack_link, sticker_count, created_at, creator_id, pack_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (pack_name, pack_link, len(stickers), datetime.now().isoformat(), message.from_user.id, 'emoji'))
        
        cursor.execute('DELETE FROM temp_stickers WHERE user_id = ? AND pack_type = "emoji"', (message.from_user.id,))
        conn.commit()
        conn.close()
        
        await message.answer(
            f"🎉 Эмодзи-пак создан!\n\n"
            f"📦 Название: {pack_name}\n"
            f"📊 Эмодзи: {len(stickers)}\n"
            f"🔗 Ссылка: {pack_link}\n\n"
            f"Теперь другие могут получить его по команде:\n"
            f"/get {pack_name}"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании эмодзи-пака: {str(e)}")
    
    await state.clear()

@dp.message(Command("get"))
async def get_pack(message: Message):
    try:
        pack_name = message.text.replace('/get', '').strip()
        if not pack_name:
            await message.answer("❌ Укажи название: /get название_пака")
            return
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('SELECT pack_link, sticker_count, pack_type FROM packs WHERE pack_name = ?', (pack_name,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            pack_link, count, pack_type = result
            await message.answer(
                f"✅ Найден {'эмодзи-пак' if pack_type == 'emoji' else 'пак'}!\n\n"
                f"📦 Название: {pack_name}\n"
                f"📊 {'Эмодзи' if pack_type == 'emoji' else 'Стикеров'}: {count}\n"
                f"🔗 Добавить: {pack_link}"
            )
        else:
            await message.answer(f"❌ Пак с названием '{pack_name}' не найден!")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("list"))
async def list_packs(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    conn = sqlite3.connect('packs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT pack_name, sticker_count, created_at, pack_type FROM packs ORDER BY created_at DESC')
    packs = cursor.fetchall()
    conn.close()
    
    if not packs:
        await message.answer("📭 У тебя пока нет созданных паков.")
        return
    
    text = "📦 **Твои паки:**\n\n"
    for name, count, created, pack_type in packs:
        emoji = "🎨" if pack_type == 'sticker' else "✨"
        text += f"{emoji} `{name}` — {count} {'стикеров' if pack_type == 'sticker' else 'эмодзи'} (создан {created[:10]})\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("delete"))
async def delete_pack(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    try:
        pack_name = message.text.replace('/delete', '').strip()
        if not pack_name:
            await message.answer("❌ Укажи название: /delete название_пака")
            return
        
        conn = sqlite3.connect('packs.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM packs WHERE pack_name = ?', (pack_name,))
        conn.commit()
        conn.close()
        
        await message.answer(f"✅ Пак '{pack_name}' удален из базы.")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    conn = sqlite3.connect('packs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM packs')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(sticker_count) FROM packs')
    total_stickers = cursor.fetchone()[0] or 0
    cursor.execute('SELECT COUNT(*) FROM packs WHERE pack_type = "emoji"')
    total_emoji = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM packs WHERE pack_type = "sticker"')
    total_sticker_packs = cursor.fetchone()[0]
    conn.close()
    
    await message.answer(
        f"📊 **Статистика:**\n\n"
        f"📦 Всего паков: {total}\n"
        f"🎨 Стикер-паков: {total_sticker_packs}\n"
        f"✨ Эмодзи-паков: {total_emoji}\n"
        f"🖼️ Всего элементов: {total_stickers}"
    )

# ========== ДЛЯ RENDER (HEALTH CHECK) ==========
async def health_check(request):
    return web.Response(text="🤖 Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    print("🌐 Web server started on port 10000")

# ========== ЗАПУСК ==========
async def main():
    await asyncio.sleep(3)
    print("🤖 Бот запущен с поддержкой стикеров и эмодзи!")
    
    # Запускаем веб-сервер в фоне
    asyncio.create_task(start_web_server())
    
    # Запускаем бота
    await dp.start_polling(bot, request_timeout=60)

if __name__ == "__main__":
    asyncio.run(main())
