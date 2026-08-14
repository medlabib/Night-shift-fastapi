"""Runtime configuration, read from the environment."""

import os
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
    # 0 means "match the host". Hard-coding 8 workers onto a free tier's
    # fraction of a core makes solving slower, not faster.
    solver_workers: int = 0

    @property
    def workers(self) -> int:
        if self.solver_workers > 0:
            return self.solver_workers
        return max(1, min(8, os.cpu_count() or 1))

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
