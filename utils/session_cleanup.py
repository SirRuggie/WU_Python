# utils/session_cleanup.py

"""Cleanup task for expired image collection sessions"""

import asyncio
from datetime import datetime, timedelta


async def cleanup_expired_sessions():
    """Cleanup expired image collection sessions"""
    # Import here to avoid circular imports
    from extensions.commands.clan.report.dm_recruitment import (
        image_collection_sessions,
        dm_recruitment_data
    )

    while True:
        try:
            # Check every 30 seconds for expired sessions
            await asyncio.sleep(30)

            current_time = datetime.now()
            expired_sessions = []

            # Find sessions older than 2 minutes
            for session_key, session_data in image_collection_sessions.items():
                if current_time - session_data['timestamp'] > timedelta(minutes=2):
                    expired_sessions.append(session_key)

            # Remove expired sessions
            for session_key in expired_sessions:
                del image_collection_sessions[session_key]
                # Also clean up any related dm_recruitment_data
                if session_key in dm_recruitment_data:
                    del dm_recruitment_data[session_key]

            if expired_sessions:
                print(f"[Session Cleanup] Removed {len(expired_sessions)} expired sessions")

        except Exception as e:
            print(f"[Session Cleanup] Error: {e}")


def start_cleanup_task():
    """Start the cleanup task"""
    asyncio.create_task(cleanup_expired_sessions())
    # print("[Session Cleanup] Started session cleanup task")