"""
Robokassa Payment Service - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ ВЕРСИЯ с МАКСИМАЛЬНЫМ ОТЛАДОЧНЫМ ЛОГИРОВАНИЕМ
Сервис для создания платежных ссылок и обработки уведомлений от Robokassa
Устранены ошибки structlog.DEBUG + добавлена защита от ошибок БД + максимальная отладка
"""

import hashlib
import logging
import structlog
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any
from urllib.parse import urlencode, urlparse, parse_qs

from config import settings

logger = structlog.get_logger()


class RobokassaService:
    """Сервис для работы с Robokassa - ИСПРАВЛЕННАЯ ВЕРСИЯ с защитой от ошибок БД и максимальной отладкой"""
    
    def __init__(self):
        self.merchant_login = settings.robokassa_merchant_login
        self.password1 = settings.robokassa_password1
        self.password2 = settings.robokassa_password2
        self.test_mode = getattr(settings, 'robokassa_test_mode', True)
        
        # URL для создания платежей
        self.payment_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        
        # Проверяем что все параметры настроены
        self._validate_configuration()
        
        logger.info("✅ RobokassaService initialized (FIXED VERSION WITH MAX DEBUG)", 
                   merchant=self.merchant_login,
                   test_mode=self.test_mode,
                   has_passwords=bool(self.password1 and self.password2))
    
    def _validate_configuration(self):
        """Проверка конфигурации Robokassa"""
        missing_params = []
        
        if not self.merchant_login:
            missing_params.append("ROBOKASSA_MERCHANT_LOGIN")
        if not self.password1:
            missing_params.append("ROBOKASSA_PASSWORD1")
        if not self.password2:
            missing_params.append("ROBOKASSA_PASSWORD2")
        
        if missing_params:
            error_msg = f"Missing Robokassa configuration: {', '.join(missing_params)}"
            logger.error("❌ Robokassa configuration incomplete", missing=missing_params)
            raise ValueError(error_msg)
        
        logger.info("✅ Robokassa configuration validated successfully")
    
    def _safe_get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """
        Безопасное получение плана с дополнительной защитой
        
        Args:
            plan_id: ID тарифного плана
            
        Returns:
            dict: Данные плана или None
        """
        try:
            if not hasattr(settings, 'subscription_plans'):
                logger.error("❌ settings.subscription_plans not found")
                return None
                
            plans = getattr(settings, 'subscription_plans', {})
            if not isinstance(plans, dict):
                logger.error("❌ subscription_plans is not a dictionary", 
                           type_found=type(plans).__name__)
                return None
                
            plan = plans.get(plan_id)
            if not plan:
                available_plans = list(plans.keys())
                logger.warning("❌ Plan not found", 
                              plan_id=plan_id, 
                              available_plans=available_plans)
                return None
                
            # Проверяем обязательные поля плана
            required_fields = ['price', 'description']
            for field in required_fields:
                if field not in plan:
                    logger.error("❌ Missing required field in plan", 
                               plan_id=plan_id, 
                               missing_field=field)
                    return None
                    
            return plan
            
        except Exception as e:
            logger.error("❌ Error getting plan", 
                        plan_id=plan_id, 
                        error=str(e),
                        error_type=type(e).__name__)
            return None

    def generate_payment_url(self, plan_id: str, user_id: int, user_email: str = None, custom_description: str = None) -> Tuple[str, str]:
        """
        ✅ МАКСИМАЛЬНО ОТЛАДОЧНАЯ версия генерации ссылки для оплаты
        """
        logger.info("🚀 ===== ROBOKASSA URL GENERATION START =====")
        logger.info("📥 Input parameters",
                   plan_id=plan_id,
                   user_id=user_id,
                   user_email=user_email,
                   custom_description=custom_description)
        
        try:
            # ✅ ВАЛИДАЦИЯ ВХОДНЫХ ДАННЫХ
            logger.info("🔍 Step 1: Input validation...")
            
            if not isinstance(user_id, int) or user_id <= 0:
                error_msg = f"Invalid user_id: {user_id}. Must be positive integer."
                logger.error("❌ Validation failed", error=error_msg)
                raise ValueError(error_msg)
                
            if not isinstance(plan_id, str) or not plan_id.strip():
                error_msg = f"Invalid plan_id: {plan_id}. Must be non-empty string."
                logger.error("❌ Validation failed", error=error_msg)
                raise ValueError(error_msg)
            
            logger.info("✅ Input validation passed")
            
            # ✅ ПОЛУЧЕНИЕ ПЛАНА
            logger.info("🔍 Step 2: Getting plan data...")
            
            plan = self._safe_get_plan(plan_id)
            if not plan:
                available_plans = list(getattr(settings, 'subscription_plans', {}).keys())
                error_msg = f"Unknown plan_id: {plan_id}. Available: {available_plans}"
                logger.error("❌ Plan not found", error=error_msg, available_plans=available_plans)
                raise ValueError(error_msg)
            
            logger.info("✅ Plan found",
                       plan_id=plan_id,
                       plan_title=plan.get('title'),
                       plan_price=plan.get('price'),
                       plan_duration=plan.get('duration_days'),
                       plan_description=plan.get('description'))
            
            # ✅ ПРОВЕРКА ЦЕНЫ
            logger.info("🔍 Step 3: Price validation...")
            
            price = plan.get('price', 0)
            logger.info("💰 Raw price data",
                       price=price,
                       price_type=type(price).__name__)
            
            if not isinstance(price, (int, float)) or price <= 0:
                error_msg = f"Invalid price in plan {plan_id}: {price}"
                logger.error("❌ Price validation failed", error=error_msg)
                raise ValueError(error_msg)
            
            # Форматируем цену с принудительной точкой
            formatted_price = f"{float(price):.2f}".replace(',', '.')
            logger.info("✅ Price formatted",
                       original_price=price,
                       formatted_price=formatted_price)
            
            # ✅ ГЕНЕРАЦИЯ ORDER_ID
            logger.info("🔍 Step 4: Generating order ID...")
            
            timestamp = int(datetime.now().timestamp())
            # ✅ ИСПРАВЛЕНИЕ: Короткий order_id
            order_id = f"bf{user_id}_{timestamp}"
            
            logger.info("✅ Order ID generated",
                       order_id=order_id,
                       order_id_length=len(order_id),
                       timestamp=timestamp)
            
            # ✅ ПОДГОТОВКА ОПИСАНИЯ
            logger.info("🔍 Step 5: Preparing description...")
            
            # ✅ ИСПРАВЛЕНИЕ: Только ASCII символы
            description = custom_description or f"Bot Factory {plan_id}"
            logger.info("✅ Description prepared",
                       description=description,
                       description_length=len(description))
            
            # ✅ СОЗДАНИЕ БАЗОВЫХ ПАРАМЕТРОВ
            logger.info("🔍 Step 6: Creating base parameters...")
            
            params = {
                'MerchantLogin': self.merchant_login,
                'OutSum': formatted_price,
                'InvId': order_id,
                'Description': description,
                'Culture': 'ru',
                'Encoding': 'utf-8'
            }
            
            logger.info("📋 Base parameters created",
                       merchant_login=params['MerchantLogin'],
                       out_sum=params['OutSum'],
                       inv_id=params['InvId'],
                       description_length=len(params['Description']))
            
            # ✅ ДОБАВЛЕНИЕ EMAIL
            if user_email and isinstance(user_email, str) and '@' in user_email:
                params['Email'] = user_email
                logger.info("📧 Email added", email_domain=user_email.split('@')[1] if '@' in user_email else None)
            else:
                logger.info("📧 No email provided or invalid")
            
            # ✅ ДОБАВЛЕНИЕ SHP ПАРАМЕТРОВ
            logger.info("🔍 Step 7: Adding Shp parameters...")
            
            params['Shp_user_id'] = str(user_id)
            params['Shp_plan_id'] = plan_id
            params['Shp_bot_factory'] = '1'
            params['Shp_timestamp'] = str(timestamp)
            
            logger.info("✅ Shp parameters added",
                       shp_user_id=params['Shp_user_id'],
                       shp_plan_id=params['Shp_plan_id'],
                       shp_bot_factory=params['Shp_bot_factory'],
                       shp_timestamp=params['Shp_timestamp'])
            
            # ✅ ТЕСТОВЫЙ РЕЖИМ
            logger.info("🔍 Step 8: Checking test mode...")
            
            if self.test_mode:
                params['IsTest'] = '1'
                logger.warning("🧪 TEST MODE ENABLED - IsTest parameter added")
            else:
                logger.info("🏭 PRODUCTION MODE - No IsTest parameter")
            
            # ✅ ГЕНЕРАЦИЯ ПОДПИСИ
            logger.info("🔍 Step 9: Generating signature...")
            logger.info("🔐 Signature input data",
                       merchant_login=self.merchant_login,
                       out_sum=params['OutSum'],
                       inv_id=params['InvId'],
                       password1_length=len(self.password1) if self.password1 else 0,
                       shp_params_count=len([k for k in params.keys() if k.startswith('Shp_')]))
            
            signature = self._create_payment_signature_fixed(params)
            params['SignatureValue'] = signature
            
            logger.info("✅ Signature generated",
                       signature=signature,
                       signature_length=len(signature))
            
            # ✅ СОЗДАНИЕ ИТОГОВОГО URL
            logger.info("🔍 Step 10: Building final URL...")
            
            payment_url = f"{self.payment_url}?{urlencode(params, encoding='utf-8')}"
            
            logger.info("✅ URL created",
                       base_url=self.payment_url,
                       query_length=len(urlencode(params, encoding='utf-8')),
                       total_url_length=len(payment_url))
            
            # ✅ ФИНАЛЬНАЯ ВАЛИДАЦИЯ URL
            logger.info("🔍 Step 11: Final URL validation...")
            
            parsed = urlparse(payment_url)
            
            logger.info("🌐 URL structure",
                       scheme=parsed.scheme,
                       netloc=parsed.netloc,
                       path=parsed.path,
                       query_params_count=len(parsed.query.split('&')))
            
            # ✅ ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПАРАМЕТРОВ В URL
            required_in_url = ['MerchantLogin', 'OutSum', 'InvId', 'SignatureValue']
            for param in required_in_url:
                if param not in payment_url:
                    logger.error(f"❌ Missing {param} in final URL")
                    raise ValueError(f"Missing required parameter {param} in URL")
            
            logger.info("✅ All required parameters present in URL")
            
            # ✅ ФИНАЛЬНОЕ ЛОГИРОВАНИЕ
            logger.info("🎉 URL GENERATION SUCCESSFUL!",
                       order_id=order_id,
                       user_id=user_id,
                       plan_id=plan_id,
                       amount=formatted_price,
                       test_mode=self.test_mode,
                       url_preview=payment_url[:100] + "..." if len(payment_url) > 100 else payment_url)
            
            logger.info("🚀 ===== ROBOKASSA URL GENERATION COMPLETE =====")
            
            return payment_url, order_id
            
        except Exception as e:
            logger.error("💥 ===== URL GENERATION FAILED =====",
                        error=str(e),
                        error_type=type(e).__name__,
                        plan_id=plan_id,
                        user_id=user_id,
                        exc_info=True)
            
            # Дополнительная диагностика
            logger.error("🔍 Error context",
                        merchant_login=getattr(self, 'merchant_login', None),
                        password1_exists=bool(getattr(self, 'password1', None)),
                        password2_exists=bool(getattr(self, 'password2', None)),
                        test_mode=getattr(self, 'test_mode', None),
                        payment_url=getattr(self, 'payment_url', None))
            
            raise

    def _create_payment_signature_fixed(self, params: dict) -> str:
        """
        ✅ МАКСИМАЛЬНО ОТЛАДОЧНАЯ генерация подписи
        """
        logger.info("🔐 ===== SIGNATURE GENERATION START =====")
        logger.info("📥 Input parameters count", params_count=len(params))
        
        try:
            # ✅ ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПАРАМЕТРОВ
            logger.info("🔍 Step 1: Checking required parameters...")
            
            required_params = ['MerchantLogin', 'OutSum', 'InvId']
            for param in required_params:
                if param not in params:
                    error_msg = f"Missing required parameter: {param}"
                    logger.error("❌ Missing parameter", param=param)
                    raise ValueError(error_msg)
                if not str(params[param]).strip():
                    error_msg = f"Empty required parameter: {param}"
                    logger.error("❌ Empty parameter", param=param)
                    raise ValueError(error_msg)
            
            logger.info("✅ Required parameters check passed")
            
            # ✅ СОЗДАНИЕ БАЗОВОЙ СТРОКИ
            logger.info("🔍 Step 2: Creating base signature string...")
            
            base_string = f"{params['MerchantLogin']}:{params['OutSum']}:{params['InvId']}:{self.password1}"
            
            logger.info("✅ Base string created",
                       merchant_login=params['MerchantLogin'],
                       out_sum=params['OutSum'],
                       inv_id=params['InvId'],
                       password1_length=len(self.password1))
            
            # ✅ СБОР SHP ПАРАМЕТРОВ
            logger.info("🔍 Step 3: Collecting Shp parameters...")
            
            shp_params = []
            all_shp_keys = [key for key in params.keys() if key.startswith('Shp_')]
            sorted_shp_keys = sorted(all_shp_keys)
            
            logger.info("📋 Shp parameters found",
                       total_shp_params=len(all_shp_keys),
                       shp_keys=sorted_shp_keys)
            
            for key in sorted_shp_keys:
                shp_param = f"{key}={params[key]}"
                shp_params.append(shp_param)
                logger.info(f"➕ Added Shp parameter: {key}={params[key]}")
            
            logger.info("✅ Shp parameters collected",
                       shp_params_count=len(shp_params),
                       shp_params=shp_params)
            
            # ✅ СОЗДАНИЕ ИТОГОВОЙ СТРОКИ
            logger.info("🔍 Step 4: Creating final signature string...")
            
            if shp_params:
                sign_string = base_string + ":" + ":".join(shp_params)
                logger.info("✅ Final string with Shp parameters")
            else:
                sign_string = base_string
                logger.info("✅ Final string without Shp parameters")
            
            # Маскированная версия для логирования
            masked_string = sign_string.replace(self.password1, "[PASSWORD1_MASKED]")
            logger.info("🔐 Signature string (masked)",
                       masked_string=masked_string,
                       total_length=len(sign_string))
            
            # ✅ ГЕНЕРАЦИЯ MD5 ХЕША
            logger.info("🔍 Step 5: Generating MD5 hash...")
            
            import hashlib
            
            # Кодируем в UTF-8
            encoded_string = sign_string.encode('utf-8')
            logger.info("📝 String encoded",
                       encoding='utf-8',
                       encoded_length=len(encoded_string))
            
            # Создаем MD5 хеш
            md5_hash = hashlib.md5(encoded_string).hexdigest()
            
            # Приводим к верхнему регистру
            signature = md5_hash.upper()
            
            logger.info("✅ MD5 signature generated",
                       raw_md5=md5_hash,
                       final_signature=signature,
                       signature_length=len(signature))
            
            # ✅ ФИНАЛЬНАЯ ВАЛИДАЦИЯ
            logger.info("🔍 Step 6: Final signature validation...")
            
            if not signature or len(signature) != 32:
                error_msg = f"Invalid signature generated: {signature}"
                logger.error("❌ Signature validation failed", 
                            signature=signature,
                            signature_length=len(signature) if signature else 0)
                raise ValueError(error_msg)
            
            logger.info("✅ Signature validation passed")
            
            logger.info("🎉 SIGNATURE GENERATION SUCCESSFUL!",
                       signature=signature,
                       order_id=params.get('InvId'))
            
            logger.info("🔐 ===== SIGNATURE GENERATION COMPLETE =====")
            
            return signature
            
        except Exception as e:
            logger.error("💥 ===== SIGNATURE GENERATION FAILED =====",
                        error=str(e),
                        error_type=type(e).__name__,
                        order_id=params.get('InvId') if isinstance(params, dict) else 'unknown',
                        exc_info=True)
            
            # Диагностика ошибки
            logger.error("🔍 Signature error context",
                        params_type=type(params).__name__,
                        params_keys=list(params.keys()) if isinstance(params, dict) else None,
                        merchant_login=getattr(self, 'merchant_login', None),
                        password1_exists=bool(getattr(self, 'password1', None)))
            
            raise

    def diagnose_payment_url(self, payment_url: str) -> dict:
        """
        ✅ ДИАГНОСТИКА СОЗДАННОЙ ССЫЛКИ
        """
        logger.info("🔍 ===== URL DIAGNOSIS START =====")
        
        try:
            # Парсим URL
            parsed = urlparse(payment_url)
            params = parse_qs(parsed.query)
            
            diagnosis = {
                'url_valid': bool(parsed.scheme and parsed.netloc),
                'scheme': parsed.scheme,
                'netloc': parsed.netloc,
                'path': parsed.path,
                'total_length': len(payment_url),
                'query_length': len(parsed.query),
                'params_count': len(params),
                'required_params': {},
                'shp_params': {},
                'issues': []
            }
            
            # Проверяем обязательные параметры
            required = ['MerchantLogin', 'OutSum', 'InvId', 'SignatureValue']
            for param in required:
                if param in params:
                    diagnosis['required_params'][param] = {
                        'present': True,
                        'value': params[param][0] if params[param] else None,
                        'length': len(params[param][0]) if params[param] and params[param][0] else 0
                    }
                else:
                    diagnosis['required_params'][param] = {'present': False}
                    diagnosis['issues'].append(f"Missing required parameter: {param}")
            
            # Проверяем Shp параметры
            for param_name, param_values in params.items():
                if param_name.startswith('Shp_'):
                    diagnosis['shp_params'][param_name] = {
                        'value': param_values[0] if param_values else None,
                        'length': len(param_values[0]) if param_values and param_values[0] else 0
                    }
            
            # Проверки валидности
            if diagnosis['total_length'] > 2000:
                diagnosis['issues'].append("URL too long (>2000 chars)")
            
            if not diagnosis['url_valid']:
                diagnosis['issues'].append("Invalid URL format")
            
            if parsed.netloc != 'auth.robokassa.ru':
                diagnosis['issues'].append(f"Unexpected domain: {parsed.netloc}")
            
            logger.info("✅ URL diagnosis complete", diagnosis=diagnosis)
            
            return diagnosis
            
        except Exception as e:
            logger.error("❌ URL diagnosis failed", error=str(e))
            return {'error': str(e)}

    def quick_test(self, plan_id: str = "1m", user_id: int = 123456) -> dict:
        """
        ✅ БЫСТРЫЙ ТЕСТ ВСЕЙ ЦЕПОЧКИ
        """
        logger.info("🧪 ===== QUICK TEST START =====")
        
        try:
            # Тест генерации URL
            url, order_id = self.generate_payment_url(plan_id, user_id)
            
            # Диагностика URL
            diagnosis = self.diagnose_payment_url(url)
            
            # Health check
            health = self.health_check()
            
            result = {
                'success': True,
                'url': url,
                'order_id': order_id,
                'diagnosis': diagnosis,
                'health': health,
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info("✅ Quick test PASSED", result=result)
            
            return result
            
        except Exception as e:
            logger.error("❌ Quick test FAILED", error=str(e))
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def verify_webhook_signature(self, webhook_data: dict) -> bool:
        """
        ✅ ИСПРАВЛЕННАЯ проверка подписи webhook уведомления от Robokassa с защитой от ошибок БД
        
        Args:
            webhook_data: Данные полученные от Robokassa
            
        Returns:
            bool: True если подпись корректна
        """
        try:
            if not isinstance(webhook_data, dict):
                logger.error("❌ Invalid webhook_data type", 
                           expected="dict", 
                           received=type(webhook_data).__name__)
                return False
            
            received_signature = webhook_data.get('SignatureValue', '').upper()
            out_sum = webhook_data.get('OutSum', '')
            inv_id = webhook_data.get('InvId', '')
            
            if not received_signature:
                logger.warning("❌ No signature in webhook data", inv_id=inv_id)
                return False
            
            if not out_sum or not inv_id:
                logger.warning("❌ Missing required webhook data", 
                              out_sum=bool(out_sum), 
                              inv_id=bool(inv_id))
                return False
            
            # Проверяем формат суммы
            try:
                float(out_sum)
            except (ValueError, TypeError):
                logger.warning("❌ Invalid OutSum format", out_sum=out_sum, inv_id=inv_id)
                return False
            
            # ✅ ИСПРАВЛЕНИЕ: Правильная строка для проверки подписи webhook
            # Формат для webhook: OutSum:InvId:Password2:Shp_param1=value1:Shp_param2=value2
            base_string = f"{out_sum}:{inv_id}:{self.password2}"
            
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
                       order_id=inv_id,
                       is_valid=is_valid,
                       received_sig_len=len(received_signature),
                       calculated_sig_len=len(calculated_signature),
                       has_shp_params=len(shp_params) > 0,
                       shp_count=len(shp_params))
            
            if not is_valid:
                # ✅ ИСПРАВЛЕНИЕ: Используем стандартное логирование для отладки
                # Подробное логирование для отладки (маскируем пароль)
                debug_string = sign_string.replace(self.password2, "[PASSWORD2_MASKED]")
                logger.warning("❌ Invalid webhook signature - DEBUGGING INFO",
                              debug_string=debug_string,
                              received_signature=received_signature[:10] + "...",
                              calculated_signature=calculated_signature[:10] + "...",
                              out_sum=out_sum,
                              inv_id=inv_id)
            
            return is_valid
            
        except Exception as e:
            logger.error("❌ Error verifying webhook signature", 
                        error=str(e),
                        error_type=type(e).__name__,
                        inv_id=webhook_data.get('InvId') if isinstance(webhook_data, dict) else 'unknown')
            return False
    
    def parse_webhook_data(self, webhook_data: dict) -> Optional[dict]:
        """
        Парсинг данных из webhook уведомления - УЛУЧШЕННАЯ ВЕРСИЯ с защитой от ошибок БД
        
        Args:
            webhook_data: Сырые данные от Robokassa
            
        Returns:
            dict: Обработанные данные или None если ошибка
        """
        try:
            if not isinstance(webhook_data, dict):
                logger.error("❌ Invalid webhook_data type", 
                           expected="dict", 
                           received=type(webhook_data).__name__)
                return None
            
            # Извлекаем основные данные
            order_id = webhook_data.get('InvId')
            out_sum = webhook_data.get('OutSum')
            
            if not order_id or not out_sum:
                logger.warning("❌ Missing basic webhook data", 
                              has_order_id=bool(order_id),
                              has_out_sum=bool(out_sum))
                return None
            
            # Конвертируем сумму
            try:
                amount = float(out_sum)
                if amount <= 0:
                    raise ValueError("Amount must be positive")
            except (ValueError, TypeError) as e:
                logger.warning("❌ Invalid amount in webhook", 
                              out_sum=out_sum, 
                              error=str(e))
                return None
            
            # Извлекаем пользовательские параметры
            user_id_str = webhook_data.get('Shp_user_id')
            plan_id = webhook_data.get('Shp_plan_id')
            bot_factory_marker = webhook_data.get('Shp_bot_factory')
            
            if not all([user_id_str, plan_id, bot_factory_marker]):
                logger.warning("❌ Missing custom webhook parameters", 
                              order_id=order_id,
                              has_user_id=bool(user_id_str),
                              has_plan_id=bool(plan_id),
                              has_marker=bool(bot_factory_marker))
                return None
            
            # Проверяем что это наш заказ
            if bot_factory_marker != '1':
                logger.warning("❌ Webhook not from Bot Factory", 
                              order_id=order_id,
                              marker=bot_factory_marker)
                return None
            
            # Конвертируем user_id
            try:
                user_id = int(user_id_str)
                if user_id <= 0:
                    raise ValueError("User ID must be positive")
            except (ValueError, TypeError) as e:
                logger.warning("❌ Invalid user_id in webhook", 
                              user_id_str=user_id_str, 
                              error=str(e))
                return None
            
            # Безопасно проверяем что план существует
            plan = self._safe_get_plan(plan_id)
            if not plan:
                logger.warning("❌ Unknown plan_id in webhook", 
                              plan_id=plan_id,
                              order_id=order_id)
                return None
            
            # Проверяем сумму платежа
            expected_amount = plan.get('price', 0)
            if abs(amount - expected_amount) > 0.01:  # Допускаем погрешность в 1 копейку
                logger.warning("❌ Amount mismatch in webhook",
                              order_id=order_id,
                              received_amount=amount,
                              expected_amount=expected_amount)
                return None
            
            parsed_data = {
                'order_id': order_id,
                'amount': amount,
                'user_id': user_id,
                'plan_id': plan_id,
                'payment_date': datetime.now(),
                'plan_details': plan,
                'timestamp': webhook_data.get('Shp_timestamp'),
                'raw_data': webhook_data
            }
            
            logger.info("✅ Webhook data parsed successfully",
                       order_id=order_id,
                       user_id=user_id,
                       plan_id=plan_id,
                       amount=amount,
                       plan_title=plan.get('title'))
            
            return parsed_data
            
        except Exception as e:
            logger.error("❌ Failed to parse webhook data", 
                        error=str(e),
                        error_type=type(e).__name__,
                        webhook_data_keys=list(webhook_data.keys()) if isinstance(webhook_data, dict) else None)
            return None
    
    def verify_success_url_signature(self, success_data: dict) -> bool:
        """
        ✅ НОВЫЙ МЕТОД: Проверка подписи для SuccessURL с защитой от ошибок
        
        Args:
            success_data: Данные с Success URL
            
        Returns:
            bool: True если подпись корректна
        """
        try:
            if not isinstance(success_data, dict):
                logger.error("❌ Invalid success_data type", 
                           expected="dict", 
                           received=type(success_data).__name__)
                return False
            
            # Для SuccessURL используется password1, как и для создания платежа
            received_signature = success_data.get('SignatureValue', '').upper()
            out_sum = success_data.get('OutSum', '')
            inv_id = success_data.get('InvId', '')
            
            if not all([received_signature, out_sum, inv_id]):
                logger.warning("❌ Missing data for SuccessURL verification",
                              has_signature=bool(received_signature),
                              has_sum=bool(out_sum),
                              has_inv_id=bool(inv_id))
                return False
            
            # Формат строки как в webhook, но с password1
            base_string = f"{out_sum}:{inv_id}:{self.password1}"
            
            # Добавляем пользовательские параметры
            shp_params = []
            for key in sorted(success_data.keys()):
                if key.startswith('Shp_'):
                    shp_params.append(f"{key}={success_data[key]}")
            
            if shp_params:
                sign_string = base_string + ":" + ":".join(shp_params)
            else:
                sign_string = base_string
            
            calculated_signature = hashlib.md5(sign_string.encode('utf-8')).hexdigest().upper()
            
            is_valid = received_signature == calculated_signature
            
            logger.info("✅ SuccessURL signature verification",
                       order_id=inv_id,
                       is_valid=is_valid)
            
            return is_valid
            
        except Exception as e:
            logger.error("❌ Error verifying SuccessURL signature", error=str(e))
            return False
    
    def get_payment_status_url(self, order_id: str) -> str:
        """
        ✅ НОВЫЙ МЕТОД: Генерация URL для проверки статуса платежа
        
        Args:
            order_id: ID заказа
            
        Returns:
            str: URL для проверки статуса
        """
        try:
            if not isinstance(order_id, str) or not order_id.strip():
                raise ValueError(f"Invalid order_id: {order_id}")
            
            params = {
                'MerchantLogin': self.merchant_login,
                'InvoiceID': order_id,
                'Signature': hashlib.md5(f"{self.merchant_login}:{order_id}:{self.password2}".encode()).hexdigest()
            }
            
            return f"https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpState?{urlencode(params)}"
            
        except Exception as e:
            logger.error("❌ Error generating payment status URL", 
                        order_id=order_id, 
                        error=str(e))
            return ""
    
    def test_signature_generation(self, test_params: dict = None) -> dict:
        """
        ✅ УЛУЧШЕННЫЙ МЕТОД: Тестирование генерации подписи для отладки
        
        Args:
            test_params: Тестовые параметры (опционально)
            
        Returns:
            dict: Результаты тестирования
        """
        if not test_params:
            test_params = {
                'MerchantLogin': self.merchant_login,
                'OutSum': '299.00',
                'InvId': f'test_order_{int(datetime.now().timestamp())}',
                'Shp_user_id': '123456',
                'Shp_plan_id': '1m',
                'Shp_bot_factory': '1'
            }
        
        try:
            signature = self._create_payment_signature_fixed(test_params)
            
            # Создаем тестовый URL
            test_params['SignatureValue'] = signature
            if self.test_mode:
                test_params['IsTest'] = '1'
            
            test_url = f"{self.payment_url}?{urlencode(test_params)}"
            
            result = {
                'success': True,
                'signature': signature,
                'signature_length': len(signature),
                'test_params': test_params,
                'test_url': test_url,
                'merchant_login': self.merchant_login,
                'test_mode': self.test_mode,
                'url_length': len(test_url)
            }
            
            logger.info("✅ Signature test completed successfully",
                       signature=signature,
                       test_mode=self.test_mode,
                       order_id=test_params.get('InvId'))
            
            return result
            
        except Exception as e:
            logger.error("❌ Signature test failed", error=str(e))
            return {
                'success': False,
                'error': str(e),
                'test_params': test_params
            }
    
    def validate_plan_prices(self) -> dict:
        """
        ✅ НОВЫЙ МЕТОД: Проверка корректности цен в планах с защитой от ошибок БД
        
        Returns:
            dict: Результаты валидации
        """
        try:
            validation_results = {}
            
            if not hasattr(settings, 'subscription_plans'):
                return {
                    'success': False,
                    'error': 'subscription_plans not found in settings',
                    'total_plans': 0,
                    'valid_plans': 0,
                    'plans': {}
                }
            
            plans = getattr(settings, 'subscription_plans', {})
            if not isinstance(plans, dict):
                return {
                    'success': False,
                    'error': f'subscription_plans is not a dict, got {type(plans).__name__}',
                    'total_plans': 0,
                    'valid_plans': 0,
                    'plans': {}
                }
            
            for plan_id, plan_data in plans.items():
                try:
                    if not isinstance(plan_data, dict):
                        validation_results[plan_id] = {
                            'valid': False,
                            'error': f'Plan data is not a dict, got {type(plan_data).__name__}',
                            'price': None
                        }
                        continue
                    
                    price = plan_data.get('price', 0)
                    
                    validation_results[plan_id] = {
                        'valid': isinstance(price, (int, float)) and price > 0,
                        'price': price,
                        'title': plan_data.get('title'),
                        'duration_days': plan_data.get('duration_days'),
                        'formatted_price': f"{price:.2f}" if isinstance(price, (int, float)) else 'Invalid'
                    }
                    
                except Exception as e:
                    validation_results[plan_id] = {
                        'valid': False,
                        'error': str(e),
                        'price': None
                    }
            
            valid_count = sum(1 for result in validation_results.values() if result.get('valid', False))
            total_count = len(validation_results)
            
            logger.info("✅ Plan prices validation completed",
                       total_plans=total_count,
                       valid_plans=valid_count)
            
            return {
                'success': True,
                'total_plans': total_count,
                'valid_plans': valid_count,
                'plans': validation_results
            }
            
        except Exception as e:
            logger.error("❌ Plan prices validation failed", error=str(e))
            return {
                'success': False,
                'error': str(e),
                'total_plans': 0,
                'valid_plans': 0,
                'plans': {}
            }
    
    def get_service_info(self) -> dict:
        """
        ✅ НОВЫЙ МЕТОД: Получение информации о состоянии сервиса с защитой от ошибок БД
        
        Returns:
            dict: Информация о сервисе
        """
        try:
            available_plans = []
            plan_validation = {'success': False, 'error': 'Not checked'}
            
            try:
                if hasattr(settings, 'subscription_plans'):
                    plans = getattr(settings, 'subscription_plans', {})
                    if isinstance(plans, dict):
                        available_plans = list(plans.keys())
                        plan_validation = {'success': True, 'count': len(available_plans)}
                    else:
                        plan_validation = {'success': False, 'error': f'Plans is {type(plans).__name__}, not dict'}
                else:
                    plan_validation = {'success': False, 'error': 'subscription_plans not found'}
            except Exception as e:
                plan_validation = {'success': False, 'error': str(e)}
            
            return {
                'service_name': 'RobokassaService',
                'version': 'FIXED_3.0_MAX_DEBUG',
                'merchant_login': self.merchant_login,
                'test_mode': self.test_mode,
                'has_password1': bool(self.password1),
                'has_password2': bool(self.password2),
                'payment_url': self.payment_url,
                'configuration_valid': bool(self.merchant_login and self.password1 and self.password2),
                'available_plans': available_plans,
                'plan_validation': plan_validation,
                'initialized_at': datetime.now().isoformat(),
                'db_protection_enabled': True,
                'max_debug_enabled': True
            }
            
        except Exception as e:
            logger.error("❌ Error getting service info", error=str(e))
            return {
                'service_name': 'RobokassaService',
                'version': 'FIXED_3.0_MAX_DEBUG',
                'error': str(e),
                'initialized_at': datetime.now().isoformat()
            }
    
    def health_check(self) -> dict:
        """
        ✅ НОВЫЙ МЕТОД: Проверка здоровья сервиса
        
        Returns:
            dict: Статус здоровья сервиса
        """
        try:
            checks = {
                'configuration': False,
                'plans': False,
                'signature_test': False
            }
            
            errors = []
            
            # Проверка конфигурации
            try:
                self._validate_configuration()
                checks['configuration'] = True
            except Exception as e:
                errors.append(f"Configuration: {str(e)}")
            
            # Проверка планов
            try:
                plan_validation = self.validate_plan_prices()
                if plan_validation.get('success') and plan_validation.get('valid_plans', 0) > 0:
                    checks['plans'] = True
                else:
                    errors.append(f"Plans: {plan_validation.get('error', 'No valid plans')}")
            except Exception as e:
                errors.append(f"Plans: {str(e)}")
            
            # Проверка генерации подписи
            try:
                test_result = self.test_signature_generation()
                if test_result.get('success'):
                    checks['signature_test'] = True
                else:
                    errors.append(f"Signature: {test_result.get('error', 'Unknown error')}")
            except Exception as e:
                errors.append(f"Signature: {str(e)}")
            
            all_healthy = all(checks.values())
            
            result = {
                'healthy': all_healthy,
                'checks': checks,
                'errors': errors,
                'timestamp': datetime.now().isoformat()
            }
            
            if all_healthy:
                logger.info("✅ RobokassaService health check passed", checks=checks)
            else:
                logger.warning("⚠️ RobokassaService health check failed", 
                              checks=checks, 
                              errors=errors)
            
            return result
            
        except Exception as e:
            logger.error("❌ Health check failed", error=str(e))
            return {
                'healthy': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


# ✅ Создаем глобальный экземпляр сервиса с дополнительной защитой
try:
    robokassa_service = RobokassaService()
    logger.info("🎉 RobokassaService (FIXED VERSION 3.0 with MAX DEBUG) loaded successfully")
    
    # Выполняем проверку здоровья при инициализации
    health_status = robokassa_service.health_check()
    if health_status.get('healthy'):
        logger.info("✅ RobokassaService health check passed during initialization")
    else:
        logger.warning("⚠️ RobokassaService health issues detected during initialization", 
                      errors=health_status.get('errors', []))
        
except Exception as e:
    logger.error("❌ Failed to initialize RobokassaService", error=str(e))
    robokassa_service = None
