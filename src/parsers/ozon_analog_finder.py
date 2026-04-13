"""
Парсер Ozon для поиска аналогов товаров по названию/бренду
Использует существующий парсер product_parser.py
"""

import logging
import re
import time
from typing import List, Optional, Dict
from dataclasses import dataclass
from .product_parser import OzonProductParser, ProductInfo
from ..utils.selenium_manager import SeleniumManager

logger = logging.getLogger(__name__)


@dataclass
class OzonAnalogInfo:
    """Информация об аналоге товара на Ozon"""
    article: str
    name: str = ""
    price: int = 0  # Цена в копейках/рублях (как вернет парсер)
    card_price: int = 0  # Цена по карте
    original_price: int = 0  # Старая цена
    rating: float = 0.0
    reviews_count: int = 0
    image_url: str = ""
    product_url: str = ""
    similarity_score: float = 0.0  # Оценка схожести (0-1)
    success: bool = False
    error: str = ""


class OzonAnalogFinder:
    """Поиск аналогов товаров на Ozon"""
    
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.selenium_manager = None
    
    def find_analogs_by_query(self, query: str, max_results: int = 10) -> List[OzonAnalogInfo]:
        """
        Поиск аналогов по поисковому запросу
        
        Args:
            query: Поисковый запрос (название товара, бренд)
            max_results: Максимальное количество результатов
            
        Returns:
            Список найденных аналогов
        """
        logger.info(f"Поиск аналогов на Ozon по запросу: {query}")
        
        try:
            # Формируем URL поиска
            search_url = f"https://www.ozon.ru/search/?text={query.replace(' ', '%20')}"
            
            # Используем Selenium для получения ссылок на товары
            links = self._get_search_links(search_url, max_results)
            
            if not links:
                return [OzonAnalogInfo(
                    article="",
                    success=False,
                    error="Не удалось получить результаты поиска"
                )]
            
            # Парсим информацию о товарах
            parser = OzonProductParser(max_workers=self.max_workers)
            results = parser.parse_products(links)
            
            # Преобразуем в формат OzonAnalogInfo
            analogs = []
            for result in results:
                if result.success:
                    analog = OzonAnalogInfo(
                        article=result.article,
                        name=result.name,
                        price=result.price,
                        card_price=result.card_price,
                        original_price=result.original_price,
                        image_url=result.image_url,
                        product_url=f"https://www.ozon.ru/product/{result.article}",
                        success=True
                    )
                    
                    # Вычисляем схожесть с исходным запросом
                    analog.similarity_score = self._calculate_similarity(query, result.name)
                    analogs.append(analog)
            
            # Сортируем по схожести и цене
            analogs.sort(key=lambda x: (-x.similarity_score, x.price))
            
            logger.info(f"Найдено {len(analogs)} аналогов")
            return analogs[:max_results]
            
        except Exception as e:
            logger.error(f"Ошибка поиска аналогов: {e}")
            return [OzonAnalogInfo(
                article="",
                success=False,
                error=str(e)
            )]
        finally:
            parser.cleanup()
    
    def _get_search_links(self, search_url: str, max_results: int) -> Dict[str, str]:
        """
        Получить ссылки на товары из результатов поиска
        
        Returns:
            Dict[url, image_url] - словарь ссылок и изображений
        """
        if self.selenium_manager is None:
            self.selenium_manager = SeleniumManager(headless=True)
        
        driver = self.selenium_manager.create_driver()
        links_dict = {}
        
        try:
            driver.get(search_url)
            time.sleep(3)  # Ждем загрузки страницы
            
            # Прокручиваем страницу для загрузки товаров
            for _ in range(3):
                driver.execute_script("window.scrollBy(0, 500)")
                time.sleep(1)
            
            # Находим все карточки товаров
            product_cards = driver.find_elements("css selector", "[data-widget='galleryProduct']")
            
            for card in product_cards[:max_results]:
                try:
                    # Ищем ссылку на товар
                    link_element = card.find_element("css selector", "a[href*='/product/']")
                    product_url = link_element.get_attribute("href")
                    
                    # Извлекаем артикул из URL
                    article_match = re.search(r'/product/[^/]+-(\d+)/', product_url)
                    if article_match:
                        article = article_match.group(1)
                        
                        # Пытаемся найти изображение
                        img_url = ""
                        try:
                            img_element = card.find_element("css selector", "img")
                            img_url = img_element.get_attribute("src")
                        except:
                            pass
                        
                        links_dict[product_url] = img_url
                except Exception as e:
                    logger.debug(f"Ошибка обработки карточки: {e}")
                    continue
            
            logger.info(f"Получено {len(links_dict)} ссылок из поиска")
            return links_dict
            
        except Exception as e:
            logger.error(f"Ошибка получения ссылок: {e}")
            return {}
        finally:
            driver.quit()
    
    def _calculate_similarity(self, query: str, product_name: str) -> float:
        """
        Вычислить схожесть между запросом и названием товара
        
        Returns:
            float от 0 до 1
        """
        query_lower = query.lower()
        name_lower = product_name.lower()
        
        # Полное совпадение
        if query_lower in name_lower or name_lower in query_lower:
            return 1.0
        
        # Совпадение слов
        query_words = set(query_lower.split())
        name_words = set(name_lower.split())
        
        common_words = query_words & name_words
        if not query_words:
            return 0.0
        
        similarity = len(common_words) / len(query_words)
        return min(similarity, 1.0)
    
    def find_cheapest_analog(self, query: str) -> Optional[OzonAnalogInfo]:
        """
        Найти самый дешевый аналог по запросу
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Самый дешевый аналог или None
        """
        analogs = self.find_analogs_by_query(query, max_results=20)
        
        if not analogs:
            return None
        
        # Фильтруем успешные результаты
        valid_analogs = [a for a in analogs if a.success and a.price > 0]
        
        if not valid_analogs:
            return None
        
        # Находим самый дешевый
        cheapest = min(valid_analogs, key=lambda x: x.price)
        return cheapest
    
    def close(self):
        """Закрыть ресурсы"""
        if self.selenium_manager:
            self.selenium_manager.close()


