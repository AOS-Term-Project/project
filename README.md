**Project demo video:** https://drive.google.com/drive/folders/19XfJFubtciIHLfzhAgukN4_EaI8X68tH?usp=sharing

**Libraries to install:**

pip3 install grpcio  
pip3 install grpcio-tools

**STEPS TO RUN**
**Clear the old logs-** Delete the old json and jsonl files
rm *.json *.jsonl

**Terminal 1-** LLM Server
run _python3 llm_server.py_

**Terminal 2-** App Server 1
run _python3 app_server/app_server.py 50051 50051 localhost:50053 localhost:50054_

**Terminal 3-** App Server 2
run _python3 app_server/app_server.py 50053 50053 localhost:50051 localhost:50054_

**Terminal 4-** App Server 3
run _python3 app_server/app_server.py 50054 50054 localhost:50051 localhost:50053_

**Terminal 5-** Client
run _python3 client.py_

Application Server started on port 50051, 50053, 50054.

LLM Server started on port 50052.

when client runs , it will display the following options:


<img width="346" height="194" alt="image" src="https://github.com/user-attachments/assets/38d9447c-d143-401b-ae1e-890863e0df99" />


**Menu Functionalities**

   1. Login - used for client authentication using userid and password . if successfull , the app server will return a session token and "Login Successfull"             message .

   2. Get Seat Availability - Displays which seats are Booked or Available for the particular movie slot.

   3. Book Seat - client books the seat for the particular slot using the seat ids and the server updated the seat status accordingly , If successfull will return       the booking id to the client .

      <img width="1199" height="70" alt="image" src="https://github.com/user-attachments/assets/2c068afd-8dcd-423e-b894-5167fa921ebc" />


   4. Ask Chatbot - to resolve customer queries.

  Possible Chat Bot Questions :

  <img width="537" height="164" alt="image" src="https://github.com/user-attachments/assets/44e7ec3f-f2fb-4a1c-b811-ac43921f77f2" />

  5. Logout - to end the user session.

  6. Exit - to end the client application successfully. Closes all the active connections with the app server.

  
