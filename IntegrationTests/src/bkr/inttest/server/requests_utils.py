
import json
import requests
from bkr.inttest import data_setup, get_server_base

def json_request(method, url, **kwargs):
    # encode data as json
    data = json.dumps(kwargs.pop('data'))
    # add Content-Type request header
    headers = kwargs.pop('headers', {})
    headers.update({'Content-Type': 'application/json'})
    # call .request() on the session if given, else the module
    real_request_func = kwargs.pop('session', requests).request
    return real_request_func(method, url, data=data, headers=headers, **kwargs)

def post_json(url, **kwargs):
    return json_request('POST', url, **kwargs)

def put_json(url, **kwargs):
    return json_request('PUT', url, **kwargs)

def login(session, user=None, password=None):
    if user is None and password is None:
        user = data_setup.ADMIN_USER
        password = data_setup.ADMIN_PASSWORD
    session.post(get_server_base() + 'login',
            data=dict(user_name=user, password=password)).raise_for_status()
