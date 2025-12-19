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

# ========================================
# Selenium browser driven helper functions
# ========================================

# create the driver, this is persistent throughout a session and retains cookies and session headers
def create_driver():

    # define standard options preventing large leaking
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")

    # create driver and set implicit wait time
    driver = uc.Chrome(options=options)
    driver.implicitly_wait(5)
    
    # return created driver
    return driver

# create driver using brightdata web api, runs on their network with built in fingerprint injection, rotating proxies and captcha bypassing
def create_brightdata_driver():
    server_addr = "https://brd-customer-hl_e515818b-zone-fixr_bot_test:vyh29zcom1gz@brd.superproxy.io:9515"
    connection = Connection(server_addr, 'goog', 'chrome')
    driver = Remote(connection, options=Options())
    return driver

# function that waits for a page to load - reduces bot detection - for sign in function
def wait_for_document_ready(driver, timeout: int = 10):
    """Wait until document.readyState == 'complete'."""
    js_ready = "return document.readyState === 'complete';"
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script(js_ready))

# function that polls web server for ticket code - for reserve ticket function
def wait_for_code():
    return get_variable("TICKET_CODE")

# detects whether or not the ticket needs a code to be inputted - for reserve ticket function
def fast_code_field_detect(driver):
    """
    Return the *element* of a visible code input field if present, else None.
    Fast path via JS; fallback to a short Selenium search.
    """
    try:
        elem = driver.execute_script(
            """
            const el = document.querySelector(
              'input[placeholder*="code" i], input[id*="code" i], input[name*="code" i]'
            );
            return (el && el.offsetParent !== null) ? el : null;
            """
        )
        if elem:
            return elem

        driver.implicitly_wait(0.3)
        inputs = driver.find_elements(By.CSS_SELECTOR, "input")
        for i in inputs:
            meta = (i.get_attribute("placeholder") or "") + (i.get_attribute("name") or "") + (i.get_attribute("id") or "")
            if "code" in meta.lower() and i.is_displayed():
                return i
        return None
    except Exception:
        return None
    finally:
        driver.implicitly_wait(5)  # restore default wait

# switches in and out of iframe context for specialised input boxes - for checkout function
def _fill_stripe_input(driver,iframe_selector: str,input_selector: str,value: str, timeout: int = 5):
    # payment details require specialised logic to fill iframes
    iframe = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, iframe_selector))
    )
    driver.switch_to.frame(iframe)
    field = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, input_selector))
    )
    field.clear()
    field.send_keys(value)
    driver.switch_to.default_content()
    return True

# ============================================
# Selenium browser driven navigation functions
# ============================================

# reserve tickets flow
def reserve_ticket(driver, ticket_text: str, page_url: str, timeout: int = 20, server_IP: str = "127.0.0.1", server_port: str = "9999"):
    # set timer and get page URL
    t0 = time.time()
    driver.get(page_url)

    # wait until tickets can be seen
    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid^='ticket-list-item-']"))
    )

    log_event("found tickets")

    # scrolls until ticket found
    ticket_item = None
    end = time.time() + timeout
    while time.time() < end and ticket_item is None:
        items = driver.find_elements(By.CSS_SELECTOR, "div[data-testid^='ticket-list-item-']")
        for item in items:
            text = item.text.lower()
            if (ticket_text.lower() in text or ticket_text == "*") and "sold out" not in text:

                log_event("found correct ticket")

                ticket_item = item
                
                # clicks '+' button
                candidate = ticket_item.find_element(By.XPATH, ".//button[@data-disabled='false']")
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", candidate)
                driver.execute_script("arguments[0].click();", candidate)

                log_event("added ticket to basket")
                
                # Detects whether ticket requires a code
                code_el = fast_code_field_detect(driver)
    
                # if there is a code continue to unlock flow
                if code_el:

                    log_event("ticket requires code")

                    # get code from server
                    code_to_fill = wait_for_code(server_IP, server_port, ticket_text)

                    log_event("code fetched from server")
        
                    # inputs code into field
                    code_el.send_keys(code_to_fill)

                    log_event("input code")

                    # click unlock button
                    unlock_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[.//div[contains(text(),'Unlock')]]"))
                    )
                    driver.execute_script("arguments[0].click();", unlock_btn)

                    log_event("click unlock ticket")
            
            if ticket_text.lower() in text and "on sale soon" in text:
                log_event("ticket found - not yet on sale")
                return "NOT_RELEASED"
    
        
        # if ticket items not found, scrolls to find them
        if ticket_item is None:
            driver.execute_script("window.scrollBy(0, 600)")
            time.sleep(0.2)

    # Click 'Reserve'
    reserve_btn = WebDriverWait(driver, 50).until(
        EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(),'Reserve')]]"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", reserve_btn)
    driver.execute_script("arguments[0].click();", reserve_btn)

    log_event("click reserve ticket")

    log_event(f"reserved ticket in {time.time() - t0}")

    time.sleep(10)

    return driver.current_url

