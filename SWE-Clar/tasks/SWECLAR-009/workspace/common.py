"""Public HTTP validation helpers; workflow decisions live in marketplace.py."""
import re
class Problem(Exception):
 def __init__(self,status,code):self.status=status;self.code=code

def require(condition,code='invalid',status=400):
 if not condition:raise Problem(status,code)

def fields(value,names):require(isinstance(value,dict) and set(value)==set(names))
def ident(value):return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value) is not None
def timestamp(value):return type(value) is int and 0<=value<=253402300799999

def text(value,limit,nonempty=True,trim=True):
 require(isinstance(value,str));result=value.strip() if trim else value
 require(len(result)<=limit and (bool(result) or not nonempty));return result
