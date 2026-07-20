import logging
import sqlite3
import os
from datetime import datetime
from PIL import Image
import io
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8658625238:AAGIfOAz3cuVBUNrjvOinFK_2QGpoiVihvk"
ADMIN_ID = 5145527096

# ========== СОСТОЯНИЯ ДЛЯ FSM ==========
class CreatePack(StatesGroup):
    waiting_for_images = State()
    waiting_for_pack_name = State()
    waiting_for_emoji_images = State()
    waiting_for_emoji_pack_name = State()

# ========== БАЗА ЭМОДЗИ-КОНВЕРТАЦИИ ==========
LETTER_TO_EMOJI = {
    'a': '🇦', 'b': '🇧', 'c': '🇨', 'd': '🇩', 'e': '🇪',
    'f': '🇫', 'g': '🇬', 'h': '🇭', 'i': '🇮', 'j': '🇯',
    'k': '🇰', 'l': '🇱', 'm': '🇲', 'n': '🇳', 'o': '🇴',
    'p': '🇵', 'q': '🇶', 'r': '🇷', 's': '🇸', 't': '🇹',
    'u': '🇺', 'v': '🇻', 'w': '🇼', 'x': '🇽', 'y': '🇾', 'z': '🇿'
}

TEXT_TO_EMOJI = {
    ':heart:': '❤️',
    ':fire:': '🔥',
    ':cat:': '🐱',
    ':dog:': '🐶',
    ':star:': '⭐',
    ':rainbow:': '🌈',
    ':unicorn:': '🦄',
    ':rocket:': '🚀',
    ':sparkles:': '✨',
    ':thumbsup:': '👍',
    ':smile:': '😊',
    ':laugh:': '😂',
    ':love:': '🥰',
    ':cool:': '😎',
    ':cry:': '😢',
    ':angry:': '😡',
    ':surprised:': '😮',
    ':sleep:': '😴',
    ':pray:': '🙏',
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
    """Превращает текст в эмодзи"""
    text = text.lower().strip()
    
    # Проверяем, есть ли текст в виде :слово:
    if text in TEXT_TO_EMOJI:
        return TEXT_TO_EMOJI[text]
    
    # Превращаем каждую букву в эмодзи-букву
    result = []
    for char in text:
        if char in LETTER_TO_EMOJI:
            result.append(LETTER_TO_EMOJI[char])
        elif char == ' ':
            result.append('  ')
        else:
            result.append(char)
    
    return ' '.join(result) if result else '❓ Неизвестный текст'

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "🎨 Привет, Создатель!\n\n"
            "Доступные команды:\n"
            "/newpack - Создать новый пак стикеров\n"
            "/newemoji - Создать новый пак эмодзи\n"
            "/maketext [текст] - Превратить текст в эмодзи\n"
            "/list - Показать все паки\n"
            "/delete [название] - Удалить пак\n"
            "/stats - Статистика\n\n"
            "Просто кидай мне картинки (PNG/JPG) и я превращу их в стикеры или эмодзи!"
        )
    else:
        await message.answer(
            "👋 Привет!\n\n"
            "Я бот для создания стикеров и эмодзи.\n"
            "Используй /get [название] чтобы получить ссылку на пак."
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
        
        # Для эмодзи используем тот же конвертер
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

# ========== ЗАПУСК ==========
async def main():
    await asyncio.sleep(3)
    print("🤖 Бот запущен с поддержкой стикеров и эмодзи!")
    await dp.start_polling(bot, request_timeout=60)

if __name__ == "__main__":
    asyncio.run(main())
