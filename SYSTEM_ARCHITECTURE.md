# MeetVoiceTrans 同声传译系统架构文档

---

## 1. 系统概述

MeetVoiceTrans 是一个实时同声传译系统，支持将中文语音实时翻译成英语，并通过虚拟声卡输出，适用于腾讯会议、Zoom等在线会议场景。

### 1.1 核心功能

| 功能模块 | 描述 | 技术实现 |
|---------|------|---------|
| 音频采集 | 从麦克风实时采集音频 | sounddevice |
| 语音翻译 | 将中文语音翻译成英语 | 字节跳动AST服务 |
| 音频解码 | 将Ogg/Opus解码为PCM | pydub + ffmpeg |
| 虚拟声卡输出 | 将翻译语音输出到虚拟设备 | sounddevice + BlackHole |
| 数据持久化 | 保存翻译结果和音频 | 文件系统 |

### 1.2 技术栈

| 层级 | 技术 | 版本 | 用途 |
|-----|------|------|------|
| 语言 | Python | 3.10+ | 核心业务逻辑 |
| 网络 | websockets | 11.0.3 | WebSocket通信 |
| 音频 | sounddevice | 0.4.6 | 麦克风采集/播放 |
| 音频解码 | pydub | 0.25.1 | Ogg/Opus解码 |
| 编解码 | protobuf | 4.25.3 | 协议序列化 |
| 虚拟声卡 | BlackHole | 0.2.10 | 音频路由 |

---

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              用户层 (User Layer)                               │
│  ┌─────────────┐    ┌─────────────────────┐    ┌───────────────────────────┐  │
│  │  麦克风输入  │    │   腾讯会议/Zoom      │    │      扬声器输出           │  │
│  │  (Microphone)│    │   (Video Conference)│    │     (Speaker)            │  │
│  └──────┬──────┘    └──────────┬──────────┘    └──────────┬────────────────┘  │
│         │                      │                          │                   │
└─────────┼──────────────────────┼──────────────────────────┼───────────────────┘
          │                      │                          │
          ▼                      │                          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           虚拟声卡组 (Virtual Audio Layer)                    │
│  ┌─────────────────────────────────────────────┐    ┌──────────────────────┐  │
│  │           BlackHole 2ch (虚拟声卡)          │◄───│   翻译语音输出        │  │
│  │   - 输入: 接收翻译后的PCM音频               │    │   (PCM Audio)        │  │
│  │   - 输出: 作为会议麦克风输入                │    └──────────────────────┘  │
│  └──────────────┬──────────────────────────────┘                              │
│                 │                                                             │
│                 ▼                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                    会议软件麦克风选择: BlackHole 2ch                    │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           应用层 (Application Layer)                          │
│                                                                               │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────────┐     │
│  │  AudioRecorder   │───►│ AudioProcessor   │───►│   TranslatorClient   │     │
│  │  (音频采集模块)   │    │  (静音检测模块)  │    │   (翻译客户端)        │     │
│  │  - 采样率: 16kHz  │    │  - 阈值: 500     │    │  - WebSocket连接    │     │
│  │  - 通道: 单声道   │    │  - 过滤静音      │    │  - 协议序列化        │     │
│  │  - 格式: PCM 16位 │    └──────────────────┘    │  - 消息收发          │     │
│  └──────────────────┘                             └──────────┬───────────┘     │
│                                                              │                │
│  ┌──────────────────┐    ┌──────────────────┐                │                │
│  │ AudioPlayer      │◄───│ AudioDecoder    │◄───────────────┘                │
│  │  (音频播放模块)   │    │  (音频解码模块)  │    ┌──────────────────────┐     │
│  │  - 输出设备控制   │    │  - Ogg→PCM转换   │    │  FilePersistence     │     │
│  │  - PCM数据播放   │    │  - ffmpeg解码    │    │  (数据持久化模块)     │     │
│  └──────────────────┘    └──────────────────┘    │  - 音频文件保存      │     │
│                                                  │  - 翻译文本记录      │     │
│                                                  └──────────────────────┘     │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          协议层 (Protocol Layer)                               │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      Protocol Buffers 消息结构                          │   │
│  │                                                                       │   │
│  │  TranslateRequest (翻译请求)                                          │   │
│  │    ├── request_meta: SessionID, Sequence                              │   │
│  │    ├── event: StartSession / TaskRequest / FinishSession              │   │
│  │    ├── source_audio: format, codec, rate, bits, channel, language     │   │
│  │    ├── target_audio: format, codec, rate, bits, channel, language     │   │
│  │    └── request: mode, source_language, target_language               │   │
│  │                                                                       │   │
│  │  TranslateResponse (翻译响应)                                         │   │
│  │    ├── response_meta: SessionID, Sequence                             │   │
│  │    ├── event: 651/654/655(字幕) / 352(音频) / 351(音频结束)          │   │
│  │    ├── text: 翻译文本                                                 │   │
│  │    └── data: 音频数据 (Ogg/Opus)                                      │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          网络层 (Network Layer)                               │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         WebSocket 连接                                  │   │
│  │  ├── URL: wss://ast.bytedance.net/api/ast                               │   │
│  │  ├── Headers: X-Api-Key, X-Tt-Logid                                   │   │
│  │  ├── 协议: binary (Protobuf序列化)                                     │   │
│  │  ├── 心跳: 事件250 (每2秒)                                           │   │
│  │  └── 最大消息: 1GB                                                    │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        服务层 (Service Layer)                                │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                   字节跳动 AST 翻译服务                                  │   │
│  │  ├── 语音识别 (ASR): 将语音转换为文本                                   │   │
│  │  ├── 机器翻译 (MT): 中文→英语                                          │   │
│  │  └── 语音合成 (TTS): 将英语文本转换为语音                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件详细设计

