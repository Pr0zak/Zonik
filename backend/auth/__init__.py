"""Accounts, roles and request authentication.

resolve.py   who is calling (session cookie, device token, Subsonic params) + the /api, /rest
             and websocket gates, grace mode and the CSRF check
policy.py    which permission each /api route needs
permissions.py  what each role may do
sessions.py / devices.py  web login sessions and per-device app tokens (stored hashed)
passwords.py / lockout.py  bcrypt helpers and the failed-login lockout
"""
