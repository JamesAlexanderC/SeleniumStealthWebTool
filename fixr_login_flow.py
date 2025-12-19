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

# function that polls web server for ticket code - for reserve ticket function
def wait_for_code():
    return get_variable("TICKET_CODE")

# function that waits for a page to load - reduces bot detection - for sign in function
def wait_for_document_ready(driver, timeout: int = 10):
    """Wait until document.readyState == 'complete'."""
    js_ready = "return document.readyState === 'complete';"
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script(js_ready))

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

# sign in flow
def sign_in(driver, email: str, password: str, url: str = "https://fixr.co/login"):
    
    # get URL and wait for page to load
    driver.get(url)
    wait_for_document_ready(driver)

    # finds email input element and inputs account email
    email_el = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login-email")))
    email_el.clear()
    email_el.send_keys(email)

    log_event("input email")

    # waits for continue button to be clickable and clicks it
    continue_btn = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, "//button[.//span[normalize-space()='Continue']]"))
    )
    continue_btn.click()

    log_event("click continue")

    # finds password input element and inputs password
    password_el = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "login-password")))
    password_el.clear()
    password_el.send_keys(password)

    log_event("input_password")

    # waits for sign in button to be clickable, scrolls down to it if needed and clicks it
    sign_in_btn = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, "//button[.//span[normalize-space()='Sign in']]"))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sign_in_btn)
    sign_in_btn.click()

    log_event("sign_in")

    # waits until sign in finished to return successful
    wait_for_document_ready(driver)
    time.sleep(2)
    return True
