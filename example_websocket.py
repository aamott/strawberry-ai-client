"""Example of WebSocket skill routing integration.

This shows how to wire up the HubClient WebSocket with SkillService.
"""

import asyncio
import logging
from pathlib import Path

from strawberry.config import load_config
from strawberry.hub import HubClient, HubConfig
from strawberry.skills import SkillService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Example WebSocket integration."""
    # Load config
    config_path = Path("config/config.yaml")
    settings = load_config(config_path) if config_path.exists() else None
    
    if not settings or not settings.hub.token:
        print("Error: Hub token not configured")
        print("Set HUB_TOKEN in .env or config/config.yaml")
        return 1
    
    # Initialize Hub client
    hub_config = HubConfig(
        url=settings.hub.url,
        token=settings.hub.token,
        timeout=settings.hub.timeout_seconds,
    )
    hub_client = HubClient(hub_config)
    
    # Initialize Skill Service
    skills_path = Path("skills")
    skill_service = SkillService(
        skills_path=skills_path,
        hub_client=hub_client,
        use_sandbox=True,
    )
    
    # Load and register skills
    skills = skill_service.load_skills()
    logger.info(f"Loaded {len(skills)} skills")
    
    if await skill_service.register_with_hub():
        logger.info("Skills registered with Hub")
    
    # Start heartbeat
    await skill_service.start_heartbeat()
    
    # Set up WebSocket callback
    async def skill_callback(skill_name: str, method_name: str, args: list, kwargs: dict):
        """Handle incoming skill execution requests from Hub."""
        logger.info(f"Executing skill: {skill_name}.{method_name}")
        return await skill_service.execute_skill_by_name(
            skill_name, method_name, args, kwargs
        )
    
    hub_client.set_skill_callback(skill_callback)
    
    # Connect WebSocket
    await hub_client.connect_websocket()
    logger.info("WebSocket connected - ready to receive skill requests")
    
    # Keep running
    try:
        print("\\nSpoke is running. Press Ctrl+C to stop.")
        print("Other devices can now call skills on this device via the Hub.\\n")
        
        # Wait indefinitely
        while True:
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    
    finally:
        # Cleanup
        await skill_service.shutdown()
        await hub_client.close()
        logger.info("Shutdown complete")
    
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
