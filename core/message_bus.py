"""
SOVERYN Message Bus
Enables async agent-to-agent communication
"""
import asyncio
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional
import threading
import uuid

class Message:
    """Single message between agents"""
    def __init__(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_id: str = None,
        timestamp: str = None
    ):
        self.message_id = message_id or str(uuid.uuid4())
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.content = content
        self.timestamp = timestamp or datetime.now().isoformat()
        self.status = "pending"
    
    def to_dict(self) -> dict:
        return {
            'message_id': self.message_id,
            'from_agent': self.from_agent,
            'to_agent': self.to_agent,
            'content': self.content,
            'timestamp': self.timestamp,
            'status': self.status
        }


class MessageBus:
    """Central message routing system for SOVERYN"""
    
    def __init__(self, db_path: str = "soveryn_memory/message_bus.db"):
        self.db_path = db_path
        self._init_database()
        self.queues: Dict[str, asyncio.Queue] = {}
        self.lock = threading.Lock()
    
    def _init_database(self):
        """Create message bus database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                response_to TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_to_agent 
            ON messages(to_agent, status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_from_agent 
            ON messages(from_agent)
        """)
        
        conn.commit()
        conn.close()
        print(f"[OK] Message Bus initialized: {self.db_path}")
    
    async def send_message(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        response_to: str = None
    ) -> Message:
        """Send message from one agent to another"""
        message = Message(from_agent, to_agent, content)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO messages 
            (message_id, from_agent, to_agent, content, timestamp, status, response_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            message.message_id,
            message.from_agent,
            message.to_agent,
            message.content,
            message.timestamp,
            message.status,
            response_to
        ))
        
        conn.commit()
        conn.close()
        
        print(f"📨 Message sent: {from_agent} → {to_agent}")
        return message
    
    def get_pending_messages(self, agent: str) -> List[Message]:
        """Get all pending messages for an agent"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT message_id, from_agent, to_agent, content, timestamp, status
            FROM messages
            WHERE to_agent = ? AND status = 'pending'
            ORDER BY timestamp ASC
        """, (agent,))
        
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in rows:
            msg = Message(
                from_agent=row[1],
                to_agent=row[2],
                content=row[3],
                message_id=row[0],
                timestamp=row[4]
            )
            msg.status = row[5]
            messages.append(msg)
        
        return messages
    
    def mark_delivered(self, message_id: str):
        """Mark message as delivered"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE messages
            SET status = 'delivered'
            WHERE message_id = ?
        """, (message_id,))
        
        conn.commit()
        conn.close()
    
    def get_conversation_history(
        self,
        agent1: str,
        agent2: str,
        limit: int = 50
    ) -> List[Message]:
        """Get conversation history between two agents"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT message_id, from_agent, to_agent, content, timestamp, status
            FROM messages
            WHERE (from_agent = ? AND to_agent = ?)
               OR (from_agent = ? AND to_agent = ?)
            ORDER BY timestamp DESC
            LIMIT ?
        """, (agent1, agent2, agent2, agent1, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in reversed(rows):
            msg = Message(
                from_agent=row[1],
                to_agent=row[2],
                content=row[3],
                message_id=row[0],
                timestamp=row[4]
            )
            msg.status = row[5]
            messages.append(msg)
        
        return messages


# Global message bus instance
message_bus = MessageBus()