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
