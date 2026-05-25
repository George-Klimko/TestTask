from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_prefix='APP_')

    host: str = '0.0.0.0'
    port: int = 8000
    redis_url: str = 'redis://localhost:6379/0'

    max_threads_per_job: int = 50
    max_file_size_mb: int = 20
    max_active_jobs: int = 10


settings = Settings()