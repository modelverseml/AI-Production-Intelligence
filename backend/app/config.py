from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL : str
    JWT_SECRET : str
    JWT_ALGORITHM : str = "HS256"
    ACCESS_TOKEN_MINUTES : int = 60
    CORS_ORIGINS : str = "http://localhost:5173,http://127.0.0.1:5173"
    EMBEDDING_MODEL : str = "sentence-transformers/all-MiniLM-L6-v2"
    ADMIN_EMAIL : str | None = None
    ADMIN_PASSWORD : str | None = None
    AZURE_OPENAI_ENDPOINT : str | None = None
    AZURE_OPENAI_API_VERSION : str = "openai/v1/"
    AZURE_OPENAI_KEY : str | None = None
    AZURE_OPENAI_DEPLOYMENT_NAME_LOWER : str = "gpt-4.1-mini"
    AZURE_OPENAI_DEPLOYMENT_NAME_HIGHER : str = "gpt-5-mini"

    model_config = SettingsConfigDict(
        env_file = ".env",
        extra = "ignore"
    )

settings = Settings()
