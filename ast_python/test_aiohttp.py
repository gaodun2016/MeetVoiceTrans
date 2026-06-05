#!/usr/bin/env python3
import asyncio
import aiohttp

async def test():
    print("Testing aiohttp WebSocket...")
    
    headers = {
        'X-Test': 'test-value'
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('wss://echo.websocket.org', headers=headers) as ws:
            print("Connected successfully!")
            await ws.send_str("Hello")
            msg = await ws.receive()
            print(f"Received: {msg.data}")
            await ws.close()
    
    print("Test passed!")

asyncio.run(test())