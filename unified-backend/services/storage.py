"""
SQLite Storage Service for Scans and Selections
Container-friendly implementation with proper path handling
"""
import sqlite3
import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class StorageService:
    """SQLite-based storage service for scans and selections"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize storage service
        
        Args:
            db_path: Path to SQLite database file. If None, uses default:
                     - Container: /app/data/scans.db
                     - Local: ./data/scans.db
        """
        if db_path is None:
            # Default path: use /app/data in container, ./data locally
            # Check if we're in a container by looking for /app directory
            if os.path.exists('/app') and os.path.isdir('/app'):
                # In container, use /app/data
                data_dir = '/app/data'
            else:
                # Local development, use relative path from unified-backend directory
                # Get the unified-backend directory (parent of services/)
                backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                data_dir = os.path.join(backend_dir, 'data')
            
            db_path = os.path.join(data_dir, 'scans.db')
        
        self.db_path = db_path
        self.data_dir = os.path.dirname(db_path)
        
        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        logger.info(f"Storage service initialized: {self.db_path}")
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self):
        """Initialize database schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create scans table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY,
                    selection_id TEXT,
                    status TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    timestamp TEXT,
                    mode TEXT,
                    cluster_name TEXT,
                    node_name TEXT,
                    progress INTEGER DEFAULT 0,
                    config TEXT,
                    timing TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Add timing column if it doesn't exist (for existing databases)
            try:
                cursor.execute('ALTER TABLE scans ADD COLUMN timing TEXT')
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Create scan_results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT,
                    status TEXT,
                    score INTEGER,
                    details TEXT,
                    remediation TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
                )
            ''')
            
            # Create selections table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS selections (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    selected_items TEXT,
                    timestamp TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create audit_events table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,              -- e.g. scan, remediation, manual
                    check_id TEXT,
                    node_name TEXT,
                    cluster_name TEXT,
                    action TEXT,                     -- short description
                    command TEXT,                    -- full command or playbook
                    source TEXT,                     -- ansible, kube_check, backend
                    status TEXT,                     -- SUCCESS, FAILED
                    user TEXT,
                    timestamp TEXT,
                    details_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scans_timestamp 
                ON scans(timestamp DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scans_nodeName 
                ON scans(node_name)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scans_status 
                ON scans(status)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id 
                ON scan_results(scan_id)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp 
                ON audit_events(timestamp DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_audit_events_type 
                ON audit_events(type)
            ''')
            
            conn.commit()
            logger.info("Database schema initialized")
    
    # ==================== Scans ====================
    
    def create_scan(self, scan_data: Dict[str, Any]) -> str:
        """Create a new scan"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scans (
                    id, selection_id, status, start_time, timestamp,
                    mode, cluster_name, node_name, progress, config
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                scan_data['id'],
                scan_data.get('selectionId'),
                scan_data.get('status', 'running'),
                scan_data.get('startTime'),
                scan_data.get('timestamp'),
                scan_data.get('mode'),
                scan_data.get('clusterName'),
                scan_data.get('nodeName'),
                scan_data.get('progress', 0),
                json.dumps(scan_data.get('config', {}))
            ))
            return scan_data['id']
    
    def update_scan(self, scan_id: str, updates: Dict[str, Any]):
        """Update an existing scan"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Build update query dynamically
            fields = []
            values = []
            
            if 'status' in updates:
                fields.append('status = ?')
                values.append(updates['status'])
            
            if 'endTime' in updates:
                fields.append('end_time = ?')
                values.append(updates['endTime'])
            
            if 'timestamp' in updates:
                fields.append('timestamp = ?')
                values.append(updates['timestamp'])
            
            if 'progress' in updates:
                fields.append('progress = ?')
                values.append(updates['progress'])
            
            if 'results' in updates:
                # Delete old results and insert new ones
                cursor.execute('DELETE FROM scan_results WHERE scan_id = ?', (scan_id,))
                self._insert_scan_results(conn, scan_id, updates['results'])
            
            if 'timing' in updates:
                fields.append('timing = ?')
                values.append(json.dumps(updates['timing']) if isinstance(updates['timing'], dict) else updates['timing'])
            
            if fields:
                values.append(scan_id)
                query = f"UPDATE scans SET {', '.join(fields)} WHERE id = ?"
                cursor.execute(query, values)
                conn.commit()
    
    def _insert_scan_results(self, conn, scan_id: str, results: List[Dict[str, Any]]):
        """Insert scan results"""
        cursor = conn.cursor()
        for result in results:
            cursor.execute('''
                INSERT INTO scan_results (
                    scan_id, item_id, title, status, score, details, remediation, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                scan_id,
                result.get('itemId') or result.get('id'),
                result.get('title'),
                result.get('status'),
                result.get('score', 0),
                result.get('details'),
                result.get('remediation'),
                result.get('timestamp')
            ))
    
    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """Get a scan by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM scans WHERE id = ?', (scan_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            scan = dict(row)
            
            # Get results
            cursor.execute('SELECT * FROM scan_results WHERE scan_id = ?', (scan_id,))
            results = [dict(r) for r in cursor.fetchall()]
            
            # Convert to API format
            return self._scan_to_dict(scan, results)
    
    def get_all_scans(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all scans, optionally limited"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM scans ORDER BY timestamp DESC'
            if limit:
                query += f' LIMIT {limit}'
            
            cursor.execute(query)
            scans = []
            
            for row in cursor.fetchall():
                scan = dict(row)
                scan_id = scan['id']
                
                # Get results for this scan
                cursor.execute('SELECT * FROM scan_results WHERE scan_id = ?', (scan_id,))
                results = [dict(r) for r in cursor.fetchall()]
                
                scans.append(self._scan_to_dict(scan, results))
            
            return scans
    
    def _scan_to_dict(self, scan: Dict, results: List[Dict]) -> Dict[str, Any]:
        """Convert database row to API format"""
        timing = None
        if scan.get('timing'):
            try:
                timing = json.loads(scan['timing']) if isinstance(scan['timing'], str) else scan['timing']
            except (json.JSONDecodeError, TypeError):
                timing = None
        
        return {
            'id': scan['id'],
            'selectionId': scan.get('selection_id'),
            'status': scan['status'],
            'startTime': scan.get('start_time'),
            'endTime': scan.get('end_time'),
            'timestamp': scan.get('timestamp') or scan.get('start_time'),
            'mode': scan.get('mode'),
            'clusterName': scan.get('cluster_name'),
            'nodeName': scan.get('node_name'),
            'progress': scan.get('progress', 0),
            'config': json.loads(scan.get('config', '{}')) if scan.get('config') else {},
            'results': [self._result_to_dict(r) for r in results],
            'timing': timing
        }
    
    def _result_to_dict(self, result: Dict) -> Dict[str, Any]:
        """Convert result row to API format"""
        return {
            'itemId': result.get('item_id'),
            'id': result.get('item_id'),  # For compatibility
            'title': result.get('title'),
            'status': result.get('status'),
            'score': result.get('score', 0),
            'details': result.get('details'),
            'remediation': result.get('remediation'),
            'timestamp': result.get('timestamp')
        }
    
    # ==================== Selections ====================
    
    def create_selection(self, selection_data: Dict[str, Any]) -> str:
        """Create a new selection"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO selections (id, name, description, selected_items, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                selection_data['id'],
                selection_data.get('name'),
                selection_data.get('description'),
                json.dumps(selection_data.get('selectedItems', [])),
                selection_data.get('timestamp')
            ))
            return selection_data['id']
    
    def get_selection(self, selection_id: str) -> Optional[Dict[str, Any]]:
        """Get a selection by ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM selections WHERE id = ?', (selection_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            selection = dict(row)
            return {
                'id': selection['id'],
                'name': selection.get('name'),
                'description': selection.get('description'),
                'selectedItems': json.loads(selection.get('selected_items', '[]')),
                'timestamp': selection.get('timestamp')
            }
    
    def get_all_selections(self) -> List[Dict[str, Any]]:
        """Get all selections"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM selections ORDER BY created_at DESC')
            selections = []
            
            for row in cursor.fetchall():
                selection = dict(row)
                selections.append({
                    'id': selection['id'],
                    'name': selection.get('name'),
                    'description': selection.get('description'),
                    'selectedItems': json.loads(selection.get('selected_items', '[]')),
                    'timestamp': selection.get('timestamp')
                })
            
            return selections
    
    def delete_selection(self, selection_id: str) -> bool:
        """Delete a selection"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM selections WHERE id = ?', (selection_id,))
            return cursor.rowcount > 0

    # ==================== Audit Events ====================

    def log_audit_event(self, event: Dict[str, Any]) -> str:
        """Insert an audit event"""
        from uuid import uuid4
        event_id = event.get('id') or str(uuid4())
        now_utc = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO audit_events (
                    id, type, check_id, node_name, cluster_name, action,
                    command, source, status, user, timestamp, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_id,
                event.get('type', 'remediation'),
                event.get('check_id'),
                event.get('node_name'),
                event.get('cluster_name'),
                event.get('action'),
                event.get('command'),
                event.get('source', 'backend'),
                event.get('status'),
                event.get('user'),
                event.get('timestamp', now_utc),
                json.dumps(event.get('details', {}))
            ))

        return event_id

    def get_audit_events(self, limit: int = 50, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch recent audit events"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if event_type:
                cursor.execute(
                    'SELECT * FROM audit_events WHERE type = ? ORDER BY timestamp DESC LIMIT ?',
                    (event_type, limit)
                )
            else:
                cursor.execute(
                    'SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?',
                    (limit,)
                )

            rows = cursor.fetchall()
            events: List[Dict[str, Any]] = []
            for row in rows:
                r = dict(row)
                # Parse details_json back to dict
                details = {}
                if r.get('details_json'):
                    try:
                        details = json.loads(r['details_json'])
                    except Exception:
                        details = {"raw": r['details_json']}

                events.append({
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "checkId": r.get("check_id"),
                    "nodeName": r.get("node_name"),
                    "clusterName": r.get("cluster_name"),
                    "action": r.get("action"),
                    "command": r.get("command"),
                    "source": r.get("source"),
                    "status": r.get("status"),
                    "user": r.get("user"),
                    "timestamp": r.get("timestamp"),
                    "details": details,
                })

            return events

