from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://conv_search:conv_search_dev@localhost:5433/conv_search"
    )
    openai_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"


settings = Settings()
