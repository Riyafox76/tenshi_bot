import logging
import sqlite3
import os
import random
import asyncio
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8658625238:AAGIfOAz3cuVBUNrjvOinFK_2QGpoiVihvk"
ADMIN_ID = 5145527096

# ========== НАСТРОЙКИ ОЧЕРЕДИ ==========
MAX_CONCURRENT_TASKS = 2  # Сколько задач выполнять одновременно
TASK_TIMEOUT = 60  # Таймаут на выполнение одной задачи (сек)

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class CreatePack(StatesGroup):
    waiting_for_images = State()
    waiting_for_pack_name = State()
    waiting_for_pack_tags = State()
    waiting_for_emoji_images = State()
    waiting_for_emoji_pack_name = State()
    waiting_for_emoji_pack_tags = State()
    waiting_for_palette = State()
    waiting_for_preview = State()
    waiting_for_font = State()
    waiting_for_contrast = State()
    waiting_for_pxrem = State()
    waiting_for_golden = State()

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

DESIGN_TIPS = {
    'синий': '💡 К синему отлично подходят:\n• Оранжевый (#FFA500) — для контраста\n• Белый (#FFFFFF) — для чистоты\n• Желтый (#FFD700) — для теплоты\n• Фиолетовый (#8B00FF) — для глубины',
    'красный': '💡 К красному отлично подходят:\n• Белый — для контраста\n• Черный — для строгости\n• Золотой — для роскоши',
    'зеленый': '💡 К зеленому отлично подходят:\n• Белый — для свежести\n• Коричневый — для натуральности\n• Желтый — для яркости',
    'черный': '💡 К черному отлично подходят:\n• Белый — классика\n• Золотой — роскошь\n• Красный — акцент',
    'белый': '💡 К белому отлично подходят:\n• Любой цвет! Но особенно:\n• Черный — контраст\n• Золотой — элегантность\n• Пастельные тона — нежность'
}

# ========== БАЗА ДЛЯ ЧЕЛЛЕНДЖЕЙ ==========
CHALLENGES = [
    {
        "title": "Логотип для кофейни",
        "description": "Сделай логотип для кофейни с капибарами",
        "style": "Киберпанк + ретро-футуризм",
        "colors": ["#00D4FF", "#9B59B6", "#1A1A1A"],
        "format": "512×512 px"
    },
    {
        "title": "Иконка для приложения",
        "description": "Создай иконку для приложения 'Космическое такси'",
        "style": "Минимализм с элементами неона",
        "colors": ["#FF6B6B", "#4ECDC4", "#2C3E50"],
        "format": "1024×1024 px"
    },
    {
        "title": "Постер для концерта",
        "description": "Дизайн постера для джазового фестиваля",
        "style": "Винтаж + современная типографика",
        "colors": ["#F39C12", "#8E44AD", "#ECF0F1"],
        "format": "A4 (210×297 мм)"
    },
    {
        "title": "Упаковка для чая",
        "description": "Разработай дизайн упаковки для коллекции чаёв",
        "style": "Ботаника + акварель",
        "colors": ["#27AE60", "#F1C40F", "#FFFFFF"],
        "format": "Коробка 120×80×60 мм"
    },
    {
        "title": "Интерфейс для погодного приложения",
        "description": "Нарисуй экран погоды с анимацией",
        "style": "Глассморфизм (Glassmorphism)",
        "colors": ["#74B9FF", "#DFE6E9", "#2D3436"],
        "format": "375×812 px (iPhone X)"
    }
]

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN)

os.makedirs('fonts', exist_ok=True)

