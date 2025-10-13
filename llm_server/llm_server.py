import grpc
from concurrent import futures
import time
import uuid
import sys
import os

# Adds the project's root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import llm_pb2
import llm_pb2_grpc

class LLMServiceServicer(llm_pb2_grpc.LLMServiceServicer):
    def __init__(self):
        self.faqs = {
            "1": "For real-time seat availability, please use the 'Get seat availability' feature after logging in. This will show you all available seats for a specific showtime.",
            "2": "We accept all major credit cards, as well as several digital payment methods. You will be prompted to enter your payment details during the booking process.",
            "3": "To get a refund, you must cancel your ticket at least 24 hours before the showtime. Refunds are processed within 5-7 business days.",
            "4": "The show times can be found on the movie's details page. Our system will display this information before you select your seats.",
            "5": "Currently, cancellations are handled by contacting customer support."
        }

    def GetLLMAnswer(self, request, context):
        print(f"Received query ID: '{request.query}'")
        
        answer = self.faqs.get(request.query, "I'm sorry, I don't have an answer for that question. Please choose from the available options.")
        
        return llm_pb2.GetLLMAnswerResponse(answer=answer)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    llm_pb2_grpc.add_LLMServiceServicer_to_server(LLMServiceServicer(), server)
    server.add_insecure_port('[::]:50052')
    print("LLM Server started on port 50052")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()