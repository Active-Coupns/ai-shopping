import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Database configuration
    DATABASE_URL: str = "sqlite:///./gateway.db"
    
    # Third-party API keys (Empty string triggers mock mode fallback)
    HASDATA_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Gateway Configuration
    ADMIN_API_KEY: str = "gateway_admin_secret_token_123"
    
    # Environment variables loading config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