# checkout flow
def checkout(driver, url: str, card_number: str = "1", expiry: str = "1", cvc: str = "1", postal_code: str = "1"):
   # gets the checkout url passed when ticket was reserved
    driver.get(url)

    # Radios (insurance + extra question)
    first_radio = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "ticket-protection-no"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", first_radio)
    driver.execute_script("arguments[0].click();", first_radio)
    WebDriverWait(driver, 5).until(lambda d: first_radio.is_selected())

    log_event("first radio selected no")

    second_radio = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH,"//input[@type='radio' and @value='no' and not(@id='ticket-protection-no')]",))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", second_radio)
    driver.execute_script("arguments[0].click();", second_radio)
    WebDriverWait(driver, 5).until(lambda d: second_radio.is_selected())

    log_event("second radio selected no")

    # press continue button
    continue_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[.//span[normalize-space()='Continue']]"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", continue_btn)
    driver.execute_script("arguments[0].click();", continue_btn)
    WebDriverWait(driver, 10).until(
        EC.invisibility_of_element_located((By.XPATH, "//button[.//span[normalize-space()='Continue']]"))
    )

    log_event("click continue")

    # selects payment by card if needed, if not found continues
    try:
        card_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "card-tab")))
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card_button)
        driver.execute_script("arguments[0].click();", card_button)
    except Exception:
        pass
    
    # scrolls by set amount
    driver.execute_script("window.scrollBy(0, 600);")
    time.sleep(0.5)

    # fill card number field
    _fill_stripe_input(driver,"iframe[id*='number'], iframe[name*='__privateStripeFrame']","input[name='number']",card_number)
    time.sleep(0.3)

    log_event("fill card number")

    # fill expiry field
    _fill_stripe_input(driver,"iframe[id*='expiry'], iframe[name*='__privateStripeFrame']","input[name='expiry']",expiry,)
    time.sleep(0.3)

    log_event("fill card expiry")

    # fill cvc field
    _fill_stripe_input(driver,"iframe[id*='cvc'], iframe[name*='__privateStripeFrame']","input[name='cvc']",cvc,)
    time.sleep(0.3)

    log_event("fill card cvc")

    # fill postal code field
    _fill_stripe_input(driver,"iframe[id*='postalCodeInput'], iframe[name*='__privateStripeFrame']","#Field-postalCodeInput",postal_code,)
    time.sleep(0.3)

    log_event("fill post code")

    # fill country field
    iframe = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "iframe[id*='Field-countryInput'], iframe[name*='__privateStripeFrame']")
    ))
    driver.switch_to.frame(iframe)
    country = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "Field-countryInput")))
    country.send_keys("United Kingdom")
    driver.switch_to.default_content()

    log_event("fill country")

    # press pay now button
    pay_now_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[.//span[normalize-space()='Pay now']]"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pay_now_btn)
    driver.execute_script("arguments[0].click();", pay_now_btn)

    log_event("click pay now")

    # Check success
    try:
        view_btn = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//button[.//span[normalize-space()='View tickets']]"))
        )
        if view_btn:
            return True
        log_event("purchase successful")
    except Exception:
        time.sleep(10)
        log_event("cannot confirm successful purchase may require 3ds")
    return False

# =================
# Main client flow
# =================

def remote_controlled_workflow():
    
    # define starting variables
    client_status = "INACTIVE"

    server_IP = "127.0.0.1"
    server_port = 9999

    variables = {
        "BOT_ID" : "NONE",
        "TICKET_TEXT" : "NONE",
        "TICKET_CODE" : "NONE",
        "TICKET_URL" : "NONE",
        "ACCOUNT_EMAIL" : "NONE",
        "ACCOUNT_PASSWORD" : "NONE"
    }

    connection = init_network_connection(server_IP, server_port)

    # get variables from server
    """for i in variables.keys():
                if variables.get(i) == None:
                    variables[i] = get_variable(i)"""
    
    # make selenium driver (uc)
    driver = create_driver()
    
    while True:
        # checks for and reponds to any incoming server requests
        messages = get_all_incoming_requests()
        for i in messages: 
            split_msg = split_message(i)
            if split_msg[0] == "CLIENT_STATUS_REQUEST":
                respond_to_status_request(client_status)
            if split_msg[0] == "CHECK_VARIABLE_REQUEST":
                respond_to_variable_check(split_msg[1], variables)
            if split_msg[0] == "CHANGE_VARIABLE_REQUEST":
                respond_to_variable_change(split_msg[1], split_msg[2], variables)
            if split_msg[0] == "CLIENT_LOGIN":
                try:
                    sign_in(driver, variables.get("ACCOUNT_EMAIL"), variables.get("ACCOUNT_PASSWORD"))
                except:
                    report_error("could not complete sign in")
            if split_msg[0] == "CLIENT_BUY_TICKET":
                try: 
                    while True:
                        checkout_url = reserve_ticket(driver, variables.get("TICKET_TEXT"), variables.get("TICKET_URL"))
                        if checkout_url != "NOT_RELEASED":
                            break
                except:
                    report_error("could not complete ticket reservation")
                try:
                    checkout(driver, checkout_url)
                except:
                    report_error("could not checkout")

def testing_workflow():
    driver = create_driver()
    sign_in(driver, "EMAIL", "PASSWORD")
    checkout_url = reserve_ticket(driver, "TICKET_TEXT", "TICKET_URL")
    checkout(driver, checkout_url)

if __name__ == "__main__":
    testing_workflow()