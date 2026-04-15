"""
Human-in-the-Loop Approval Queue
Security layer for dangerous operations
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

class ApprovalQueue:
    """Queue system for human approval of agent actions"""
    
    def __init__(self, queue_file: str = "soveryn_memory/approval_queue.json"):
        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(exist_ok=True)
        self._init_queue()
    
    def _init_queue(self):
        """Initialize queue file"""
        if not self.queue_file.exists():
            self._save_queue([])
    
    def _load_queue(self) -> List[Dict]:
        """Load queue from disk"""
        try:
            with open(self.queue_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _save_queue(self, queue: List[Dict]):
        """Save queue to disk"""
        with open(self.queue_file, 'w') as f:
            json.dump(queue, f, indent=2)
    
    def add_request(
        self,
        agent: str,
        tool: str,
        command: str,
        reason: str
    ) -> str:
        """Add approval request to queue"""
        request_id = str(uuid.uuid4())[:8]
        
        request = {
            'request_id': request_id,
            'agent': agent,
            'tool': tool,
            'command': command,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }
        
        queue = self._load_queue()
        queue.append(request)
        self._save_queue(queue)
        
        print(f"🔐 APPROVAL REQUIRED: Request {request_id} from {agent}")
        print(f"   Tool: {tool}")
        print(f"   Command: {command}")
        print(f"   Reason: {reason}")
        
        return request_id
    
    def get_pending(self) -> List[Dict]:
        """Get all pending approval requests"""
        queue = self._load_queue()
        return [r for r in queue if r['status'] == 'pending']
    
    def approve(self, request_id: str) -> bool:
        """Approve a request"""
        queue = self._load_queue()
        for request in queue:
            if request['request_id'] == request_id:
                request['status'] = 'approved'
                request['approved_at'] = datetime.now().isoformat()
                self._save_queue(queue)
                print(f"✅ Request {request_id} APPROVED")
                return True
        return False
    
    def reject(self, request_id: str, reason: str = "") -> bool:
        """Reject a request"""
        queue = self._load_queue()
        for request in queue:
            if request['request_id'] == request_id:
                request['status'] = 'rejected'
                request['rejected_at'] = datetime.now().isoformat()
                request['rejection_reason'] = reason
                self._save_queue(queue)
                print(f"❌ Request {request_id} REJECTED: {reason}")
                return True
        return False
    
    def get_status(self, request_id: str) -> Optional[str]:
        """Get status of a request"""
        queue = self._load_queue()
        for request in queue:
            if request['request_id'] == request_id:
                return request['status']
        return None

# Global approval queue
approval_queue = ApprovalQueue()