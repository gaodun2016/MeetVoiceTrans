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


class SimpleAEC:
    """简单的声学回声消除器 (Acoustic Echo Cancellation)
    
    使用自适应滤波器（NLMS算法）来消除回声
    """
    
    def __init__(self, filter_length=2048, mu=0.1, sample_rate=16000):
        """
        初始化 AEC
        
        Args:
            filter_length: 滤波器长度（样本数），越大能消除的延迟越长，但计算量越大
            mu: NLMS 步长参数，0.01-0.5 之间，越大收敛越快但可能不稳定
            sample_rate: 采样率
        """
        self.filter_length = filter_length
        self.mu = mu
        self.sample_rate = sample_rate
        
        # 滤波器系数（自适应权重）
        self.w = np.zeros(filter_length)
        
        # 参考信号缓冲区（存储最近播放的音频）
        self.x_buffer = np.zeros(filter_length)
        
        # 估计的回声信号
        self.echo_estimate = 0
        
        print(f"[AEC] SimpleAEC initialized: filter_length={filter_length}, mu={mu}, sample_rate={sample_rate}")
    
    def process(self, mic_input, speaker_output):
        """
        处理音频数据，消除回声
        
        Args:
            mic_input: 麦克风输入（numpy array，int16 或 float）
            speaker_output: 扬声器输出/参考信号（numpy array，int16 或 float）
        
        Returns:
            消除了回声的麦克风输入
        """
        # 转换为 float32（如果需要）
        if mic_input.dtype != np.float32:
            mic_input = mic_input.astype(np.float32) / 32768.0
        if speaker_output.dtype != np.float32:
            speaker_output = speaker_output.astype(np.float32) / 32768.0
        
        # 更新参考信号缓冲区
        self.x_buffer = np.roll(self.x_buffer, len(speaker_output))
        self.x_buffer[:len(speaker_output)] = speaker_output
        
        # 计算估计的回声：y = w * x
        self.echo_estimate = np.dot(self.w, self.x_buffer)
        
        # 计算误差（麦克风输入 - 估计的回声）
        error = mic_input - self.echo_estimate
        
        # 使用 NLMS 算法更新滤波器系数
        # w = w + mu * e * x / (x^T * x + epsilon)
        x_norm = np.dot(self.x_buffer, self.x_buffer) + 1e-8
        self.w = self.w + self.mu * error * self.x_buffer / x_norm
        
        # 限制滤波器系数的大小，避免发散
        max_coef = 10.0
        self.w = np.clip(self.w, -max_coef, max_coef)
        
        return error
    
    def reset(self):
        """重置滤波器状态"""
        self.w = np.zeros(self.filter_length)
        self.x_buffer = np.zeros(self.filter_length)
        self.echo_estimate = 0
        print("[AEC] Reset")


