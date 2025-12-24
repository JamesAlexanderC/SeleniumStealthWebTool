from fastapi import FastAPI

from enum import Enum

app = FastAPI()

"""
this server will act as a node

each node may contain up to N selenium instances (slots)

this server will act as communication between a client all the slots
"""


@app.get("/")
def read_root():
    return {"Hello": "World"}