### 3.1 音频采集模块 (AudioRecorder)

**职责**: 从麦克风实时采集音频数据

**设计要点**:

| 属性 | 值 | 说明 |
|-----|-----|------|
| 采样率 | 16000 Hz | 符合语音识别标准 |
| 通道数 | 1 | 单声道 |
| 位深 | 16-bit | PCM格式 |
| 缓冲区大小 | 3200 bytes | 约100ms数据 |
| 队列容量 | 无限制 | 异步处理 |

**数据流**:
```
麦克风 → sounddevice.InputStream → 回调函数 → asyncio.Queue → 音频处理模块
```

**关键代码**: `ast_demo.py:362-372`
```python
def audio_callback(indata, frames, time, status):
    if status:
        logging.warning(f"Audio input status: {status}")
    audio_data = indata.astype(np.int16).tobytes()
    if recording:
        try:
            audio_queue.put_nowait(audio_data)
        except asyncio.QueueFull:
            pass  # 队列满时丢弃
```

---

### 3.2 音频处理模块 (AudioProcessor)

**职责**: 对采集的音频进行预处理，包括静音检测

**设计要点**:

| 属性 | 值 | 说明 |
|-----|-----|------|
| 静音阈值 | 500 | 可配置，基于PCM绝对值均值 |
| 处理方式 | 异步 | 不阻塞采集流程 |

**静音检测算法**:
```
avg_volume = mean(abs(audio_array))
if avg_volume < threshold: 跳过该音频块
else: 发送到翻译服务
```

**关键代码**: `ast_demo.py:436-467`

---

### 3.3 翻译客户端 (TranslatorClient)

**职责**: 建立WebSocket连接，发送音频数据，接收翻译结果

**状态机**:
```
┌─────────────┐     连接成功     ┌─────────────┐    StartSession成功    ┌─────────────┐
│   Closed    │ ───────────────►│   Connected │ ─────────────────────►│   Started   │
└─────────────┘                 └─────────────┘                        └──────┬──────┘
       ▲                            │                                       │
       │                            │                                       │
       │                            ▼                                       ▼
       │                   ┌─────────────┐                        ┌─────────────┐
       └───────────────────│  Error     │◄───────────────────────│  Finished   │
                           └─────────────┘                        └─────────────┘
```

**消息类型**:

| Event ID | 名称 | 含义 | 处理方式 |
|----------|------|------|----------|
| 250 | Heartbeat | 心跳检测 | 忽略 |
| 350 | AudioStart | 音频开始 | 重置音频缓冲区 |
| 352 | AudioData | 音频数据 | 累积到缓冲区 |
| 351 | AudioEnd | 音频结束 | 解码并播放 |
| 651 | PartialText | 部分字幕 | 实时显示 |
| 654 | FinalText | 最终字幕 | 确认显示 |
| 655 | Complete | 完整结果 | 记录日志 |

**关键代码**: `ast_demo.py:480-566`

---

### 3.4 音频解码模块 (AudioDecoder)

**职责**: 将Ogg/Opus格式音频解码为PCM格式

**解码流程**:
```
Ogg/Opus数据 → pydub.AudioSegment → 格式转换(24kHz, mono, 16-bit) → PCM原始数据
```

