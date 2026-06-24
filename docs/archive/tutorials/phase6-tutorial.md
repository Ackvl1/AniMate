# Phase 6 开发手册 · 语音识别 + 语音输出

> 目标：基于 Phase 3 的 I/O 适配器接口，实现实时语音对话——用户对着麦克风说话，祥子用语音回答，像打电话一样自然交流。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。
>
> **前置状态**：Phase 3 通用框架（`InputAdapter` / `OutputAdapter` / `EventBus` 就绪），Phase 5 Unity UI 已完成（语音输入可在 Unity 中使用麦克风按钮触发）。

---

## 你需要先有的认知

- **ASR（自动语音识别）**：把音频波形转成文字。实时对话一般走云端 API（DashScope 语音识别、OpenAI Whisper），延迟约 200~500ms。
- **TTS（文本转语音）**：把文字转成音频波形。需要低延迟方案——逐句合成 + 流式播放。
- **VAD（语音活动检测）**：判断当前是否有"有效语音"还是"静音"。最简单方案：用 `webrtcvad` 库做能量检测。
- **实时对话流水线**：`监听(VAD) → 录音 → ASR → Agent.chat() → TTS → 播放 → 回到监听`。总延迟目标 < 2 秒。

如果上面任何一条你觉得模糊，先去查清楚再继续。

---

## 总览

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| 1 | `requirements.txt` / `.env` | 加依赖和配置 |
| 2 | `animate/config.py` | **修改**：新增 ASR / TTS 客户端工厂 |
| 3 | `animate/io/audio_utils.py` | **新建**：录音、播放、VAD 音频工具 |
| 4 | `animate/io/asr.py` | **新建**：语音识别输入适配器 |
| 5 | `animate/io/tts.py` | **新建**：语音合成输出适配器 |
| 6 | `cli.py` | **修改**：支持 `--voice` 切换到语音模式 |
| 7 | 跑通 & 调优 | 实测延迟、VAD 灵敏度 |

---

## Step 1 · 环境准备

**requirements.txt 新增**：

```
pyaudio          # 或 sounddevice（Windows 更容易装）
webrtcvad        # VAD 语音活动检测
```

**.env 新增**（`.env.example` 同步）：

```
ANIMATE_ASR_PROVIDER=dashscope    # 或 openai
ANIMATE_TTS_PROVIDER=dashscope    # 或 openai
ANIMATE_TTS_VOICE=zh_female_1     # 音色 ID
```

---

## Step 2 · `animate/config.py` — 扩展配置

新增 `get_asr_client()` 和 `get_tts_client()` 工厂函数，遵循"单一入口"规则。

---

## Step 3 · `animate/io/audio_utils.py` — 音频工具

三个类：

### AudioRecorder — 环形缓冲区录音器
- 16kHz 采样率，30ms 帧长（480 帧）
- 环形缓冲保留 2 秒音频（VAD 检测到语音开始时向前回退用）

### VADDetector — WebRTC VAD 检测器
- `aggressiveness=2`（推荐值）
- `is_speech(frame)` → 单帧判断
- `detect_speech_boundary(buffer)` → 扫描整段音频，返回 (speech_start, speech_end)

### AudioPlayer — PCM/WAV 播放器
- `play(audio_bytes, format)` → 一次性播放
- `play_stream(generator)` → 流式播放（降低首字延迟）

**自检**：录音 3 秒 → 播放 → 听到自己的声音；安静环境 VAD 返回 False，说话返回 True。

---

## Step 4 · `animate/io/asr.py` — ASR 语音识别适配器

**实现 `InputAdapter` 接口**：

```python
class ASRInput(InputAdapter):
    def __init__(self, sample_rate=16000, silence_timeout=1.0,
                 max_speech_duration=15.0): ...

    def receive(self) -> str:
        """
        主循环：
        1. 开启录音，等待 VAD 检测到语音开始
        2. 持续录音直到 silence_timeout 秒静音
        3. 将录音送往 ASR API，返回识别文本
        4. 如果返回空（没听清），回到第 1 步继续听
        """
```

**关键决策**：
- `receive()` 内部是 while 循环——对外是"阻塞等待直到拿到有效输入"
- VAD 参数需要实测调：N=5 帧（150ms）判为开始，M=15 帧（450ms）判为结束
- 先做 REST ASR（够用），后续可升级为 WebSocket 流式 ASR（延迟更低）

**自检**：说话 → 打印识别结果；安静 5 秒 → `receive()` 继续等待不返回空。

---

## Step 5 · `animate/io/tts.py` — TTS 语音合成适配器

**实现 `OutputAdapter` 接口**：

```python
class TTSOutput(OutputAdapter):
    def __init__(self, sample_rate=16000, streaming=True): ...

    def send(self, response: AgentResponse) -> None:
        """
        1. 取 response.text
        2. 调 TTS API 合成
        3. 播放（流式优先）
        4. 回填 response.audio_data
        """
```

**关键决策**：
- 流式合成+播放 → 首字延迟低（TTS 返回第一帧就开始播，不等全文）
- 文本过长（>200 字）时分段合成，逐段播放
- `response.audio_data` 回填 → 如果以后需要缓存（同样的话不重复合成），直接就能拿到

**自检**：给文字 → 听到语音；空白文本 → 不合成不报错。

---

## Step 6 · `cli.py` — 语音模式入口

```python
parser.add_argument("--voice", action="store_true", help="语音对话模式")

if args.voice:
    from animate.io.asr import ASRInput
    from animate.io.tts import TTSOutput
    input_adapter = ASRInput()
    output_adapter = TTSOutput()
```

语音模式下主循环同文字模式，只是适配器不同。

---

## Step 7 · 跑通后会想做的事

1. **延迟测试**：从说完话到听到回复第一个字 < 2 秒
2. **VAD 调参**：实际环境反复调 `aggressiveness` 和起止阈值
3. **打断功能**：用户说话时中断 TTS 播放
4. **情绪音色**：PLEASED 时语速稍快、COLD 时语速稍慢
5. **流式 ASR**：从 REST 升级为 WebSocket 流式，实时显示识别文字

---

## 完成 Phase 6 的判定

- [ ] `python cli.py --voice` 进入语音模式
- [ ] 说话 → Saki 语音回复，内容与说的相关
- [ ] 安静环境下不误识别
- [ ] 首字延迟 < 2 秒
- [ ] `python cli.py`（无 --voice）文字模式不受影响
