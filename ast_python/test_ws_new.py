import asyncio
import websockets

async def test():
    print(f"Websockets version: {websockets.__version__}")
    headers = [('X-Test', 'test-value')]
    try:
        async with websockets.connect('wss://echo.websocket.org', additional_headers=headers) as ws:
            print('Connected successfully!')
            await ws.send('Hello')
            response = await ws.recv()
            print(f"Received: {response}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

asyncio.run(test())