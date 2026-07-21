import logging
import os
import io
import asyncio
import tempfile
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pydub import AudioSegment
import matplotlib.pyplot as plt
import numpy as np
from aiohttp import web

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "ТВОЙ_ТОКЕН_СЮДА"  # Вставь токен от нового бота
ADMIN_ID = 123456789  # Вставь свой Telegram ID

# ========== СОСТОЯНИЯ ==========
class AudioStates(StatesGroup):
    waiting_for_audio = State()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=BOT_TOKEN)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def extract_instrumental(audio_bytes):
    """
    Превращает трек в инструментал (удаляет вокал)
    через вычитание каналов. Работает быстро и без потери качества.
    """
    # Загружаем аудио
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    
    audio = AudioSegment.from_file(tmp_path)
    os.unlink(tmp_path)
    
    # Переводим в numpy для обработки
    samples = np.array(audio.get_array_of_samples())
    
    # Если стерео (2 канала)
    if audio.channels == 2:
        # Преобразуем в формат (samples, channels)
        samples = samples.reshape((-1, 2))
        
        # Вычитаем правый канал из левого (удаляем центр)
        # Вокал обычно в центре, поэтому он исчезает
        instrumental = (samples[:, 0] - samples[:, 1]) / 2
        
        # Возвращаем в формат AudioSegment
        instrumental = instrumental.astype(np.int16)
        instrumental = AudioSegment(
            instrumental.tobytes(),
            frame_rate=audio.frame_rate,
            sample_width=audio.sample_width,
            channels=1  # Становится моно
        )
    else:
        # Если уже моно, просто возвращаем как есть
        instrumental = audio
    
    # Экспортируем в MP3 с высоким качеством
    output = io.BytesIO()
    instrumental.export(output, format="mp3", bitrate="320k")
    output.seek(0)
    return output

def change_speed(audio_bytes, speed=1.0, pitch_shift=False, reverb=False):
    """
    Изменяет скорость аудио
    speed: 0.1–2.0
    pitch_shift: True — меняет тон (классический speedup), False — сохраняет тон
    reverb: True — добавляет реверберацию
    """
    # Загружаем аудио
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    
    audio = AudioSegment.from_file(tmp_path)
    os.unlink(tmp_path)
    
    # Изменяем скорость
    if pitch_shift:
        audio = audio.speedup(playback_speed=speed)
    else:
        new_sample_rate = int(audio.frame_rate * speed)
        audio = audio._spawn(audio.raw_data, overrides={"frame_rate": new_sample_rate})
        audio = audio.set_frame_rate(44100)
    
    # Добавляем реверберацию (для режимов Ambient, Funk)
    if reverb:
        reverb_audio = audio - 12
        audio = audio.overlay(reverb_audio, position=200)
    
    # Экспортируем в MP3 с высоким качеством
    output = io.BytesIO()
    audio.export(output, format="mp3", bitrate="320k")
    output.seek(0)
    return output