class TranslatorAdapter:
    def __init__(self, api_key, output_device=None, translation_enabled=True):
        self.api_key = api_key
        self.output_device = output_device
        self.translation_enabled = translation_enabled
        self.running = False
        self.translate_callback = None
        self.status_callback = None
        self.error_callback = None
        self.audio_callback = None
        self.conn = None  # WebSocket connection reference
        
        # 初始化 AEC（声学回声消除器）
        # 用于消除扬声器播放的翻译音频被麦克风重新捕捉产生的回声
        self.aec_enabled = True  # 默认开启 AEC
        self.aec = SimpleAEC(filter_length=2048, mu=0.1, sample_rate=16000)
        
        # 缓冲区用于存储播放的音频数据（作为 AEC 的参考信号）
        self.playback_buffer = b""
        self.playback_buffer_size = 16000 * 2  # 1秒的音频（16bit, 16kHz, mono）
    
    def set_aec_enabled(self, enabled):
        """启用/禁用 AEC（声学回声消除）"""
        self.aec_enabled = enabled
        if enabled:
            self.aec.reset()
            self._status("AEC 已开启，回声消除已启用")
        else:
            self._status("AEC 已关闭，回声消除已禁用")
    
    def set_translation_enabled(self, enabled):
        """Toggle translation without stopping connection"""
        self.translation_enabled = enabled
        status = "翻译功能已开启" if enabled else "翻译功能已关闭"
        self._status(status)
    
    def set_callbacks(self, translate_callback=None, status_callback=None, 
                     error_callback=None, audio_callback=None):
        self.translate_callback = translate_callback
        self.status_callback = status_callback
        self.error_callback = error_callback
        self.audio_callback = audio_callback
    
    def set_translate_callback(self, callback):
        """Set translate callback (for backward compatibility)"""
        self.translate_callback = callback
    
    def set_error_callback(self, callback):
        """Set error callback (for backward compatibility)"""
        self.error_callback = callback
    
    def set_status_callback(self, callback):
        """Set status callback (for backward compatibility)"""
        self.status_callback = callback
    
    async def start(self):
        """Start translation (alias for run)"""
        await self.run()
    
    def _status(self, msg):
        if self.status_callback:
            self.status_callback(msg)
    
    def _error(self, msg):
        if self.error_callback:
            self.error_callback(msg)
    
    def _translate(self, text):
        import time
        timestamp = time.strftime("%H:%M:%S.%f")
        print(f"[{timestamp}] TranslatorAdapter._translate called with text: '{text[:50]}...'")
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
                
                mic_input = indata.astype(np.int16)
                
                # 使用 AEC 处理音频，消除扬声器播放的回声
                if self.aec_enabled and len(self.playback_buffer) > 0:
                    # 获取最近播放的音频数据作为参考信号
                    # 延迟一段时间以模拟声学延迟（通常10-50ms）
                    delay_samples = int(0.03 * 16000)  # 30ms 延迟
                    start_pos = max(0, len(self.playback_buffer) - len(mic_input.tobytes()) - delay_samples)
                    reference_audio = self.playback_buffer[start_pos:start_pos + len(mic_input.tobytes())]
                    
                    if len(reference_audio) == len(mic_input.tobytes()):
                        reference_array = np.frombuffer(reference_audio, dtype=np.int16)
                        # 使用 AEC 处理
                        processed_audio = self.aec.process(mic_input, reference_array)
                        # 将处理后的音频转换回 int16
                        processed_audio = (processed_audio * 32768).astype(np.int16)
                        audio_data = processed_audio.tobytes()
                    else:
                        audio_data = mic_input.tobytes()
                else:
                    audio_data = mic_input.tobytes()
                
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
            
            # Create SSL context to bypass certificate verification issues
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            try:
                conn = await websockets.connect(
                    conf.ws_url,
                    additional_headers=headers,
                    max_size=1000000000,
                    ping_interval=None,
                    ssl=ssl_context
                )
                self.conn = conn  # Save connection reference for stop()
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
                            
                            if self.translation_enabled:
                                # Send audio to server for translation
                                chunk_request = TranslateRequestData(
                                    session_id=session_id,
                                    event="Type_TaskRequest",
                                    source_audio=Audio(binary_data=audio_data)
                                )
                                await send_request(conn, chunk_request)
                            else:
                                # When translation is disabled, directly output microphone audio to virtual device
                                # Need to resample from 16000Hz to 24000Hz
                                if self.output_device is not None and self.output_device >= 0:
                                    try:
                                        # Convert bytes to numpy array
                                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                                        
                                        # Resample from 16000Hz to 24000Hz
                                        # Simple linear interpolation resampling
                                        target_length = int(len(audio_array) * 24000 / 16000)
                                        resampled = np.interp(
                                            np.linspace(0, len(audio_array), target_length),
                                            np.arange(len(audio_array)),
                                            audio_array
                                        ).astype(np.int16)
                                        
                                        # Output to virtual device
                                        await output_audio_queue.put(resampled.tobytes())
                                        print(f"[DIRECT OUTPUT] Sent {len(resampled)} samples to virtual device")
                                    except Exception as e:
                                        print(f"[DIRECT OUTPUT ERROR] {e}")
                                
                                # 发送静音数据保持连接
                                # 创建3200个0值的int16数组（静音数据）并转换为字节流，用于网络传输
                                silent_audio = np.zeros(3200, dtype=np.int16).tobytes()
                                chunk_request = TranslateRequestData(
                                    session_id=session_id,
                                    event="Type_TaskRequest",
                                    source_audio=Audio(binary_data=silent_audio)
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
            pending_text = ""  # Buffer for accumulating partial text
            last_output_text = ""  # Track last output text to avoid duplicates
            
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
                            # 651: Partial/incremental result (accumulate only)
                            # 654: Sentence-level result (accumulate only)
                            # 655: Final result (output complete sentence)
                            
                            if resp.event == 655:
                                # 收到最终结果时，直接使用当前文本，不再累加
                                # 防止服务器重复返回导致重复输出
                                current_text = resp.text.strip()
                                
                                # 检查是否是完整句子（以句末标点结尾）
                                if current_text and (
                                    current_text.endswith('。') or
                                    current_text.endswith('.') or
                                    current_text.endswith('?') or
                                    current_text.endswith('！') or
                                    current_text.endswith('!')
                                ):
                                    # 检查是否与上次输出相同，避免重复
                                    if current_text != last_output_text:
                                        self._translate(current_text)
                                        last_output_text = current_text
                                    pending_text = ""  # 重置累积缓冲区
                                elif len(current_text) > 50:
                                    # 如果文本很长但没有句末标点，也输出
                                    if current_text != last_output_text:
                                        self._translate(current_text)
                                        last_output_text = current_text
                                    pending_text = ""  # 重置累积缓冲区
                            else:
                                # 非最终结果，累积到缓冲区
                                pending_text += resp.text
                    
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
            # Get device info to check supported channels
            device_info = sd.query_devices(self.output_device)
            max_channels = device_info.get('max_output_channels', 0)
            
            # Check if device has any output channels
            if max_channels == 0:
                raise ValueError(f"Device {self.output_device} ('{device_info.get('name', 'unknown')}') has no output channels")
            
            # Try mono first, fallback to stereo if mono is not supported
            channels = 1 if max_channels >= 1 else 2
            if max_channels < channels:
                channels = max_channels
            
            output_stream = sd.OutputStream(
                samplerate=24000,
                channels=channels,
                dtype='int16',
                device=self.output_device
            )
            output_stream.start()
            
            while True:
                audio_data = await audio_queue.get()
                if audio_data is None:
                    break
                
                # 将播放的音频数据存储到 playback_buffer 中，用于 AEC 处理
                self.playback_buffer += audio_data
                # 保持缓冲区大小在合理范围内
                if len(self.playback_buffer) > self.playback_buffer_size * 2:
                    self.playback_buffer = self.playback_buffer[-self.playback_buffer_size:]
                
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                
                # If using stereo output, convert mono to stereo
                if channels == 2:
                    audio_array = np.repeat(audio_array, 2)
                
                output_stream.write(audio_array)
        except ValueError as e:
            self._error(f"Audio playback configuration error: {e}")
        except Exception as e:
            self._error(f"Audio playback error: {e}")
            self._error(f"Device info: {device_info}")
            self._error(f"Tried to open with channels={channels}, samplerate=24000, dtype=int16")
        finally:
            if output_stream:
                output_stream.stop()
                output_stream.close()
    
    async def stop(self):
        """Stop translation and close connection"""
        self.running = False
        # 主动关闭 WebSocket 连接以中断等待
        if self.conn:
            try:
                await self.conn.close()
            except Exception as e:
                pass
        self.conn = None