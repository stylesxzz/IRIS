"""
Mercado Pago integration module for IRIS
Gerencia pagamentos e webhooks do Mercado Pago
"""

import os
import requests
import json
from datetime import datetime
from iris_core import log

# Configuração do Mercado Pago
MP_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "")
MP_PUBLIC_KEY = os.environ.get("MERCADO_PAGO_PUBLIC_KEY", "")
MP_WEBHOOK_URL = os.environ.get("MERCADO_PAGO_WEBHOOK_URL", "")

MP_API_BASE = "https://api.mercadopago.com/v1"

# Preços dos planos (em reais)
PLANS = {
    "monthly": {
        "name": "Plano Mensal",
        "price": 29.90,
        "credits": 500,
        "duration_days": 30
    },
    "annual": {
        "name": "Plano Anual",
        "price": 299.90,
        "credits": 6000,  # 500 * 12
        "duration_days": 365
    }
}

def create_preference(user_id, plan_type, user_email):
    """
    Cria preferência de pagamento no Mercado Pago.
    Retorna URL de checkout.
    """
    if not MP_ACCESS_TOKEN:
        log("ERROR", "MERCADO_PAGO_ACCESS_TOKEN não configurado")
        return {"success": False, "error": "Mercado Pago não configurado"}
    
    if plan_type not in PLANS:
        return {"success": False, "error": "Plano inválido"}
    
    plan = PLANS[plan_type]
    
    try:
        preference_data = {
            "items": [
                {
                    "title": plan["name"],
                    "description": f"Acesso ao IRIS Agent com {plan['credits']} créditos",
                    "quantity": 1,
                    "unit_price": plan["price"],
                    "currency_id": "BRL"
                }
            ],
            "payer": {
                "email": user_email
            },
            "external_reference": f"iris_user_{user_id}_{plan_type}",
            "notification_url": MP_WEBHOOK_URL,
            "back_urls": {
                "success": f"/payment/success",
                "failure": f"/payment/failure",
                "pending": f"/payment/pending"
            },
            "auto_return": "approved"
        }
        
        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{MP_API_BASE}/preferences",
            json=preference_data,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 201:
            data = response.json()
            log("INFO", f"Preferência criada para usuário {user_id}: {data['id']}")
            return {
                "success": True,
                "preference_id": data['id'],
                "checkout_url": data.get('init_point', ''),
                "plan": plan_type,
                "amount": plan["price"]
            }
        else:
            log("ERROR", f"Erro ao criar preferência: {response.text}")
            return {"success": False, "error": "Erro ao criar preferência"}
    
    except Exception as e:
        log("ERROR", f"Exceção ao criar preferência: {str(e)}")
        return {"success": False, "error": str(e)}

def verify_payment(payment_id):
    """
    Verifica status do pagamento no Mercado Pago.
    """
    if not MP_ACCESS_TOKEN:
        return {"success": False, "error": "Mercado Pago não configurado"}
    
    try:
        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}"
        }
        
        response = requests.get(
            f"{MP_API_BASE}/payments/{payment_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            payment_info = {
                "success": True,
                "payment_id": data['id'],
                "status": data['status'],
                "status_detail": data.get('status_detail', ''),
                "amount": data['transaction_amount'],
                "external_reference": data.get('external_reference', ''),
                "payer_email": data.get('payer', {}).get('email', ''),
                "created_at": data.get('date_created', '')
            }
            
            log("INFO", f"Pagamento verificado: {payment_id} - Status: {data['status']}")
            return payment_info
        else:
            log("ERROR", f"Erro ao verificar pagamento: {response.text}")
            return {"success": False, "error": "Erro ao verificar pagamento"}
    
    except Exception as e:
        log("ERROR", f"Exceção ao verificar pagamento: {str(e)}")
        return {"success": False, "error": str(e)}

def process_webhook(data):
    """
    Processa webhook do Mercado Pago.
    Retorna informações do pagamento se válido.
    """
    try:
        # Mercado Pago envia o payment_id no webhook
        payment_id = data.get('data', {}).get('id')
        
        if not payment_id:
            log("WARN", "Webhook recebido sem payment_id")
            return {"success": False, "error": "payment_id não encontrado"}
        
        # Verifica o pagamento
        payment_info = verify_payment(payment_id)
        
        if payment_info.get("success"):
            return payment_info
        else:
            return {"success": False, "error": "Falha ao verificar pagamento"}
    
    except Exception as e:
        log("ERROR", f"Erro ao processar webhook: {str(e)}")
        return {"success": False, "error": str(e)}

def get_plan_info(plan_type):
    """Retorna informações do plano."""
    return PLANS.get(plan_type, None)

def format_price(amount):
    """Formata preço em BRL."""
    return f"R$ {amount:.2f}".replace(".", ",")
