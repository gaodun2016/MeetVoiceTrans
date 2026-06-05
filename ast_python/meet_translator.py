import asyncio
import uuid
import os
from pathlib import Path
from dataclasses import dataclass
import logging
from typing import Optional, List
import websockets
from websockets import Headers
import sys
import time
import json
import numpy as np
import sounddevice as sd
from google.protobuf.json_format import MessageToDict

# Handle different websockets versions
try:
    from websockets.legacy.exceptions import InvalidStatusCode
except ImportError:
    try:
        from websockets.exceptions import InvalidStatusCode
    except ImportError:
        InvalidStatusCode = Exception

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 计算 python_protogen 目录的路径
protogen_dir = os.path.join(current_dir, "python_protogen")

# 设置 pydub 使用打包后的 ffmpeg
# 在打包后的应用中，ffmpeg 可能在以下位置：
# 1. 当前目录下的 ffmpeg 子目录
# 2. PyInstaller 打包的 Frameworks 目录
# 3. 系统路径

# 尝试多个可能的 ffmpeg 路径
possible_ffmpeg_paths = [
    os.path.join(current_dir, 'ffmpeg', 'ffmpeg'),
    os.path.join(current_dir, '..', 'Frameworks', 'ffmpeg', 'ffmpeg'),
    os.path.join(current_dir, 'Frameworks', 'ffmpeg', 'ffmpeg'),
]

# 添加到环境变量 PATH
for ffmpeg_dir in possible_ffmpeg_paths:
    ffmpeg_dir = os.path.dirname(ffmpeg_dir)
    if os.path.exists(ffmpeg_dir):
        os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']

# 尝试导入 pydub 并设置 ffmpeg 路径
try:
    from pydub import AudioSegment
    
    # 查找可用的 ffmpeg
    import shutil
    ffmpeg_path = shutil.which('ffmpeg')
    
    # 如果在系统路径中找不到，尝试打包路径
    if not ffmpeg_path:
        for path in possible_ffmpeg_paths:
            if os.path.exists(path):
                ffmpeg_path = path
                break
    
    if ffmpeg_path:
        AudioSegment.converter = ffmpeg_path
        print(f"[INFO] Using ffmpeg: {ffmpeg_path}")
    else:
        print("[WARNING] ffmpeg not found! Audio playback may not work correctly.")
except ImportError:
    pass

# 只添加一次 python_protogen 目录
sys.path.append(protogen_dir)

# 现在可以直接导入所有模块
from products.understanding.ast.ast_service_pb2 import TranslateRequest, ReqParams, TranslateResponse
from common.events_pb2 import Type

# Configuration
@dataclass
class Config:
    ws_url: str
    app_key: str
    resource_id: str
    # Add other config fields as needed


@dataclass
class Audio:
    format: str = None
    codec: Optional[str] = None
    language: Optional[str] = None
    rate: int = None
    bits: Optional[int] = None
    channel: Optional[int] = None
    binary_data: Optional[bytes] = None


@dataclass
class TranslateRequestData:
    session_id: str
    event: str
    source_audio: Optional[Audio] = None
    target_audio: Optional[Audio] = None
    mode: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None


@dataclass
class TranslateResponseData:
    event: str
    session_id: str
    sequence: int
    text: str
    data: bytes
    spk_chg: bool
    message: str = None


