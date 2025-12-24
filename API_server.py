from fastapi import FastAPI

from enum import Enum

app = FastAPI()

"""
this server will act as a Node

each Node may contain up to N selenium instances (Slots)

a Controller may connect to M nodes and through them manage M*N Slots
"""


@app.get("/")
def read_root():
    return {"Hello": "World"}