import grpc
import sys
import os

# Adds the project's root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Generated gRPC code
import booking_pb2
import booking_pb2_grpc
import llm_pb2
import llm_pb2_grpc

def _get_movies_and_showtimes():
    """
    Returns a mock mapping of movie IDs to titles and showtimes.
    """
    return {
        "1": {"title": "Shawshank Redemption", "showtimes": ["10:00AM", "1:00PM"]},
        "2": {"title": "Star Wars: A New Hope", "showtimes": ["11:30AM", "4:00PM"]},
        "3": {"title": "Mission: Impossible - Fallout", "showtimes": ["2:30PM", "7:30PM"]},
        "4": {"title": "Lord of the Rings: Fellowship of the Ring", "showtimes": ["10:00AM"]},
        "5": {"title": "The Batman", "showtimes": ["8:00PM"]},
    }

def run():
    booking_channel = grpc.insecure_channel('localhost:50051')
    booking_stub = booking_pb2_grpc.BookingServiceStub(booking_channel)
    
    llm_channel = grpc.insecure_channel('localhost:50052')
    llm_stub = llm_pb2_grpc.LLMServiceStub(llm_channel)

    token = None
    username = None
    
    faq_questions = {
        "1": "What seats are available?",
        "2": "What payment methods are accepted?",
        "3": "What is the refund policy?",
        "4": "What are the timings of the movie?",
        "5": "How to cancel a booking?"
    }

    while True:
        print("\n--- Available Functions ---")
        print("1. Login")
        print("2. Get seat availability")
        print("3. Book seat")
        print("4. Ask chatbot")
        print("5. Logout")
        print("6. Exit")
        
        choice = input("Enter your choice (1-6): ")
        
        if choice == '1':
            if token:
                print("You are already logged in.")
                continue
            username = input("Enter username: ")
            password = input("Enter password: ")
            
            login_request = booking_pb2.LoginRequest(username=username, password=password)
            login_response = booking_stub.Login(login_request)
            
            if login_response.status == booking_pb2.LoginResponse.Status.SUCCESS:
                token = login_response.token
                print(f"Login successful. Token: {token}")
            else:
                print(f"Login failed: {booking_pb2.LoginResponse.Status.Name(login_response.status)}")
        
        elif choice == '2':
            if not token:
                print("Please log in first.")
                continue
            
            movies_info = _get_movies_and_showtimes()
            print("\n--- Available Movies and Showtimes ---")
            for movie_id, data in movies_info.items():
                print(f" Movie ID: {movie_id}, Title: {data['title']}")
                print(f"   Showtimes: {', '.join(data['showtimes'])}")

            movie_id = input("\nEnter movie ID: ")
            showtime = input("Enter showtime: ")
            
            avail_request = booking_pb2.GetAvailabilityRequest(token=token, movie_id=movie_id, showtime=showtime)
            avail_response = booking_stub.GetAvailability(avail_request)
            
            if avail_response.status == booking_pb2.GetAvailabilityResponse.Status.SUCCESS:
                print("Available seats:")
                for seat in avail_response.seats:
                    status = "Available" if seat.is_available else "Booked"
                    print(f"  Seat {seat.seat_id}: {status}")
            else:
                print(f"Failed to get availability: {booking_pb2.GetAvailabilityResponse.Status.Name(avail_response.status)}")

        elif choice == '3':
            if not token:
                print("Please log in first.")
                continue
            
            movie_id = input("Enter movie ID: ")
            showtime = input("Enter showtime: ")
            seat_ids = input("Enter seat IDs to book (comma-separated): ").split(',')
            
            book_request = booking_pb2.BookSeatRequest(token=token, movie_id=movie_id, showtime=showtime, seat_ids=seat_ids)
            book_response = booking_stub.BookSeat(book_request)
            
            if book_response.status == booking_pb2.BookSeatResponse.Status.SUCCESS:
                print(f"Booking successful! Booking ID: {book_response.booking_id}")
            else:
                print(f"Booking failed: {booking_pb2.BookSeatResponse.Status.Name(book_response.status)}")

        elif choice == '4':
            print("\n--- FAQ Chatbot ---")
            for key, question in faq_questions.items():
                print(f"{key}. {question}")
            print("Enter any other key to return to the main menu.")
            
            faq_choice = input("Select a question (1-5): ")
            
            if faq_choice in faq_questions:
                try:
                    llm_request = llm_pb2.GetLLMAnswerRequest(query=faq_choice, context="")
                    llm_response = llm_stub.GetLLMAnswer(llm_request)
                    print(f"\nChatbot says: {llm_response.answer}")
                except grpc.RpcError as e:
                    print(f"Error communicating with the chatbot service: {e}")
            else:
                print("Returning to main menu.")

        elif choice == '5':
            if not token:
                print("You are not logged in.")
                continue
            
            logout_request = booking_pb2.LogoutRequest(token=token)
            logout_response = booking_stub.Logout(logout_request)
            
            if logout_response.status == booking_pb2.LogoutResponse.Status.SUCCESS:
                token = None
                print("Logout successful.")
            else:
                print(f"Logout failed: {booking_pb2.LogoutResponse.Status.Name(logout_response.status)}")
                
        elif choice == '6':
            print("Exiting...")
            break
            
        else:
            print("Invalid choice. Please try again.")

    booking_channel.close()
    llm_channel.close()

if __name__ == '__main__':
    run()