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
        print(f"Received query: '{request.query}'")
        print(f"With context: '{request.context}'")
        
        # --- New Context-Aware Logic ---
        
        # 1. Check for context-aware answer first.
        #    If context was provided, use it.
        if request.context:
            if "booking" in request.query.lower() or "my seat" in request.query.lower():
                answer = f"I've checked your account. {request.context}"
                return llm_pb2.GetLLMAnswerResponse(answer=answer)
            
            if "available" in request.query.lower():
                answer = f"I found some availability in the system: {request.context}"
                return llm_pb2.GetLLMAnswerResponse(answer=answer)
        
        # 2. No context. Check if the query is an FAQ ID (like "1", "2").
        if request.query in self.faqs:
            answer = self.faqs[request.query]
            return llm_pb2.GetLLMAnswerResponse(answer=answer)

        # 3. No ID. Check for keywords (for natural language general questions).
        query_lower = request.query.lower()
        if "cancel" in query_lower:
            faq_id = "5"
        elif "payment" in query_lower:
            faq_id = "2"
        elif "refund" in query_lower:
            faq_id = "3"
        elif "timing" in query_lower:
            faq_id = "4"
        elif "available" in query_lower or "seat" in query_lower:
            faq_id = "1"
        else:
            faq_id = "unknown" # Fallback

        answer = self.faqs.get(faq_id, "I'm sorry, I don't have an answer for that. Can you rephrase?")
        
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