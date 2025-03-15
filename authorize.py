#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

import requests

import ssl

SCOPES = "activity heartrate nutrition oxygen_saturation respiratory_rate settings sleep temperature weight"
REDIRECT_URI = "https://localhost:5000/callback"
AUTHORIZATION_URL = "https://www.fitbit.com/oauth2/authorize"
TOKEN_URL = "https://api.fitbit.com/oauth2/token"
SERVER_ADDRESS = ("127.0.0.1", 5000)
authorization_code = None

# Fitbit requires callback URLs to be HTTPS so we'll just use some random certs.
CERT_FILE = "ssl/cert.pem"
KEY_FILE = "ssl/key.pem"


# ------------------ PKCE Generation ------------------ #

def generate_code_verifier():
    # Generates a cryptographically secure random string between 43 and 128 characters
    code_verifier = base64.urlsafe_b64encode(os.urandom(96)).decode('utf-8')
    return code_verifier.rstrip('=')


def generate_code_challenge(code_verifier):
    # Generates a code challenge based on the code verifier
    sha256 = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(sha256).decode('utf-8').rstrip('=')
    return code_challenge


# ------------------ HTTP Server with HTTPS ------------------ #

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global authorization_code

        parsed_url = urlparse(self.path)
        if parsed_url.path == '/':
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b'''
                <html>
                    <head><title>SSL Certificate Accepted</title></head>
                    <body>
                        <h1>SSL Certificate Accepted</h1>
                        <p>You can now close this window and return to the terminal.</p>
                    </body>
                </html>
            ''')
            self.server.ssl_accepted_event.set()
        elif parsed_url.path == '/callback':
            query_params = parse_qs(parsed_url.query)
            if 'code' not in query_params:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Authorization code not found.')
                return

            authorization_code = query_params['code'][0]
            self.server.authorization_event.set()

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b'''
                <html>
                    <head><title>Authorization Successful</title></head>
                    <body>
                        <h1>Authorization Successful</h1>
                        <p>You can close this window.</p>
                    </body>
                </html>
            ''')
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')


def get_ssl_context(certfile, keyfile):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    context.set_ciphers("@SECLEVEL=1:ALL")
    return context


def start_server(authorization_event, ssl_accepted_event):
    httpd = HTTPServer(SERVER_ADDRESS, OAuthHandler)
    httpd.authorization_code = None
    httpd.authorization_event = authorization_event
    httpd.ssl_accepted_event = ssl_accepted_event
    ssl_context = get_ssl_context(CERT_FILE, KEY_FILE)
    httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
    print(f"Starting HTTPS server at https://{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}")
    httpd.serve_forever()


# ------------------ Main Authorization Flow ------------------ #

def authorize(client_id):
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    authorization_url = f"{AUTHORIZATION_URL}?{urlencode(params)}"
    authorization_event = threading.Event()
    ssl_accepted_event = threading.Event()
    server_thread = threading.Thread(target=start_server, args=(authorization_event, ssl_accepted_event))
    server_thread.daemon = True
    server_thread.start()

    print("Opening the browser to accept the SSL certificate...")
    webbrowser.open('https://localhost:5000', new=1, autoraise=True)
    ssl_accepted_event.wait()
    print("SSL certificate accepted.")

    print("Opening the browser to authorize the application...")
    webbrowser.open(authorization_url, new=1, autoraise=True)
    authorization_event.wait()

    print(f"Authorization code received: {authorization_code}")

    # Exchange authorization code for tokens
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": authorization_code,
        "code_verifier": code_verifier,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }

    response = requests.post(TOKEN_URL, data=data, headers=headers)
    if response.status_code != 200:
        print(f"Failed to obtain tokens: {response.status_code} {response.text}")
        sys.exit(1)

    token_data = response.json()
    print("Access and refresh tokens obtained successfully.")

    # Calculate the token expiry time
    expires_in = token_data.get("expires_in")  # in seconds
    expires_at = int(time.time()) + expires_in

    token_info = {
        "client_id": client_id,
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": expires_at,
        "scope": token_data.get("scope"),
        "token_type": token_data.get("token_type"),
        "user_id": token_data.get("user_id"),
    }

    print("\nToken Info (JSON):")
    print(json.dumps(token_info))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:  ./authorize.py <client_id>")
        sys.exit(1)
    authorize(sys.argv[1])