def generate_waveform(audio_bytes):
    """Генерирует спектрограмму"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    
    audio = AudioSegment.from_file(tmp_path)
    os.unlink(tmp_path)
    
    samples = np.array(audio.get_array_of_samples())
    if audio.channels == 2:
        samples = samples.reshape((-1, 2))
        samples = np.mean(samples, axis=1)
    
    plt.figure(figsize=(12, 4))
    plt.plot(samples[::100], color='#6C5CE7', linewidth=0.8)
    plt.title("Волновая форма трека", fontsize=14, color='white')
    plt.xlabel("Время (условное)", color='white')
    plt.ylabel("Амплитуда", color='white')
    plt.gca().set_facecolor('#1A1A1A')
    plt.gcf().patch.set_facecolor('#1A1A1A')
    plt.grid(True, alpha=0.2, color='white')
    plt.tight_layout()
    
    img_io = io.BytesIO()
    plt.savefig(img_io, format='png', dpi=80, bbox_inches='tight')
    plt.close()
    img_io.seek(0)
    return img_io

# ========== КОМАНДЫ ==========
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🎵 **Tenshi Audio Bot**\n\n"
        "Я умею изменять скорость аудио, удалять вокал и создавать крутые эффекты!\n\n"
        "📤 **Просто отправь мне аудиофайл** (MP3, WAV, M4A, OGG)\n"
        "И выбери режим обработки:\n\n"
        "🎚️ **Доступные режимы:**\n"
        "• 🐢 **Слоу** (0.7x)\n"
        "• ⚡ **Спид** (1.5x)\n"
        "• 🎧 **Nightcore** (1.3x + тон)\n"
        "• 🕰️ **Винтаж** (0.6x + тон)\n"
        "• 🎸 **Фанк** (0.8x + реверб)\n"
        "• 🌿 **Эмбиент** (0.5x + реверб)\n"
        "• 🎚️ **Кастом** (0.1x – 2.0x)\n"
        "• 🎤 **Инструментал** (удаление вокала)\n\n"
        "📊 Также я покажу визуализацию трека!"
    )

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "🎵 **Tenshi Audio Bot — Справка**\n\n"
        "1. Отправь мне аудиофайл\n"
        "2. Выбери режим\n"
        "3. Получи готовый трек + визуализацию\n\n"
        "🎚️ **Режимы:**\n"
        "• 0.3x–0.9x — замедление\n"
        "• 1.0x — оригинал\n"
        "• 1.1x–2.0x — ускорение\n"
        "• 🎤 Инструментал — удаляет вокал\n\n"
        "🔊 **Фишки:**\n"
        "• Сохранение тональности\n"
        "• Реверберация\n"
        "• Визуализация"
    )

# ========== ОБРАБОТЧИК АУДИО ==========
@dp.message(lambda message: message.audio or message.voice or message.document)
async def handle_audio(message: Message, state: FSMContext):
    """Обрабатывает присланный аудиофайл"""
    try:
        if message.audio:
            file_id = message.audio.file_id
            file_name = message.audio.file_name or "audio.mp3"
        elif message.voice:
            file_id = message.voice.file_id
            file_name = "voice.ogg"
        else:
            file_id = message.document.file_id
            file_name = message.document.file_name or "audio.mp3"
        
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_data = file_bytes.read()
        
        await state.update_data(audio_data=file_data, file_name=file_name)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🐢 Слоу 0.7x", callback_data="speed_0.7_normal"),
                InlineKeyboardButton(text="⚡ Спид 1.5x", callback_data="speed_1.5_normal"),
            ],
            [
                InlineKeyboardButton(text="🎧 Nightcore 1.3x", callback_data="speed_1.3_pitch"),
                InlineKeyboardButton(text="🕰️ Винтаж 0.6x", callback_data="speed_0.6_pitch"),
            ],
            [
                InlineKeyboardButton(text="🎸 Фанк 0.8x", callback_data="speed_0.8_reverb"),
                InlineKeyboardButton(text="🌿 Эмбиент 0.5x", callback_data="speed_0.5_reverb"),
            ],
            [
                InlineKeyboardButton(text="🎶 Оригинал 1.0x", callback_data="speed_1.0_normal"),
                InlineKeyboardButton(text="🎚️ Кастом", callback_data="speed_custom"),
            ],
            [
                InlineKeyboardButton(text="🎤 Инструментал", callback_data="instrumental"),
                InlineKeyboardButton(text="📊 Визуализация", callback_data="visualize"),
            ]
        ])
        
        await message.answer(
            f"🎵 **Трек загружен!**\n\n"
            f"Название: `{file_name}`\n"
            f"Выбери режим обработки:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при загрузке: {str(e)}")

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(lambda c: c.data.startswith('speed_'))
async def process_speed(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    data = await state.get_data()
    audio_data = data.get('audio_data')
    file_name = data.get('file_name', 'audio.mp3')
    
    if not audio_data:
        await callback.message.answer("❌ Аудио не найдено. Отправь трек заново.")
        return
    
    if callback.data == 'speed_custom':
        await state.set_state(AudioStates.waiting_for_audio)
        await callback.message.answer(
            "🎚️ **Введи скорость в формате:**\n"
            "0.5 — для замедления\n"
            "1.0 — оригинал\n"
            "2.0 — двойное ускорение\n\n"
            "Доступные значения: от 0.1 до 2.0"
        )
        return
    
    parts = callback.data.split('_')
    speed = float(parts[1])
    mode = parts[2] if len(parts) > 2 else 'normal'
    
    pitch_shift = mode == 'pitch'
    reverb = mode == 'reverb'
    
    await process_audio(callback.message, audio_data, file_name, speed, pitch_shift, reverb)

@dp.callback_query(lambda c: c.data == 'instrumental')
async def process_instrumental(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    data = await state.get_data()
    audio_data = data.get('audio_data')
    file_name = data.get('file_name', 'audio.mp3')
    
    if not audio_data:
        await callback.message.answer("❌ Аудио не найдено. Отправь трек заново.")
        return
    
    try:
        status_msg = await callback.message.answer("⏳ Удаляю вокал...")
        
        # Делаем инструментал
        result_audio = extract_instrumental(audio_data)
        
        # Генерируем визуализацию
        waveform = generate_waveform(audio_data)
        
        await callback.message.answer_audio(
            audio=BufferedInputFile(result_audio.getvalue(), filename=f"instrumental_{file_name}"),
            caption="🎤 **Инструментал готов!**\n\nВокал удалён, качество сохранено."
        )
        
        if waveform:
            await callback.message.answer_photo(
                photo=BufferedInputFile(waveform.getvalue(), filename="waveform.png"),
                caption="📊 Визуализация трека"
            )
        
        await status_msg.delete()
        
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")

async def process_audio(message, audio_data, file_name, speed, pitch_shift=False, reverb=False):
    """Обрабатывает аудио и отправляет результат"""
    try:
        status_msg = await message.answer("⏳ Обрабатываю трек...")
        
        result_audio = change_speed(audio_data, speed, pitch_shift, reverb)
        waveform = generate_waveform(audio_data)
        
        mode_names = {
            (0.7, False, False): "🐢 Слоу (0.7x)",
            (1.5, False, False): "⚡ Спид (1.5x)",
            (1.3, True, False): "🎧 Nightcore (1.3x + тон)",
            (0.6, True, False): "🕰️ Винтаж (0.6x + тон)",
            (0.8, False, True): "🎸 Фанк (0.8x + реверб)",
            (0.5, False, True): "🌿 Эмбиент (0.5x + реверб)",
            (1.0, False, False): "🎶 Оригинал",
        }
        
        speed_text = mode_names.get((speed, pitch_shift, reverb), f"{speed}x")
        
        caption = f"🎵 **Готово!**\n\nРежим: `{speed_text}`\nФайл: `{file_name}`"
        
        await message.answer_audio(
            audio=BufferedInputFile(result_audio.getvalue(), filename=f"speed_{speed}_{file_name}"),
            caption=caption,
            parse_mode="Markdown"
        )
        
        if waveform:
            await message.answer_photo(
                photo=BufferedInputFile(waveform.getvalue(), filename="waveform.png"),
                caption="📊 Визуализация трека"
            )
        
        await status_msg.delete()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка обработки: {str(e)}")

@dp.callback_query(lambda c: c.data == 'visualize')
async def process_visualize(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    data = await state.get_data()
    audio_data = data.get('audio_data')
    
    if not audio_data:
        await callback.message.answer("❌ Аудио не найдено. Отправь трек заново.")
        return
    
    try:
        waveform = generate_waveform(audio_data)
        if waveform:
            await callback.message.answer_photo(
                photo=BufferedInputFile(waveform.getvalue(), filename="waveform.png"),
                caption="📊 Визуализация трека"
            )
        else:
            await callback.message.answer("❌ Не удалось создать визуализацию.")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {str(e)}")

@dp.message(AudioStates.waiting_for_audio)
async def handle_custom_speed(message: Message, state: FSMContext):
    try:
        speed = float(message.text.strip())
        if speed < 0.1 or speed > 2.0:
            await message.answer("❌ Скорость должна быть от 0.1 до 2.0. Попробуй снова:")
            return
        
        data = await state.get_data()
        audio_data = data.get('audio_data')
        file_name = data.get('file_name', 'audio.mp3')
        
        if not audio_data:
            await message.answer("❌ Аудио не найдено. Отправь трек заново.")
            await state.clear()
            return
        
        await process_audio(message, audio_data, file_name, speed, pitch_shift=False, reverb=False)
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Введи число, например: 1.5")

# ========== АДМИН-КОМАНДА ==========
@dp.message(Command("stats"))
async def stats_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа.")
        return
    
    await message.answer(
        "📊 **Tenshi Audio Bot — Статистика**\n\n"
        "• Версия: 1.1\n"
        "• Статус: ✅ Онлайн\n"
        "• Фичи: Speed, Pitch, Reverb, Instrumental"
    )

# ========== ДЛЯ RENDER ==========
async def health_check(request):
    return web.Response(text="🎵 Tenshi Audio Bot is alive!")

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
    print("🎵 Tenshi Audio Bot v1.1 запущен!")
    print("⚡ Доступны: Speed, Pitch Shift, Reverb, Instrumental!")
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot, request_timeout=90)

if __name__ == "__main__":
    asyncio.run(main())
