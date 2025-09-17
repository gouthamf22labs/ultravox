import os
from typing import List, Dict, Optional, Any
from supabase import create_client, Client
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class SupabaseClient:
    """Handles Supabase database operations for call management."""

    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")

        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

        self.client: Client = create_client(self.url, self.key)
        self.calls_table = "calls"

    def insert_call(self, call_data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new call record into the database."""
        try:
            result = self.client.table(self.calls_table).insert(call_data).execute()
            logger.info(f"Call inserted successfully: {call_data.get('call_id')}")
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Error inserting call: {str(e)}")
            raise

    def get_all_calls(self) -> List[Dict[str, Any]]:
        """Retrieve all call records from the database."""
        try:
            result = self.client.table(self.calls_table).select("*").order("created_at", desc=True).execute()
            return result.data
        except Exception as e:
            logger.error(f"Error retrieving calls: {str(e)}")
            return []

    def update_call(self, call_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing call record."""
        try:
            result = self.client.table(self.calls_table).update(update_data).eq("call_id", call_id).execute()
            logger.info(f"Call updated successfully: {call_id}")
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Error updating call {call_id}: {str(e)}")
            raise

    def get_call_by_id(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific call by call_id."""
        try:
            result = self.client.table(self.calls_table).select("*").eq("call_id", call_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error retrieving call {call_id}: {str(e)}")
            return None

    def delete_call(self, call_id: str) -> bool:
        """Delete a call record by call_id."""
        try:
            self.client.table(self.calls_table).delete().eq("call_id", call_id).execute()
            logger.info(f"Call deleted successfully: {call_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting call {call_id}: {str(e)}")
            return False