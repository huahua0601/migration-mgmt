from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DB_HOST: str = "mysql"
    DB_PORT: int = 3306
    DB_USER: str = "mgmt"
    DB_PASSWORD: str = "mgmt123456"
    DB_NAME: str = "migration_mgmt"
    JWT_SECRET: str = "migration-mgmt-secret-key-2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    @property
    def database_url(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"


@lru_cache
def get_settings() -> Settings:
    return Settings()
