"""Runtime configuration, read from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Night Shift"
    environment: str = "development"
    debug: bool = False

    # postgresql+psycopg://user:password@host:port/database
    database_url: str = "postgresql+psycopg://nightshift:nightshift@localhost:5432/nightshift"

    # Signs session cookies and the share/reset/verification tokens.
    # Override in production: a rotated secret invalidates every session.
    secret_key: str = "dev-only-insecure-secret-change-me"
    session_cookie: str = "nightshift_session"
    session_max_age: int = 60 * 60 * 24 * 14  # two weeks
    cookie_secure: bool = False  # True behind HTTPS
    cookie_samesite: str = "lax"

    password_reset_ttl: int = 60 * 60          # one hour
    email_verify_ttl: int = 60 * 60 * 24 * 3   # three days

    # Solver budget. The CP-SAT model is usually optimal well inside this.
    solver_time_limit: float = 10.0
    solver_workers: int = 8

    # Auth throttling: attempts allowed per window, per email + IP.
    login_max_attempts: int = 10
    login_window: int = 15 * 60

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
