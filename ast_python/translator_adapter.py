"""Adapter to use meet_translator.py in PyQt application"""
import asyncio
import os
import sys

# Add meet_translator dependencies to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from meet_translator import (
    Config, translate_v4_microphone, decode_opus
)
import numpy as np
import sounddevice as sd

class TranslatorAdapter:
    def __init__(self, api_key, output_device=None):
        self.api_key = api_key
        self.output_device = output_device
        self.running = False
        self.translate_callback = None
        self.status_callback = None
        self.error_callback = None
        self.audio_callback = None
    
    def set_callbacks(self, translate_callback=None, status_callback=None, 
                     error_callback=None, audio_callback=None):
        self.translate_callback = translate_callback
        self.status_callback = status_callback
        self.error_callback = error_callback
        self.audio_callback = audio_callback
    
    def _status(self, msg):
        if self.status_callback:
            self.status_callback(msg)
    
    def _error(self, msg):
        if self.error_callback:
            self.error_callback(msg)
    
    def _translate(self, text):
        if self.translate_callback:
            self.translate_callback(text)
    
    def _audio(self, audio_data):
        if self.audio_callback:
            self.audio_callback(audio_data)
    
    async def run(self):
        """Run the translation loop"""
        self.running = True
        
        try:
            # Create config
            conf = Config(
                ws_url="wss://openspeech.bytedance.com/api/v4/ast/v2/translate",
                app_key=self.api_key,
                resource_id="volc.service_type.10053"
            )
            
            self._status("Connecting to translation server...")
            
            # Audio recording settings
            SAMPLE_RATE = 16000
            CHUNK_SIZE = 3200
            CHANNELS = 1
            
            # Queue for audio chunks
            audio_queue = asyncio.Queue()
            recording = True
            
            # Output audio queue for playing to device
            output_audio_queue = asyncio.Queue()
            
            # Start audio playback task if output device is specified
            if self.output_device is not None and self.output_device >= 0:
                self._status(f"Will output translated audio to device {self.output_device}")
                playback_task = asyncio.create_task(self._play_audio_to_device(output_audio_queue))
            
            def audio_callback(indata, frames, time, status):
                if status:
                    print(f"Audio input status: {status}")
                audio_data = indata.astype(np.int16).tobytes()
                if recording:
                    try:
                        audio_queue.put_nowait(audio_data)
                    except asyncio.QueueFull:
                        pass
            
            # Import websockets here to ensure it's properly loaded
            import websockets
            from websockets import Headers
            
            # Connect to server
            conn_id = str(os.urandom(16).hex())
            headers = Headers({
                "X-Api-Key": conf.app_key,
                "X-Api-Resource-Id": conf.resource_id,
            })
            
            self._status(f"Connecting to {conf.ws_url}")
            
            try:
                conn = await websockets.connect(
                    conf.ws_url,
                    additional_headers=headers,
                    max_size=1000000000,
                    ping_interval=None
                )
                log_id = conn.response.headers.get('X-Tt-Logid')
                self._status(f"Connected to server (log_id={log_id})")
            except Exception as e:
                self._error(f"Connection failed: {e}")
                return
            
            # Import protobuf modules
            from meet_translator import (
                TranslateRequest, TranslateResponse, ReqParams, Type,
                TranslateRequestData, TranslateResponseData, Audio, MessageToDict
            )
            
            session_id = str(os.urandom(16).hex())
            self._status(f"Starting session (ID={session_id[:8]}...)")
            
            # Send start session request
            from google.protobuf.json_format import MessageToDict
            
            async def send_request(ws, request):
                request_data = TranslateRequest()
                request_data.request_meta.SessionID = request.session_id
                if request.event == "Type_StartSession":
                    request_data.event = Type.StartSession
                elif request.event == "Type_TaskRequest":
                    request_data.event = Type.TaskRequest
                elif request.event == "Type_FinishSession":
                    request_data.event = Type.FinishSession
                request_data.user.uid = "ast_py_client"
                request_data.user.did = "ast_py_client"
                request_data.source_audio.format = "wav"
                request_data.source_audio.rate = 16000
                request_data.source_audio.bits = 16
                request_data.source_audio.channel = 1
                if request.source_audio and request.source_audio.binary_data:
                    request_data.source_audio.binary_data = request.source_audio.binary_data
                request_data.target_audio.format = "ogg_opus"
                request_data.target_audio.rate = 24000
                request_data.request.mode = "s2s"
                request_data.request.source_language = "zh"
                request_data.request.target_language = "en"
                await ws.send(request_data.SerializeToString())
            
            async def receive_message(ws):
                response = await ws.recv()
                Response_data = TranslateResponse()
                Response_data.ParseFromString(response)
                
                response_text = Response_data.text
                if Response_data.event == Type.UsageResponse:
                    response_dict = MessageToDict(Response_data)
                    response_text = str(response_dict)
                
                return TranslateResponseData(
                    event=Response_data.event,
                    session_id=Response_data.response_meta.SessionID,
                    sequence=Response_data.response_meta.Sequence,
                    text=response_text,
                    data=Response_data.data,
                    spk_chg=Response_data.spk_chg,
                    message=Response_data.response_meta.Message
                )
            
            start_request = TranslateRequestData(
                session_id=session_id,
                event="Type_StartSession",
                source_audio=Audio(format="wav", codec="pcm_s16le", language="zh", 
                                 rate=SAMPLE_RATE, bits=16, channel=CHANNELS),
                target_audio=Audio(format="ogg", codec="opus", language="en", 
                                 rate=24000, bits=16, channel=1),
                mode="s2s",
                source_language="zh",
                target_language="en"
            )
            
            try:
                await send_request(conn, start_request)
                resp = await receive_message(conn)
                if resp.event != Type.SessionStarted:
                    self._error(f"Failed to start session: {resp.message}")
                    await conn.close()
                    return
                self._status(f"Session started successfully!")
            except Exception as e:
                self._error(f"Start session error: {e}")
                await conn.close()
                return
            
            # Start microphone recording
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype='int16',
                    blocksize=CHUNK_SIZE,
                    callback=audio_callback
                )
                stream.start()
                self._status("Microphone recording started. Speak in Chinese...")
            except Exception as e:
                self._error(f"Failed to start microphone: {e}")
                await conn.close()
                return
            
            # Send audio task
            async def send_audio():
                nonlocal recording
                try:
                    while recording or not audio_queue.empty():
                        try:
                            audio_data = await asyncio.wait_for(audio_queue.get(), timeout=1.0)
                            chunk_request = TranslateRequestData(
                                session_id=session_id,
                                event="Type_TaskRequest",
                                source_audio=Audio(binary_data=audio_data)
                            )
                            await send_request(conn, chunk_request)
                        except asyncio.TimeoutError:
                            continue
                        except Exception as e:
                            self._error(f"Error sending audio: {e}")
                            break
                except Exception as e:
                    self._error(f"Send audio error: {e}")
                finally:
                    finish_request = TranslateRequestData(
                        session_id=session_id,
                        event="Type_FinishSession",
                        source_audio=Audio()
                    )
                    try:
                        await send_request(conn, finish_request)
                    except Exception as e:
                        pass
            
            sender_task = asyncio.create_task(send_audio())
            
            # Receive responses
            audio_buffer = bytearray()
            last_audio_seq = -1
            
            try:
                while self.running:
                    resp = await receive_message(conn)
                    
                    if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                        self._error(f"Session failed: {resp.message}")
                        break
                    
                    if resp.event == Type.SessionFinished:
                        self._status("Session finished by server.")
                        break
                    
                    if resp.event == Type.UsageResponse:
                        continue
                    
                    if resp.event in [651, 654, 655]:
                        if resp.text.strip():
                            self._translate(resp.text)
                    
                    elif resp.event == 352:
                        if len(resp.data) > 0:
                            audio_buffer.extend(resp.data)
                    
                    elif resp.event == 351:
                        if resp.sequence != last_audio_seq:
                            if len(audio_buffer) > 0:
                                pcm_data = decode_opus(bytes(audio_buffer))
                                
                                if self.output_device is not None and self.output_device >= 0 and pcm_data:
                                    await output_audio_queue.put(pcm_data)
                                
                                audio_buffer.clear()
                                last_audio_seq = resp.sequence
                        audio_buffer.clear()
            
            except Exception as e:
                self._error(f"Receive error: {e}")
            finally:
                recording = False
                stream.stop()
                stream.close()
                
                try:
                    await asyncio.wait_for(sender_task, timeout=5.0)
                except:
                    pass
                
                if self.output_device is not None and self.output_device >= 0 and 'playback_task' in locals():
                    try:
                        await output_audio_queue.put(None)
                        await asyncio.wait_for(playback_task, timeout=3.0)
                    except:
                        pass
                
                await conn.close()
                self._status("Disconnected from server")
        
        except Exception as e:
            import traceback
            self._error(f"Unexpected error: {e}")
            self._error(f"Traceback: {traceback.format_exc()}")
    
    async def _play_audio_to_device(self, audio_queue):
        """Play audio chunks from queue to specified audio device"""
        output_stream = None
        try:
            output_stream = sd.OutputStream(
                samplerate=24000,
                channels=1,
                dtype='int16',
                device=self.output_device
            )
            output_stream.start()
            
            while True:
                audio_data = await audio_queue.get()
                if audio_data is None:
                    break
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                output_stream.write(audio_array)
        except Exception as e:
            self._error(f"Audio playback error: {e}")
        finally:
            if output_stream:
                output_stream.stop()
                output_stream.close()
    
    def stop(self):
        self.running = False