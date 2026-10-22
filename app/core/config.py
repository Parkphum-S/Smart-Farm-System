from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMARTFARM_", extra="ignore")

    app_name: str = "Smart Farm System API"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    archive_path: str = "/mnt/smartfarm-data/archive"


settings = Settings()
