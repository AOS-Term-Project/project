import grpc
import threading
import random
import time
import sys
import os
import uuid
from concurrent import futures

# Adds the project's root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import all generated stubs
import raft_pb2
import raft_pb2_grpc
import booking_pb2
import booking_pb2_grpc
import llm_pb2
import llm_pb2_grpc

from raft_log import PersistentLog

# --- Initial State ---
# This is the "genesis" state for the whole cluster.
# On first boot, the leader will apply this to its state machine.
def get_initial_state():
    return {
        "users": {
            "user1": "pass123",
            "user2": "mango07",
            "user3": "dot987"},
        "tokens": {}, # All tokens are ephemeral
        "movies": {
            "1": {
                "title": "Shawshank Redemption",
                "showtimes": {
                    "10:00AM": { "seats": { "A1": True, "A2": True, "B1": True, "B2": True } },
                    "1:00PM":  { "seats": { "C1": True, "C2": True } }
                }
            },
            "2": {
                "title": "Star Wars: A New Hope",
                "showtimes": {
                    "11:30AM": { "seats": { "A1": True, "A2": True, "A3": True, "A4": True, "B1": True } },
                    "4:00PM":  { "seats": { "D1": True, "D2": True, "D3": True } }
                }
            },
            "3": {
                "title": "Mission: Impossible - Fallout",
                "showtimes": {
                    "2:30PM": { "seats": { "E1": True, "E2": True } },
                    "7:30PM": { "seats": { "F1": True, "F2": True } }
                }
            },
            "4": {
                "title": "The Dark Knight",
                "showtimes": {
                    "9:00PM": { "seats": { "G1": True, "G2": True, "G3": True } }
                }
            },
            "5": {
                "title": "The Godfather",
                "showtimes": {
                    "5:00PM": { "seats": { "B3": True, "B4": True, "B5": True}},
                    "8:30PM": { "seats": { "F5": True, "F6": True, "F7": True}}
                }
            }
        }
    }


# Define node states
class State:
    FOLLOWER = 0
    CANDIDATE = 1
    LEADER = 2