async def read_audio_chunks(audio_path: str, chunk_size: int) -> List[bytes]:
    """Read audio file in chunks"""
    chunks = []
    with open(audio_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
    return chunks


async def play_audio_to_device(audio_queue, device_id):
    """Play audio chunks from queue to specified audio device"""
    output_stream = None
    try:
        output_stream = sd.OutputStream(
            samplerate=24000,
            channels=1,
            dtype='int16',
            device=device_id
        )
        output_stream.start()
        print(f"[PLAYBACK] Started audio output to device {device_id}")
        
        while True:
            try:
                audio_data = await audio_queue.get()
                if audio_data is None:
                    break  # Signal to stop
                # Audio data is already decoded to PCM, play directly
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                output_stream.write(audio_array)
                print(f"[PLAYBACK] Played {len(audio_data)} bytes of PCM audio")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[PLAYBACK ERROR] {e}")
    finally:
        if output_stream:
            output_stream.stop()
            output_stream.close()
        print(f"[PLAYBACK] Stopped audio output to device {device_id}")


def decode_opus(opus_data):
    """Decode audio data - server may return either Opus or PCM"""
    # Debug: print first bytes to identify format
    print(f"[DECODE DEBUG] Data length: {len(opus_data)} bytes, first 16 bytes: {opus_data[:16].hex()}")
    
    # Check for Ogg container (starts with 'OggS')
    if opus_data.startswith(b'OggS'):
        print("[DECODE] Detected Ogg container format")
        
        # Try using pydub with ffmpeg
        try:
            from io import BytesIO
            from pydub import AudioSegment
            
            # Set ffmpeg path for pydub
            import os
            os.environ['FFMPEG_BINARY'] = os.path.expanduser("~/.local/bin/ffmpeg")
            
            # Create AudioSegment from Ogg data
            audio = AudioSegment.from_file(BytesIO(opus_data), format="ogg")
            
            # Convert to 16-bit PCM, 24kHz, mono
            audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
            
            # Export as raw PCM bytes
            pcm_data = audio.raw_data
            print(f"[DECODE] pydub decoded {len(opus_data)} bytes to {len(pcm_data)} bytes PCM")
            return pcm_data
        except Exception as e:
            print(f"[DECODE ERROR] pydub: {type(e).__name__}: {e}")
            
        # Try using subprocess with ffmpeg
        try:
            import subprocess
            
            ffmpeg_path = os.path.expanduser("~/.local/bin/ffmpeg")
            
            # Use project directory for temporary files (usually not restricted by sandbox)
            temp_dir = "/Users/admin/Documents/MeetVoiceTrans/ast_python/tmp"
            os.makedirs(temp_dir, exist_ok=True)
            
            import uuid
            input_path = os.path.join(temp_dir, f"input_{uuid.uuid4().hex}.ogg")
            output_path = os.path.join(temp_dir, f"output_{uuid.uuid4().hex}.pcm")
            
            try:
                # Write input file and ensure it's flushed to disk
                with open(input_path, 'wb') as f:
                    f.write(opus_data)
                    f.flush()
                    os.fsync(f.fileno())
                
                # Check if file exists and has content
                if not os.path.exists(input_path):
                    print(f"[DECODE ERROR] Input file not created: {input_path}")
                    raise FileNotFoundError(f"Input file not created: {input_path}")
                
                file_size = os.path.getsize(input_path)
                print(f"[DECODE DEBUG] Input file size: {file_size} bytes")
                
                if file_size == 0:
                    print(f"[DECODE ERROR] Input file is empty")
                    raise ValueError("Input file is empty")
                
                # Use ffmpeg to decode
                cmd = [
                    ffmpeg_path,
                    '-y',
                    '-i', input_path,
                    '-f', 's16le',
                    '-acodec', 'pcm_s16le',
                    '-ar', '24000',
                    '-ac', '1',
                    '-loglevel', 'error',
                    output_path
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    with open(output_path, 'rb') as f:
                        pcm_data = f.read()
                    
                    if len(pcm_data) > 0:
                        print(f"[DECODE] ffmpeg decoded {len(opus_data)} bytes to {len(pcm_data)} bytes PCM")
                        return pcm_data
                    else:
                        print("[DECODE ERROR] ffmpeg produced empty output")
                else:
                    error_msg = result.stderr.decode() if result.stderr else "Unknown error"
                    print(f"[DECODE ERROR] ffmpeg failed (code {result.returncode}): {error_msg[:200]}")
            finally:
                try:
                    os.unlink(input_path)
                except:
                    pass
                try:
                    os.unlink(output_path)
                except:
                    pass
                    
        except FileNotFoundError:
            print(f"[DECODE ERROR] ffmpeg not found")
        except subprocess.TimeoutExpired:
            print("[DECODE ERROR] ffmpeg timeout")
        except Exception as e:
            print(f"[DECODE ERROR] subprocess error: {type(e).__name__}: {e}")
    
    # Try opuslib for raw Opus frames
    try:
        import opuslib
        decoder = opuslib.Decoder(24000, 1)
        pcm_data = decoder.decode(opus_data, frame_size=960)
        print(f"[DECODE] opuslib decoded {len(opus_data)} bytes to {len(pcm_data)} bytes PCM")
        return pcm_data
    except ImportError:
        print("[WARNING] opuslib not available")
    except Exception as e:
        print(f"[DECODE ERROR] opuslib: {type(e).__name__}: {e}")
    
    # Fallback: return as-is if even length (possible PCM)
    if len(opus_data) % 2 == 0:
        print(f"[DECODE] Returning as PCM: {len(opus_data)} bytes")
        return opus_data
    
    # For odd-length data, try padding
    padded_data = opus_data + b'\x00'
    print(f"[DECODE] Padded to {len(padded_data)} bytes, returning as PCM")
    return padded_data
    
    # Try opuslib for raw Opus frames
    try:
        import opuslib
        decoder = opuslib.Decoder(24000, 1)
        pcm_data = decoder.decode(opus_data, frame_size=960)
        print(f"[DECODE] opuslib decoded {len(opus_data)} bytes to {len(pcm_data)} bytes PCM")
        return pcm_data
    except ImportError:
        print("[WARNING] opuslib not available")
    except Exception as e:
        print(f"[DECODE ERROR] opuslib: {type(e).__name__}: {e}")
    
    # Fallback: return as-is if even length (possible PCM)
    if len(opus_data) % 2 == 0:
        print(f"[DECODE] Returning as PCM: {len(opus_data)} bytes")
        return opus_data
    
    # For odd-length data, try padding
    padded_data = opus_data + b'\x00'
    print(f"[DECODE] Padded to {len(padded_data)} bytes, returning as PCM")
    return padded_data


async def send_request(ws, request: TranslateRequestData):
    """Send request to WebSocket server"""
    # Implement your actual protocol serialization here
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
    if request.source_audio.binary_data:
        request_data.source_audio.binary_data = request.source_audio.binary_data
    request_data.target_audio.format = "ogg_opus"
    request_data.target_audio.rate = 24000
    request_data.request.mode = "s2s"
    request_data.request.source_language = "zh"
    request_data.request.target_language = "en"
    await ws.send(request_data.SerializeToString())  # Replace with your actual serialization


async def receive_message(ws) -> TranslateResponseData:
    """Receive and parse response from server"""
    response = await ws.recv()
    # Implement your actual protocol deserialization here
    # This is a placeholder - adapt to your actual response format
    Response_data = TranslateResponse()
    Response_data.ParseFromString(response)

    response_text = Response_data.text # Extract from actual response
    if Response_data.event == Type.UsageResponse:
        # 将 protobuf 消息转换为字典
        response_dict = MessageToDict(Response_data)
        # 以 JSON 格式打印，设置缩进和确保 ASCII 不转义
        #print("Response content (event=154):")
        #print(json.dumps(response_dict, indent=2, ensure_ascii=False))
        response_text = json.dumps(response_dict, indent=2, ensure_ascii=False)

    return TranslateResponseData(
        event=Response_data.event,  # Extract from actual response
        session_id=Response_data.response_meta.SessionID,  # Extract from actual response
        sequence=Response_data.response_meta.Sequence,  # Extract from actual response
        text=response_text,
        data=Response_data.data,  # Extract from actual response
        spk_chg=Response_data.spk_chg,  # Extract from actual response
        message= Response_data.response_meta.Message
    )


async def build_http_headers(conf: Config, conn_id: str) -> Headers:
    """Build WebSocket connection headers from config"""
    headers = Headers({
        "X-Api-Key": conf.app_key,
        "X-Api-Resource-Id": conf.resource_id,
    })
    return headers

async def translate_v4_microphone(conf: Config, out_dir: str = "output", output_device: int = None):
    """Main translation function using microphone input with virtual audio output"""
    # Audio recording settings
    SAMPLE_RATE = 16000
    CHUNK_SIZE = 3200  # 100ms chunks
    CHANNELS = 1
    
    # Queue for audio chunks
    audio_queue = asyncio.Queue()
    recording = True
    session_id = None  # Initialize session_id
    
    # Output audio queue for playing to device
    output_audio_queue = asyncio.Queue()
    
    # Start audio playback task if output device is specified
    if output_device is not None:
        print(f"[CONFIG] Will output translated audio to device {output_device}")
        playback_task = asyncio.create_task(play_audio_to_device(output_audio_queue, output_device))
    
    def audio_callback(indata, frames, time, status):
        """Callback function for audio input"""
        if status:
            logging.warning(f"Audio input status: {status}")
        # Convert to bytes and put in queue
        audio_data = indata.astype(np.int16).tobytes()
        if recording:
            try:
                audio_queue.put_nowait(audio_data)
            except asyncio.QueueFull:
                pass  # Skip if queue is full
    
    # Connect to server
    try:
        conn_id = str(uuid.uuid4())
        headers = await build_http_headers(conf, conn_id)
        conn = await websockets.connect(
            conf.ws_url,
            additional_headers=headers,
            max_size = 1000000000,
            ping_interval = None
        )
        logging.info(f"Connected to server (log id={conn.response.headers.get('X-Tt-Logid')})")
        log_id = conn.response.headers.get('X-Tt-Logid')
    except Exception as e:
        logging.error(f"Connect: {e}")
        # Better error handling - don't assume e.response exists
        try:
            if hasattr(e, 'response') and e.response:
                logging.error(f"Response headers: {e.response.headers}")
        except:
            pass
        return

    session_id = str(uuid.uuid4())
    logging.info(f"Starting session (ID={session_id})...")

    # Start session
    start_request = TranslateRequestData(
        session_id=session_id,
        event="Type_StartSession",
        source_audio=Audio(format="wav", codec="pcm_s16le", language="zh", rate=SAMPLE_RATE, bits=16, channel=CHANNELS),
        target_audio=Audio(format="ogg", codec="opus", language="en", rate=24000, bits=16, channel=1),
        mode="s2s",
        source_language="zh",
        target_language="en"
    )

    try:
        await send_request(conn, start_request)
        resp = await receive_message(conn)
        if resp.event != Type.SessionStarted:
            logging.error(f"Failed to start session - logid: {log_id}")
            logging.error(f"Response: {resp.event}")
            logging.error(f"Message: {resp.message}")
            await conn.close()
            return
        logging.info(f"Session (ID={session_id}) started successfully!")
    except Exception as e:
        logging.error(f"Start session error: {e}")
        await conn.close()
        return

    # Start microphone recording in a separate thread
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='int16',
            blocksize=CHUNK_SIZE,
            callback=audio_callback
        )
        stream.start()
        logging.info("Microphone recording started...")
        logging.info("Speak in Chinese, the translation will appear below...")
        logging.info("Press Ctrl+C to stop...")
    except Exception as e:
        logging.error(f"Failed to start microphone: {e}")
        await conn.close()
        return

    # Send audio chunks from queue
    async def send_audio_from_queue():
        """Continuously send audio chunks from the queue"""
        try:
            while recording or not audio_queue.empty():
                try:
                    # Wait for audio data with timeout
                    audio_data = await asyncio.wait_for(audio_queue.get(), timeout=1.0)
                    chunk_request = TranslateRequestData(
                        session_id=session_id,
                        event="Type_TaskRequest",
                        source_audio=Audio(binary_data=audio_data)
                    )
                    await send_request(conn, chunk_request)
                    # logging.info(f"Sent chunk: {len(audio_data)} bytes")
                except asyncio.TimeoutError:
                    continue  # No data in queue, continue waiting
                except Exception as e:
                    logging.error(f"Error sending audio: {e}")
                    break
        except Exception as e:
            logging.error(f"Send audio error: {e}")
        finally:
            # Send finish session when stopping
            logging.info("Sending FinishSession request...")
            finish_request = TranslateRequestData(
                session_id=session_id,
                event="Type_FinishSession",
                source_audio=Audio()
            )
            try:
                await send_request(conn, finish_request)
                logging.info("FinishSession request sent.")
            except Exception as e:
                logging.error(f"Error sending FinishSession: {e}")

    # Start sender task
    sender_task = asyncio.create_task(send_audio_from_queue())

    # Receive responses
    recv_audio = bytearray()
    recv_text = []
    audio_buffer = bytearray()  # Buffer for accumulating Ogg audio chunks
    last_audio_seq = -1  # Track last processed audio sequence to prevent duplicates

    try:
        while True:
            resp = await receive_message(conn)
            
            # Debug: print all events
            print(f"[DEBUG] Received event type: {resp.event}, text length: {len(resp.text) if resp.text else 0}")

            if resp.event == Type.SessionFailed or resp.event == Type.SessionCanceled:
                logging.error(f"Session failed - logid: {log_id}, message: {resp.message}")
                break

            if resp.event == Type.SessionFinished:
                logging.info("Session finished by server.")
                break

            if resp.event == Type.UsageResponse:
                continue  # Skip usage response

            # Log translation results with detailed information
            if resp.event in [651, 654, 655]:  # Subtitle events
                if resp.text.strip():
                    # Print translation result with more details
                    print("-" * 60)
                    print(f"[TRANSLATION RESULT]")
                    print(f"  Event Type: {resp.event}")
                    print(f"  Session ID: {resp.session_id[:8]}...")
                    print(f"  Sequence: {resp.sequence}")
                    print(f"  Text: {resp.text}")
                    print("-" * 60)
                    logging.info(f"[Translation] Seq={resp.sequence} | {resp.text}")
                    recv_text.append(resp.text)
            elif resp.event == 352:  # TTS audio chunk
                if len(resp.data) > 0:
                    audio_buffer.extend(resp.data)  # Accumulate audio chunks
                    recv_audio.extend(resp.data)
                    logging.info(f"[Audio] Received {len(resp.data)} bytes of TTS audio")
                    
                    # Real-time save audio chunk (disabled - output to file commented out)
                    # os.makedirs(out_dir, exist_ok=True)
                    # audio_output_path = Path(out_dir) / f"translate_audio_{session_id[:8] if session_id else 'unknown'}.opus"
                    # try:
                    #     with open(audio_output_path, 'ab') as f:
                    #         f.write(resp.data)
                    #     print(f"[SAVE] Audio chunk saved: {len(resp.data)} bytes")
                    # except Exception as e:
                    #     print(f"[ERROR] Failed to save audio: {e}")
            elif resp.event == 351:  # Audio end marker
                # Check for duplicate sequence
                import time
                timestamp = time.strftime("%H:%M:%S.%f")
                if resp.sequence == last_audio_seq:
                    print(f"[{timestamp}] [AUDIO END] Duplicate sequence {resp.sequence}, skipping...")
                    recv_audio.extend(resp.data)
                    logging.info(f"Event 351: ")
                    continue
                
                # Decode and play accumulated audio
                if len(audio_buffer) > 0:
                    print(f"[{timestamp}] [AUDIO END] Decoding {len(audio_buffer)} bytes accumulated audio...")
                    pcm_data = decode_opus(bytes(audio_buffer))
                    
                    # Send decoded audio to virtual output device if configured
                    if output_device is not None and pcm_data:
                        try:
                            await output_audio_queue.put(pcm_data)
                            print(f"[{timestamp}] [PLAYBACK] Sent {len(pcm_data)} bytes to output device, queue size: {output_audio_queue.qsize()}")
                        except Exception as e:
                            print(f"[PLAYBACK ERROR] Failed to queue audio: {e}")
                    
                    # Clear buffer immediately after sending
                    audio_buffer.clear()
                    print(f"[{timestamp}] [AUDIO BUFFER] Cleared, size: {len(audio_buffer)}")
                    last_audio_seq = resp.sequence
                else:
                    print(f"[{timestamp}] [AUDIO END] Audio buffer is empty, skipping...")
                recv_audio.extend(resp.data)
                logging.info(f"Event 351: ")
            else:
                # Print other events with details
                if resp.text and resp.text.strip():
                    print(f"[OTHER EVENT] Type={resp.event}, Session={resp.session_id[:8]}...")
                    print(f"  Message: {resp.text[:200]}..." if len(resp.text) > 200 else f"  Message: {resp.text}")
                logging.info(f"Event {resp.event}: {resp.text[:100]}..." if len(str(resp.text)) > 100 else f"Event {resp.event}: {resp.text}")

    except Exception as e:
        logging.error(f"Receive message error: {e}")
    finally:
        # Stop recording
        recording = False
        stream.stop()
        stream.close()
        logging.info("Microphone recording stopped.")

        # Wait for sender to finish
        try:
            await asyncio.wait_for(sender_task, timeout=5.0)
        except asyncio.TimeoutError:
            logging.warning("Sender task timeout, forcing close.")
        except Exception as e:
            logging.error(f"Error waiting for sender: {e}")

        # Stop audio playback task if running
        if output_device is not None and 'playback_task' in locals():
            try:
                # Send stop signal to playback task
                await output_audio_queue.put(None)
                await asyncio.wait_for(playback_task, timeout=3.0)
                logging.info("Audio playback task stopped.")
            except asyncio.TimeoutError:
                logging.warning("Playback task timeout, forcing close.")
                playback_task.cancel()
            except Exception as e:
                logging.error(f"Error stopping playback task: {e}")

        await conn.close()

    # Save results (disabled - output to file commented out)
    # if recv_audio:
    #     os.makedirs(out_dir, exist_ok=True)
    #     output_path = Path(out_dir) / f"translate_audio_mic_{int(time.time())}.opus"
    #     try:
    #         with open(output_path, 'wb') as f:
    #             f.write(recv_audio)
    #         logging.info(f"TTS audio saved as: {output_path}")
    #     except Exception as e:
    #         logging.error(f"Save audio file: {e}")

    if recv_text:
        logging.info(f"=== Translation Results ===")
        logging.info(f"{' '.join(recv_text)}")
        logging.info(f"===========================")
        
        # Save translation text to file (disabled)
        # print(f"\n[DEBUG] recv_text has {len(recv_text)} items")
        # print(f"[DEBUG] session_id = {session_id}")
        
        # os.makedirs(out_dir, exist_ok=True)
        # text_output_path = Path(out_dir) / f"translate_text_{int(time.time())}.txt"
        # print(f"[DEBUG] Saving to: {text_output_path}")
        
        # try:
        #     with open(text_output_path, 'w', encoding='utf-8') as f:
        #         f.write("=== Translation Results ===\n")
        #         if session_id:
        #             f.write(f"Session ID: {session_id}\n")
        #         f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        #         f.write("=" * 60 + "\n\n")
        #         for i, text in enumerate(recv_text, 1):
        #             f.write(f"{i}. {text}\n")
        #         f.write("\n" + "=" * 60 + "\n")
        #         f.write("Full text:\n")
        #         f.write(' '.join(recv_text))
        #     logging.info(f"Translation text saved as: {text_output_path}")
        #     print(f"\n[SAVE] Translation text saved to: {text_output_path}")
        #     print(f"[SAVE] File size: {os.path.getsize(text_output_path)} bytes")
        # except Exception as e:
        #     logging.error(f"Save text file: {e}")
        #     print(f"[ERROR] Failed to save: {e}")
    else:
        print("\n[DEBUG] recv_text is empty, nothing to save")


# Example usage
async def main(output_device=None):
    conf = Config(ws_url="wss://openspeech.bytedance.com/api/v4/ast/v2/translate",
                   app_key="91a2aed7-1566-4872-be25-de03af780fda",
                  resource_id="volc.service_type.10053")
    
    logging.info("="*60)
    logging.info("Starting real-time speech translation from microphone...")
    if output_device is not None:
        logging.info(f"Output device: {output_device}")
    logging.info("="*60)
    
    start = time.time()
    try:
        await translate_v4_microphone(conf, "output", output_device)
    except KeyboardInterrupt:
        logging.info("\nStopping...")
    
    end = time.time()
    logging.info(f"Total time: {end - start:.6f} 秒")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Real-time speech translation with virtual audio output')
    parser.add_argument('-o', '--output-device', type=int, default=None, 
                        help='Audio output device ID for virtual audio (use -l to list devices)')
    parser.add_argument('-l', '--list-devices', action='store_true', 
                        help='List all available audio devices')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    if args.list_devices:
        print("=== Available Audio Devices ===")
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            print(f"\n{i}: {dev['name']}")
            print(f"  Input channels: {dev['max_input_channels']}")
            print(f"  Output channels: {dev['max_output_channels']}")
        print("\nTo use virtual audio output, run:")
        print("  python3 ast_demo.py -o <device_id>")
        exit(0)
    
    print("=== Script started ===")
    logging.info("=== Script started ===")
    try:
        asyncio.run(main(args.output_device))
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Error: {e}")
        import traceback
        traceback.print_exc()