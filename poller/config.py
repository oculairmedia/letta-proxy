import logging
import os
from logging import INFO
from dotenv import load_dotenv
import requests
from dataclasses import dataclass
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Settings configuration
@dataclass
class Settings:
    # Graphiti HTTP API settings
    GRAPHITI_ENDPOINT: str = os.environ.get("GRAPHITI_ENDPOINT", "http://192.168.50.90:8003")
    
    # Plane API settings
    PLANE_API_URL: str = os.environ.get("PLANE_BASE_URL", "http://192.168.50.90")  # Base URL without /api/v1
    PLANE_WORKSPACE_SLUG: str = os.environ.get("PLANE_WORKSPACE_SLUG", "production-applications")
    PLANE_API_KEY: str = os.environ.get("PLANE_API_KEY")
    
    # BookStack API settings
    BS_URL: str = os.environ.get("BS_URL", "https://knowledge.oculair.ca").rstrip("/")
    BS_TOKEN_ID: str = os.environ.get("BS_TOKEN_ID")
    BS_TOKEN_SECRET: str = os.environ.get("BS_TOKEN_SECRET")

settings = Settings()

class GraphitiHTTPClient:
    """Simple HTTP client for Graphiti API"""
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip('/')
        self.session = requests.Session()
        
    def add_messages(self, group_id: str, messages: List[Dict[str, Any]]) -> bool:
        """
        Send messages to Graphiti /messages endpoint
        
        Args:
            group_id: The group ID (typically agent ID)
            messages: List of message objects
            
        Returns:
            bool: True if successful, False otherwise
        """
        url = f"{self.endpoint}/messages"
        payload = {
            "group_id": group_id,
            "messages": messages
        }
        
        try:
            logger.info(f"Sending {len(messages)} messages to Graphiti for group {group_id}")
            response = self.session.post(url, json=payload, timeout=30)
            
            if response.status_code == 202:
                logger.info(f"Successfully sent messages to Graphiti (HTTP {response.status_code})")
                return True
            else:
                logger.error(f"Graphiti API error: HTTP {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending messages to Graphiti: {e}")
            return False

def init_graphiti():
    """Initialize Graphiti HTTP client"""
    logger.info(f"Using Graphiti HTTP endpoint: {settings.GRAPHITI_ENDPOINT}")
    return GraphitiHTTPClient(settings.GRAPHITI_ENDPOINT)
