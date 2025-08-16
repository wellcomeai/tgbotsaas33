"""
Robokassa Payment Service - ИСПРАВЛЕННАЯ ВЕРСИЯ
Сервис для создания платежных ссылок и обработки уведомлений от Robokassa
"""

import hashlib
import structlog
from datetime import datetime
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

from config import settings

logger = structlog.get_logger()


class RobokassaService:
    """Сервис для работы с Robokassa - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    
    def __init__(self):
        self.merchant_login = settings.robokassa_merchant_login
        self.password1 = settings.robokassa_password1
        self.password2 = settings.robokassa_password2
        self.test_mode = settings.robokassa_test_mode
        
        # URL для создания платежей
        self.payment_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        
        logger.info("✅ RobokassaService initialized (FIXED VERSION)", 
                   merchant=self.merchant_login,
                   test_mode=self.test_mode)
    
    def generate_payment_url(self, 
                           plan_id: str, 
                           user_id: int, 
                           user_email: str = None) -> Tuple[str, str]:
        """
        Генерация ссылки для оплаты - ИСПРАВЛЕННАЯ ВЕРСИЯ
        
        Args:
            plan_id: ID тарифного плана (1m, 3m, 6m, 12m)
            user_id: ID пользователя Telegram
            user_email: Email пользователя (опционально)
            
        Returns:
            Tuple[payment_url, order_id]: Ссылка для оплаты и ID заказа
        """
        try:
            # Получаем данные плана
            plan = settings.subscription_plans.get(plan_id)
            if not plan:
                raise ValueError(f"Unknown plan_id: {plan_id}")
            
            # Генерируем уникальный ID заказа
            timestamp = int(datetime.now().timestamp())
            order_id = f"botfactory_{user_id}_{plan_id}_{timestamp}"
            
            # ✅ ИСПРАВЛЕНИЕ: Правильные основные параметры
            params = {
                'MerchantLogin': self.merchant_login,
                'OutSum': str(plan['price']),  # Robokassa требует строку
                'InvId': order_id,  # ✅ КРИТИЧЕСКИ ВАЖНО: InvId обязателен
                'Description': plan['description'],
                'Culture': 'ru'
            }
            
            # Дополнительные параметры
            if user_email:
                params['Email'] = user_email
            
            # ✅ ИСПРАВЛЕНИЕ: Пользовательские параметры в правильном формате
            params['Shp_user_id'] = str(user_id)
            params['Shp_plan_id'] = plan_id
            params['Shp_bot_factory'] = '1'  # Маркер что это наш проект
            
            # ✅ ИСПРАВЛЕНИЕ: Правильная работа с тестовым режимом
            if self.test_mode:
                params['IsTest'] = '1'
                logger.warning("🧪 ТЕСТОВЫЙ РЕЖИМ Robokassa активен!")
            
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Правильная генерация подписи
            signature = self._create_payment_signature_fixed(params)
            params['SignatureValue'] = signature
            
            # Формируем полную ссылку
            payment_url = f"{self.payment_url}?{urlencode(params)}"
            
            logger.info("✅ Payment URL generated successfully (FIXED)",
                       order_id=order_id,
                       user_id=user_id, 
                       plan_id=plan_id,
                       amount=plan['price'],
                       test_mode=self.test_mode,
                       signature_length=len(signature),
                       url_length=len(payment_url))
            
            return payment_url, order_id
            
        except Exception as e:
            logger.error("❌ Failed to generate payment URL", 
                        error=str(e),
                        plan_id=plan_id,
                        user_id=user_id,
                        error_type=type(e).__name__)
            raise
    
    def _create_payment_signature_fixed(self, params: dict) -> str:
        """
        ✅ ИСПРАВЛЕННАЯ генерация подписи согласно документации Robokassa
        
        Формат подписи: MerchantLogin:OutSum:InvId:Password1:[Пользовательские параметры]
        Пользовательские параметры должны быть отсортированы в алфавитном порядке
        """
        
        # ✅ ОСНОВНАЯ СТРОКА согласно документации Robokassa
        base_string = f"{params['MerchantLogin']}:{params['OutSum']}:{params['InvId']}:{self.password1}"
        
        # ✅ Собираем пользовательские параметры в АЛФАВИТНОМ порядке
        shp_params = []
        for key in sorted(params.keys()):
            if key.startswith('Shp_'):
                shp_params.append(f"{key}={params[key]}")
        
        # ✅ ПРАВИЛЬНОЕ объединение через двоеточие
        if shp_params:
            sign_string = base_string + ":" + ":".join(shp_params)
        else:
            sign_string = base_string
        
        # MD5 хеш в верхнем регистре (как требует Robokassa)
        signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
        
        logger.info("✅ Payment signature created (FIXED)", 
                   order_id=params.get('InvId'),
                   signature_base_length=len(sign_string),
                   signature_length=len(signature),
                   has_shp_params=len(shp_params) > 0,
                   shp_params_count=len(shp_params))
        
        # ✅ DEBUG: Логируем строку подписи (маскируем пароль для безопасности)
        debug_string = sign_string.replace(self.password1, "[PASSWORD1_MASKED]")
        logger.debug("🔍 Signature string (password masked)", 
                    debug_string=debug_string)
        
        return signature
    
    def verify_webhook_signature(self, webhook_data: dict) -> bool:
        """
        ✅ ИСПРАВЛЕННАЯ проверка подписи webhook уведомления от Robokassa
        
        Args:
            webhook_data: Данные полученные от Robokassa
            
        Returns:
            bool: True если подпись корректна
        """
        try:
            received_signature = webhook_data.get('SignatureValue', '').upper()
            
            if not received_signature:
                logger.warning("❌ No signature in webhook data")
                return False
            
            # ✅ ИСПРАВЛЕНИЕ: Правильная строка для проверки подписи webhook
            # Формат для webhook: OutSum:InvId:Password2:[Пользовательские параметры]
            base_string = f"{webhook_data.get('OutSum')}:{webhook_data.get('InvId')}:{self.password2}"
            
            # Добавляем пользовательские параметры в алфавитном порядке
            shp_params = []
            for key in sorted(webhook_data.keys()):
                if key.startswith('Shp_'):
                    shp_params.append(f"{key}={webhook_data[key]}")
            
            if shp_params:
                sign_string = base_string + ":" + ":".join(shp_params)
            else:
                sign_string = base_string
            
            # Вычисляем подпись
            calculated_signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
            
            is_valid = received_signature == calculated_signature
            
            logger.info("✅ Webhook signature verification (FIXED)", 
                       order_id=webhook_data.get('InvId'),
                       is_valid=is_valid,
                       received_sig_len=len(received_signature),
                       calculated_sig_len=len(calculated_signature),
                       has_shp_params=len(shp_params) > 0)
            
            if not is_valid:
                # ✅ DEBUG: Подробное логирование для отладки (маскируем пароль)
                debug_string = sign_string.replace(self.password2, "[PASSWORD2_MASKED]")
                logger.warning("❌ Invalid webhook signature - DEBUGGING INFO",
                              debug_string=debug_string,
                              received_signature=received_signature[:10] + "...",
                              calculated_signature=calculated_signature[:10] + "...",
                              out_sum=webhook_data.get('OutSum'),
                              inv_id=webhook_data.get('InvId'))
            
            return is_valid
            
        except Exception as e:
            logger.error("❌ Error verifying webhook signature", 
                        error=str(e),
                        error_type=type(e).__name__)
            return False
    
    def parse_webhook_data(self, webhook_data: dict) -> Optional[dict]:
        """
        Парсинг данных из webhook уведомления - БЕЗ ИЗМЕНЕНИЙ
        
        Args:
            webhook_data: Сырые данные от Robokassa
            
        Returns:
            dict: Обработанные данные или None если ошибка
        """
        try:
            # Извлекаем основные данные
            order_id = webhook_data.get('InvId')
            amount = float(webhook_data.get('OutSum', 0))
            
            # Извлекаем пользовательские параметры
            user_id = webhook_data.get('Shp_user_id')
            plan_id = webhook_data.get('Shp_plan_id')
            
            if not all([order_id, amount, user_id, plan_id]):
                logger.warning("❌ Missing required webhook data", 
                              order_id=order_id,
                              user_id=user_id, 
                              plan_id=plan_id,
                              amount=amount)
                return None
            
            # Проверяем что это наш заказ
            if webhook_data.get('Shp_bot_factory') != '1':
                logger.warning("❌ Webhook not from Bot Factory", 
                              order_id=order_id)
                return None
            
            parsed_data = {
                'order_id': order_id,
                'amount': amount,
                'user_id': int(user_id),
                'plan_id': plan_id,
                'payment_date': datetime.now(),
                'raw_data': webhook_data
            }
            
            logger.info("✅ Webhook data parsed successfully",
                       order_id=order_id,
                       user_id=user_id,
                       plan_id=plan_id,
                       amount=amount)
            
            return parsed_data
            
        except Exception as e:
            logger.error("❌ Failed to parse webhook data", 
                        error=str(e),
                        webhook_data=webhook_data,
                        error_type=type(e).__name__)
            return None
    
    def test_signature_generation(self, test_params: dict = None) -> dict:
        """
        ✅ НОВЫЙ МЕТОД: Тестирование генерации подписи для отладки
        
        Args:
            test_params: Тестовые параметры (опционально)
            
        Returns:
            dict: Результаты тестирования
        """
        if not test_params:
            test_params = {
                'MerchantLogin': self.merchant_login,
                'OutSum': '299',
                'InvId': 'test_order_12345',
                'Shp_user_id': '123456',
                'Shp_plan_id': '1m',
                'Shp_bot_factory': '1'
            }
        
        try:
            signature = self._create_payment_signature_fixed(test_params)
            
            result = {
                'success': True,
                'signature': signature,
                'signature_length': len(signature),
                'test_params': test_params,
                'merchant_login': self.merchant_login,
                'test_mode': self.test_mode
            }
            
            logger.info("✅ Signature test completed successfully",
                       signature=signature,
                       test_mode=self.test_mode)
            
            return result
            
        except Exception as e:
            logger.error("❌ Signature test failed", error=str(e))
            return {
                'success': False,
                'error': str(e),
                'test_params': test_params
            }


# ✅ Создаем глобальный экземпляр сервиса
robokassa_service = RobokassaService()

# ✅ Логируем успешную инициализацию
logger.info("🎉 RobokassaService (FIXED VERSION) loaded successfully")
