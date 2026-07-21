import logging
import sqlite3
import os
import random
import asyncio
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8658625238:AAGIfOAz3cuVBUNrjvOinFK_2QGpoiVihvk"
ADMIN_ID = 5145527096
REMOVE_BG_API_KEY = "PXqz6KQmZGPLSNJqVBhne55L"

# ========== НАСТРОЙКИ БЕСПЛАТНОГО ИИ (Hugging Face) ==========
# Токен берётся из переменных окружения на Render (безопасно!)
HF_API_TOKEN = os.getenv("HF_API_TOKEN", "")

MAX_CONCURRENT_TASKS = 2
TASK_TIMEOUT = 90

# ========== СОСТОЯНИЯ ==========
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
    waiting_for_removebg = State()
    waiting_for_ai = State()

# ========== БАЗЫ ==========
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

# ========== РАСШИРЕННЫЙ СПИСОК ЧЕЛЛЕНДЖЕЙ ==========
CHALLENGES = [
    {"title": "Логотип для кофейни", "description": "Сделай логотип для кофейни с капибарами", "style": "Киберпанк + ретро-футуризм", "colors": ["#00D4FF", "#9B59B6", "#1A1A1A"], "format": "512×512 px"},
    {"title": "Иконка для приложения", "description": "Создай иконку для приложения 'Космическое такси'", "style": "Минимализм + неон", "colors": ["#FF6B6B", "#4ECDC4", "#2C3E50"], "format": "1024×1024 px"},
    {"title": "Постер для концерта", "description": "Дизайн постера для джазового фестиваля", "style": "Винтаж + современная типографика", "colors": ["#F39C12", "#8E44AD", "#ECF0F1"], "format": "A4 (210×297 мм)"},
    {"title": "Упаковка для чая", "description": "Разработай дизайн упаковки для коллекции травяных чаёв", "style": "Ботаника + акварель", "colors": ["#27AE60", "#F1C40F", "#FFFFFF"], "format": "Коробка 120×80×60 мм"},
    {"title": "Интерфейс для погодного приложения", "description": "Нарисуй экран погоды с анимацией", "style": "Глассморфизм (Glassmorphism)", "colors": ["#74B9FF", "#DFE6E9", "#2D3436"], "format": "375×812 px (iPhone X)"},
    {"title": "Обложка для альбома", "description": "Сделай обложку для альбома в жанре Lo-Fi", "style": "Аналоговый синтвейв + городской пейзаж", "colors": ["#2C3E50", "#E74C3C", "#F1C40F"], "format": "3000×3000 px"},
    {"title": "Презентация для стартапа", "description": "Дизайн 3-х слайдов для стартапа по ИИ", "style": "Минимализм + дата-визуализация", "colors": ["#6C5CE7", "#00CEC9", "#DFE6E9"], "format": "1920×1080 px"},
    {"title": "Вывеска для магазина", "description": "Дизайн вывески для магазина винила", "style": "Неон + ретро-шрифты", "colors": ["#FF0050", "#00E5FF", "#1A1A1A"], "format": "2000×1000 px"},
    {"title": "Иллюстрация для статьи", "description": "Создай иллюстрацию для статьи о космосе", "style": "Векторная графика + футуризм", "colors": ["#0C0C1D", "#6C5CE7", "#FDCB6E"], "format": "1200×800 px"},
    {"title": "Дизайн для соцсетей", "description": "Сделай шаблон для Instagram-сторис о психологии", "style": "Пастельные тона + минимализм", "colors": ["#FFB8B8", "#A8D8EA", "#FFD3B4"], "format": "1080×1920 px"},
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
        future = asyncio.Future()
        await self.queue.put((task_func, args, kwargs, future))
        return await future

    async def _worker(self):
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
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    def stop(self):
        self.is_running = False
        if self._worker_task:
            self._worker_task.cancel()

task_queue = None

# ========== ОБЁРТКА ДЛЯ ОЧЕРЕДИ ==========
async def process_with_queue(func, message, *args, **kwargs):
    """Обёртка для выполнения функции через очередь"""
    status_msg = await message.answer("⏳ Обрабатываю запрос...")
    try:
        result = await task_queue.add_task(func, message, *args, **kwargs)
        await status_msg.delete()
        return result
    except asyncio.TimeoutError:
        await status_msg.edit_text("❌ Время выполнения задачи истекло. Попробуйте позже.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)}")

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

async def remove_background(image_bytes):
    if not REMOVE_BG_API_KEY:
        return None
    try:
        response = requests.post(
            'https://api.remove.bg/v1.0/removebg',
            files={'image_file': ('image.jpg', image_bytes, 'image/jpeg')},
            data={'size': 'auto'},
            headers={'X-Api-Key': REMOVE_BG_API_KEY}
        )
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        logging.error(f"Remove.bg error: {e}")
        return None

# ========== ИСПРАВЛЕННЫЙ БЕСПЛАТНЫЙ ИИ (Hugging Face) ==========
async def ai_assistant(prompt):
    """Бесплатный ИИ-помощник через Hugging Face"""
    if not HF_API_TOKEN:
        logging.warning("⚠️ HF_API_TOKEN не найден. Использую локальный режим.")
        return await local_ai_assistant(prompt)
    
    # Создаём сессию с повторными попытками
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    try:
        headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
        data = {
            "inputs": f"Ты — профессиональный дизайнер-ассистент Tenshi. Ответь кратко, полезно и по делу: {prompt}",
            "parameters": {"max_new_tokens": 150, "temperature": 0.7}
        }
        
        logging.info(f"📤 Отправка запроса в HF: {prompt[:30]}...")
        
        response = session.post(
            "https://api-inference.huggingface.co/models/google/flan-t5-base",
            headers=headers,
            json=data,
            timeout=30
        )
        
        logging.info(f"📥 HF статус: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            logging.info(f"📄 HF ответ: {str(result)[:200]}")
            
            if isinstance(result, list) and len(result) > 0:
                generated = result[0].get('generated_text')
                if generated:
                    return generated
                else:
                    logging.warning("⚠️ HF ответ без текста")
                    return await local_ai_assistant(prompt)
            else:
                logging.warning(f"⚠️ HF неожиданный формат ответа: {type(result)}")
                return await local_ai_assistant(prompt)
        
        elif response.status_code == 503:
            logging.warning("⏳ HF модель загружается (503). Повтор через 5 сек...")
            await asyncio.sleep(5)
            response = session.post(
                "https://api-inference.huggingface.co/models/google/flan-t5-base",
                headers=headers,
                json=data,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    generated = result[0].get('generated_text')
                    if generated:
                        return generated
            return await local_ai_assistant(prompt)
            
        else:
            logging.warning(f"⚠️ HF ошибка {response.status_code}: {response.text[:200]}")
            return await local_ai_assistant(prompt)
            
    except requests.exceptions.Timeout:
        logging.error("⏰ HF таймаут (30 сек). Использую локальный режим.")
        return await local_ai_assistant(prompt)
    except Exception as e:
        logging.error(f"❌ HF исключение: {e}")
        return await local_ai_assistant(prompt)
    finally:
        session.close()

async def local_ai_assistant(prompt):
    """Локальный ИИ на базе знаний (работает без интернета)"""
    prompt_lower = prompt.lower()
    
    if any(word in prompt_lower for word in ["цвет", "цвета", "палитра", "сочетание", "оттенок"]):
        return "🎨 **Советы по цвету:**\n\n• Используй цветовой круг для подбора гармоничных сочетаний\n• Комплементарные цвета дают максимальный контраст\n• Аналоговые цвета создают спокойную гармонию\n• Триадные цвета — динамичные сочетания\n• Проверь контраст через /contrast"
    
    elif any(word in prompt_lower for word in ["логотип", "лого", "бренд", "айдентика"]):
        return "💡 **Советы по логотипу:**\n\n• Простота — ключ к запоминанию\n• Используй не более 2-3 цветов\n• Шрифт должен читаться в любом размере\n• Проверь логотип в чёрно-белом варианте\n• Проверь в маленьком размере (аватарка)"
    
    elif any(word in prompt_lower for word in ["шрифт", "шрифты", "типографика", "гарнитура"]):
        return "📝 **Советы по типографике:**\n\n• Не используй более 2-3 шрифтов в проекте\n• Контрастные шрифты создают динамику\n• Проверяй читаемость на разных размерах\n• Для заголовков используй display-шрифты\n• Для текста — шрифты с хорошей читаемостью"
    
    elif any(word in prompt_lower for word in ["композиция", "верстка", "макет", "сетка", "расположение"]):
        return "📐 **Советы по композиции:**\n\n• Правило третей — размещай ключевые элементы на пересечении линий\n• Используй направляющие линии для движения глаз\n• Создавай иерархию через размер и цвет\n• Оставляй достаточно пустого пространства"
    
    elif any(word in prompt_lower for word in ["ux", "ui", "интерфейс", "приложение", "сайт", "юзабилити"]):
        return "📱 **Советы по UX/UI:**\n\n• Пользователь должен понимать интерфейс без инструкции\n• Кнопки должны быть заметными и удобными\n• Цвета должны быть контрастными для читаемости\n• Используй привычные паттерны (корзина, поиск)"
    
    else:
        return "🤔 **Я пока не знаю точного ответа.**\n\nМогу помочь с темами:\n• Цвет и палитры 🎨\n• Логотипы и брендинг 💡\n• Шрифты и типографика 📝\n• Композиция и верстка 📐\n• UX/UI интерфейсы 📱\n\n**Попробуй переформулировать вопрос** или спроси про одну из этих тем."

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "🎨 **Привет, Tenshi!**\n\n"
            "📦 **Стикеры и эмодзи:**\n"
            "/newpack - Создать пак стикеров\n"
            "/newemoji - Создать пак эмодзи\n"
            "/get [название] - Получить пак\n"
            "/search [тег] - Найти паки по тегу\n"
            "/list - Мои паки\n"
            "/delete [название] - Удалить пак\n"
            "/stats - Статистика\n\n"
            "🎨 **Дизайн-инструменты:**\n"
            "/palette - Вырезать цвета из картинки\n"
            "/preview - Показать стикер в кружке\n"
            "/font [текст] - Красивые шрифты\n"
            "/ask [вопрос] - Советы по дизайну\n"
            "/contrast - Проверить контраст\n"
            "/removebg - Удалить фон\n"
            "/challenge - Получить дизайн-задачу\n"
            "/pxrem - Конвертер PX ↔ REM\n"
            "/golden - Золотое сечение\n\n"
            "🤖 **ИИ-помощник:**\n"
            "/ai [вопрос] - Задать вопрос по дизайну\n\n"
            "📝 **Текст:**\n"
            "/maketext [текст] - Текст в эмодзи"
        )
    else:
        await message.answer(
            "✦ **Привет!**\n\n"
            "🎨 **Дизайн-инструменты:**\n"
            "/palette - Вырезать цвета\n"
            "/preview - Превью стикера\n"
            "/font [текст] - Красивые шрифты\n"
            "/ask - Советы по дизайну\n"
            "/contrast - Проверить контраст\n"
            "/pxrem - Конвертер PX ↔ REM\n"
            "/golden - Золотое сечение\n"
            "/maketext - Текст в эмодзи\n\n"
            "📦 **Получить пак:**\n"
            "/get [название] - Ссылка на пак\n"
            "/search [тег] - Найти паки"
        )

# ========== НОВЫЙ /ask (расширенный) ==========
@dp.message(Command("ask"))
async def ask_command(message: Message):
    question = message.text.replace('/ask', '').strip()
    if not question:
        await message.answer(
            "❓ Напиши вопрос после команды:\n"
            "/ask как подобрать шрифты?\n\n"
            "Я знаю про: цвета, логотипы, шрифты, композицию, UX/UI."
        )
        return
    
    response = None
    if any(word in question.lower() for word in ["цвет", "палитр", "оттенок", "сочетание"]):
        response = "🎨 **Советы по цвету:**\n\n• Используй цветовой круг\n• Комплементарные цвета дают контраст\n• Аналоговые цвета — спокойная гармония\n• Проверяй контраст через /contrast"
    elif any(word in question.lower() for word in ["логотип", "лого", "бренд", "айдентика"]):
        response = "💡 **Советы по логотипу:**\n\n• Простота — ключ к запоминанию\n• Не более 2-3 цветов\n• Шрифт должен читаться в любом размере\n• Проверь в чёрно-белом варианте"
    elif any(word in question.lower() for word in ["шрифт", "типографик", "гарнитур", "начертани"]):
        response = "📝 **Советы по типографике:**\n\n• Не более 2-3 шрифтов в проекте\n• Контрастные шрифты создают динамику\n• Проверяй читаемость на разных размерах\n• Для заголовков используй display-шрифты"
    elif any(word in question.lower() for word in ["композици", "верстк", "макет", "сетк", "расположени"]):
        response = "📐 **Советы по композиции:**\n\n• Правило третей — ключевые элементы на пересечении линий\n• Направляющие линии для движения глаз\n• Иерархия через размер и цвет\n• Пустое пространство — не враг"
    elif any(word in question.lower() for word in ["ux", "ui", "интерфейс", "приложени", "сайт", "юзабилити"]):
        response = "📱 **Советы по UX/UI:**\n\n• Пользователь должен понимать интерфейс без инструкции\n• Кнопки должны быть заметными и удобными\n• Цвета должны быть контрастными для читаемости\n• Используй привычные паттерны"
    else:
        response = "🤔 Я пока знаю советы по темам:\n• Цвета 🎨\n• Логотипы 💡\n• Шрифты 📝\n• Композиция 📐\n• UX/UI 📱\n\nПопробуй переформулировать вопрос или спроси про одну из этих тем."
    
    await message.answer(response)

# ========== НОВЫЙ /challenge (с перемешиванием) ==========
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

# ========== ВЫБОР РЕЖИМА ДЛЯ /ai ==========
@dp.message(Command("ai"))
async def ai_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.")
        return
    
    args = message.text.replace('/ai', '').strip()
    if not args:
        await state.set_state(CreatePack.waiting_for_ai)
        await message.answer(
            "🤖 **ИИ-помощник по дизайну**\n\n"
            "Напиши свой вопрос.\n"
            "Например:\n"
            "• Как подобрать цвета для логотипа?\n"
            "• Какие шрифты сочетаются?\n"
            "• Что такое композиция?"
        )
        return
    
    await state.update_data(ai_question=args)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧠 Локально", callback_data="ai_local"),
            InlineKeyboardButton(text="🤖 ИИ (HF)", callback_data="ai_hf")
        ]
    ])
    
    await message.answer(
        f"❓ **Вопрос:**\n{args}\n\n"
        "Выбери режим ответа:",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('ai_'))
async def process_ai_choice(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    
    data = await state.get_data()
    question = data.get('ai_question')
    
    if not question:
        await callback_query.message.answer("❌ Вопрос не найден. Напиши /ai заново.")
        return
    
    status_msg = await callback_query.message.answer("⏳ Думаю...")
    
    if callback_query.data == 'ai_local':
        response = await local_ai_assistant(question)
        mode = "🧠 Локальный режим"
    else:
        response = await ai_assistant(question)
        mode = "🤖 Режим ИИ (Hugging Face)"
    
    await status_msg.delete()
    await callback_query.message.answer(
        f"{mode}\n\n{response}",
        parse_mode="Markdown"
    )
    await state.clear()

@dp.message(CreatePack.waiting_for_ai)
async def handle_ai_question(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Напиши текст!")
        return
    
    await state.update_data(ai_question=message.text)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧠 Локально", callback_data="ai_local"),
            InlineKeyboardButton(text="🤖 ИИ (HF)", callback_data="ai_hf")
        ]
    ])
    
    await message.answer(
        f"❓