class UnifiedServer(raft_pb2_grpc.RaftServicer, booking_pb2_grpc.BookingServiceServicer):
    """
    This class is both the Raft Node and the Booking Application Server.
    It inherits from both gRPC servicers.
    """

    def __init__(self, node_id, port, peer_addresses):
        # --- Node's Identity & Network ---
        self.node_id = node_id
        self.address = f"localhost:{port}"
        self.peer_addresses = peer_addresses
        self.majority = (len(self.peer_addresses) + 1) // 2 + 1
        
        # --- Concurrency ---
        self.lock = threading.Lock()
        self.votes_received = 0
        self.commit_cv = threading.Condition(self.lock)
        self.pending_commands = {} # To notify RPCs when their command is applied

        # --- Raft's Persistent State ---
        self.log_handler = PersistentLog(self.node_id)
        self.current_term = self.log_handler.current_term
        self.voted_for = self.log_handler.voted_for
        self.log = self.log_handler.log

        # --- Raft's Volatile State ---
        self.state = State.FOLLOWER
        self.leader_id = -1
        self.leader_hint = ""
        self.commit_index = 0
        self.last_applied = 0
        
        # --- Leader's Volatile State ---
        self.next_index = {}
        self.match_index = {}

        # --- Application State ---
        self.state_machine = {} # This is our "database"
        
        # --- Timers ---
        self.election_timer = None
        self.heartbeat_timer = None
        self._reset_election_timer()

        # --- Start the state machine apply loop ---
        self.apply_thread = threading.Thread(target=self._apply_loop, daemon=True)
        self.apply_thread.start()

        # --- LLM Client (for ProcessBusinessRequest) ---
        self.llm_channel = grpc.insecure_channel('localhost:50052')
        self.llm_stub = llm_pb2_grpc.LLMServiceStub(self.llm_channel)

        print(f"[Node {self.node_id}]: Initialized as FOLLOWER in term {self.current_term}.")
        print(f"[Node {self.node_id}]: Peers: {self.peer_addresses}, Majority needed: {self.majority}")

    # --- Application State Machine Logic ---

    def _apply_loop(self):
        """
        Runs in a background thread, applying committed log entries
        to the state machine.
        """
        # On startup, apply all already-committed logs
        with self.lock:
            if not self.log:
                # This is a brand new node, initialize with genesis state
                self.state_machine = get_initial_state()
                print(f"[Node {self.node_id} SM]: Initialized with GENESIS state.")
            else:
                # This node is recovering, replay the log to rebuild state
                print(f"[Node {self.node_id} SM]: Replaying log to rebuild state...")
                for entry in self.log:
                    self._apply_command(entry.command)
                self.last_applied = len(self.log)
                self.commit_index = len(self.log)
                print(f"[Node {self.node_id} SM]: State rebuilt. Last applied index: {self.last_applied}")

        # Now, enter the main apply loop
        while True:
            with self.lock:
                while self.commit_index <= self.last_applied:
                    self.commit_cv.wait()
                
                start_index = self.last_applied + 1
                end_index = self.commit_index
                entries_to_apply = self.log[start_index - 1 : end_index]
            
            for i, entry in enumerate(entries_to_apply):
                cmd_index = start_index + i
                self._apply_command(entry.command)
                
                with self.lock:
                    self.last_applied = cmd_index
                    # Check if any RPC is waiting on this commit
                    if cmd_index in self.pending_commands:
                        self.pending_commands[cmd_index].notify_all()
                        del self.pending_commands[cmd_index]

    def _apply_command(self, command):
        """
        The "engine" of our state machine.
        This deterministically applies a command string to the state.
        """
        # print(f"[Node {self.node_id} SM]: Applying command '{command}'")
        try:
            parts = command.split()
            cmd_type = parts[0]
            
            if cmd_type == "REGISTER" and len(parts) == 3:
                user, pw = parts[1], parts[2]
                self.state_machine["users"][user] = pw
                
            elif cmd_type == "LOGIN" and len(parts) == 3:
                token, user = parts[1], parts[2]
                self.state_machine["tokens"][token] = user
                
            elif cmd_type == "LOGOUT" and len(parts) == 2:
                token = parts[1]
                if token in self.state_machine["tokens"]:
                    del self.state_machine["tokens"][token]
                    
            elif cmd_type == "BOOK" and len(parts) >= 5:
                movie_id, showtime, user = parts[1], parts[2], parts[3]
                seats_to_book = parts[4:]
                for seat in seats_to_book:
                    self.state_machine["movies"][movie_id]["showtimes"][showtime]["seats"][seat] = user
                print(f"[Node {self.node_id} SM]: Booked seats {seats_to_book} for {user}")

            else:
                print(f"[Node {self.node_id} SM]: Unknown command: {command}")
                
        except Exception as e:
            print(f"[Node {self.node_id} SM]: Error applying command '{command}': {e}")
            # In a real system, you'd need robust error handling
            # For this, we assume commands are pre-validated by the leader
            
    def _submit_command(self, command):
        """
        Internal function for leaders to submit a command to the Raft log
        and WAIT for it to be applied.
        Returns (index, term) or (None, None) on failure.
        """
        if self.state != State.LEADER:
            return (None, None)
            
        with self.lock:
            new_entry = raft_pb2.LogEntry(
                term=self.current_term,
                command=command
            )
            
            # Append to local log
            self.log_handler.append_entry(new_entry)
            
            new_log_index = self.log_handler.get_last_log_index()
            print(f"[Node {self.node_id} Leader]: Submitted command to log at index {new_log_index}")
            
            # Create a condition variable for this specific command
            commit_event = threading.Condition(self.lock)
            self.pending_commands[new_log_index] = commit_event
            
            # Wake up heartbeat threads to replicate
            self.heartbeat_timer.cancel()
            self._send_heartbeats()
            
            # Wait for this command to be applied
            if not commit_event.wait(timeout=5.0): # 5 second timeout
                print(f"[Node {self.node_id} Leader]: Timeout waiting for commit {new_log_index}")
                del self.pending_commands[new_log_index]
                return (None, None)

            # It's committed!
            return (new_log_index, self.current_term)
        
    def _gather_context_for_llm(self, user_id, query):
        """
        Scans the state machine to build a context string
        for the LLM based on the user's query.
        """
        context = ""
        try:
            # Check for booking-related keywords
            if "booking" in query.lower() or "my seat" in query.lower() or "ticket" in query.lower():
                my_bookings = []
                for movie_id, movie_data in self.state_machine["movies"].items():
                    movie_title = movie_data["title"]
                    for showtime, showtime_data in movie_data["showtimes"].items():
                        for seat_id, seat_value in showtime_data["seats"].items():
                            #booked_by_user = showtime_data["seats"].get(seat_id)
                            if seat_value == user_id:
                                my_bookings.append(f"{seat_id} for '{movie_title}' at {showtime}")
                
                if my_bookings:
                    context = f"The user '{user_id}' has the following bookings: {', '.join(my_bookings)}."
                else:
                    context = f"The user '{user_id}' has no bookings."

            # Check for availability keywords
            elif "available" in query.lower() or "showtime" in query.lower():
                available_seats = []
                # Just find the first 5 available seats as an example
                for movie_id, movie_data in self.state_machine["movies"].items():
                    for showtime, showtime_data in movie_data["showtimes"].items():
                        for seat_id, seat_value in showtime_data["seats"].items():
                            if seat_value == True:
                                available_seats.append(f"{seat_id} for '{movie_data['title']}' at {showtime}")
                                if len(available_seats) >= 5:
                                    break
                        if len(available_seats) >= 5:
                            break
                    if len(available_seats) >= 5:
                        break
                if available_seats:
                    context = f"Some available seats are: {', '.join(available_seats)}."
        
        except Exception as e:
            print(f"[Node {self.node_id} ERROR]: Failed to gather context: {e}")
            context = "Error retrieving state."

        return context

    # --- BookingService gRPC Implementation ---

    def Login(self, request, context):
        with self.lock:
            if self.state != State.LEADER:
                return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.NOT_LEADER, leader_hint=self.leader_hint)

            # 1. Validate credentials against the state machine
            user = request.username
            if self.state_machine["users"].get(user) != request.password:
                return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.INVALID_CREDENTIALS)
            
            # 2. Create token and command
            token = str(uuid.uuid4())
            command = f"LOGIN {token} {user}"
            
        # 3. Submit command to Raft (outside the lock, as it waits)
        index, term = self._submit_command(command)
        
        if index is not None:
            return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.SUCCESS, token=token, leader_hint=self.address)
        else:
            return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.NOT_LEADER) # Or some other error

    def Logout(self, request, context):
        with self.lock:
            if self.state != State.LEADER:
                return booking_pb2.LogoutResponse(status=booking_pb2.LogoutResponse.Status.NOT_LEADER)
            
            # 1. Validate token
            if request.token not in self.state_machine["tokens"]:
                return booking_pb2.LogoutResponse(status=booking_pb2.LogoutResponse.Status.INVALID_TOKEN)
            
            command = f"LOGOUT {request.token}"
            
        # 2. Submit command (this is a 'fire and forget' in this case)
        self._submit_command(command)
        
        return booking_pb2.LogoutResponse(status=booking_pb2.LogoutResponse.Status.SUCCESS)

    def GetAvailability(self, request, context):
        with self.lock:
            if self.state != State.LEADER:
                return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.NOT_LEADER, leader_hint=self.leader_hint)

            # 1. Check Auth
            if request.token not in self.state_machine["tokens"]:
                return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.UNAUTHORIZED)
            
            # 2. Read from state machine
            movie_data = self.state_machine["movies"].get(request.movie_id)
            if not movie_data:
                return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SHOWTIME_NOT_FOUND)
            
            showtime_data = movie_data["showtimes"].get(request.showtime)
            if not showtime_data:
                return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SHOWTIME_NOT_FOUND)

            seats_list = []
            for seat_id, is_avail in showtime_data["seats"].items():
                is_seat_available = (is_avail == True)
                seats_list.append(
                    booking_pb2.Seat(seat_id=seat_id, is_available=is_seat_available)
                )

            return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SUCCESS, seats=seats_list, leader_hint=self.address)

    def BookSeat(self, request, context):
        with self.lock:
            if self.state != State.LEADER:
                return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.NOT_LEADER, leader_hint=self.leader_hint)
            
            # 1. Check Auth
            user = self.state_machine["tokens"].get(request.token)
            if not user:
                return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.UNAUTHORIZED)

            # 2. Check availability (Business Logic)
            movie_data = self.state_machine["movies"].get(request.movie_id)
            if not movie_data:
                return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)
            
            showtime_data = movie_data["showtimes"].get(request.showtime)
            if not showtime_data:
                return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)

            for seat_id in request.seat_ids:
                if not showtime_data["seats"].get(seat_id): # .get(seat_id) is False or None
                    return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)

            # 3. Create command
            seats_str = " ".join(request.seat_ids)
            command = f"BOOK {request.movie_id} {request.showtime} {user} {seats_str}"
            
        # 4. Submit command to Raft and wait
        index, term = self._submit_command(command)
        
        if index is not None:
            booking_id = f"{term}-{index}" # A unique, deterministic booking ID
            return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SUCCESS, booking_id=booking_id, leader_hint=self.address)
        else:
            return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.NOT_LEADER)
        
    def AskChatbot(self, request, context):
        with self.lock:
            if self.state != State.LEADER:
                return booking_pb2.ChatbotResponse(
                    status=booking_pb2.ChatbotResponse.Status.NOT_LEADER, 
                    leader_hint=self.leader_hint
                )
            
            # 1. Authenticate user
            user_id = self.state_machine["tokens"].get(request.token)
            if not user_id:
                return booking_pb2.ChatbotResponse(
                    status=booking_pb2.ChatbotResponse.Status.UNAUTHORIZED
                )
            
            print(f"[Node {self.node_id}]: Gathering context for query: '{request.payload}'")
            
            # 2. Gather context (The new helper function)
            # This logic must be inside the lock to safely read self.state_machine
            context_string = self._gather_context_for_llm(user_id, request.payload)

        # 3. Call LLM Server (outside the lock)
        try:
            llm_request = llm_pb2.GetLLMAnswerRequest(
                query=request.payload, 
                context=context_string
            )
            llm_response = self.llm_stub.GetLLMAnswer(llm_request)
            
            return booking_pb2.ChatbotResponse(
                status=booking_pb2.ChatbotResponse.Status.SUCCESS, 
                answer=llm_response.answer
            )
        except grpc.RpcError as e:
            print(f"[Node {self.node_id} ERROR]: LLM Server call failed: {e}")
            return booking_pb2.ChatbotResponse(
                status=booking_pb2.ChatbotResponse.Status.UNAUTHORIZED, # Re-using status,
                answer="Sorry, the chatbot service is currently unavailable."
            )

    # --- Raft gRPC Implementation ---
    # (These are identical to our previous raft_server.py)
    # ... (RequestVote, AppendEntries, _become_follower, _start_election, etc.) ...
    # (Pasting them all below for completeness)

    def RequestVote(self, request, context):
        with self.lock:
            vote_granted = False
            
            if request.term < self.current_term:
                return raft_pb2.VoteReply(term=self.current_term, vote_granted=False)
            
            if request.term > self.current_term:
                self.log_handler.update_term(request.term)
                self.current_term = request.term
                self._become_follower(request.term)

            log_ok = (request.last_log_term >= self.log_handler.get_last_log_term() and 
                      request.last_log_index >= self.log_handler.get_last_log_index())
            
            if (self.voted_for is None or self.voted_for == request.candidate_id) and log_ok:
                vote_granted = True
                self.log_handler.update_term_and_vote(self.current_term, request.candidate_id)
                self.voted_for = request.candidate_id
                self._reset_election_timer()
            
            return raft_pb2.VoteReply(term=self.current_term, vote_granted=vote_granted)

    def AppendEntries(self, request, context):
        with self.lock:
            if request.term < self.current_term:
                return raft_pb2.AppendEntriesReply(term=self.current_term, success=False)

            if request.term > self.current_term:
                self.log_handler.update_term(request.term)
                self.current_term = request.term
                self._become_follower(request.term)
            
            if self.state == State.CANDIDATE:
                self._become_follower(request.term)

            self.leader_id = request.leader_id
            self.leader_hint = f"localhost:{request.leader_id}" # Assuming port == node_id
            self._reset_election_timer()
            
            if request.prev_log_index > 0:
                prev_log_term = self.log_handler.get_term(request.prev_log_index)
                if prev_log_term != request.prev_log_term:
                    return raft_pb2.AppendEntriesReply(term=self.current_term, success=False)
            
            new_entries_start_index = 0
            for i, entry in enumerate(request.entries):
                entry_index = request.prev_log_index + 1 + i
                if entry_index > self.log_handler.get_last_log_index():
                    new_entries_start_index = i
                    break
                if self.log_handler.get_term(entry_index) != entry.term:
                    self.log_handler.truncate_log(entry_index)
                    new_entries_start_index = i
                    break
            else:
                new_entries_start_index = len(request.entries)
                
            if new_entries_start_index < len(request.entries):
                for entry_to_add in request.entries[new_entries_start_index:]:
                    self.log_handler.append_entry(entry_to_add)
            
            if request.leader_commit > self.commit_index:
                self.commit_index = min(request.leader_commit, self.log_handler.get_last_log_index())
                self.commit_cv.notify()
            
            return raft_pb2.AppendEntriesReply(term=self.current_term, success=True)
    
    # --- Raft State Machine & Logic ---
    
    def _get_election_timeout(self):
        return random.uniform(5.0, 10.0)

    def _reset_election_timer(self):
        if self.election_timer:
            self.election_timer.cancel()
        self.election_timer = threading.Timer(self._get_election_timeout(), self._start_election)
        self.election_timer.start()

    def _become_follower(self, term):
        print(f"[Node {self.node_id}]: Becoming FOLLOWER for term {term}.")
        self.state = State.FOLLOWER
        self.current_term = self.log_handler.current_term
        self.voted_for = self.log_handler.voted_for
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = None
        self._reset_election_timer()

    def _start_election(self):
        with self.lock:
            if self.state == State.LEADER:
                return
            self.state = State.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            self.log_handler.update_term_and_vote(self.current_term, self.node_id)
            self.votes_received = 1
            print(f"[Node {self.node_id}]: Becoming CANDIDATE for term {self.current_term}.")
            self._reset_election_timer()
        
        for peer_addr in self.peer_addresses:
            threading.Thread(target=self._send_request_vote_rpc, args=(peer_addr, self.current_term)).start()

    def _send_request_vote_rpc(self, peer_address, election_term):
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = raft_pb2_grpc.RaftStub(channel)
                request = raft_pb2.VoteRequest(
                    term=election_term,
                    candidate_id=self.node_id,
                    last_log_index=self.log_handler.get_last_log_index(),
                    last_log_term=self.log_handler.get_last_log_term()
                )
                response = stub.RequestVote(request, timeout=1.0)
                self._process_vote_reply(response, election_term)
        except grpc.RpcError:
            pass # Peer is down

    def _process_vote_reply(self, response, election_term):
        with self.lock:
            if response.term > self.current_term:
                self.log_handler.update_term(response.term)
                self.current_term = response.term
                self._become_follower(response.term)
                return
            if self.state != State.CANDIDATE or self.current_term != election_term:
                return
            if response.vote_granted:
                self.votes_received += 1
                if self.votes_received >= self.majority:
                    self._become_leader()

    def _become_leader(self):
        if self.state != State.CANDIDATE:
            return
        print(f"[Node {self.node_id}]: **** BECOMING LEADER FOR TERM {self.current_term} ****")
        self.state = State.LEADER
        self.leader_id = self.node_id
        self.leader_hint = self.address
        
        last_log_idx = self.log_handler.get_last_log_index()
        self.next_index = {peer: last_log_idx + 1 for peer in self.peer_addresses}
        self.match_index = {peer: 0 for peer in self.peer_addresses}
        
        if self.election_timer:
            self.election_timer.cancel()
        self._send_heartbeats()

    def _update_leader_commit_index(self):
        last_log_idx = self.log_handler.get_last_log_index()
        for N in range(self.commit_index + 1, last_log_idx + 1):
            if self.log_handler.get_term(N) != self.current_term:
                continue
            match_count = 1
            for peer in self.peer_addresses:
                if self.match_index[peer] >= N:
                    match_count += 1
            if match_count >= self.majority:
                if self.commit_index != N:
                    self.commit_index = N
                    self.commit_cv.notify()
            else:
                break

    def _send_heartbeats(self):
        if self.state != State.LEADER:
            return
        for peer_addr in self.peer_addresses:
            threading.Thread(target=self._send_append_entries_rpc, args=(peer_addr,)).start()
        
        self.heartbeat_timer = threading.Timer(2.0, self._send_heartbeats)
        self.heartbeat_timer.start()

    def _send_append_entries_rpc(self, peer_address):
        if self.state != State.LEADER:
            return
        with self.lock:
            next_idx = self.next_index[peer_address]
            prev_log_index = next_idx - 1
            prev_log_term = self.log_handler.get_term(prev_log_index)
            entries_to_send = self.log[next_idx - 1:]
            
            request = raft_pb2.AppendEntriesRequest(
                term=self.current_term,
                leader_id=self.node_id, # Use node_id, which we assume is the port
                prev_log_index=prev_log_index,
                prev_log_term=prev_log_term,
                entries=entries_to_send,
                leader_commit=self.commit_index
            )
        try:
            with grpc.insecure_channel(peer_address) as channel:
                stub = raft_pb2_grpc.RaftStub(channel)
                response = stub.AppendEntries(request, timeout=1.0)
                with self.lock:
                    if self.state != State.LEADER: return
                    if response.term > self.current_term:
                        self.log_handler.update_term(response.term)
                        self.current_term = response.term
                        self._become_follower(response.term)
                        return
                    if response.success:
                        new_next_index = prev_log_index + len(entries_to_send) + 1
                        self.next_index[peer_address] = new_next_index
                        self.match_index[peer_address] = new_next_index - 1
                        self._update_leader_commit_index()
                    else:
                        self.next_index[peer_address] = max(1, self.next_index[peer_address] - 1)
        except grpc.RpcError:
            pass

def serve(node_id, port, peer_addresses):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # Create our one, unified server class
    unified_servicer = UnifiedServer(node_id, port, peer_addresses)
    
    # Register BOTH servicers to the server
    raft_pb2_grpc.add_RaftServicer_to_server(unified_servicer, server)
    booking_pb2_grpc.add_BookingServiceServicer_to_server(unified_servicer, server)
    
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    print(f"--- Unified App+Raft Server (Node {node_id}) started on port {port} ---")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print(f"\nStopping Node {node_id}...")
        if unified_servicer.election_timer: unified_servicer.election_timer.cancel()
        if unified_servicer.heartbeat_timer: unified_servicer.heartbeat_timer.cancel()
        server.stop(0)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python unified_server.py <node_id> <port> [peer_address1] [peer_address2] ...")
        print("Example (Node 50051): python unified_server.py 50051 50051 localhost:50053 localhost:50054")
        sys.exit(1)
    
    node_id = int(sys.argv[1])
    port = int(sys.argv[2])
    peers = sys.argv[3:]
    
    serve(node_id, port, peers)