import socket 
import threading
from queue import Queue, Empty
import time
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import WebDriverException
from typing import Optional
from selenium.webdriver import Remote, ChromeOptions as Options
from selenium.webdriver.chromium.remote_connection import ChromiumRemoteConnection as Connection

global INCOMING, OUTGOING, RESPONSE
INCOMING = Queue()
OUTGOING = Queue()
RESPONSE = ""

# ========================
# TCP Networking functions
# ========================

# I am using exact size messages (1024 bytes)
# this function waits until that number of bytes exactly are sent down the stream before returning the message
def recv_exact(sock, size):
    chunks = []
    received = 0
    while received < size:
        try:
            chunk = sock.recv(size - received)
            if not chunk:
                raise ConnectionError("Connection closed while receiving data")
            chunks.append(chunk)
            received += len(chunk)
        except BlockingIOError:
            # No data available right now, try again
            time.sleep(0.001)
            continue
    return b"".join(chunks)

# the network Thread
# runs independently from mainloop
# uses INCOMING, OUTGOING and RESPONSE gloabl variables to communicate with main loop
def network_thread(sock):
    global RESPONSE
    sock.setblocking(False)  # ← Change to non-blocking
    while True:
        # handle outgoing message logic
        try:
            msg = OUTGOING.get_nowait()
            msg_bytes = msg.encode('utf-8') if isinstance(msg, str) else msg
            msg_bytes = msg_bytes.ljust(1024, b'\0')
            sock.sendall(msg_bytes)
        except Empty:
            pass
        except BlockingIOError:
            pass  # Socket not ready to send

        # handle incoming message logic
        try:
            data = recv_exact(sock, 1024)
            if not data:
                break
            
            # Decode bytes to string
            msg_str = data.rstrip(b'\0').decode('utf-8', errors='ignore')
            
            if RESPONSE == "WAITING":
                RESPONSE = msg_str
            else:
                INCOMING.put(msg_str)
        except BlockingIOError:
            pass  # No data available yet
        except ConnectionError:
            break
        
        time.sleep(0.01)  # ← Add small sleep to prevent busy-waiting

# initiates TCP connection with specified IP and port
def init_network_connection(server_IP, server_port):
    # create socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_IP, server_port))

    # start thread, pass socket as argument
    connection_manager = threading.Thread(target=network_thread, args=(sock,), daemon=True)
    connection_manager.start()

    return connection_manager

# returns all requests from server in a list in order they were sent
def get_all_incoming_requests():
    requests = []
    while True:
        try:
            requests.append(INCOMING.get_nowait())
        except Empty:
            break
    return requests

# sends message to server - does not wait for response
def send_message_no_wait(message):
    OUTGOING.put(message)

# sends message to server - waits for response and returns it from function
def send_request_return_response(message):
    global RESPONSE
    RESPONSE = "WAITING"
    OUTGOING.put(message)
    while RESPONSE == "WAITING":
        time.sleep(0.1)
    response = RESPONSE
    RESPONSE = ""
    return response

# defining all messages that can be recognised - payloads and responses
# technically superfluous to code, however helps as a reference
protocol = {
    "SERVER_STATUS_REQUEST" : [None, "SERVER_STATUS_RESPONSE"],
    "SERVER_STATUS_RESPONSE" : [["INACTIVE", "ACTIVE"], None],
    
    "CLIENT_STATUS_REQUEST" : [None, "CLIENT_STATUS_RESPONSE"],
    "CLIENT_STATUS_RESPONSE" : [["INACTIVE", "WAITING_FOR_VARIABLES", "ERROR", "READY_TO_LOGIN", "READY_TO_BUY", "FINISHED"], None],

    "CHECK_VARIABLE_REQUEST" : [["TICKET_TEXT", "TICKET_CODE", "TICKET_URL", "ACCOUNT_EMAIL", "ACCOUNT_PASSWORD", "BOT_ID"], "CHECK_VARIABLE_RESPONSE"],
    "CHECK_VARIABLE_RESPONSE" : ["ANY_STRING", None],

    "CHANGE_VARIABLE_REQUEST" : [[["TICKET_TEXT", "TICKET_CODE", "TICKET_URL", "ACCOUNT_EMAIL", "ACCOUNT_PASSWORD", "BOT_ID"], "ANY_STRING"], "CHANGE_VARIABLE_RESPONSE"],
    "CHANGE_VARIABLE_RESPONSE" : [["SUCCESS", "FAIL"], None],

    "REPORT_CLIENT_ERROR" : [[["TICKET_TEXT", "TICKET_CODE", "TICKET_URL", "ACCOUNT_EMAIL", "ACCOUNT_PASSWORD", "BOT_ID"], "ANY_STRING"], None],

    "REPORT_CLIENT_FINISH" : [["SUCCESS", "FAIL"], None],

    "CLIENT_LOG_EVENT" : ["ANY_STRING", None],

    "CLIENT_LOGIN" : [None, None],

    "CLIENT_BUY_TICKET" : [None, None]
}

# ==============================================================
# Protocol wrapping and unwrapping functions - no commenting / self explanatory
# ==============================================================

def report_error(err_msg):
    msg_code = "REPORT_CLIENT_ERROR"
    msg = f"{msg_code}|{err_msg}"
    send_message_no_wait(msg)

def get_variable(var):
    msg_code = "CHECK_VARIABLE_REQUEST"
    msg = f"{msg_code}/{var}"
    raw_response = send_request_return_response(msg)
    temp = raw_response.split("|")
    response = temp[1]
    return response

def get_server_status():
    msg = "SERVER_STATUS_REQUEST"
    raw_response = send_request_return_response(msg)
    temp = raw_response.split("|")
    response = temp[1]
    return response

def report_finished(success):
    msg_code = "REPORT_CLIENT_FINISH"
    msg = f"{msg_code}|{success}"
    send_message_no_wait(msg)

def split_message(msg):
    temp = msg.split("|")
    split_msg=[]
    for i in temp:
        split_msg.append(i)
    return split_msg

def respond_to_variable_check(variable, variables):

    value = variables.get(variable)
    msg_code = "CHECK_VARIABLE_RESPONSE"
    msg = f"{msg_code}|{value}"
    send_message_no_wait(msg)

def respond_to_status_request(response):
    msg_code = "CLIENT_STATUS_RESPONSE"
    msg = f"{msg_code}|{response}"
    send_message_no_wait(msg)

def respond_to_variable_change(variable, new_value, variables):
    variables[variable] = new_value
    success = "FAIL"
    if variables.get(variable) == new_value:
        success = "SUCCESS"
    msg_code = "CHANGE_VARIABLE_RESPONSE"
    msg= f"{msg_code}|{success}"
    send_message_no_wait(msg)

def log_event(log_msg):
    msg_code = "LOG_CLIENT_EVENT"
    msg = f"{msg_code}|{log_msg}"
    send_message_no_wait(msg)
