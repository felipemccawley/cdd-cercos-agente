"""Integraciones externas (Kommo CRM, Webpay, correo). Cablear credenciales en .env."""

try:  # cargar variables de .env (SMTP, Kommo, Webpay) en cualquier punto de entrada
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass
