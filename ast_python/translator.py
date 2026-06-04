import asyncio
import uuid
import logging
from datetime import datetime
from python_protogen.products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse, ReqParams
from python_protogen.products.understanding.base.au_base_pb2 import Audio
from python_protogen.common.rpcmeta_pb2 import RequestMeta
from python_protogen.common.events_pb2 import Type

logging.basicConfig(level=logging.INFO)

class Translator:
    def __init__(self, api_key, resource_id="default", ws_url="wss://ast.bytedance.net/api/ast"):
        self.api_key = api_key
        self.resource_id = resource_id
        self.ws_url = ws_url
        self.conn = None
        self.session = None
        self.session_id = None
        self.sequence = 0
        self.running = False
        self.audio_buffer = bytearray()
        self.on_translate = None
        self.on_audio = None
        self.on_status = None
        self.on_error = None
    
    def set_callbacks(self, on_translate=None, on_audio=None, on_status=None, on_error=None):
        self.on_translate = on_translate
        self.on_audio = on_audio
        self.on_status = on_status
        self.on_error = on_error
    
    def _status(self, msg):
        if self.on_status:
            self.on_status(msg)
        logging.info(msg)
    
    def _error(self, msg):
        if self.on_error:
            self.on_error(msg)
        logging.error(msg)
    
    async def connect(self):
        try:
            import aiohttp
            
            log_id = datetime.now().strftime("%Y%m%d%H%M%S") + str(uuid.uuid4()).replace("-", "")[:20]
            
            headers = {
                "X-Api-Key": self.api_key,
                "X-Tt-Logid": log_id,
                "X-Api-Resource-Id": self.resource_id
            }
            
            self._status(f"Connecting to: {self.ws_url}")
            self._status(f"Headers: {headers}")
            
            # 设置超时配置
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            
            # 添加连接超时处理
            try:
                self.conn = await asyncio.wait_for(
                    self.session.ws_connect(self.ws_url, headers=headers),
                    timeout=15  # 连接超时时间
                )
            except asyncio.TimeoutError:
                raise ConnectionError(f"Connection timeout. Server {self.ws_url} is not accessible.")
            
            self._status(f"Connected to server (log_id={log_id})")
            return True
        except ConnectionError as e:
            self._error(f"Connection failed: {e}")
            return False
        except Exception as e:
            import traceback
            self._error(f"Connection failed: {e}")
            self._error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def start_session(self, source_lang="zh", target_lang="en"):
        if not self.conn:
            return False
        
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        
        request = TranslateRequest(
            request_meta=RequestMeta(
                SessionID=self.session_id,
                Sequence=self.sequence
            ),
            event=Type.StartSession,
            source_audio=Audio(
                format="wav",
                codec="pcm_s16le",
                language=source_lang,
                rate=16000,
                bits=16,
                channel=1
            ),
            target_audio=Audio(
                format="ogg",
                codec="opus",
                language=target_lang,
                rate=24000,
                bits=16,
                channel=1
            ),
            request=ReqParams(
                mode="s2s",
                source_language=source_lang,
                target_language=target_lang
            )
        )
        
        await self.conn.send_bytes(request.SerializeToString())
        self.sequence += 1
        
        response_data = await self.conn.receive_bytes()
        response = TranslateResponse()
        response.ParseFromString(response_data)
        
        if response.event == Type.SessionStarted:
            self._status(f"Session started: {self.session_id[:8]}...")
            return True
        return False
    
    async def send_audio(self, audio_data):
        if not self.conn:
            return
        
        request = TranslateRequest(
            request_meta=RequestMeta(
                SessionID=self.session_id,
                Sequence=self.sequence
            ),
            event=Type.TaskRequest,
            source_audio=Audio(
                format="wav",
                codec="pcm_s16le",
                language="zh",
                rate=16000,
                bits=16,
                channel=1,
                binary_data=audio_data
            )
        )
        
        await self.conn.send_bytes(request.SerializeToString())
        self.sequence += 1
    
    async def receive_loop(self):
        self.running = True
        while self.running:
            try:
                msg = await self.conn.receive()
                
                if msg.type == aiohttp.WSMsgType.BINARY:
                    response_data = msg.data
                    response = TranslateResponse()
                    response.ParseFromString(response_data)
                    
                    event = response.event
                    
                    # 翻译文本结果
                    if event in [651, 654, 655]:  # Subtitle events
                        if response.text.strip() and self.on_translate:
                            self.on_translate(response.text, response.sequence)
                    
                    # TTS 音频数据
                    elif event == 352:  # TTSResponse
                        if response.data:
                            self.audio_buffer.extend(response.data)
                    
                    # 音频结束标记
                    elif event == 351:  # TTSSentenceEnd
                        if len(self.audio_buffer) > 0 and self.on_audio:
                            self.on_audio(bytes(self.audio_buffer))
                        self.audio_buffer.clear()
                    
                    # 会话结束
                    elif event == Type.SessionFinished:
                        self._status("Session finished")
                        break
                    
                    # 会话失败
                    elif event == Type.SessionFailed:
                        self._error(f"Session failed: {response.response_meta.Message}")
                        break
                
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    self._status("Connection closed")
                    break
                
            except Exception as e:
                self._error(f"Receive error: {e}")
                break
    
    async def stop(self):
        self.running = False
        if self.conn:
            request = TranslateRequest(
                request_meta=RequestMeta(
                    SessionID=self.session_id,
                    Sequence=self.sequence
                ),
                event=Type.FinishSession
            )
            try:
                await self.conn.send_bytes(request.SerializeToString())
            except:
                pass
            await self.conn.close()
            if self.session:
                await self.session.close()
            self._status("Disconnected from server")