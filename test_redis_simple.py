#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple Redis connection test
"""

import redis
import sys

try:
    print("Testing simple Redis connection...")

    # Try with explicit timeout - using WSL2 IP address
    r = redis.StrictRedis(
        host='192.168.18.62',
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5
    )

    # Test connection
    result = r.ping()
    print(f"Ping result: {result}")

    # Test set/get
    r.set('test:python', 'Hello from Python!', ex=60)
    value = r.get('test:python')
    print(f"Set/get test passed: {value}")

    print("\nSuccess! Python can connect to Redis!")

except Exception as e:
    print(f"\nError: {type(e).__name__}: {e}")
    print("\nDebug info:")
    import socket
    try:
        sock = socket.create_connection(('127.0.0.1', 6379), timeout=2)
        print("Socket connection successful!")
        sock.close()
    except Exception as se:
        print(f"Socket connection failed: {se}")
        import os
        print(f"Python path: {sys.executable}")
        print(f"os.name: {os.name}")
    sys.exit(1)
