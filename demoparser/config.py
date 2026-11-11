"""Configuration management for the demo processor."""

from dotenv import load_dotenv
from os import getenv
from dataclasses import dataclass
from typing import Optional
import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
load_dotenv()

@dataclass
class DatabaseConfig:
    """Database configuration."""
    database: str
    host: str
    username: str
    password: str
    port: int
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        host = getenv("DB_HOST")
        port = getenv("DB_PORT")
        print(f"DEBUG: Python is trying to connect to {host}:{port}")
        return cls(
            database=getenv("DB_DATABASE"),
            host=host,
            username=getenv("DB_USERNAME"),
            password=getenv("DB_PASSWORD"),
            port=int(port or 3306)
        )

@dataclass
class SteamConfig:
    """Steam API configuration."""
    api_key: str
    
    @classmethod
    def from_env(cls) -> 'SteamConfig':
        return cls(api_key=getenv('STEAM_AUTH_API_KEYS'))

@dataclass
class DebugConfig:
    """Debug configuration."""
    enabled: bool
    demo_file_path: Optional[str]
    user_id: int
    demo_name: str
    save: bool
    
    @classmethod
    def from_env(cls) -> 'DebugConfig':
        return cls(
            enabled=getenv("DEBUG_MODE", False),
            demo_file_path=getenv("DEBUG_DEMO_PATH", "sørby2anc.dem"),
            user_id=int(getenv("DEBUG_USER_ID", "18")),
            demo_name=getenv("DEBUG_DEMO_NAME", "sørby2anc"),
            save=getenv("DEBUG_SAVE", True)
        )

@dataclass
class AppConfig:
    """Main application configuration."""
    database: DatabaseConfig
    steam: SteamConfig
    debug: DebugConfig
    version: int
    
    @classmethod
    def from_env(cls) -> 'AppConfig':
        return cls(
            database=DatabaseConfig.from_env(),
            steam=SteamConfig.from_env(),
            debug=DebugConfig.from_env(),
            version=5
        )