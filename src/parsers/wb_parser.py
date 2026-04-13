"""
Парсер Wildberries для получения информации о товаре по артикулу
"""

import logging
import json
import re
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth

logger = logging.getLogger(__name__)


@dataclass
class WBProductInfo:
    """Информация о товаре Wildberries"""
    article: str
    name: str = ""
    brand: str = ""
    price: int = 0  # Цена в копейках
    original_price: int = 0  # Оригинальная цена в копейках
    discount: int = 0  # Скидка в процентах
    rating: float = 0.0
    reviews_count: int = 0
    image_url: str = ""
    product_url: str = ""
    success: bool = False
    error: str = ""


class WBParser:
    """Парсер Wildberries"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        })
    
    def get_product_by_article(self, article: str) -> WBProductInfo:
        """
        Получить информацию о товаре по артикулу
        
        Args:
            article: Артикул товара на Wildberries
            
        Returns:
            WBProductInfo с информацией о товаре
        """
        logger.info(f"Поиск товара WB по артикулу: {article}")
        
        try:
            # Пытаемся получить информацию через API Wildberries
            product_info = self._get_product_via_api(article)
            
            if product_info and product_info.success:
                logger.info(f"Товар WB найден: {product_info.name}, цена: {product_info.price} коп.")
                return product_info
            
            # Если API не сработал, пробуем через Selenium
            logger.info(f"API не вернул результат, пробуем через браузер...")
            product_info = self._get_product_via_selenium(article)
            
            if product_info and product_info.success:
                logger.info(f"Товар WB найден через браузер: {product_info.name}, цена: {product_info.price} коп.")
                return product_info
            
            return WBProductInfo(
                article=article,
                success=False,
                error="Товар не найден или недоступен"
            )
            
        except Exception as e:
            logger.error(f"Ошибка парсинга WB товара {article}: {e}")
            return WBProductInfo(
                article=article,
                success=False,
                error=str(e)
            )
    
    def _get_product_via_api(self, article: str) -> Optional[WBProductInfo]:
        """Получение информации о товаре через API Wildberries"""
        try:
            # Получаем ID товара (vol) и корзину (basket) для артикула
            # Используем публичное API Wildberries
            card_url = f"https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=0&nm={article}"
            
            response = self.session.get(card_url, timeout=15)
            
            if response.status_code != 200:
                logger.debug(f"API вернул статус {response.status_code}")
                return None
            
            data = response.json()
            
            if 'data' not in data or 'products' not in data['data']:
                logger.debug("В ответе API нет данных о продукте")
                return None
            
            products = data['data']['products']
            if not products:
                return None
            
            product = products[0]
            
            # Извлекаем информацию
            name = product.get('name', '')
            brand = product.get('brand', '')
            
            # Цены
            price_info = product.get('price', {})
            total = price_info.get('total', 0)
            original = price_info.get('original', 0)
            
            # Рейтинг и отзывы
            rating = product.get('rating', 0.0)
            reviews_count = product.get('feedbacks', 0)
            
            # Изображения
            images = product.get('images', [])
            image_url = f"https://{images[0]}" if images else ""
            
            # Формируем URL товара
            product_url = f"https://www.wildberries.ru/catalog/{article}/detail.aspx"
            
            return WBProductInfo(
                article=article,
                name=name,
                brand=brand,
                price=total,
                original_price=original,
                discount=product.get('discount', 0),
                rating=float(rating) if rating else 0.0,
                reviews_count=int(reviews_count) if reviews_count else 0,
                image_url=image_url,
                product_url=product_url,
                success=True
            )
            
        except Exception as e:
            logger.debug(f"Ошибка API WB: {e}")
            return None
    
    def _get_product_via_selenium(self, article: str) -> Optional[WBProductInfo]:
        """Получение информации о товаре через Selenium (резервный метод)"""
        driver = None
        try:
            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--window-size=1920,1080")
            
            driver = webdriver.Chrome(options=chrome_options)
            stealth(driver,
                   languages=["ru-RU", "ru"],
                   vendor="Google Inc.",
                   platform="Win32",
                   webgl_vendor="Intel Inc.",
                   renderer="Intel Iris OpenGL Engine",
                   fix_hairline=True)
            
            product_url = f"https://www.wildberries.ru/catalog/{article}/detail.aspx"
            driver.get(product_url)
            time.sleep(3)
            
            # Пробуем найти данные на странице
            page_source = driver.page_source
            
            # Ищем JSON с данными товара
            import re
            json_pattern = r'__INITIAL_STATE__\s*=\s*({.*?});'
            match = re.search(json_pattern, page_source, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                # Парсим данные из state
                # Это упрощенная реализация
                pass
            
            # Альтернативно ищем цену и название через селекторы
            return None
            
        except Exception as e:
            logger.error(f"Ошибка Selenium WB: {e}")
            return None
        finally:
            if driver:
                driver.quit()


def parse_wb_article(article: str) -> WBProductInfo:
    """
    Удобная функция для парсинга товара WB по артикулу
    
    Args:
        article: Артикул товара
        
    Returns:
        WBProductInfo с информацией о товаре
    """
    parser = WBParser()
    return parser.get_product_by_article(article)


if __name__ == "__main__":
    # Тест
    logging.basicConfig(level=logging.INFO)
    
    test_article = input("Введите артикул WB: ")
    result = parse_wb_article(test_article)
    
    if result.success:
        print(f"\n✅ Товар найден:")
        print(f"Название: {result.name}")
        print(f"Бренд: {result.brand}")
        print(f"Цена: {result.price / 100} ₽")
        print(f"Скидка: {result.discount}%")
        print(f"Рейтинг: {result.rating}")
        print(f"Отзывов: {result.reviews_count}")
        print(f"URL: {result.product_url}")
    else:
        print(f"❌ Ошибка: {result.error}")
