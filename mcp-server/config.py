from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    backend_url: str = "http://backend:8080"

    class Config:
        env_file = ".env"


settings = Settings()