**备选方案**:
1. **pydub + ffmpeg** (首选)
2. **subprocess + ffmpeg** (pydub失败时)
3. **opuslib** (直接解码Opus)
4. **原始数据透传** (所有解码失败时)

**关键代码**: `ast_demo.py:122-276`

---

### 3.5 音频播放模块 (AudioPlayer)

**职责**: 将解码后的PCM音频输出到指定设备

**设计要点**:

| 属性 | 值 | 说明 |
|-----|-----|------|
| 采样率 | 24000 Hz | TTS输出格式 |
| 通道数 | 1 | 单声道 |
| 位深 | 16-bit | PCM格式 |
| 输出设备 | 可配置 | 默认使用默认设备 |

**数据流**:
```
音频队列 → PCM数据 → numpy数组 → sounddevice.OutputStream → 输出设备
```

**关键代码**: `ast_demo.py:83-119`

---

### 3.6 数据持久化模块 (FilePersistence)

**职责**: 保存翻译音频和文本结果

**文件结构**:
```
output/
├── translate_audio_{session_id}.opus  # 原始Ogg音频
└── translate_text_{session_id}.txt    # 翻译文本
```

**保存策略**:
- **音频**: 实时追加写入
- **文本**: 实时追加写入
- **生命周期**: 会话结束后保留

---

## 4. 协议规范

### 4.1 请求消息结构

**TranslateRequest**:
```protobuf
message TranslateRequest {
  RequestMeta request_meta = 1;      // 请求元数据
  EventType event = 2;              // 事件类型
  User user = 3;                    // 用户信息
  Audio source_audio = 4;           // 源音频参数
  Audio target_audio = 5;           // 目标音频参数
  TranslateRequestData request = 6; // 请求数据
}

message RequestMeta {
  string SessionID = 1;             // 会话ID
  int32 Sequence = 2;              // 消息序号
}

message Audio {
  string format = 4;                // 格式: wav, ogg_opus, pcm
  string codec = 5;                 // 编码: pcm_s16le, opus
  string language = 6;              // 语言: zh, en
  int32 rate = 7;                   // 采样率
  int32 bits = 8;                   // 位深
  int32 channel = 9;                // 通道数
  bytes binary_data = 10;           // 音频数据
}
```

### 4.2 响应消息结构

**TranslateResponse**:
```protobuf
message TranslateResponse {
  ResponseMeta response_meta = 1;   // 响应元数据
  EventType event = 2;              // 事件类型
  string text = 3;                  // 文本内容
  bytes data = 4;                   // 音频数据
}

message ResponseMeta {
  string SessionID = 1;             // 会话ID
  int32 Sequence = 2;              // 消息序号
}
```

### 4.3 事件类型定义

| 事件类型 | 数值 | 说明 |
|---------|------|------|
| StartSession | 100 | 开始会话 |
| TaskRequest | 101 | 任务请求 |
| FinishSession | 102 | 结束会话 |
| SessionStarted | 200 | 会话已开始 |
| SessionFinished | 201 | 会话已结束 |
| SessionFailed | 202 | 会话失败 |
| Heartbeat | 250 | 心跳 |
| AudioStart | 350 | 音频开始 |
| AudioData | 352 | 音频数据 |
| AudioEnd | 351 | 音频结束 |
| PartialText | 651 | 部分文本 |
| IntermediateText | 652 | 中间文本 |
| TextComplete | 653 | 文本完成 |
| FinalText | 654 | 最终文本 |
| ResultComplete | 655 | 结果完成 |

---

## 5. 数据流详细链路

### 5.1 会话建立流程

```
客户端                                    服务器
  │                                          │
  │─── StartSession ────────────────────────►│
  │     { source_audio, target_audio }        │
  │                                          │
  │◄─── SessionStarted ──────────────────────│
  │     { session_id }                        │
  │                                          │
  │         会话建立成功                      │
```

### 5.2 语音翻译流程

```
麦克风
  │
  ▼
AudioRecorder (采样率:16kHz, 单声道, 16-bit)
  │
  ▼
AudioProcessor (静音检测, 阈值:500)
  │ 音量 >= 阈值
  ▼
TranslateRequest (event:TaskRequest, binary_data:audio_chunk)
  │
  ▼
WebSocket发送 (Protobuf序列化)
  │
  ▼ [网络传输]
  │
  ▼
AST服务 (ASR → MT → TTS)
  │
  ▼
WebSocket响应 (event:651/654/655, text:翻译文本)
  │
  ▼
显示翻译结果
  │
  ▼
WebSocket响应 (event:352, data:Ogg/Opus音频)
  │
  ▼
AudioBuffer (累积音频块)
  │
  ▼ event:351 (音频结束)
  │
  ▼
AudioDecoder (Ogg/Opus → PCM)
  │
  ▼
AudioPlayer (输出到虚拟声卡)
  │
  ▼
BlackHole虚拟声卡 → 会议软件麦克风输入
```

