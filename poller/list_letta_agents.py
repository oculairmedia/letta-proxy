#!/usr/bin/env python3
"""
Script to list all agents from the Letta API and fetch their messages.

This script connects to the Letta API, retrieves all agents,
and polls for new messages for each agent since the last check.
It maintains a state file to track the last message ID processed for each agent.
It also sends new messages as episodes to Graphiti for knowledge graph integration.
"""

import logging
import os
import sys
import json
import requests
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv
from config import init_graphiti

# Logger configuration
# import logging # logging is imported via graphiti_core or other dependencies implicitly, or should be added if not
# Ensure os and sys are imported if not already (they are: os on L11, sys on L12)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout # Explicitly stream to stdout for containerized environments
)
logger = logging.getLogger(__name__)
# Define the path to the state file in the mounted volume
STATE_FILE_PATH = "/app/state/polling_state.json"

# Define message types to process
ALLOWED_MESSAGE_TYPES = {"reasoning_message", "assistant_message", "user_message"}
SKIPPED_MESSAGE_TYPES = {"tool_return_message"}

# Agents to exclude from Graphiti ingestion (e.g., sleeptime agents, system agents)
# These agents' conversations will not be sent to the knowledge graph
EXCLUDED_AGENT_IDS = set(os.getenv('GRAPHITI_EXCLUDED_AGENT_IDS', '').split(','))
EXCLUDED_AGENT_IDS.discard('')  # Remove empty string if env var is empty

# Agent name patterns to exclude (case-insensitive partial match)
EXCLUDED_AGENT_NAME_PATTERNS = [
    'sleeptime',  # Sleeptime memory agents
    '-sleeptime',  # Agents ending with -sleeptime
]


def should_exclude_agent(agent_id: str, agent_name: str) -> bool:
    """
    Check if an agent should be excluded from Graphiti ingestion.

    Args:
        agent_id: The agent's ID
        agent_name: The agent's name

    Returns:
        True if the agent should be excluded, False otherwise
    """
    # Check if agent ID is explicitly excluded
    if agent_id in EXCLUDED_AGENT_IDS:
        return True

    # Check if agent name matches any exclusion patterns
    agent_name_lower = agent_name.lower()
    for pattern in EXCLUDED_AGENT_NAME_PATTERNS:
        if pattern.lower() in agent_name_lower:
            return True

    return False


def load_config() -> Dict[str, str]:
    """
    Load configuration from environment variables.
    
    Returns:
        Dict[str, str]: Configuration dictionary with API base URL and password
    """
    # Load environment variables from .env file if it exists
    load_dotenv()
    
    # Get required environment variables
    base_url = os.getenv('LETTA_BASE_URL')
    password = os.getenv('LETTA_PASSWORD')
    
    # Validate required environment variables
    if not base_url:
        sys.exit("Error: Missing required environment variable: LETTA_BASE_URL")
    if not password:
        sys.exit("Error: Missing required environment variable: LETTA_PASSWORD")
    
    # Construct the full API base URL
    api_url_base = f"{base_url}/v1"
    
    return {
        'api_url_base': api_url_base,
        'password': password
    }

def get_auth_headers(password: str) -> Dict[str, str]:
    """
    Create authentication headers for Letta API requests.
    
    Args:
        password (str): The API password
        
    Returns:
        Dict[str, str]: Headers dictionary with authentication credentials
    """
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-BARE-PASSWORD': f"password {password}",
        'Authorization': f"Bearer {password}"
    }

