import grpc
from concurrent import futures
import time
import uuid
import sys
import os

# Adds the project's root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Generated gRPC code
import booking_pb2
import booking_pb2_grpc
import llm_pb2
import llm_pb2_grpc

class BookingServiceServicer(booking_pb2_grpc.BookingServiceServicer):
    def __init__(self):
        self.users = {"user1": "pass123"}
        self.tokens = {}
        # Expanded in-memory mock data
        self.mock_db = {
            "1": {  # Movie ID
                "title": "Shawshank Redemption",
                "showtimes": {
                    "10:00AM": {
                        "seats": {
                            "A1": {"is_available": True},
                            "A2": {"is_available": True},
                            "B1": {"is_available": False},
                            "B2": {"is_available": True},
                        }
                    },
                    "1:00PM": {
                        "seats": {
                            "C1": {"is_available": True},
                            "C2": {"is_available": True},
                        }
                    }
                }
            },
            "2": {
                "title": "Star Wars: A New Hope",
                "showtimes": {
                    "11:30AM": {
                        "seats": {
                            "A1": {"is_available": True},
                            "A2": {"is_available": True},
                            "A3": {"is_available": False},
                            "A4": {"is_available": True},
                            "B1": {"is_available": True},
                        }
                    },
                    "4:00PM": {
                        "seats": {
                            "D1": {"is_available": True},
                            "D2": {"is_available": True},
                            "D3": {"is_available": True},
                        }
                    }
                }
            },
            "3": {
                "title": "Mission: Impossible - Fallout",
                "showtimes": {
                    "2:30PM": {
                        "seats": {
                            "E1": {"is_available": True},
                            "E2": {"is_available": True},
                        }
                    },
                    "7:30PM": {
                        "seats": {
                            "F1": {"is_available": True},
                            "F2": {"is_available": False},
                        }
                    }
                }
            },
            "4": {
                "title": "Lord of the Rings: Fellowship of the Ring",
                "showtimes": {
                    "10:00AM": {
                        "seats": {
                            "A1": {"is_available": True},
                            "A2": {"is_available": True},
                            "A3": {"is_available": True},
                            "A4": {"is_available": True},
                        }
                    },
                }
            },
            "5": {
                "title": "The Batman",
                "showtimes": {
                    "8:00PM": {
                        "seats": {
                            "G1": {"is_available": True},
                            "G2": {"is_available": True},
                            "G3": {"is_available": True},
                            "G4": {"is_available": False},
                            "G5": {"is_available": True},
                        }
                    }
                }
            }
        }
        # gRPC client for the LLM service
        self.llm_channel = grpc.insecure_channel('localhost:50052')
        self.llm_stub = llm_pb2_grpc.LLMServiceStub(self.llm_channel)

    def Login(self, request, context):
        if request.username in self.users and self.users[request.username] == request.password:
            token = str(uuid.uuid4())
            self.tokens[token] = request.username
            return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.SUCCESS, token=token)
        return booking_pb2.LoginResponse(status=booking_pb2.LoginResponse.Status.INVALID_CREDENTIALS)

    def Logout(self, request, context):
        if request.token in self.tokens:
            del self.tokens[request.token]
            return booking_pb2.LogoutResponse(status=booking_pb2.LogoutResponse.Status.SUCCESS)
        return booking_pb2.LogoutResponse(status=booking_pb2.LogoutResponse.Status.INVALID_TOKEN)

    def GetAvailability(self, request, context):
        if request.token not in self.tokens:
            return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.UNAUTHORIZED)

        # Use the movie_id from the request to find the showtime data
        movie_data = self.mock_db.get(request.movie_id)
        if not movie_data:
            return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SHOWTIME_NOT_FOUND)

        showtime_data = movie_data["showtimes"].get(request.showtime)
        if not showtime_data:
            return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SHOWTIME_NOT_FOUND)

        seats_list = [
            booking_pb2.Seat(seat_id=seat_id, is_available=seat_data["is_available"])
            for seat_id, seat_data in showtime_data["seats"].items()
        ]
        return booking_pb2.GetAvailabilityResponse(status=booking_pb2.GetAvailabilityResponse.Status.SUCCESS, seats=seats_list)

    def BookSeat(self, request, context):
        if request.token not in self.tokens:
            return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.UNAUTHORIZED)

        # Use the movie_id from the request
        movie_data = self.mock_db.get(request.movie_id)
        if not movie_data:
            return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)

        showtime_data = movie_data["showtimes"].get(request.showtime)
        if not showtime_data:
            return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)

        for seat_id in request.seat_ids:
            if seat_id not in showtime_data["seats"] or not showtime_data["seats"][seat_id]["is_available"]:
                return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SEAT_UNAVAILABLE)
            showtime_data["seats"][seat_id]["is_available"] = False
        
        booking_id = str(uuid.uuid4())
        print(f"Booking {booking_id} created for seats {request.seat_ids} for movie {movie_data['title']}")
        return booking_pb2.BookSeatResponse(status=booking_pb2.BookSeatResponse.Status.SUCCESS, booking_id=booking_id)

    def ProcessBusinessRequest(self, request, context):
        llm_request = llm_pb2.GetLLMAnswerRequest(query=request.payload, context=request.context)
        llm_response = self.llm_stub.GetLLMAnswer(llm_request)
        return booking_pb2.ProcessBusinessResponse(answer=llm_response.answer)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    booking_pb2_grpc.add_BookingServiceServicer_to_server(BookingServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    print("Application Server started on port 50051")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()