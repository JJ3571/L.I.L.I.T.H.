import aiohttp
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CraftyAPI:
    """
    Async wrapper for Crafty Controller API v2
    Handles authentication, server management, and statistics
    """
    
    def __init__(self, base_url: str, username: str, password: str):
        """
        Initialize the Crafty API client
        
        Args:
            base_url: Base URL of Crafty Controller (e.g., "http://192.168.0.206:8111")
            username: Crafty Controller username
            password: Crafty Controller password
        """
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api/v2"
        self.username = username
        self.password = password
        self.token = None
        self.token_expires = None
        self._session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            # Use proper SSL for production domains, disable for local development
            ssl_verify = not (self.base_url.startswith("https://192.168.") or 
                            self.base_url.startswith("https://10.") or
                            self.base_url.startswith("https://localhost"))
            
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(ssl=ssl_verify)
            )
        return self._session
    
    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _ensure_authenticated(self) -> bool:
        """
        Ensure we have a valid authentication token
        Returns True if authenticated, False otherwise
        """
        # Check if token is still valid (with 5 minute buffer)
        if (self.token and self.token_expires and 
            datetime.now() < self.token_expires - timedelta(minutes=5)):
            return True
        
        # Login to get new token
        try:
            session = await self._get_session()
            login_data = {
                "username": self.username,
                "password": self.password
            }
            
            async with session.post(f"{self.api_url}/auth/login", json=login_data) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok":
                        self.token = data["data"]["token"]
                        # JWT tokens typically expire in 1 hour, but we'll be conservative
                        self.token_expires = datetime.now() + timedelta(minutes=50)
                        logger.info("Successfully authenticated with Crafty Controller")
                        return True
                    else:
                        logger.error(f"Authentication failed: {data}")
                        return False
                else:
                    logger.error(f"Authentication request failed with status {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    async def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Optional[Dict]:
        """
        Make an authenticated request to the Crafty API
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without /api/v2 prefix)
            data: Optional data to send
            
        Returns:
            Response data or None if failed
        """
        if not await self._ensure_authenticated():
            return None
        
        try:
            session = await self._get_session()
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.api_url}{endpoint}"
            
            async with session.request(method, url, json=data, headers=headers) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data.get("status") == "ok":
                        return response_data.get("data")
                    else:
                        logger.error(f"API request failed: {response_data}")
                        return None
                else:
                    logger.error(f"API request failed with status {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"API request error: {e}")
            return None

    async def _make_action_request(self, endpoint: str, data: Dict = None) -> bool:
        """
        Make an authenticated action request to the Crafty API
        For server actions, we only care about the status, not the data
        
        Args:
            endpoint: API endpoint (without /api/v2 prefix)
            data: Optional data to send
            
        Returns:
            True if successful (status == "ok"), False otherwise
        """
        if not await self._ensure_authenticated():
            return False
        
        try:
            session = await self._get_session()
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.api_url}{endpoint}"
            
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    response_data = await response.json()
                    success = response_data.get("status") == "ok"
                    logger.info(f"Action request to {endpoint}: status={response_data.get('status')}, success={success}")
                    return success
                else:
                    logger.error(f"Action request failed with status {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Action request error: {e}")
            return False
    
    async def get_servers(self) -> Optional[List[Dict]]:
        """Get list of all servers"""
        return await self._make_request("GET", "/servers")
    
    async def get_server(self, server_id: str) -> Optional[Dict]:
        """Get detailed information about a specific server"""
        return await self._make_request("GET", f"/servers/{server_id}")
    
    async def get_server_stats(self, server_id: str) -> Optional[Dict]:
        """Get server statistics"""
        return await self._make_request("GET", f"/servers/{server_id}/stats")
    
    async def get_server_public_data(self, server_id: str) -> Optional[Dict]:
        """Get server public data (less detailed)"""
        return await self._make_request("GET", f"/servers/{server_id}/public")
    
    async def start_server(self, server_id: str) -> bool:
        """Start a server"""
        return await self._make_action_request(f"/servers/{server_id}/action/start_server")
    
    async def stop_server(self, server_id: str) -> bool:
        """Stop a server"""
        return await self._make_action_request(f"/servers/{server_id}/action/stop_server")
    
    async def restart_server(self, server_id: str) -> bool:
        """Restart a server"""
        return await self._make_action_request(f"/servers/{server_id}/action/restart_server")
    
    async def kill_server(self, server_id: str) -> bool:
        """Force kill a server"""
        return await self._make_action_request(f"/servers/{server_id}/action/kill_server")
    
    async def backup_server(self, server_id: str) -> bool:
        """Create a backup of the server"""
        return await self._make_action_request(f"/servers/{server_id}/action/backup_server")
    
    async def send_command(self, server_id: str, command: str) -> bool:
        """
        Send a command to the server console
        
        Args:
            server_id: ID of the server
            command: Command to send (without leading slash)
        """
        # Based on API docs, the command is sent as plain text in the request body
        if not await self._ensure_authenticated():
            return False
        
        try:
            session = await self._get_session()
            headers = {"Authorization": f"Bearer {self.token}"}
            url = f"{self.api_url}/servers/{server_id}/stdin"
            
            async with session.post(url, data=command, headers=headers) as response:
                if response.status == 200:
                    response_data = await response.json()
                    return response_data.get("status") == "ok"
                else:
                    logger.error(f"Command send failed with status {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Command send error: {e}")
            return False
    
    async def get_server_logs(self, server_id: str, raw: bool = False) -> Optional[List[str]]:
        """
        Get server logs
        
        Args:
            server_id: ID of the server
            raw: Whether to get raw logs or formatted
        """
        endpoint = f"/servers/{server_id}/logs"
        if raw:
            endpoint += "?raw=true"
        
        return await self._make_request("GET", endpoint)
    
    def format_server_info(self, server_data: Dict) -> str:
        """Format server information for Discord display"""
        name = server_data.get("server_name", "Unknown")
        server_type = server_data.get("type", "unknown")
        server_id = server_data.get("server_id", "N/A")
        
        return f"**{name}** (ID: {server_id}) - Type: {server_type}"
    
    def format_server_stats(self, stats_data: Dict) -> str:
        """Format server statistics for Discord display"""
        if not stats_data:
            return "No statistics available"
        
        server_info = stats_data.get("server_id", {})
        server_name = server_info.get("server_name", "Unknown Server")
        
        running = stats_data.get("running", False)
        status = "🟢 Online" if running else "🔴 Offline"
        
        # Get version information
        version = stats_data.get("version", "Unknown")
        
        cpu = stats_data.get("cpu", 0)
        mem = stats_data.get("mem", "0MB")
        mem_percent = stats_data.get("mem_percent", 0)
        
        online_players = stats_data.get("online", 0)
        max_players = stats_data.get("max", 0)
        
        world_name = stats_data.get("world_name", "Unknown")
        world_size = stats_data.get("world_size", "Unknown")
        
        stats_text = f"""**{server_name}**
{status}
**Version:** {version}
**Players:** {online_players}/{max_players}
**World:** {world_name} ({world_size})
**CPU:** {cpu}%
**Memory:** {mem} ({mem_percent}%)"""
        
        if running:
            started = stats_data.get("started", "Unknown")
            stats_text += f"\n**Uptime:** Since {started}"
        
        return stats_text