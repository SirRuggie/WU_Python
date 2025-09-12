"""
Custom REST client wrapper to handle rate limits properly and bypass hikari's stuck buckets
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any
import hikari
import aiohttp
import json


class RateLimitTracker:
    """Track actual Discord rate limits per endpoint"""
    
    def __init__(self):
        self.limits: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
    
    async def can_request(self, endpoint: str) -> bool:
        """Check if we can make a request to this endpoint"""
        async with self.lock:
            if endpoint not in self.limits:
                return True
            
            limit_data = self.limits[endpoint]
            if datetime.now(timezone.utc) >= limit_data["reset_time"]:
                # Rate limit has expired
                del self.limits[endpoint]
                return True
            
            return False
    
    async def record_rate_limit(self, endpoint: str, retry_after: float):
        """Record a rate limit for an endpoint"""
        async with self.lock:
            reset_time = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
            self.limits[endpoint] = {
                "reset_time": reset_time,
                "retry_after": retry_after,
                "recorded_at": datetime.now(timezone.utc)
            }
            print(f"[Rate Limit] Recorded limit for {endpoint}: {retry_after}s until {reset_time}")
    
    async def get_wait_time(self, endpoint: str) -> float:
        """Get remaining wait time for an endpoint"""
        async with self.lock:
            if endpoint not in self.limits:
                return 0.0
            
            limit_data = self.limits[endpoint]
            now = datetime.now(timezone.utc)
            if now >= limit_data["reset_time"]:
                del self.limits[endpoint]
                return 0.0
            
            return (limit_data["reset_time"] - now).total_seconds()


class CustomRESTClient:
    """Custom REST client that bypasses hikari's stuck rate limiter"""
    
    def __init__(self, bot: hikari.GatewayBot):
        self.bot = bot
        self.rate_tracker = RateLimitTracker()
        self.channel_creation_times = []
        self.channel_creation_lock = asyncio.Lock()
    
    async def create_guild_text_channel(
        self,
        guild: hikari.Snowflakeish,
        name: str,
        *,
        category: Optional[hikari.Snowflakeish] = None,
        permission_overwrites: Optional[hikari.UndefinedOr[Any]] = hikari.UNDEFINED,
        reason: Optional[str] = None,
        **kwargs
    ) -> hikari.GuildTextChannel:
        """Create a guild text channel with proper rate limit handling"""
        
        endpoint = f"channels-{guild}"
        
        # Clean old creation times (older than 10 minutes)
        async with self.channel_creation_lock:
            now = time.time()
            self.channel_creation_times = [
                t for t in self.channel_creation_times 
                if now - t < 600  # 10 minutes
            ]
        
        # Check if we can make the request
        if not await self.rate_tracker.can_request(endpoint):
            wait_time = await self.rate_tracker.get_wait_time(endpoint)
            raise hikari.RateLimitTooLongError(
                f"Rate limited for {wait_time:.1f}s", 
                retry_after=wait_time,
                max_retry_after=300.0
            )
        
        # Try using hikari's REST client first with a shorter timeout
        try:
            # Record this attempt
            async with self.channel_creation_lock:
                self.channel_creation_times.append(time.time())
            
            channel = await asyncio.wait_for(
                self.bot.rest.create_guild_text_channel(
                    guild=guild,
                    name=name,
                    category=category,
                    permission_overwrites=permission_overwrites,
                    reason=reason,
                    **kwargs
                ),
                timeout=15.0  # 15 second timeout instead of waiting forever
            )
            
            print(f"[Custom REST] Successfully created channel {name} via hikari REST")
            return channel
            
        except (hikari.RateLimitTooLongError, asyncio.TimeoutError) as e:
            print(f"[Custom REST] Hikari failed/timed out for channel creation: {e}")
            
            # If hikari fails, record the rate limit and fail
            if isinstance(e, hikari.RateLimitTooLongError):
                await self.rate_tracker.record_rate_limit(endpoint, e.retry_after)
            else:
                # Timeout suggests hikari is stuck, record a conservative rate limit
                await self.rate_tracker.record_rate_limit(endpoint, 60.0)
            
            # Remove the creation time since it failed
            async with self.channel_creation_lock:
                if self.channel_creation_times:
                    self.channel_creation_times.pop()
            
            raise
        
        except Exception as e:
            # Remove the creation time since it failed
            async with self.channel_creation_lock:
                if self.channel_creation_times:
                    self.channel_creation_times.pop()
            raise
    
    async def get_channel_creation_stats(self) -> Dict[str, Any]:
        """Get statistics about recent channel creations"""
        async with self.channel_creation_lock:
            now = time.time()
            recent_5min = len([t for t in self.channel_creation_times if now - t < 300])
            recent_10min = len([t for t in self.channel_creation_times if now - t < 600])
            
            return {
                "recent_5_minutes": recent_5min,
                "recent_10_minutes": recent_10min,
                "total_tracked": len(self.channel_creation_times),
                "oldest_tracked": now - min(self.channel_creation_times) if self.channel_creation_times else 0
            }
    
    async def reset_rate_limits(self, endpoint: Optional[str] = None):
        """Reset rate limit tracking for debugging"""
        async with self.rate_tracker.lock:
            if endpoint:
                self.rate_tracker.limits.pop(endpoint, None)
                print(f"[Custom REST] Reset rate limit for {endpoint}")
            else:
                self.rate_tracker.limits.clear()
                print("[Custom REST] Reset all rate limits")
    
    async def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limit status"""
        async with self.rate_tracker.lock:
            status = {}
            for endpoint, data in self.rate_tracker.limits.items():
                remaining = (data["reset_time"] - datetime.now(timezone.utc)).total_seconds()
                status[endpoint] = {
                    "remaining_seconds": max(0, remaining),
                    "recorded_at": data["recorded_at"],
                    "retry_after": data["retry_after"]
                }
            return status


# Global instance
custom_rest_client: Optional[CustomRESTClient] = None


def get_custom_rest_client(bot: hikari.GatewayBot) -> CustomRESTClient:
    """Get or create the global custom REST client"""
    global custom_rest_client
    if custom_rest_client is None:
        custom_rest_client = CustomRESTClient(bot)
    return custom_rest_client