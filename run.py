"""Run the application"""

from src.main import main
from src.package.config import load_config

config = load_config()
main(config=config)
