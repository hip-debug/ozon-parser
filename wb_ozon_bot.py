#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram бот для сравнения цен Wildberries и Ozon
На вход принимает артикул товара WB, на выходе показывает самый дешевый аналог на Ozon
"""

import logging
import asyncio
import threading
from typing import Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.parsers.wb_parser import parse_wb_article
from src.parsers.ozon_analog_finder import find_cheapest_ozon_analog

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ParsingStates(StatesGroup):
    waiting_for_article = State()


class WBToOzonBot:
    """Telegram бот для сравнения цен WB и Ozon"""
    
    def __init__(self, bot_token: str, allowed_user_ids: list = None):
        self.bot_token = bot_token
        self.allowed_user_ids = allowed_user_ids or []  # Если пустой - все пользователи разрешены
        self.bot = Bot(token=bot_token)
        self.dp = Dispatcher()
        self.is_running = False
        self._register_handlers()
    
    def _is_authorized(self, user_id: int) -> bool:
        """Проверка авторизации пользователя"""
        if not self.allowed_user_ids:
            return True
        return str(user_id) in [str(uid) for uid in self.allowed_user_ids]
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        self.dp.message.register(self._cmd_start, Command('start'))
        self.dp.message.register(self._cmd_help, Command('help'))
        self.dp.message.register(self._handle_article_input, StateFilter(ParsingStates.waiting_for_article))
        self.dp.message.register(self._handle_message)
    
    async def _cmd_start(self, message: Message, state: FSMContext):
        """Обработчик команды /start"""
        if not self._is_authorized(message.from_user.id):
            await message.reply("❌ У вас нет доступа к этому боту")
            return
        
        await state.clear()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти аналог", callback_data="find_analog")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
        ])
        
        welcome_text = (
            "🤖 <b>Добро пожаловать в WB → Ozon Price Comparator!</b>\n\n"
            "Этот бот поможет найти самый дешевый аналог товара с Wildberries на Ozon.\n\n"
            "<b>Как использовать:</b>\n"
            "1️⃣ Отправьте артикул товара с WB\n"
            "2️⃣ Бот найдет товар на WB\n"
            "3️⃣ Бот поищет аналоги на Ozon\n"
            "4️⃣ Покажет самый дешевый вариант\n\n"
            "Пример артикула: <code>15062891</code>"
        )
        
        await message.reply(welcome_text, reply_markup=keyboard, parse_mode="HTML")
    
    async def _cmd_help(self, message: Message):
        """Обработчик команды /help"""
        help_text = (
            "🆘 <b>Помощь</b>\n\n"
            "<b>Что делает этот бот:</b>\n"
            "• Принимает артикул товара с Wildberries\n"
            "• Ищет этот товар на WB\n"
            "• Находит аналоги на Ozon по названию и бренду\n"
            "• Показывает самый дешевый аналог\n\n"
            "<b>Пример использования:</b>\n"
            "Отправьте: <code>15062891</code>\n\n"
            "<b>Команды:</b>\n"
            "/start - Главное меню\n"
            "/help - Эта справка"
        )
        
        await message.reply(help_text, parse_mode="HTML")
    
    async def _handle_article_input(self, message: Message, state: FSMContext):
        """Обработка введенного артикула"""
        if not self._is_authorized(message.from_user.id):
            return
        
        article = message.text.strip()
        
        # Проверяем что это цифры
        if not article.isdigit():
            await message.reply(
                "❌ Артикул должен содержать только цифры.\n"
                "Пожалуйста, отправьте корректный артикул WB."
            )
            return
        
        await message.reply(f"🔍 Ищу товар WB по артикулу <code>{article}</code>...")
        
        # Запускаем поиск в отдельном потоке чтобы не блокировать бота
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._find_analog_sync, article)
        
        await self._send_result(message, result, state)
    
    def _find_analog_sync(self, article: str) -> dict:
        """Синхронная функция поиска аналога (для executor)"""
        try:
            # Шаг 1: Парсим товар с WB
            logger.info(f"Парсинг WB товара: {article}")
            wb_product = parse_wb_article(article)
            
            if not wb_product.success:
                return {
                    'success': False,
                    'error': f"WB: {wb_product.error}",
                    'wb_product': None,
                    'ozon_analog': None
                }
            
            # Шаг 2: Ищем аналог на Ozon
            logger.info(f"Поиск аналога на Ozon для: {wb_product.name}")
            ozon_analog = find_cheapest_ozon_analog(
                wb_product_name=wb_product.name,
                brand=wb_product.brand
            )
            
            return {
                'success': True,
                'wb_product': wb_product,
                'ozon_analog': ozon_analog
            }
            
        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
            return {
                'success': False,
                'error': str(e),
                'wb_product': None,
                'ozon_analog': None
            }
    
    async def _send_result(self, message: Message, result: dict):
        """Отправка результата пользователю"""
        if not result['success']:
            await message.reply(
                f"❌ Ошибка: {result['error']}\n\n"
                "Попробуйте другой артикул или команду /help"
            )
            return
        
        wb_product = result['wb_product']
        ozon_analog = result['ozon_analog']
        
        # Формируем сообщение о товаре WB
        wb_text = (
            f"✅ <b>Товар найден на Wildberries:</b>\n\n"
            f"📦 <b>{wb_product.name}</b>\n"
            f"🏷️ Бренд: {wb_product.brand or 'Не указан'}\n"
            f"💰 Цена: <b>{wb_product.price / 100} ₽</b>\n"
        )
        
        if wb_product.original_price > 0:
            wb_text += f"~~{wb_product.original_price / 100} ₽~~\n"
        
        if wb_product.discount > 0:
            wb_text += f"🏷️ Скидка: {wb_product.discount}%\n"
        
        if wb_product.rating > 0:
            wb_text += f"⭐ Рейтинг: {wb_product.rating} ({wb_product.reviews_count} отзывов)\n"
        
        wb_text += f"\n🔗 <a href='{wb_product.product_url}'>Ссылка на WB</a>"
        
        # Отправляем информацию о WB
        await message.reply(wb_text, parse_mode="HTML", disable_web_page_preview=False)
        
        # Информация об аналоге на Ozon
        if ozon_analog and ozon_analog.success:
            ozon_text = (
                f"\n🎉 <b>Найден аналог на Ozon!</b>\n\n"
                f"📦 <b>{ozon_analog.name}</b>\n"
                f"💰 Цена: <b>{ozon_analog.price} ₽</b>\n"
            )
            
            if ozon_analog.card_price > 0 and ozon_analog.card_price != ozon_analog.price:
                ozon_text += f"💳 Цена по карте: {ozon_analog.card_price} ₽\n"
            
            ozon_text += f"\n🔗 <a href='{ozon_analog.product_url}'>Ссылка на Ozon</a>"
            
            # Сравниваем цены
            wb_price = wb_product.price / 100
            ozon_price = ozon_analog.price
            
            if ozon_price < wb_price:
                savings = wb_price - ozon_price
                savings_percent = (savings / wb_price) * 100
                ozon_text += f"\n\n💚 <b>Выгода: {savings:.0f} ₽ ({savings_percent:.0f}%)</b>"
            elif ozon_price > wb_price:
                difference = ozon_price - wb_price
                ozon_text += f"\n\n⚠️ На Ozon дороже на {difference:.0f} ₽"
            else:
                ozon_text += f"\n\n💛 Цены одинаковые"
            
            await message.reply(ozon_text, parse_mode="HTML", disable_web_page_preview=False)
        else:
            await message.reply(
                "\n⚠️ <b>Аналоги на Ozon не найдены</b>\n\n"
                "Возможно, этот товар уникален для Wildberries.",
                parse_mode="HTML"
            )
        
        # Кнопки для дальнейшего действия
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти другой товар", callback_data="find_another")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
        ])
        
        await message.reply("Хотите найти другой товар?", reply_markup=keyboard)
    
    async def _handle_message(self, message: Message):
        """Обработка обычных сообщений - пытаемся распознать артикул"""
        if not self._is_authorized(message.from_user.id):
            return
        
        text = message.text.strip()
        
        # Если сообщение содержит только цифры - считаем это артикулом
        if text.isdigit():
            await message.reply(f"🔍 Ищу товар WB по артикулу <code>{text}</code>...")
            
            # Запускаем поиск в отдельном потоке чтобы не блокировать бота
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._find_analog_sync, text)
            
            await self._send_result(message, result)
        else:
            # Предлагаем ввести артикул
            await message.reply(
                "🔍 Пожалуйста, отправьте артикул товара с Wildberries.\n\n"
                "Артикул обычно указан в URL товара или в карточке товара.\n"
                "Пример: <code>15062891</code>",
                parse_mode="HTML"
            )
    
    async def _handle_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback запросов от кнопок"""
        data = callback.data
        
        if data == "find_analog":
            await callback.message.edit_text(
                "🔍 Отправьте артикул товара с Wildberries:\n\n"
                "Или нажмите /cancel для отмены"
            )
            await state.set_state(ParsingStates.waiting_for_article)
        elif data == "find_another":
            await state.clear()
            await callback.message.edit_text(
                "🔍 Отправьте новый артикул товара с Wildberries:"
            )
            await state.set_state(ParsingStates.waiting_for_article)
        elif data == "help":
            await self._cmd_help(callback.message)
        
        await callback.answer()
    
    def start(self) -> bool:
        """Запуск бота в отдельном потоке"""
        try:
            def run_bot():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    self.is_running = True
                    loop.run_until_complete(self.dp.start_polling(self.bot))
                finally:
                    loop.close()
                    self.is_running = False
            
            self.bot_thread = threading.Thread(target=run_bot, daemon=True)
            self.bot_thread.start()
            
            import time
            time.sleep(2)
            
            return self.is_running
            
        except Exception as e:
            logger.error(f"Ошибка запуска бота: {e}")
            return False
    
    def stop(self):
        """Остановка бота"""
        try:
            if self.bot:
                asyncio.run(self.bot.session.close())
            self.is_running = False
            logger.info("Бот остановлен")
        except Exception as e:
            logger.error(f"Ошибка остановки бота: {e}")


def main():
    """Точка входа"""
    import os
    from pathlib import Path
    
    # Загружаем токен из config.txt или переменной окружения
    config_path = Path("config.txt")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_users = []
    
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    bot_token = line.split("=", 1)[1]
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1]
                    allowed_users.append(chat_id)
    
    if not bot_token:
        print("❌ Укажите TELEGRAM_BOT_TOKEN в config.txt или в переменной окружения")
        print("\nПример config.txt:")
        print("TELEGRAM_BOT_TOKEN=your_bot_token_here")
        print("TELEGRAM_CHAT_ID=your_user_id_here")
        return
    
    print("🤖 Запуск WB → Ozon Price Comparator бота...")
    print(f"✅ Токен получен: {bot_token[:10]}...")
    print(f"👥 Разрешенные пользователи: {allowed_users or 'Все'}")
    
    bot = WBToOzonBot(bot_token, allowed_users)
    
    if bot.start():
        print("✅ Бот запущен успешно!")
        print("\nОткройте Telegram и найдите вашего бота.")
        print("Отправьте /start для начала работы.\n")
        
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Остановка бота...")
            bot.stop()
    else:
        print("❌ Ошибка запуска бота")


if __name__ == "__main__":
    main()