def find_ozon_analogs(wb_product_name: str, brand: str = "") -> List[OzonAnalogInfo]:
    """
    Удобная функция для поиска аналогов на Ozon
    
    Args:
        wb_product_name: Название товара с WB
        brand: Бренд товара (опционально)
        
    Returns:
        Список аналогов с Ozon
    """
    finder = OzonAnalogFinder()
    
    # Формируем поисковый запрос
    query = f"{brand} {wb_product_name}".strip() if brand else wb_product_name
    
    try:
        return finder.find_analogs_by_query(query, max_results=10)
    finally:
        finder.close()


def find_cheapest_ozon_analog(wb_product_name: str, brand: str = "") -> Optional[OzonAnalogInfo]:
    """
    Найти самый дешевый аналог на Ozon
    
    Args:
        wb_product_name: Название товара с WB
        brand: Бренд товара (опционально)
        
    Returns:
        Самый дешевый аналог или None
    """
    finder = OzonAnalogFinder()
    
    query = f"{brand} {wb_product_name}".strip() if brand else wb_product_name
    
    try:
        return finder.find_cheapest_analog(query)
    finally:
        finder.close()


if __name__ == "__main__":
    # Тест
    logging.basicConfig(level=logging.INFO)
    
    test_query = input("Введите название товара для поиска аналогов: ")
    analogs = find_ozon_analogs(test_query)
    
    if analogs:
        print(f"\n✅ Найдено {len(analogs)} аналогов:")
        for i, analog in enumerate(analogs[:5], 1):
            print(f"\n{i}. {analog.name}")
            print(f"   Артикул: {analog.article}")
            print(f"   Цена: {analog.price} ₽")
            print(f"   Цена по карте: {analog.card_price} ₽")
            print(f"   Схожесть: {analog.similarity_score:.2f}")
            print(f"   URL: {analog.product_url}")
    else:
        print("❌ Аналоги не найдены")
