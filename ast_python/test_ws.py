#!/usr/bin/env python3
import asyncio
import websockets

async def test():
    print(f"Websockets version: {websockets.__version__}")
    
    # Test 1: Basic connection
    print("Test 1: Basic connection...")
    ws = await websockets.connect('wss://echo.websocket.org')
    await ws.close()
    print("Test 1 passed!")
    
    # Test 2: Connection with headers
    print("Test 2: Connection with headers...")
    headers = [('X-Test', 'test-value')]
    ws2 = await websockets.connect('wss://echo.websocket.org', headers=headers)
    await ws2.close()
    print("Test 2 passed!")

asyncio.run(test())