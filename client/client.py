import grpc
import sys
import os
import time


# Adds the project's root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Generated gRPC code
import booking_pb2
import booking_pb2_grpc
import llm_pb2
import llm_pb2_grpc

# --- Configuration ---
# All the App+Raft server addresses
RAFT_APP_SERVERS = ['localhost:50051', 'localhost:50053', 'localhost:50054']
LLM_SERVER = 'localhost:50052'

class BookingClient:
    def __init__(self, server_addresses, llm_address):
        self.server_addresses = server_addresses
        self.llm_address = llm_address
        self.current_leader = server_addresses[0] # Start with a guess
        
        self.token = None
        self.username = None
        
        # Create a persistent gRPC channel for the LLM server
        self.llm_channel = grpc.insecure_channel(llm_address)
        self.llm_stub = llm_pb2_grpc.LLMServiceStub(self.llm_channel)

    def _get_stub(self, address):
        """Helper to create a stub to a booking server."""
        channel = grpc.insecure_channel(address)
        return booking_pb2_grpc.BookingServiceStub(channel), channel

    def _call_rpc(self, rpc_name, request):
        """
        Smart RPC caller. Tries the cached leader first, then
        retries on failure or NOT_LEADER.
        """
        # Try cached leader first, then others
        nodes_to_try = [self.current_leader] + [n for n in self.server_addresses if n != self.current_leader]
        
        for node_addr in nodes_to_try:
            try:
                stub, channel = self._get_stub(node_addr)
                # Use getattr to call the method by name (e.g., "Login")
                rpc_method = getattr(stub, rpc_name)
                response = rpc_method(request, timeout=2.0)
                
                # Check for NOT_LEADER status
                if hasattr(response, 'status') and (
                    response.status == booking_pb2.LoginResponse.Status.NOT_LEADER or
                    response.status == booking_pb2.LogoutResponse.Status.NOT_LEADER or
                    response.status == booking_pb2.GetAvailabilityResponse.Status.NOT_LEADER or
                    response.status == booking_pb2.BookSeatResponse.Status.NOT_LEADER
                ):
                    if hasattr(response, 'leader_hint') and response.leader_hint:
                        self.current_leader = response.leader_hint
                    print(f"Node {node_addr} is not leader. Trying next...")
                    continue # Try the next node
                
                # Success!
                self.current_leader = node_addr # Cache this leader
                channel.close()
                return response

            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.UNAVAILABLE or e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    print(f"Node {node_addr} is unavailable. Trying next...")
                else:
                    print(f"An error occurred: {e}")
                channel.close()
                continue
        
        # If all nodes failed
        return None

    def login(self):
        if self.token:
            print("You are already logged in.")
            return
            
        username = input("Enter username: ")
        password = input("Enter password: ")
        request = booking_pb2.LoginRequest(username=username, password=password)
        
        response = self._call_rpc("Login", request)
        
        if response and response.status == booking_pb2.LoginResponse.Status.SUCCESS:
            self.token = response.token
            self.username = username
            print(f"Login successful. Welcome, {username}!")
        elif response:
            print(f"Login failed: {booking_pb2.LoginResponse.Status.Name(response.status)}")
        else:
            print("Login failed: Cluster is unavailable.")

    def logout(self):
        if not self.token:
            print("You are not logged in.")
            return
        
        request = booking_pb2.LogoutRequest(token=self.token)
        response = self._call_rpc("Logout", request)
        
        if response and response.status == booking_pb2.LogoutResponse.Status.SUCCESS:
            self.token = None
            self.username = None
            print("Logout successful.")
        else:
            print("Logout failed.")
            
    def get_availability(self):
        if not self.token:
            print("Please log in first.")
            return

        movies_info = {
            "1": {"title": "Shawshank Redemption", "showtimes": ["10:00AM", "1:00PM"]},
            "2": {"title": "Star Wars: A New Hope", "showtimes": ["11:30AM", "4:00PM"]},
            "3": {"title": "Mission: Impossible - Fallout", "showtimes": ["2:30PM", "7:30PM"]},
        }
        print("\n--- Available Movies and Showtimes ---")
        for movie_id, data in movies_info.items():
            print(f" Movie ID: {movie_id}, Title: {data['title']}")
            print(f"   Showtimes: {', '.join(data['showtimes'])}")

        movie_id = input("\nEnter movie ID: ")
        showtime = input("Enter showtime: ")
        
        request = booking_pb2.GetAvailabilityRequest(token=self.token, movie_id=movie_id, showtime=showtime)
        response = self._call_rpc("GetAvailability", request)
        
        if response and response.status == booking_pb2.GetAvailabilityResponse.Status.SUCCESS:
            print(f"--- Seat Availability for {movies_info[movie_id]['title']} at {showtime} ---")
            for seat in response.seats:
                status = "Available" if seat.is_available else "Booked"
                print(f"  Seat {seat.seat_id}: {status}")
        elif response:
            print(f"Failed to get availability: {booking_pb2.GetAvailabilityResponse.Status.Name(response.status)}")
        else:
            print("Failed to get availability: Cluster is unavailable.")

    def book_seat(self):
        if not self.token:
            print("Please log in first.")
            return
        
        movie_id = input("Enter movie ID: ")
        showtime = input("Enter showtime: ")
        seat_ids_str = input("Enter seat IDs to book (comma-separated): ")
        seat_ids = [s.strip().upper() for s in seat_ids_str.split(',')]
        
        request = booking_pb2.BookSeatRequest(token=self.token, movie_id=movie_id, showtime=showtime, seat_ids=seat_ids)
        response = self._call_rpc("BookSeat", request)
        
        if response and response.status == booking_pb2.BookSeatResponse.Status.SUCCESS:
            print(f"✅ Booking successful! Booking ID: {response.booking_id}")
        elif response:
            print(f"❌ Booking failed: {booking_pb2.BookSeatResponse.Status.Name(response.status)}")
        else:
            print("❌ Booking failed: Cluster is unavailable.")

    def ask_chatbot(self):
        faq_questions = {
            "1": "What seats are available?",
            "2": "What payment methods are accepted?",
            "3": "What is the refund policy?",
            "4": "What are the timings of the movie?",
            "5": "How to cancel a booking?"
        }
        
        print("\n--- FAQ Chatbot ---")
        for key, question in faq_questions.items():
            print(f" {key}. {question}")
        print(" 6. Ask a custom question (e.g., 'Show my bookings')")
        
        choice = input("Select an option (1-6): ").strip()
        
        if choice in faq_questions:
            # --- Option 1: General FAQ (Call LLM directly) ---
            # This is fast and doesn't need a token.
            print("Contacting chatbot for a general answer...")
            try:
                llm_request = llm_pb2.GetLLMAnswerRequest(query=choice, context="") # Send the ID
                llm_response = self.llm_stub.GetLLMAnswer(llm_request)
                print(f"\nChatbot says: {llm_response.answer}")
            except grpc.RpcError as e:
                print(f"Error: Could not connect to the LLM service: {e}")

        elif choice == '6':
            # --- Option 2: Custom Question (Call Raft Leader) ---
            if not self.token:
                print("You must be logged in to ask custom questions about your account.")
                return

            query = input("Your question: ")
            if not query:
                return

            print("Checking your account and contacting chatbot...")
            # This calls the leader-aware RPC, which will get context.
            request = booking_pb2.ChatbotRequest(token=self.token, payload=query, context="")
            response = self._call_rpc("AskChatbot", request) 
            
            if response and response.status == booking_pb2.ChatbotResponse.Status.SUCCESS:
                print(f"\nChatbot says: {response.answer}")
            elif response:
                print(f"Chatbot failed: {booking_pb2.ChatbotResponse.Status.Name(response.status)}")
            else:
                print("Chatbot failed: Cluster is unavailable.")
        
        else:
            print("Invalid choice. Returning to main menu.")

    def run_menu(self):
        while True:
            print("\n--- Distributed Ticket Booking System---")
            print("\n")
            print("1. Login")
            print("2. Get seat availability")
            print("3. Book seat")
            print("4. Ask chatbot")
            print("5. Logout")
            print("6. Exit")
            
            choice = input("Enter your choice (1-6): ")
            
            if choice == '1': self.login()
            elif choice == '2': self.get_availability()
            elif choice == '3': self.book_seat()
            elif choice == '4': self.ask_chatbot()
            elif choice == '5': self.logout()
            elif choice == '6':
                print("Exiting...")
                self.llm_channel.close()
                break
            else:
                print("Invalid choice. Please try again.")
            
            input("\nPress Enter to continue...")

if __name__ == '__main__':
    client = BookingClient(RAFT_APP_SERVERS, LLM_SERVER)
    client.run_menu()