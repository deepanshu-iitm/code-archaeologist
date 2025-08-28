"""
Environment Variable Loader

Handles loading environment variables from .env file and system environment.
"""

import os
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


class EnvLoader:
    """Utility class for loading environment variables."""
    
    def __init__(self, env_file: Optional[str] = None):
        """Initialize the environment loader."""
        self.env_file = env_file or self._find_env_file()
        self._load_env()
    
    def _find_env_file(self) -> Optional[str]:
        """Find the .env file in the project root."""
        current_dir = Path(__file__).parent
        
        # Look for .env file going up the directory tree
        for parent in [current_dir] + list(current_dir.parents):
            env_file = parent / '.env'
            if env_file.exists():
                return str(env_file)
        
        return None
    
    def _load_env(self):
        """Load environment variables from .env file if available."""
        if DOTENV_AVAILABLE and self.env_file and os.path.exists(self.env_file):
            load_dotenv(self.env_file)
            print(f"Loaded environment variables from: {self.env_file}")
        elif self.env_file and os.path.exists(self.env_file):
            print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
        else:
            print("No .env file found. Using system environment variables.")
    
    @staticmethod
    def get_gemini_api_key() -> Optional[str]:
        """Get the Gemini API key from environment."""
        return os.getenv('GEMINI_API_KEY')
    
    @staticmethod
    def get_neo4j_config() -> dict:
        """Get Neo4j configuration from environment."""
        return {
            'uri': os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
            'user': os.getenv('NEO4J_USER', 'neo4j'),
            'password': os.getenv('NEO4J_PASSWORD', 'password')
        }
    
    @staticmethod
    def get_web_config() -> dict:
        """Get web server configuration from environment."""
        return {
            'host': os.getenv('WEB_HOST', 'localhost'),
            'port': int(os.getenv('WEB_PORT', '8000'))
        }
    
    @staticmethod
    def validate_required_vars() -> list:
        """Validate that required environment variables are set."""
        missing_vars = []
        
        if not EnvLoader.get_gemini_api_key():
            missing_vars.append('GEMINI_API_KEY')
        
        return missing_vars


# Global instance for easy access
env_loader = EnvLoader()
