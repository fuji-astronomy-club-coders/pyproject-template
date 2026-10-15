"""Run the application"""

from src.config import load_config
from src.main import main

config = load_config()
main(config=config)
