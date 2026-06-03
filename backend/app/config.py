from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080
    mcp_server_url: str
    anthropic_api_key: str = ""
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "TimeToMeet <noreply@timetomeet.local>"
    frontend_url: str = "http://localhost:3000"

    # Google Calendar (optional — features degrade to DB-only when unset)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/auth/google/callback"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    class Config:
        env_file = ".env"


settings = Settings()
