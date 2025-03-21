#!/usr/bin/env python3
import json
import sys
import threading
import time
import webbrowser
from base64 import urlsafe_b64encode
from hashlib import sha256
from http.server import HTTPServer, BaseHTTPRequestHandler
from secrets import token_urlsafe
from urllib.parse import urlparse, parse_qs

from requests_oauthlib import OAuth2Session

import ssl

SCOPES = [
    'activity',
    'heartrate',
    'nutrition',
    'oxygen_saturation',
    'respiratory_rate',
    'settings',
    'sleep',
    'temperature',
    'weight',
]
REDIRECT_URI = 'https://localhost:5000/callback'
AUTHORIZATION_BASE_URL = 'https://www.fitbit.com/oauth2/authorize'
TOKEN_URL = 'https://api.fitbit.com/oauth2/token'
SERVER_ADDRESS = ('127.0.0.1', 5000)

# Fitbit requires HTTPS callbacks so we just use some dummy certs.
CERT_FILE = 'ssl/cert.pem'
KEY_FILE = 'ssl/key.pem'

authorization_code = None


###############################################################################
# Local HTTPS Server to handle OAuth Redirects
###############################################################################

class OAuthCallbackServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, ssl_context, auth_event):
        super().__init__(server_address, RequestHandlerClass)
        self.auth_event = auth_event
        self.authorization_code = None
        self.ssl_context = ssl_context

    def serve_forever_tls(self):
        self.socket = self.ssl_context.wrap_socket(self.socket, server_side=True)
        self.serve_forever()


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == '/':
            # Let user know they can proceed
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            message = b'''
                <html>
                  <head><title>SSL Certificate Accepted</title></head>
                  <body>
                    <h1>SSL Certificate Accepted</h1>
                    <p>You can now close this window and return to the terminal.</p>
                  </body>
                </html>
            '''
            self.wfile.write(message)
            # Notifying the user acceptance was visited; no special event needed here
        elif parsed_url.path == '/callback':
            # This is where the OAuth authorization code is returned
            query_params = parse_qs(parsed_url.query)
            if 'code' not in query_params:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Authorization code not found.')
                return

            # Store the authorization code
            global authorization_code
            authorization_code = query_params['code'][0]
            self.server.auth_event.set()  # Signal that we have a code

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            success = b'''
                <html>
                  <head><title>Authorization Successful</title></head>
                  <body>
                    <h1>Authorization Successful</h1>
                    <p>You can close this window.</p>
                  </body>
                </html>
            '''
            self.wfile.write(success)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')


def get_ssl_context(cert_file, key_file):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    context.set_ciphers('@SECLEVEL=1:ALL')
    return context


def start_callback_server(ssl_context, auth_event):
    httpd = OAuthCallbackServer(SERVER_ADDRESS, OAuthCallbackHandler, ssl_context, auth_event)
    print(f'Starting HTTPS server at https://{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}')
    httpd.serve_forever_tls()
    return httpd


###############################################################################
# PKCE Utility Functions
###############################################################################

def generate_code_verifier():
    # Must be 43-128 characters in length
    # We'll generate 64 for safety
    return token_urlsafe(64)


def generate_code_challenge(code_verifier: str):
    # Use SHA256 of the verifier, base64-url-encode, strip '='
    challenge = sha256(code_verifier.encode('utf-8')).digest()
    return urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')


###############################################################################
# Main Authorization Flow
###############################################################################

def authorize(client_id: str):
    """
    Launches a local HTTPS server and begins PKCE OAuth2 flow via requests-oauthlib.
    """
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    oauth = OAuth2Session(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES
    )

    authorization_url, _ = oauth.authorization_url(
        AUTHORIZATION_BASE_URL,
        code_challenge=code_challenge,
        code_challenge_method='S256',
    )

    auth_event = threading.Event()
    ssl_context = get_ssl_context(CERT_FILE, KEY_FILE)
    server_thread = threading.Thread(
        target=start_callback_server,
        args=(ssl_context, auth_event),
        daemon=True
    )
    server_thread.start()

    print('Opening browser to accept SSL certificate at / ...')
    webbrowser.open_new_tab(f'https://{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}/')
    time.sleep(2)

    print('Now opening the browser to request Fitbit authorization...')
    webbrowser.open_new_tab(authorization_url)

    # Wait until the server signals that authorization code arrived or time out
    print('Waiting for the authorization code from Fitbit...')
    auth_event.wait(timeout=300)  # 5-minute timeout, adjust as needed
    if authorization_code is None:
        print('No authorization code received. Exiting.')
        sys.exit(1)

    # Exchange for token
    try:
        token_dict = oauth.fetch_token(
            TOKEN_URL,
            code=authorization_code,
            code_verifier=code_verifier,
            include_client_id=True  # Must be set for PKCE if no client_secret
        )
    except Exception as e:
        print(f'Failed to fetch token: {e}')
        sys.exit(1)

    print('Access and refresh tokens obtained successfully.')

    # Calculate approximate expiry
    expires_at = token_dict.get('expires_at', time.time() + token_dict.get('expires_in', 0))
    token_dict['expires_at'] = int(expires_at)

    print('\nToken Info (JSON):')
    print(json.dumps(token_dict))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: ./authorize.py <client_id>')
        sys.exit(1)

    client_id = sys.argv[1]
    authorize(client_id)