def list_all_agents(api_url_base: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Retrieve all agents from the Letta API with pagination handling.
    
    Args:
        api_url_base (str): The base URL for the Letta API
        headers (Dict[str, str]): Authentication headers
        
    Returns:
        List[Dict[str, Any]]: List of all agent objects
    """
    endpoint = f"{api_url_base}/agents/"
    all_agents = []
    
    # Initial parameters
    params = {
        'limit': 100  # Request a larger batch size to minimize API calls
    }
    
    while True:
        try:
            # Make the API request
            response = requests.get(endpoint, headers=headers, params=params)
            response.raise_for_status()  # Raise exception for HTTP errors
            
            # Parse the response
            agents_batch = response.json()
            
            # Check if we got any agents
            if not agents_batch:
                break
                
            # Add the current batch to our collection
            all_agents.extend(agents_batch)
            
            # Check if we've reached the end of the list
            if len(agents_batch) < params['limit']:
                break
                
            # Update the 'after' parameter for the next page
            # Use the ID of the last agent in the current batch
            params['after'] = agents_batch[-1]['id']
            
        except requests.exceptions.RequestException as e:
            print(f"Error retrieving agents: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status code: {e.response.status_code}")
                print(f"Response body: {e.response.text}")
            sys.exit(1)
    
    return all_agents

def get_agent_details(agent_id: str, api_url_base: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve details for a specific agent from the Letta API.
    
    Args:
        agent_id (str): The ID of the agent
        api_url_base (str): The base URL for the Letta API
        headers (Dict[str, str]): Authentication headers
        
    Returns:
        Optional[Dict[str, Any]]: Agent details dictionary or None if an error occurs
    """
    endpoint = f"{api_url_base}/agents/{agent_id}"
    try:
        logger.info(f"Fetching agent details for agent ID: {agent_id}")
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        agent_data = response.json()
        logger.info(f"Successfully retrieved details for agent {agent_id}")
        logger.debug(f"Agent details: {json.dumps(agent_data, default=str)[:500]}...")
        return agent_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving details for agent {agent_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return None

def get_admin_users(api_url_base: str, headers: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """
    Retrieve all admin users from the Letta API.
    This is used to map user IDs in messages to actual user names.
    
    Args:
        api_url_base (str): The base URL for the Letta API
        headers (Dict[str, str]): Authentication headers
        
    Returns:
        Dict[str, Dict[str, Any]]: Dictionary mapping user IDs to user data (e.g., {'id': 'user_uuid', 'name': 'User Name'})
    """
    endpoint = f"{api_url_base}/admin/users/"
    user_map = {}
    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        users = response.json()
        if isinstance(users, list):
            for user_data in users:
                if isinstance(user_data, dict) and 'id' in user_data:
                    user_map[user_data['id']] = user_data
            print(f"Successfully fetched {len(user_map)} users from /admin/users/")
        else:
            print(f"Warning: Expected a list from /admin/users/, got {type(users)}. Response: {users}")
    except requests.exceptions.RequestException as e:
        print(f"Error retrieving admin users: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status code: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from /admin/users/: {e}")
    return user_map

def get_identity_details(identity_id: str, api_url_base: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve details for a specific identity from the Letta API.
    
    Args:
        identity_id (str): The ID of the identity
        api_url_base (str): The base URL for the Letta API
        headers (Dict[str, str]): Authentication headers
        
    Returns:
        Optional[Dict[str, Any]]: Identity details dictionary or None if an error occurs
    """
    endpoint = f"{api_url_base}/identities/{identity_id}"
    try:
        logger.info(f"Fetching identity details for identity ID: {identity_id}")
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        identity_data = response.json()
        logger.info(f"Successfully retrieved details for identity {identity_id}")
        logger.debug(f"Identity details: {json.dumps(identity_data, default=str)[:500]}...")
        return identity_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving details for identity {identity_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return None

def load_polling_state() -> Dict[str, str]:
    """
    Load the polling state from the state file in the mounted volume.
    
    Returns:
        Dict[str, str]: Dictionary mapping agent IDs to their last processed message IDs
    """
    try:
        if os.path.exists(STATE_FILE_PATH):
            with open(STATE_FILE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            print(f"State file {STATE_FILE_PATH} not found. Starting with empty state.")
            return {}
    except Exception as e:
        print(f"Error loading state file {STATE_FILE_PATH}: {e}")
        return {}

def save_polling_state(state: Dict[str, str]) -> None:
    """
    Save the polling state to the state file in the mounted volume.
    
    Args:
        state (Dict[str, str]): Dictionary mapping agent IDs to their last processed message IDs
    """
    try:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(STATE_FILE_PATH), exist_ok=True)
        
        with open(STATE_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
        print(f"Updated polling state saved to {STATE_FILE_PATH}")
    except Exception as e:
        print(f"Error saving state to {STATE_FILE_PATH}: {e}")

def fetch_new_messages_for_agent(
    agent_id: str, 
    api_url_base: str, 
    headers: Dict[str, str], 
    last_message_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve new messages for a specific agent from the Letta API with pagination handling.
    
    Args:
        agent_id (str): The ID of the agent to fetch messages for
        api_url_base (str): The base URL for the Letta API
        headers (Dict[str, str]): Authentication headers
        last_message_id (Optional[str]): The ID of the last processed message
        
    Returns:
        List[Dict[str, Any]]: List of new message objects for the agent
    """
    endpoint = f"{api_url_base}/agents/{agent_id}/messages"
    new_messages = []
    
    # Pagination strategy
    #
    # Letta's `after/before` params are cursor-based pagination in the specified
    # sort order. To fetch messages newer than our stored cursor, we need to
    # request messages in chronological order (`asc`) and page forward with
    # `after=<last_message_id>`.
    params = {
        'limit': 100,
        'order': 'asc',
        'use_assistant_message': 'false',
    }

    # Use last_message_id to only fetch messages after the last processed one
    if last_message_id:
        params['after'] = last_message_id

    tried_without_after = False

    while True:
        try:
            response = requests.get(endpoint, headers=headers, params=params)
            response.raise_for_status()

            messages_batch = response.json()

            if not messages_batch:
                break

            new_messages.extend(messages_batch)

            if len(messages_batch) < params['limit']:
                break

            # Continue paging forward in chronological order
            params['after'] = messages_batch[-1]['id']

        except requests.exceptions.RequestException as e:
            # Handle 404 errors specially - the stored message ID may have been deleted
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404:
                if 'after' in params and not tried_without_after:
                    tried_without_after = True
                    print(
                        f"  Message ID {params['after']} not found (404), trying without 'after' param to reset state"
                    )
                    del params['after']
                    continue
            print(f"Error retrieving messages for agent {agent_id}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status code: {e.response.status_code}")
                print(f"Response body: {e.response.text}")
            return []

    return new_messages

def summarize_agent(agent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract essential information from an agent object.
    
    Args:
        agent (Dict[str, Any]): The full agent object
        
    Returns:
        Dict[str, Any]: A summarized version with key information
    """
    return {
        'id': agent['id'],
        'name': agent.get('name', 'Unnamed Agent'),
        'description': agent.get('description', '')
    }

def format_message_for_graphiti(
    message_obj: Dict[str, Any],
    admin_user_map: Optional[Dict[str, Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    """
    Format a Letta message for Graphiti HTTP API.
    
    Args:
        message_obj: The message object from Letta API
        admin_user_map: Map of user IDs to user data
        
    Returns:
        Dict with formatted message or None if message should be skipped
    """
    message_id = message_obj['id']
    # Handle both 'type' and 'message_type' field names (API returns 'message_type')
    message_type = message_obj.get('type') or message_obj.get('message_type')
    # Handle both 'created_at' and 'date' field names
    created_at_str = message_obj.get('created_at') or message_obj.get('date')
    # Handle both 'user_id' and 'sender_id' field names
    message_api_user_id = message_obj.get('user_id') or message_obj.get('sender_id')
    
    # Infer message type if None
    if message_type is None:
        if message_obj.get('reasoning') is not None:
            message_type = 'reasoning_message'
        elif (message_obj.get('user_id') or message_obj.get('sender_id')) is not None and message_obj.get('content') is not None:
            message_type = 'user_message'
        elif message_obj.get('content') is not None:
            message_type = 'assistant_message'
        else:
            logger.warning(f"Could not infer type for message {message_id}")
            return None
    
    # Skip unwanted message types
    if message_type in SKIPPED_MESSAGE_TYPES:
        logger.info(f"Skipping message {message_id} of type '{message_type}'")
        return None
    if message_type not in ALLOWED_MESSAGE_TYPES:
        logger.info(f"Skipping message {message_id} of unhandled type '{message_type}'")
        return None
    
    # Extract content based on message type
    content = ""
    role = "assistant"  # default
    role_name = "Agent"
    
    if message_type == 'user_message':
        role = "user"
        content_data = message_obj.get('content', '')
        if isinstance(content_data, list):
            text_parts = [part.get('text', '') for part in content_data 
                         if isinstance(part, dict) and part.get('type') == 'text']
            content = ' '.join(text_parts)
        elif isinstance(content_data, dict):
            content = content_data.get('text', json.dumps(content_data))
        else:
            content = str(content_data)
            
        # Get user name from admin map
        if message_api_user_id and admin_user_map and message_api_user_id in admin_user_map:
            role_name = admin_user_map[message_api_user_id].get('name', f"User {message_api_user_id}")
        elif message_api_user_id:
            role_name = f"User {message_api_user_id}"
        else:
            role_name = "Unknown User"
            
    elif message_type == 'assistant_message':
        role = "assistant"
        content_data = message_obj.get('content', '')
        if isinstance(content_data, list):
            text_parts = [part.get('text', '') for part in content_data 
                         if isinstance(part, dict) and part.get('type') == 'text']
            content = ' '.join(text_parts)
        elif isinstance(content_data, dict):
            content = content_data.get('text', json.dumps(content_data))
        else:
            content = str(content_data)
        role_name = "Agent"
        
    elif message_type == 'reasoning_message':
        role = "system"
        reasoning_data = message_obj.get('reasoning', '')
        if isinstance(reasoning_data, (dict, list)):
            content = json.dumps(reasoning_data)
        else:
            content = str(reasoning_data)
        role_name = "Agent (Reasoning)"
    
    # Skip empty content
    if not content or content.strip() in ['{}', 'None', '[No text content]', '""']:
        logger.info(f"Skipping message {message_id} due to empty content")
        return None
    
    # Format timestamp
    timestamp = created_at_str if created_at_str else datetime.now().isoformat()
    if timestamp.endswith('Z'):
        timestamp = timestamp[:-1] + '+00:00'
    
    return {
        "content": content,
        "name": f"{role_name} Message",
        "role_type": role,
        "role": role_name,
        "timestamp": timestamp,
        "source_description": f"Letta {message_type}"
    }


async def main():
    """Main function to execute the script."""
    print("Polling for new messages from Letta agents...")
    
    # Load configuration
    config = load_config()
    
    # Get authentication headers
    headers = get_auth_headers(config['password'])
    
    # Load the polling state
    polling_state = load_polling_state()
    
    # Initialize Graphiti HTTP client
    try:
        graphiti = init_graphiti()
        print("Successfully connected to Graphiti")
    except Exception as e:
        print(f"Error connecting to Graphiti: {e}")
        return

    # Fetch admin users for name mapping
    print("Fetching admin user map...")
    admin_user_map = await asyncio.to_thread(
        get_admin_users, config['api_url_base'], headers
    )
    if not admin_user_map:
        print("Warning: Admin user map is empty. User names might not be resolved.")
    
    # Retrieve all agents
    print("Fetching all agents...")
    agents = await asyncio.to_thread(
        list_all_agents, config['api_url_base'], headers
    )
    
    all_agents_data = {}
    
    for i, agent_summary in enumerate(agents, 1):
        agent_id = agent_summary['id']
        agent_name = agent_summary.get('name', 'Unnamed Agent')

        # Check if agent should be excluded from Graphiti ingestion
        if should_exclude_agent(agent_id, agent_name):
            print(f"\nSkipping excluded agent {i}/{len(agents)}: {agent_name} (ID: {agent_id})")
            continue

        print(f"\nPolling for agent {i}/{len(agents)}: {agent_name} (ID: {agent_id}).")
        last_message_id_for_agent = polling_state.get(agent_id)
        if last_message_id_for_agent:
            print(f"Last known message ID for {agent_name} was: {last_message_id_for_agent} (for reference).")
        else:
            print(f"No prior polling state for agent {agent_name}.")

        fetched_messages = await asyncio.to_thread(
            fetch_new_messages_for_agent,
            agent_id,
            config['api_url_base'],
            headers,
            last_message_id_for_agent
        )
        
        processed_messages_for_agent = []
        if fetched_messages:
            print(f"Found {len(fetched_messages)} messages for agent {agent_name}.")
            
            # Format messages for Graphiti HTTP API
            graphiti_messages = []
            newest_message_id_in_batch = None
            
            for msg in fetched_messages:
                # Skip messages we've already processed (prevents duplicate ingestion when fallback is used)
                if last_message_id_for_agent and msg['id'] == last_message_id_for_agent:
                    print(f"  Skipping already processed Message ID: {msg['id']}")
                    continue

                print(f"  Processing Message ID: {msg['id']}, Type: {msg.get('type') or msg.get('message_type')}")
                
                formatted_msg = format_message_for_graphiti(msg, admin_user_map)
                if formatted_msg:
                    graphiti_messages.append(formatted_msg)
                    processed_messages_for_agent.append(msg)
                    
                if newest_message_id_in_batch is None or msg['id'] > newest_message_id_in_batch:
                    newest_message_id_in_batch = msg['id']
            
            # Send all messages to Graphiti in one HTTP call
            if graphiti_messages:
                success = graphiti.add_messages(agent_id, graphiti_messages)
                if success:
                    print(f"Successfully sent {len(graphiti_messages)} messages to Graphiti for agent {agent_name}")
                else:
                    print(f"Failed to send messages to Graphiti for agent {agent_name}")

            if newest_message_id_in_batch:
                polling_state[agent_id] = newest_message_id_in_batch
                print(f"Updating last message ID for agent {agent_name} to {newest_message_id_in_batch}.")
        else:
            print(f"No new messages found for agent {agent_name}.")
        
        all_agents_data[agent_id] = {
            'name': agent_name,
            'description': agent_summary.get('description', ''),
            'processed_messages_this_run': processed_messages_for_agent
        }
    
    # Save the updated polling state
    save_polling_state(polling_state)
    
    # Save all data to a JSON file (optional, can be removed if not needed)
    output_file = 'all_agent_messages.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_agents_data, f, indent=4)
        print(f"\nSaved all agent data and new messages to {output_file}")
    except Exception as e:
        print(f"Error saving data to {output_file}: {e}")
    
    # Display summary
    total_agents = len(all_agents_data)
    total_new_messages = sum(len(agent_data['processed_messages_this_run']) for agent_data in all_agents_data.values())
    print(f"\nSummary: Processed {total_agents} agents with {total_new_messages} new messages.")

if __name__ == "__main__":
    asyncio.run(main())