# raft_log.py
import json
import os
import threading

# We need the LogEntry message definition
import raft_pb2

class PersistentLog:
    """
    Manages Raft's persistent state: current_term, voted_for, and the log.
    """
    def __init__(self, node_id):
        self.node_id = node_id
        # A lock to protect file access from concurrent threads
        self._lock = threading.Lock()
        
        # File paths for persistence
        self._metadata_file = f"node_{node_id}_metadata.json"
        self._log_file = f"node_{node_id}_log.jsonl" # JSON Lines format
        
        # In-memory caches
        self.current_term = 0
        self.voted_for = None
        self.log = [] # List of raft_pb2.LogEntry objects

        # Load persistent state from disk
        self._load_metadata()
        self._load_log()
        print(f"[Node {node_id} Log]: Loaded. Term={self.current_term}, VotedFor={self.voted_for}, LogSize={len(self.log)}")

    # --- Metadata (Term and VotedFor) Methods ---

    def _load_metadata(self):
        """Loads current_term and voted_for from the metadata file."""
        try:
            with open(self._metadata_file, 'r') as f:
                data = json.load(f)
                self.current_term = data.get('current_term', 0)
                self.voted_for = data.get('voted_for', None)
        except (IOError, json.JSONDecodeError):
            # File doesn't exist or is corrupt, start fresh
            self.current_term = 0
            self.voted_for = None
            self._save_metadata() # Create the file

    def _save_metadata(self):
        """Saves current_term and voted_for to the metadata file."""
        # This is NOT atomic. A real implementation MUST use fsync
        # and an atomic write pattern (e.g., write to temp, then rename).
        with open(self._metadata_file, 'w') as f:
            json.dump({
                'current_term': self.current_term,
                'voted_for': self.voted_for
            }, f, indent=2)

    def update_term_and_vote(self, term, voted_for):
        """
        Sets a new term and vote, and persists it.
        This MUST be done *before* responding to an RPC.
        """
        with self._lock:
            self.current_term = term
            self.voted_for = voted_for
            self._save_metadata()

    def update_term(self, term):
        """
        Sets a new term (and resets vote), and persists it.
        """
        with self._lock:
            self.current_term = term
            self.voted_for = None # New term means we haven't voted yet
            self._save_metadata()

    # --- Log (Entries) Methods ---

    def _load_log(self):
        """Loads log entries from the log file."""
        self.log = []
        try:
            with open(self._log_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    entry = raft_pb2.LogEntry(term=data['term'], command=data['command'])
                    self.log.append(entry)
        except (IOError, json.JSONDecodeError):
            # File doesn't exist or is empty
            pass 

    def append_entry(self, entry):
        """Appends a single log entry to the log and persists it."""
        with self._lock:
            self.log.append(entry)
            # Append to file (JSON Lines)
            # This is also not atomic.
            with open(self._log_file, 'a') as f:
                f.write(json.dumps({'term': entry.term, 'command': entry.command}) + '\n')
    
    def get_last_log_index(self):
        """Raft log index is 1-based."""
        return len(self.log)

    def get_last_log_term(self):
        """Returns the term of the last log entry, or 0 if log is empty."""
        if not self.log:
            return 0
        return self.log[-1].term
    
    # (Inside the PersistentLog class in raft_log.py)

    def get_entry(self, index):
        """
        Get log entry at a 1-based index.
        Returns None if index is out of bounds.
        """
        if 1 <= index <= len(self.log):
            return self.log[index - 1] # Convert 1-based to 0-based
        return None
        
    def get_term(self, index):
        """
        Get term of entry at a 1-based index.
        Returns 0 if index is 0 (snapshot) or out of bounds.
        """
        if index == 0:
            return 0 # Term 0 for "before the log"
        entry = self.get_entry(index)
        if entry:
            return entry.term
        return 0 # Out of bounds
        
    def truncate_log(self, from_index):
        """
        Truncates the log *from* a 1-based index.
        e.g., truncate_log(5) keeps entries 1-4 and deletes 5, 6, 7...
        """
        with self._lock:
            if 1 <= from_index <= len(self.log):
                print(f"[Node {self.node_id} Log]: Truncating log from index {from_index}")
                self.log = self.log[:from_index - 1] # 1-based to 0-based slice
                
                # Re-write the entire log file (very inefficient, but simple)
                with open(self._log_file, 'w') as f:
                    for entry in self.log:
                        f.write(json.dumps({'term': entry.term, 'command': entry.command}) + '\n')
            elif from_index == 1:
                # Special case: truncate the whole log
                self.log = []
                # Clear the file
                open(self._log_file, 'w').close()