# ========== КЛАСС ОЧЕРЕДИ ==========
class TaskQueue:
    def __init__(self, max_concurrent=MAX_CONCURRENT_TASKS):
        self.queue = asyncio.Queue()
        self.active_tasks = set()
        self.max_concurrent = max_concurrent
        self.is_running = True
        self._worker_task = None

    async def add_task(self, task_func, *args, **kwargs):
        """Добавить задачу в очередь"""
        future = asyncio.Future()
        await self.queue.put((task_func, args, kwargs, future))
        return await future

    async def _worker(self):
        """Воркер, который выполняет задачи из очереди"""
        while self.is_running:
            try:
                if len(self.active_tasks) >= self.max_concurrent:
                    await asyncio.sleep(0.1)
                    continue

                try:
                    task_func, args, kwargs, future = await asyncio.wait_for(
                        self.queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                async def run_task():
                    try:
                        result = await asyncio.wait_for(
                            task_func(*args, **kwargs),
                            timeout=TASK_TIMEOUT
                        )
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                    finally:
                        self.active_tasks.discard(asyncio.current_task())
                        self.queue.task_done()

                task = asyncio.create_task(run_task())
                self.active_tasks.add(task)

            except Exception as e:
                logging.error(f"Ошибка в воркере очереди: {e}")
                await asyncio.sleep(0.5)

    def start(self):
        """Запускает воркер"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    def stop(self):
        """Останавливает воркер"""
        self.is_running = False
        if self._worker_task:
            self._worker_task.cancel()

# Глобальная переменная для очереди (будет создана в main)
task_queue = None

# ========== ФУНКЦИЯ ДЛЯ ОЧЕРЕДИ ==========
async def queue_handler(func):
    """Декоратор для обработки команд через очередь"""
    async def wrapper(message: Message, *args, **kwargs):
        status_msg = await message.answer("⏳ Ваш запрос добавлен в очередь. Ожидайте...")
        
        try:
            result = await task_queue.add_task(func, message, *args, **kwargs)
            await status_msg.delete()
            return result
        except asyncio.TimeoutError:
            await status_msg.edit_text("❌ Время выполнения задачи истекло. Попробуйте позже.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)}")
    
    return wrapper

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
            downloads INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
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
    
    try:
        cursor.execute('ALTER TABLE packs ADD COLUMN downloads INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE packs ADD COLUMN tags TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return user_id == ADMIN_ID

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

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

def create_palette_card(colors):
    if not colors:
        return None
    
    card_width = 600
    card_height = 200
    block_width = card_width // len(colors)
    
    card = Image.new('RGB', (card_width, card_height), color='#F5F5F5')
    draw = ImageDraw.Draw(card)
    
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()
    
    x = 0
    for hex_color, r, g, b in colors:
        draw.rectangle([x, 0, x + block_width, card_height - 40], fill=hex_color)
        
        text = hex_color
        brightness = (r * 0.299 + g * 0.587 + b * 0.114)
        text_color = '#FFFFFF' if brightness < 140 else '#000000'
        draw.text((x + 10, card_height - 30), text, font=font, fill=text_color)
        
        try:
            small_font = ImageFont.truetype("arial.ttf", 11)
            rgb_text = f"{r},{g},{b}"
            draw.text((x + 10, card_height - 20), rgb_text, font=small_font, fill=text_color)
        except:
            pass
        
        x += block_width
    
    img_io = io.BytesIO()
    card.save(img_io, format='PNG')
    img_io.seek(0)
    return img_io

def create_font_preview(text, font_paths):
    images = []
    for font_path in font_paths:
        img = Image.new('RGB', (600, 100), color='#FFFFFF')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(font_path, 48)
        except:
            font = ImageFont.load_default()
            draw.text((10, 20), f"[{os.path.basename(font_path)}]", font=font, fill='#000000')
        
        draw.text((20, 25), text, font=font, fill='#000000')
        
        try:
            small_font = ImageFont.truetype("arial.ttf", 12)
            font_name = os.path.splitext(os.path.basename(font_path))[0]
            draw.text((10, 5), font_name, font=small_font, fill='#888888')
        except:
            pass
        
        images.append(img)
    
    if not images:
        return None
    
    total_height = sum(img.height + 5 for img in images)
    combined = Image.new('RGB', (600, total_height), color='#FFFFFF')
    y = 0
    for img in images:
        combined.paste(img, (0, y))
        y += img.height + 5
    
    img_io = io.BytesIO()
    combined.save(img_io, format='PNG')
    img_io.seek(0)
    return img_io

def extract_colors(image_bytes, num_colors=5):
    img = Image.open(io.BytesIO(image_bytes))
    img = img.resize((100, 100))
    img = img.convert('RGB')
    
    pixels = list(img.getdata())
    
    colors = []
    for pixel in pixels:
        if len(colors) < num_colors:
            colors.append(pixel)
        else:
            min_dist = float('inf')
            min_idx = 0
            for i, c in enumerate(colors):
                dist = sum((pixel[j] - c[j])**2 for j in range(3))
                if dist < min_dist:
                    min_dist = dist
                    min_idx = i
            if min_dist > 10000:
                colors[min_idx] = pixel
    
    hex_colors = []
    for r, g, b in colors:
        hex_color = f"#{r:02x}{g:02x}{b:02x}".upper()
        hex_colors.append((hex_color, r, g, b))
    
    return hex_colors

def create_preview(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    
    size = min(img.size)
    left = (img.width - size) // 2
    top = (img.height - size) // 2
    img = img.crop((left, top, left + size, top + size))
    img = img.resize((400, 400))
    
    preview = Image.new('RGBA', (500, 500), (50, 50, 50, 255))
    
    mask = Image.new('L', (400, 400), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, 400, 400), fill=255)
    
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
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
            "🎨 Привет, Tenshi!\n\n"
            "📦 Стикеры и эмодзи:\n"
            "/newpack - Создать пак стикеров\n"
            "/newemoji - Создать пак эмодзи\n"
            "/get [название] - Получить пак\n"
            "/search [тег] - Найти паки по тегу\n"
            "/list - Мои паки\n"
            "/delete [название] - Удалить пак\n"
            "/stats - Статистика\n\n"
            "🎨 Дизайн-инструменты:\n"
            "/palette - Вырезать цвета из картинки\n"
            "/preview - Показать стикер в кружке\n"
            "/font [текст] - Красивые шрифты\n"
            "/ask [вопрос] - Советы по дизайну\n"
            "/contrast - Проверить контраст цветов\n"
            "/challenge - Получить дизайн-задачу\n"
            "/pxrem - Конвертер PX ↔ REM\n"
            "/golden - Золотое сечение\n\n"
            "📝 Текст:\n"
            "/maketext [текст] - Текст в эмодзи"
        )
    else:
        await message.answer(
            "✦ Привет!\n\n"
            "🎨 Дизайн-инструменты:\n"
            "/palette - Вырезать цвета из картинки\n"
            "/preview - Показать стикер в кружке\n"
            "/font [текст] - Красивые шрифты\n"
            "/ask [вопрос] - Советы по дизайну\n"
            "/contrast - Проверить контраст цветов\n"
            "/pxrem - Конвертер PX ↔ REM\n"
            "/golden - Золотое сечение\n"
            "/maketext [текст] - Текст в эмодзи\n\n"
            "📦 Получить пак:\n"
            "/get [название] - Получить ссылку на пак\n"
            "/search [тег] - Найти паки по тегу"
        )

@dp.message(Command("palette"))
async def palette_command(message: Message, state: FSMContext):
    await state.set_state(CreatePack.waiting_for_palette)
    await message.answer(
        "🖼️ Кинь мне картинку, и я создам для неё красивую палитру!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Другую картинку", callback_data="palette_again")]
            ]
        )
    )

@dp.message(CreatePack.waiting_for_palette)
@queue_handler
async def handle_palette(message: Message, state: FSMContext):
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
        
        palette_img = create_palette_card(colors)
        
        if palette_img:
            await message.answer_photo(
                types.BufferedInputFile(palette_img.getvalue(), filename="palette.png"),
                caption="🎨 **Твоя палитра готова!**\n\n" +
                       "\n".join([f"`{c[0]}`" for c in colors]),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🎨 Ещё", callback_data="palette_again"),
                            InlineKeyboardButton(text="📐 Применить", callback_data="palette_apply")
                        ]
                    ]
                )
            )
        else:
            await message.answer("❌ Не удалось создать палитру. Попробуй другую картинку.")
        
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("preview"))
async def preview_command(message: Message, state: FSMContext):
    await state.set_state(CreatePack.waiting_for_preview)
    await message.answer("🖼️ Кинь мне картинку или стикер, и я покажу, как он выглядит в чате!")

@dp.message(CreatePack.waiting_for_preview)
@queue_handler
async def handle_preview(message: Message, state: FSMContext):
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
            caption="🖼️ Вот как будет выглядеть твой стикер в чате!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔄 Другой стикер", callback_data="preview_again"),
                        InlineKeyboardButton(text="📦 В палитру", callback_data="preview_to_palette")
                    ]
                ]
            )
        )
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("font"))
async def font_command(message: Message, state: FSMContext):
    await state.set_state(CreatePack.waiting_for_font)
    await message.answer(
        "📝 **Напиши текст для шрифтов:**\n\n"
        "Например: `Hello, World!` или `Дизайн`",
        parse_mode="Markdown"
    )

@dp.message(CreatePack.waiting_for_font)
@queue_handler
async def handle_font(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text:
        await message.answer("❌ Напиши текст!")
        return
    
    font_list = [
        "arial.ttf",
        "times.ttf",
        "cour.ttf",
    ]
    
    available_fonts = []
    for font_name in font_list:
        if os.path.exists(font_name):
            available_fonts.append(font_name)
    
    if not available_fonts:
        img = Image.new('RGB', (600, 100), color='#FFFFFF')
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.text((20, 35), text, font=font, fill='#000000')
        img_io = io.BytesIO()
        img.save(img_io, format='PNG')
        img_io.seek(0)
        await message.answer_photo(
            types.BufferedInputFile(img_io.getvalue(), filename="font.png"),
            caption="✨ **Твой текст:**\n\n" + text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Другой текст", callback_data="font_again")]
                ]
            )
        )
        await state.clear()
        return
    
    font_preview = create_font_preview(text, available_fonts)
    
    if font_preview:
        await message.answer_photo(
            types.BufferedInputFile(font_preview.getvalue(), filename="font.png"),
            caption="✨ **Твой текст разными шрифтами!**",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Другой текст", callback_data="font_again")]
                ]
            )
        )
    else:
        await message.answer("❌ Не удалось создать превью шрифтов. Попробуй другой текст.")
    
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
        cursor.execute('SELECT pack_link, sticker_count, pack_type, downloads, tags FROM packs WHERE pack_name = ?', (pack_name,))
        result = cursor.fetchone()
        
        if result:
            pack_link, count, pack_type, downloads, tags = result
            cursor.execute('UPDATE packs SET downloads = downloads + 1 WHERE pack_name = ?', (pack_name,))
            conn.commit()
            
            tag_text = f"\n🏷️ Теги: {tags}" if tags else ""
            await message.answer(
                f"✅ Найден {'эмодзи-пак' if pack_type == 'emoji' else 'пак'}!\n\n"
                f"📦 Название: {pack_name}\n"
                f"📊 {'Эмодзи' if pack_type == 'emoji' else 'Стикеров'}: {count}\n"
                f"⬇️ Скачиваний: {downloads + 1}{tag_text}\n"
                f"🔗 Добавить: {pack_link}"
            )
        else:
            await message.answer(f"❌ Пак с названием '{pack_name}' не найден!")
        
        conn.close()
            
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(Command("search"))
async def search_packs(message: Message):
    tag = message.text.replace('/search', '').strip().lower()
    if not tag:
        await message.answer("❌ Укажи тег для поиска: /search лето")
        return
    
    conn = sqlite3.connect('packs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT pack_name, sticker_count, pack_type, downloads, tags FROM packs WHERE LOWER(tags) LIKE ? ORDER BY downloads DESC', (f'%{tag}%',))
    packs = cursor.fetchall()
    conn.close()
    
    if not packs:
        await message.answer(f"🔍 Паков с тегом '{tag}' не найдено.")
        return
    
    text = f"🔍 **Найдено по тегу '{tag}':**\n\n"
    for name, count, pack_type, downloads, tags in packs[:10]:
        emoji = "🎨" if pack_type == 'sticker' else "✨"
        text += f"{emoji} `{name}` — {count} {'стикеров' if pack_type == 'sticker' else 'эмодзи'} (⬇️{downloads})\n"
    
    if len(packs) > 10:
        text += f"\n... и ещё {len(packs) - 10} паков"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("contrast"))
async def contrast_command(message: Message, state: FSMContext):
    args = message.text.replace('/contrast', '').strip().split()
    if len(args) == 2:
        color1 = args[0].strip()
        color2 = args[1].strip()
        await check_contrast(message, color1, color2)
    else:
        await state.set_state(CreatePack.waiting_for_contrast)
        await message.answer(
            "🎨 **Контраст-чекер WCAG**\n\n"
            "Отправь мне два цвета в формате HEX или RGB.\n"
            "Пример: `#FF5733` и `#FFFFFF`\n\n"
            "Или напиши цвета через пробел: `/contrast #FF5733 #FFFFFF`",
            parse_mode="Markdown"
        )

async def check_contrast(message, color1, color2):
    try:
        if color1.startswith('#'):
            r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        else:
            rgb1 = re.findall(r'\d+', color1)
            if len(rgb1) >= 3:
                r1, g1, b1 = map(int, rgb1[:3])
            else:
                await message.answer("❌ Неправильный формат цвета! Используй HEX (`#FF5733`) или RGB (`255,87,51`).", parse_mode="Markdown")
                return
        
        if color2.startswith('#'):
            r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
        else:
            rgb2 = re.findall(r'\d+', color2)
            if len(rgb2) >= 3:
                r2, g2, b2 = map(int, rgb2[:3])
            else:
                await message.answer("❌ Неправильный формат цвета! Используй HEX (`#FF5733`) или RGB (`255,87,51`).", parse_mode="Markdown")
                return
        
        def luminance(r, g, b):
            def lum_channel(c):
                c = c / 255
                if c <= 0.03928:
                    return c / 12.92
                return ((c + 0.055) / 1.055) ** 2.4
            return 0.2126 * lum_channel(r) + 0.7152 * lum_channel(g) + 0.0722 * lum_channel(b)
        
        l1 = luminance(r1, g1, b1)
        l2 = luminance(r2, g2, b2)
        
        ratio = (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
        ratio = round(ratio, 2)
        
        if ratio >= 7.0:
            level = "✅✅✅ Проходит по **AAA** (высший уровень доступности)"
            recommendation = "Отличный контраст! Идеально для текста любого размера."
        elif ratio >= 4.5:
            level = "✅✅ Проходит по **AA** (базовый уровень)"
            recommendation = "Хороший контраст для обычного и крупного текста."
        elif ratio >= 3.0:
            level = "✅ Проходит по **AA** только для крупного текста (>18px)"
            recommendation = "Рекомендуется увеличить контраст для обычного текста."
        else:
            level = "❌ **Не проходит** ни по одному уровню WCAG"
            recommendation = "Сильно увеличь контраст! Сделай текст темнее или светлее фона."
        
        card = Image.new('RGB', (400, 200), color='#FFFFFF')
        draw = ImageDraw.Draw(card)
        
        draw.rectangle([0, 0, 200, 200], fill=(r1, g1, b1))
        draw.rectangle([200, 0, 400, 200], fill=(r2, g2, b2))
        
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()
        draw.text((10, 10), f"Контраст: {ratio}:1", font=font, fill='#000000')
        
        img_io = io.BytesIO()
        card.save(img_io, format='PNG')
        img_io.seek(0)
        
        await message.answer_photo(
            types.BufferedInputFile(img_io.getvalue(), filename="contrast.png"),
            caption=f"🎨 **Результат проверки контраста**\n\n"
                    f"Цвет 1: `{color1}`\n"
                    f"Цвет 2: `{color2}`\n"
                    f"**Соотношение:** `{ratio}:1`\n\n"
                    f"{level}\n\n"
                    f"💡 {recommendation}",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при проверке контраста: {str(e)}")

@dp.message(CreatePack.waiting_for_contrast)
async def handle_contrast(message: Message, state: FSMContext):
    colors = message.text.strip().split()
    if len(colors) >= 2:
        color1 = colors[0]
        color2 = colors[1]
        await check_contrast(message, color1, color2)
        await state.clear()
    else:
        await message.answer("❌ Отправь **два** цвета через пробел! Например: `#FF5733 #FFFFFF`")

@dp.message(Command("challenge"))
async def challenge_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    challenge = random.choice(CHALLENGES)
    
    response = (
        f"🎨 **Дизайн-челлендж!**\n\n"
        f"**Задача:** {challenge['title']}\n"
        f"**Описание:** {challenge['description']}\n"
        f"**Стиль:** {challenge['style']}\n"
        f"**Цвета:** " + ", ".join(challenge['colors']) + "\n"
        f"**Формат:** {challenge['format']}\n\n"
        f"✨ Твоя очередь! Удачи!"
    )
    
    await message.answer(response)

@dp.message(Command("pxrem"))
async def pxrem_command(message: Message):
    args = message.text.replace('/pxrem', '').strip()
    if not args:
        await message.answer(
            "📐 **Конвертер PX ↔ REM**\n\n"
            "Напиши значение в px или rem.\n"
            "Примеры:\n"
            "`/pxrem 16px` — перевести пиксели в REM\n"
            "`/pxrem 1.5rem` — перевести REM в пиксели\n\n"
            "Базовый размер: 16px (можно изменить, добавив второй параметр)\n"
            "`/pxrem 16px 20px` — с базовым размером 20px",
            parse_mode="Markdown"
        )
        return
    
    parts = args.split()
    if len(parts) >= 2:
        value = parts[0]
        base = float(parts[1].replace('px', '').strip())
    else:
        value = parts[0]
        base = 16
    
    try:
        if 'rem' in value.lower():
            rem = float(value.lower().replace('rem', '').strip())
            px = rem * base
            await message.answer(
                f"📐 **Конвертация**\n\n"
                f"{rem}rem = **{px:.2f}px**\n"
                f"(при базовом размере {base}px)"
            )
        elif 'px' in value.lower():
            px = float(value.lower().replace('px', '').strip())
            rem = px / base
            await message.answer(
                f"📐 **Конвертация**\n\n"
                f"{px}px = **{rem:.4f}rem**\n"
                f"(при базовом размере {base}px)"
            )
        else:
            px = float(value)
            rem = px / base
            await message.answer(
                f"📐 **Конвертация**\n\n"
                f"{px}px = **{rem:.4f}rem**\n"
                f"(при базовом размере {base}px)\n\n"
                f"Для конвертации в другую сторону используй `/pxrem 2rem`"
            )
    except:
        await message.answer("❌ Ошибка! Напиши число с px или rem, например: `/pxrem 16px` или `/pxrem 1.5rem`", parse_mode="Markdown")

@dp.message(Command("golden"))
async def golden_command(message: Message):
    args = message.text.replace('/golden', '').strip()
    if not args:
        await message.answer(
            "✨ **Золотое сечение**\n\n"
            "Напиши число, и я рассчитаю пропорции по золотому сечению.\n"
            "Пример: `/golden 100`"
        )
        return
    
    try:
        num = float(args)
        phi = 1.61803398875
        
        larger = num * phi
        smaller = num / phi
        
        await message.answer(
            f"✨ **Золотое сечение для {num}**\n\n"
            f"**Большее число:** {larger:.2f}\n"
            f"**Меньшее число:** {smaller:.2f}\n"
            f"**Соотношение:** {larger:.2f} / {num:.2f} = {larger/num:.4f} ≈ φ (1.618)\n\n"
            f"**Пропорции для дизайна:**\n"
            f"• {num:.0f} × {larger:.0f} (соотношение 1:1.618)\n"
            f"• {smaller:.0f} × {num:.0f} (обратное соотношение)"
        )
    except:
        await message.answer("❌ Напиши число, например: `/golden 100`")

@dp.message(Command("ask"))
async def ask_command(message: Message):
    question = message.text.replace('/ask', '').strip()
    if not question:
        await message.answer(
            "❓ Напиши вопрос после команды:\n"
            "/ask какой цвет подойдет к синему?\n\n"
            "Я знаю про цвета: синий, красный, зеленый, черный, белый"
        )
        return
    
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

# ========== АДМИН-КОМАНДЫ ==========

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

@dp.message(Command("list"))
async def list_packs(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    conn = sqlite3.connect('packs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT pack_name, sticker_count, created_at, pack_type, downloads, tags FROM packs ORDER BY created_at DESC')
    packs = cursor.fetchall()
    conn.close()
    
    if not packs:
        await message.answer("📭 У тебя пока нет созданных паков.")
        return
    
    text = "📦 **Твои паки:**\n\n"
    for name, count, created, pack_type, downloads, tags in packs:
        emoji = "🎨" if pack_type == 'sticker' else "✨"
        tag_text = f" [{tags}]" if tags else ""
        text += f"{emoji} `{name}` — {count} {'стикеров' if pack_type == 'sticker' else 'эмодзи'} (⬇️{downloads}){tag_text}\n"
    
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
    
    cursor.execute('SELECT SUM(downloads) FROM packs')
    total_downloads = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT pack_name, downloads, pack_type FROM packs ORDER BY downloads DESC LIMIT 5')
    top_packs = cursor.fetchall()
    
    conn.close()
    
    text = (
        f"📊 **Статистика:**\n\n"
        f"📦 Всего паков: {total}\n"
        f"🎨 Стикер-паков: {total_sticker_packs}\n"
        f"✨ Эмодзи-паков: {total_emoji}\n"
        f"🖼️ Всего элементов: {total_stickers}\n"
        f"⬇️ Всего скачиваний: {total_downloads}\n\n"
    )
    
    if top_packs:
        text += "🏆 **Топ-5 популярных паков:**\n"
        for name, downloads, pack_type in top_packs:
            emoji = "🎨" if pack_type == 'sticker' else "✨"
            text += f"{emoji} `{name}` — ⬇️{downloads}\n"
    
    await message.answer(text, parse_mode="Markdown")

# ========== ОБРАБОТЧИКИ ДЛЯ СОЗДАНИЯ ПАКОВ ==========

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
    
    await state.update_data(pack_name=pack_name)
    await state.set_state(CreatePack.waiting_for_pack_tags)
    await message.answer(
        "🏷️ **Добавь теги для пака** (необязательно)\n\n"
        "Напиши теги через запятую, например:\n"
        "`лето, котики, яркое`\n\n"
        "Или нажми /skip, чтобы пропустить."
    )

@dp.message(CreatePack.waiting_for_pack_tags)
async def handle_pack_tags(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text and message.text.lower() == '/skip':
        tags = ""
    else:
        tags = message.text.strip()
    
    await state.update_data(tags=tags)
    
    data = await state.get_data()
    pack_name = data.get('pack_name')
    pack_type = data.get('pack_type', 'sticker')
    
    try:
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
            INSERT INTO packs (pack_name, pack_link, sticker_count, created_at, creator_id, pack_type, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (pack_name, pack_link, len(stickers), datetime.now().isoformat(), message.from_user.id, pack_type, tags))
        
        cursor.execute('DELETE FROM temp_stickers WHERE user_id = ?', (message.from_user.id,))
        conn.commit()
        conn.close()
        
        tag_text = f"\n🏷️ Теги: {tags}" if tags else ""
        await message.answer(
            f"🎉 {'Эмодзи-пак' if pack_type == 'emoji' else 'Пак'} создан!\n\n"
            f"📦 Название: {pack_name}\n"
            f"📊 Элементов: {len(stickers)}\n"
            f"🔗 Ссылка: {pack_link}\n"
            f"⬇️ Скачиваний: 0{tag_text}\n\n"
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
    
    await state.update_data(pack_name=pack_name)
    await state.set_state(CreatePack.waiting_for_emoji_pack_tags)
    await message.answer(
        "🏷️ **Добавь теги для эмодзи-пака** (необязательно)\n\n"
        "Напиши теги через запятую, например:\n"
        "`эмодзи, эмоции, стикеры`\n\n"
        "Или нажми /skip, чтобы пропустить."
    )

@dp.message(CreatePack.waiting_for_emoji_pack_tags)
async def handle_emoji_pack_tags(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    if message.text and message.text.lower() == '/skip':
        tags = ""
    else:
        tags = message.text.strip()
    
    await state.update_data(tags=tags)
    
    data = await state.get_data()
    pack_name = data.get('pack_name')
    
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
            INSERT INTO packs (pack_name, pack_link, sticker_count, created_at, creator_id, pack_type, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (pack_name, pack_link, len(stickers), datetime.now().isoformat(), message.from_user.id, 'emoji', tags))
        
        cursor.execute('DELETE FROM temp_stickers WHERE user_id = ? AND pack_type = "emoji"', (message.from_user.id,))
        conn.commit()
        conn.close()
        
        tag_text = f"\n🏷️ Теги: {tags}" if tags else ""
        await message.answer(
            f"🎉 Эмодзи-пак создан!\n\n"
            f"📦 Название: {pack_name}\n"
            f"📊 Эмодзи: {len(stickers)}\n"
            f"🔗 Ссылка: {pack_link}\n"
            f"⬇️ Скачиваний: 0{tag_text}\n\n"
            f"Теперь другие могут получить его по команде:\n"
            f"/get {pack_name}"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании эмодзи-пака: {str(e)}")
    
    await state.clear()

# ========== ОБРАБОТЧИКИ КНОПОК ==========

@dp.callback_query(lambda c: c.data.startswith('palette_'))
async def process_palette_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    
    if callback_query.data == 'palette_again':
        await palette_command(callback_query.message, state)
    elif callback_query.data == 'palette_apply':
        await callback_query.message.answer("🔧 Скоро здесь будет функция применения палитры!")

@dp.callback_query(lambda c: c.data.startswith('preview_'))
async def process_preview_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    
    if callback_query.data == 'preview_again':
        await preview_command(callback_query.message, state)
    elif callback_query.data == 'preview_to_palette':
        await palette_command(callback_query.message, state)

@dp.callback_query(lambda c: c.data == 'font_again')
async def process_font_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await font_command(callback_query.message, state)

# ========== ДЛЯ RENDER ==========

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

async def main():
    await asyncio.sleep(3)
    
    # СОЗДАЁМ ОЧЕРЕДЬ ЗДЕСЬ (внутри event loop)
    global task_queue
    task_queue = TaskQueue()
    task_queue.start()
    
    print("🤖 Бот запущен с поддержкой стикеров, эмодзи и дизайн-инструментов!")
    print(f"⚙️ Очередь: {MAX_CONCURRENT_TASKS} задач одновременно, таймаут {TASK_TIMEOUT} сек")
    
    asyncio.create_task(start_web_server())
    
    await dp.start_polling(bot, request_timeout=60)

if __name__ == "__main__":
    asyncio.run(main())