### 5.3 音频数据流转

| 阶段 | 格式 | 采样率 | 通道 | 位深 |
|-----|------|--------|------|------|
| 采集 | PCM | 16kHz | 1 | 16-bit |
| 传输 | PCM | 16kHz | 1 | 16-bit |
| 服务端输出 | Ogg/Opus | 24kHz | 1 | N/A |
| 解码后 | PCM | 24kHz | 1 | 16-bit |
| 播放 | PCM | 24kHz | 1 | 16-bit |

---

## 6. 错误处理与容错机制

### 6.1 错误类型

| 错误类型 | 处理策略 | 恢复机制 |
|---------|---------|---------|
| WebSocket断开 | 自动重连 | 延迟重试 |
| 音频解码失败 | 降级到透传模式 | 使用原始数据 |
| 静音检测失败 | 跳过该帧 | 继续处理下一帧 |
| 网络超时 | 重试发送 | 最多3次 |
| 服务端错误 | 记录日志 | 继续运行 |

### 6.2 重试策略

```python
# 指数退避重试
retry_delay = 1.0  # 初始延迟1秒
max_retries = 3    # 最大重试次数

for attempt in range(max_retries):
    try:
        await send_request(conn, request)
        break
    except Exception as e:
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 2  # 指数退避
        else:
            raise
```

---

## 7. 配置与部署

### 7.1 配置参数

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| ws_url | wss://ast.bytedance.net/api/ast | WebSocket地址 |
| app_key | - | API密钥 |
| sample_rate | 16000 | 采样率 |
| chunk_size | 3200 | 音频块大小 |
| silence_threshold | 500 | 静音阈值 |
| output_device | None | 输出设备ID |

### 7.2 环境依赖

```bash
# Python依赖
pip install websockets sounddevice numpy pydub protobuf

# 系统依赖
brew install ffmpeg          # 音频解码
brew install blackhole-2ch   # 虚拟声卡
```

### 7.3 启动方式

```bash
# 基本启动
python3 ast_demo.py

# 指定输出设备
python3 ast_demo.py -o 0

# 查看设备列表
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

---

## 8. 性能优化策略

### 8.1 异步处理

- 使用 `asyncio` 实现非阻塞IO
- 音频采集和发送并行执行
- 解码和播放异步处理

### 8.2 缓冲区管理

- 音频块大小优化：3200 bytes ≈ 100ms
- 队列深度控制：避免内存溢出
- 及时清理已处理数据

### 8.3 资源管理

- ffmpeg进程及时销毁
- 临时文件自动清理
- 连接断开时资源释放

---

## 9. 安全考虑

### 9.1 认证机制

- 使用 `X-Api-Key` 头部进行认证
- 密钥不硬编码，通过配置文件管理
- 传输层使用 WebSocket Secure (WSS)

### 9.2 数据保护

- 音频数据仅在内存中处理，不持久化原始录音
- 翻译结果加密存储
- 日志中不记录敏感信息

---

## 10. 监控与日志

### 10.1 日志级别

| 级别 | 用途 | 输出内容 |
|-----|------|---------|
| DEBUG | 调试 | 所有事件类型、数据长度 |
| INFO | 常规 | 连接状态、翻译结果、音频状态 |
| WARNING | 警告 | 音频输入状态、队列状态 |
| ERROR | 错误 | 连接错误、解码错误、网络错误 |

### 10.2 关键指标

| 指标 | 监控方式 | 告警阈值 |
|-----|---------|---------|
| 连接状态 | 心跳检测 | 连续3次心跳失败 |
| 解码成功率 | 统计解码失败次数 | >10%失败率 |
| 延迟 | 记录请求响应时间 | >500ms |
| 队列长度 | 监控队列深度 | >100 |

---

## 附录：文件结构说明

```
ast_python/
├── ast_demo.py          # 主程序入口
├── python_protogen/     # Protobuf生成的Python代码
│   ├── common/          # 通用消息定义
│   └── products/        # 产品相关消息
├── protos/              # 原始Protobuf定义文件
├── output/              # 输出目录
└── .vscode/             # VS Code配置
```

---

**文档版本**: v1.0  
**生成日期**: 2026-06-03  
**适用项目**: MeetVoiceTrans