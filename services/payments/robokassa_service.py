"""
Robokassa Payment Service
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
    """Сервис для работы с Robokassa"""
    
    def __init__(self):
        self.merchant_login = settings.robokassa_merchant_login
        self.password1 = settings.robokassa_password1
        self.password2 = settings.robokassa_password2
        self.test_mode = settings.robokassa_test_mode
        
        # URL для создания платежей
        self.payment_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        
        logger.info("RobokassaService initialized", 
                   merchant=self.merchant_login,
                   test_mode=self.test_mode)
    
    def generate_payment_url(self, 
                           plan_id: str, 
                           user_id: int, 
                           user_email: str = None) -> Tuple[str, str]:
        """
        Генерация ссылки для оплаты
        
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
            
            # Основные параметры
            params = {
                'MerchantLogin': self.merchant_login,
                'OutSum': str(plan['price']),
                'InvId': order_id,
                'Description': plan['description'],
                'Culture': 'ru'
            }
            
            # Дополнительные параметры
            if user_email:
                params['Email'] = user_email
            
            # Пользовательские параметры (будут переданы в webhook)
            params['Shp_user_id'] = str(user_id)
            params['Shp_plan_id'] = plan_id
            params['Shp_bot_factory'] = '1'  # Маркер что это наш проект
            
            if self.test_mode:
                params['IsTest'] = '1'
            
            # Создание подписи
            signature = self._create_payment_signature(params)
            params['SignatureValue'] = signature
            
            # Формируем полную ссылку
            payment_url = f"{self.payment_url}?{urlencode(params)}"
            
            logger.info("Payment URL generated",
                       order_id=order_id,
                       user_id=user_id, 
                       plan_id=plan_id,
                       amount=plan['price'])
            
            return payment_url, order_id
            
        except Exception as e:
            logger.error("Failed to generate payment URL", 
                        error=str(e),
                        plan_id=plan_id,
                        user_id=user_id)
            raise
    
    def _create_payment_signature(self, params: dict) -> str:
        """Создание подписи для платежного запроса"""
        # Строка для подписи: MerchantLogin:OutSum:InvId:Password1
        sign_string = f"{params['MerchantLogin']}:{params['OutSum']}:{params['InvId']}:{self.password1}"
        
        # Добавляем пользовательские параметры в алфавитном порядке
        shp_params = []
        for key in sorted(params.keys()):
            if key.startswith('Shp_'):
                shp_params.append(f"{key}={params[key]}")
        
        if shp_params:
            sign_string += ":" + ":".join(shp_params)
        
        # MD5 хеш в верхнем регистре
        signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
        
        logger.debug("Payment signature created", 
                    order_id=params.get('InvId'),
                    signature_length=len(signature))
        
        return signature
    
    def verify_webhook_signature(self, webhook_data: dict) -> bool:
        """
        Проверка подписи webhook уведомления от Robokassa
        
        Args:
            webhook_data: Данные полученные от Robokassa
            
        Returns:
            bool: True если подпись корректна
        """
        try:
            received_signature = webhook_data.get('SignatureValue', '').upper()
            
            if not received_signature:
                logger.warning("No signature in webhook data")
                return False
            
            # Создаем строку для проверки подписи
            # Формат: OutSum:InvId:Password2
            sign_string = f"{webhook_data.get('OutSum')}:{webhook_data.get('InvId')}:{self.password2}"
            
            # Добавляем пользовательские параметры в алфавитном порядке
            shp_params = []
            for key in sorted(webhook_data.keys()):
                if key.startswith('Shp_'):
                    shp_params.append(f"{key}={webhook_data[key]}")
            
            if shp_params:
                sign_string += ":" + ":".join(shp_params)
            
            # Вычисляем подпись
            calculated_signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
            
            is_valid = received_signature == calculated_signature
            
            logger.info("Webhook signature verification", 
                       order_id=webhook_data.get('InvId'),
                       is_valid=is_valid,
                       received_sig_len=len(received_signature),
                       calculated_sig_len=len(calculated_signature))
            
            if not is_valid:
                logger.warning("Invalid webhook signature",
                              received=received_signature[:10] + "...",
                              calculated=calculated_signature[:10] + "...",
                              sign_string_length=len(sign_string))
            
            return is_valid
            
        except Exception as e:
            logger.error("Error verifying webhook signature", error=str(e))
            return False
    
    def parse_webhook_data(self, webhook_data: dict) -> Optional[dict]:
        """
        Парсинг данных из webhook уведомления
        
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
                logger.warning("Missing required webhook data", 
                              order_id=order_id,
                              user_id=user_id, 
                              plan_id=plan_id,
                              amount=amount)
                return None
            
            # Проверяем что это наш заказ
            if webhook_data.get('Shp_bot_factory') != '1':
                logger.warning("Webhook not from Bot Factory", 
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
            
            logger.info("Webhook data parsed successfully",
                       order_id=order_id,
                       user_id=user_id,
                       plan_id=plan_id,
                       amount=amount)
            
            return parsed_data
            
        except Exception as e:
            logger.error("Failed to parse webhook data", 
                        error=str(e),
                        webhook_data=webhook_data)
            return None


# Создаем глобальный экземпляр сервиса
robokassa_service = RobokassaService()
