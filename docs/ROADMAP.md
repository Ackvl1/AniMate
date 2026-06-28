# Anima Agent 路线图：Phase 7-9 — 表现层 · 接口层 · 桌面应用

> 最后更新：2026-06-28
> 前置条件：Phase 6.2 ✅（Return-Diff 架构重构完成，493 tests passed）

---

## 目录

- [Phase 7: 表现层基础](#phase-7-表现层基础)
  - [7.1 CosyVoice 3.0 TTS 集成](#71-cosyvoice-30-tts-集成)
  - [7.2 VRM 角色模型集成](#72-vrm-角色模型集成)
- [Phase 8: 接口层](#phase-8-接口层)
  - [8.1 FastAPI 骨架](#81-fastapi-骨架)
  - [8.2 CLI 适配器迁移到接口层](#82-cli-适配器迁移到接口层)
- [Phase 9: 桌面应用](#phase-9-桌面应用)
  - [9.1 Electron/Tauri 打包](#91-electrontauri-打包)
  - [9.2 TTS + VRM + Agent 全链路联调](#92-tts--vrm--agent-全链路联调)
- [附录：2D/3D 角色技术选型对比](#附录2d3d-角色技术选型对比)

---

## Phase 7: 表现层基础

> **目标**：为 Agent 的最终输出赋予「声音」和「形象」，将 `emotion` / `gesture` / `final_text` 从纯文本扩展到语音和 3D 角色动画。

### 7.1 CosyVoice 3.0 TTS 集成

#### 目标

- 部署 CosyVoice 3.0 作为本地/远程 TTS 引擎
- 封装统一 `TTSClient` 接口，支持流式音频输出
- 实现 `emotion → 语调映射`，让语音随情绪自然变化

#### 技术方案

**1. CosyVoice 部署模式**

| 模式 | 适用场景 | 资源需求 |
|------|---------|---------|
| 本地 GPU 推理 | 开发/桌面应用 | CUDA 11.8+, 4GB+ VRAM |
| 远程 API (HTTP) | 轻量客户端/部署 | 无 GPU 需求 |
| Docker 容器 | 服务器部署 | Docker + nvidia-container-toolkit |

推荐先以远程 API 模式验证全链路，再支持本地 GPU 推理。

**2. TTSClient 封装**

```python
# animate/core/tts/client.py

class TTSClient(ABC):
    """TTS 客户端抽象基类"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        emotion: str = "neutral",
        speaker: str = "default",
    ) -> AsyncIterator[bytes]:
        """流式合成，yield PCM/OGG 音频块"""

    @abstractmethod
    async def synthesize_file(
        self, text: str, output_path: str, **kwargs
    ) -> Path:
        """合成到文件"""

    @abstractmethod
    async def health_check(self) -> bool:
        """引擎可用性检查"""

class CosyVoiceClient(TTSClient):
    """CosyVoice 3.0 HTTP 客户端"""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))

    async def synthesize(self, text, emotion="neutral", speaker="default"):
        # 1. 映射 emotion → 语调参数
        style = EMOTION_TO_STYLE.get(emotion, EMOTION_TO_STYLE["neutral"])
        # 2. POST /tts/stream
        async with self._session.post(
            f"{self._base_url}/tts/stream",
            json={"text": text, "speaker": speaker, "style": style},
        ) as resp:
            async for chunk in resp.content.iter_any():
                yield chunk

    async def health_check(self):
        async with self._session.get(f"{self._base_url}/health") as resp:
            return resp.status == 200
```

**3. Emotion → 语调映射表**

```python
# animate/core/tts/emotion_mapping.py

EMOTION_TO_STYLE = {
    # emotion      →  (speed, pitch, energy, style_tag)
    "happy":        (1.1,  1.05, 0.8,  "cheerful"),
    "sad":          (0.85, 0.95, 0.4,  "sad"),
    "angry":        (1.15, 1.1,  0.9,  "angry"),
    "surprised":    (1.2,  1.15, 0.85, "surprised"),
    "confused":     (0.9,  1.0,  0.5,  "confused"),
    "shy":          (0.8,  0.98, 0.3,  "gentle"),
    "neutral":      (1.0,  1.0,  0.6,  "neutral"),
    "thinking":     (0.75, 1.0,  0.4,  "calm"),
    "excited":      (1.25, 1.12, 0.95, "excited"),
    "embarrassed":  (0.85, 1.02, 0.5,  "shy"),
}

def get_style_params(emotion: str) -> tuple[float, float, float, str]:
    return EMOTION_TO_STYLE.get(emotion, EMOTION_TO_STYLE["neutral"])
```

**4. 与 Agent 事件流集成**

```python
# 在 Agent 事件处理中，消费 emotion.update 和 text_token
async for event in agent.chat_stream(user_input):
    if event.type == "text_token":
        # 累积文本，按句号/逗号分句
        buffer.append(event.text)
        if is_sentence_boundary(buffer):
            text = flush(buffer)
            # 异步 TTS 合成（不阻塞文本输出）
            asyncio.create_task(tts_queue.put((text, current_emotion)))
    elif event.type == "emotion.update":
        current_emotion = event.emotion
    elif event.type == "emotion.final":
        current_emotion = event.value
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `animate/core/tts/__init__.py` | 新建 | TTS 模块入口 |
| `animate/core/tts/client.py` | 新建 | TTSClient ABC + CosyVoiceClient |
| `animate/core/tts/emotion_mapping.py` | 新建 | emotion → 语调映射表 |
| `animate/core/tts/audio_queue.py` | 新建 | 音频队列 + 播放管理 |
| `config.yaml` | 修改 | 新增 `tts` 配置段 |
| `requirements.txt` | 修改 | 新增 `aiohttp`（如未有） |
| `tests/test_tts_client.py` | 新建 | 单元测试 |
| `tests/test_tts_emotion_mapping.py` | 新建 | 映射表测试 |

#### 测试策略

- **单元测试**：emotion 映射表覆盖率 100%，边界值（未知 emotion 回退 neutral）
- **集成测试**：CosyVoiceClient HTTP mock，验证流式输出、超时重试、错误处理
- **端到端测试**：真实 CosyVoice 服务（可选，CI 跳过）
- **性能测试**：首包延迟 < 500ms（远程 API），流式连续性

#### 依赖关系

- 前置：Phase 6.2 ✅（AfterNode 输出 `final_text` + `emotion`）
- 外部：CosyVoice 3.0 服务（本地或远程）
- 并行：7.2 可同步开发

#### 预估工时

| 任务 | 工时 |
|------|------|
| CosyVoice 部署 + API 调研 | 1d |
| TTSClient 抽象 + CosyVoice 实现 | 2d |
| Emotion 映射表 + 调优 | 1d |
| 音频队列 + Agent 事件集成 | 2d |
| 测试 + 文档 | 1d |
| **合计** | **7d** |

---

### 7.2 VRM 角色模型集成

#### 目标

- 在前端（Three.js + three-vrm）渲染 VRM 3D 角色模型
- 实现 `emotion → VRM Expression 映射`（表情变化）
- 实现 `gesture → 骨骼动画驱动`（身体动作）
- 实现 `viseme 口型同步`（说话时嘴型跟随音频）

#### 技术方案

**1. 技术栈选型**

| 组件 | 选型 | 理由 |
|------|------|------|
| 3D 渲染 | Three.js r160+ | 成熟生态、VRM 原生支持 |
| VRM 加载 | @pixiv/three-vrm v3 | 官方维护、表达式系统完善 |
| 口型同步 | @pixiv/three-vrm-viseeme | 官方 viseme 驱动方案 |
| 动画 | THREE.AnimationMixer | 骨骼动画混合 |
| 构建工具 | Vite | 快速 HMR、原生 ESM |

**2. VRM Expression 映射表**

```typescript
// src/vrm/emotion-map.ts

import { VRMExpressionPresetName } from '@pixiv/three-vrm';

// Anima Agent emotion → VRM Expression 映射
const EMOTION_TO_VRM: Record<string, Partial<Record<VRMExpressionPresetName, number>>> = {
  happy:        { happy: 0.8,  mouthSmile: 0.6 },
  sad:          { sad: 0.7,   mouthFrown: 0.4,  eyesClosed: 0.3 },
  angry:        { angry: 0.8,  browInnerUp: -0.5, mouthFrown: 0.3 },
  surprised:    { surprised: 0.9, browInnerUp: 0.7, mouthOpen: 0.5 },
  confused:     { browInnerUp: 0.4, mouthFrown: 0.2, blink: 0.3 },
  shy:          { happy: 0.3,  blush: 0.6,  eyesClosed: 0.2 },
  thinking:     { browInnerUp: 0.3, eyesLookUp: 0.4, mouthPucker: 0.2 },
  excited:      { happy: 0.9,  surprised: 0.4,  mouthSmile: 0.8 },
  embarrassed:  { blush: 0.8,  browInnerUp: 0.3, eyesClosed: 0.3 },
  neutral:      {},  // 默认表情
};

export function applyEmotion(
  vrm: VRM,
  emotion: string,
  intensity: number = 1.0
) {
  const mapping = EMOTION_TO_VRM[emotion] ?? EMOTION_TO_VRM['neutral'];
  // 先重置所有表情
  vrm.expressionManager?.resetValues();
  // 再应用目标表情
  for (const [expr, value] of Object.entries(mapping)) {
    vrm.expressionManager?.setValue(
      expr as VRMExpressionPresetName,
      value * intensity
    );
  }
}
```

**3. Gesture → 骨骼动画**

```typescript
// src/vrm/gesture-driver.ts

import * as THREE from 'three';

// 预定义骨骼动画 clip（从 FBX/GLTF 导入或程序化生成）
const GESTURE_CLIPS: Record<string, THREE.AnimationClip> = {};

export class GestureDriver {
  private mixer: THREE.AnimationMixer;
  private currentAction: THREE.AnimationAction | null = null;

  constructor(mixer: THREE.AnimationMixer) {
    this.mixer = mixer;
  }

  async loadGesture(name: string, url: string) {
    const loader = new THREE.AnimationLoader();
    const clips = await loader.loadAsync(url);
    GESTURE_CLIPS[name] = clips[0];
  }

  playGesture(name: string, duration: number = 2.0) {
    const clip = GESTURE_CLIPS[name];
    if (!clip) return;

    // 停止当前动画
    this.currentAction?.fadeOut(0.3);

    const action = this.mixer.clipAction(clip);
    action.reset().fadeIn(0.2).setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();

    this.currentAction = action;

    // 自动停止
    setTimeout(() => {
      action.fadeOut(0.5);
      this.currentAction = null;
    }, duration * 1000);
  }

  update(delta: number) {
    this.mixer.update(delta);
  }
}
```

**4. Viseme 口型同步**

```typescript
// src/vrm/viseme-sync.ts

// Viseme 索引（15 个 viseme，标准 IPA 口型）
const PHONEME_TO_VISEME: Record<string, number> = {
  'a': 0, 'e': 1, 'i': 2, 'o': 3, 'u': 4,
  'b': 5, 'f': 6, 'm': 7, 'p': 8,
  's': 9, 't': 10, 'n': 11, 'l': 12,
  'k': 13, 'sil': 14,
};

export class VisemeSync {
  private vrm: VRM;
  private visemeQueue: Array<{ index: number; time: number }> = [];

  constructor(vrm: VRM) {
    this.vrm = vrm;
  }

  // 从音频 FFT 分析推断当前 viseme（简化方案）
  fromAudioLevel(level: number, prevLevel: number): number {
    if (level < 0.05) return 14; // silence
    const delta = level - prevLevel;
    if (delta > 0.3) return 0;   // 开口 (a)
    if (delta < -0.2) return 3;  // 闭口 (o)
    if (level > 0.6) return 2;   // 高频 (i)
    return 1;                     // 默认 (e)
  }

  // 从 LLM 标记的 viseme 数据驱动（精确方案）
  applyViseme(index: number, intensity: number = 1.0) {
    // 通过 BlendShape 控制口型
    const shapeName = `viseme_${index}`;
    this.vrm.expressionManager?.setValue(shapeName, intensity);
  }

  // 每帧更新
  update(audioTime: number) {
    while (this.visemeQueue.length > 0 &&
           this.visemeQueue[0].time <= audioTime) {
      const viseme = this.visemeQueue.shift()!;
      this.applyViseme(viseme.index);
    }
  }
}
```

**5. WebSocket 事件接收**

```typescript
// src/vrm/vrm-controller.ts

export class VRMController {
  private vrm: VRM;
  private gestureDriver: GestureDriver;
  private visemeSync: VisemeSync;
  private ws: WebSocket;

  connect(url: string) {
    this.ws = new WebSocket(url);

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'emotion.update':
        case 'emotion.final':
          applyEmotion(this.vrm, data.emotion);
          break;

        case 'gesture.update':
          this.gestureDriver.playGesture(data.gesture);
          break;

        case 'text_token':
          // 触发口型
          this.visemeSync.fromAudioLevel(data.audio_level ?? 0.3, 0);
          break;
      }
    };
  }
}
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/package.json` | 新建 | 前端项目依赖 |
| `frontend/src/vrm/emotion-map.ts` | 新建 | emotion → VRM Expression 映射 |
| `frontend/src/vrm/gesture-driver.ts` | 新建 | 骨骼动画驱动 |
| `frontend/src/vrm/viseme-sync.ts` | 新建 | 口型同步 |
| `frontend/src/vrm/vrm-controller.ts` | 新建 | VRM 生命周期 + WebSocket |
| `frontend/src/vrm/scene.ts` | 新建 | Three.js 场景初始化 |
| `frontend/src/main.ts` | 新建 | 前端入口 |
| `frontend/index.html` | 新建 | HTML 入口 |
| `frontend/vite.config.ts` | 新建 | Vite 配置 |
| `assets/models/*.vrm` | 新增 | 示例 VRM 模型 |
| `assets/animations/*.glb` | 新增 | 预定义手势动画 |
| `tests/vrm.test.ts` | 新建 | 前端单元测试 |

#### 测试策略

- **单元测试**：emotion 映射覆盖率 100%，viseme 索引范围校验
- **组件测试**：VRM 加载 + Expression 设置（vitest + mock WebGL）
- **集成测试**：WebSocket 连接 + 事件驱动完整流程
- **视觉测试**：关键表情截图对比（Playwright）
- **性能测试**：帧率 ≥ 30fps，表达式切换延迟 < 50ms

#### 依赖关系

- 前置：Phase 6.2 ✅（AfterNode 输出 emotion/gesture）
- 外部：@pixiv/three-vrm、Three.js、Vite
- 并行：7.1 可同步开发
- 后置：Phase 8（需要 WebSocket 接口）

#### 预估工时

| 任务 | 工时 |
|------|------|
| Three.js + VRM 环境搭建 | 1d |
| Emotion → VRM Expression 映射 | 2d |
| Gesture 骨骼动画系统 | 2d |
| Viseme 口型同步 | 2d |
| WebSocket 事件集成 | 1d |
| 测试 + 性能优化 | 1d |
| **合计** | **9d** |

---

## Phase 8: 接口层

> **目标**：在 Agent 核心与客户端之间建立标准 HTTP/WebSocket 接口层，替代直接 Python 调用，为多端接入（桌面应用、Web、移动端）提供统一协议。

### 8.1 FastAPI 骨架

#### 目标

- 构建 FastAPI 应用骨架，支持 REST + WebSocket 双协议
- 实现 `chat`（同步）和 `chat_stream`（流式）端点
- 事件格式标准化（JSON 协议）
- 支持多会话管理

#### 技术方案

**1. 技术栈**

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | async 原生、WebSocket 一等公民、自动 OpenAPI |
| ASGI 服务器 | uvicorn | 生产级、支持热重载 |
| 会话管理 | 内存 + SQLite | 轻量级，复用现有 SessionStore |
| 事件序列化 | JSON Lines | 流式友好、前端易解析 |

**2. API 端点设计**

```
POST   /api/chat              → 同步对话（等待完整回复）
POST   /api/chat/stream        → SSE 流式对话
WS     /api/ws/chat            → WebSocket 双向流式
GET    /api/sessions            → 会话列表
POST   /api/sessions            → 创建新会话
DELETE /api/sessions/{id}       → 删除会话
GET    /api/health              → 健康检查
```

**3. 服务端实现**

```python
# animate/api/app.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json, asyncio

app = FastAPI(title="Anima Agent API", version="0.1.0")

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    session_id: str
    text: str
    emotion: str
    gesture: str

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    agent = get_agent(request.session_id)
    result = await agent.chat(request.message)
    return ChatResponse(
        session_id=request.session_id,
        text=result.final_text,
        emotion=result.emotion,
        gesture=result.gesture,
    )

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    agent = get_agent(request.session_id)

    async def event_generator():
        async for event in agent.chat_stream(request.message):
            yield f"data: {json.dumps(event.to_dict())}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@app.websocket("/api/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    session_id = websocket.query_params.get("session_id", "default")
    agent = get_agent(session_id)

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")

            async for event in agent.chat_stream(message):
                await websocket.send_json(event.to_dict())

    except WebSocketDisconnect:
        pass
    finally:
        agent.shutdown()
```

**4. 事件协议**

```python
# animate/api/protocol.py

from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class AgentEvent:
    type: str           # text_token | emotion.update | gesture.update | ...
    data: dict[str, Any]

    def to_dict(self) -> dict:
        return {"type": self.type, **self.data}

# 事件类型枚举
EVENT_TYPES = {
    "text_token":       {"text": "str"},
    "emotion.update":   {"emotion": "str", "gesture": "str"},
    "emotion.final":    {"value": "str"},
    "gesture.update":   {"gesture": "str"},
    "node.start":       {"node": "str"},
    "node.done":        {"node": "str", "duration_ms": "float"},
    "error":            {"message": "str"},
    "done":             {},
}
```

**5. 会话管理**

```python
# animate/api/sessions.py

from animate.core.memory.session_store import SessionStore

class SessionManager:
    def __init__(self, agent_factory):
        self._agent_factory = agent_factory
        self._agents: dict[str, Agent] = {}

    def get_or_create(self, session_id: str) -> Agent:
        if session_id not in self._agents:
            self._agents[session_id] = self._agent_factory(session_id)
        return self._agents[session_id]

    def remove(self, session_id: str):
        agent = self._agents.pop(session_id, None)
        if agent:
            agent.shutdown()
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `animate/api/__init__.py` | 新建 | API 模块入口 |
| `animate/api/app.py` | 新建 | FastAPI 应用 + 路由 |
| `animate/api/protocol.py` | 新建 | 事件协议定义 |
| `animate/api/sessions.py` | 新建 | 会话管理器 |
| `animate/api/dependencies.py` | 新建 | 依赖注入（Agent 工厂） |
| `config.yaml` | 修改 | 新增 `api` 配置段（host, port） |
| `requirements.txt` | 修改 | 新增 `fastapi`, `uvicorn[standard]` |
| `tests/test_api_chat.py` | 新建 | REST 端点测试 |
| `tests/test_api_stream.py` | 新建 | SSE 流式测试 |
| `tests/test_api_ws.py` | 新建 | WebSocket 测试 |

#### 测试策略

- **单元测试**：协议序列化、会话管理器 CRUD
- **端点测试**：httpx AsyncClient + pytest，覆盖正常/异常路径
- **WebSocket 测试**：websockets 库 + pytest-asyncio
- **负载测试**：Locust / k6 并发 100 连接
- **契约测试**：OpenAPI schema 生成 + 前端类型同步

#### 依赖关系

- 前置：Phase 6.2 ✅（Agent 公开 `chat` / `chat_stream` 接口）
- 外部：FastAPI、uvicorn
- 后置：8.2（CLI 适配器迁移）

#### 预估工时

| 任务 | 工时 |
|------|------|
| FastAPI 骨架 + 路由 | 1d |
| chat + chat_stream 端点 | 2d |
| WebSocket 双向流式 | 2d |
| 会话管理 + 依赖注入 | 1d |
| 测试 + 文档 | 1d |
| **合计** | **7d** |

---

### 8.2 CLI 适配器迁移到接口层

#### 目标

- 将现有 `cli.py` 的 REPL 逻辑抽象为 Adapter 层
- CLI 成为接口层的一个「客户端」，而非独立入口
- 为后续多客户端（Web、桌面）奠定基础

#### 技术方案

**1. Adapter 抽象**

```python
# animate/api/adapter.py

from abc import ABC, abstractmethod

class ClientAdapter(ABC):
    """客户端适配器抽象"""

    @abstractmethod
    async def on_event(self, event: dict):
        """处理 Agent 事件"""

    @abstractmethod
    async def on_error(self, error: str):
        """处理错误"""

    @abstractmethod
    async def on_done(self):
        """处理完成"""

class CLIAdapter(ClientAdapter):
    """CLI REPL 适配器"""

    def __init__(self, color: bool = True):
        self._color = color

    async def on_event(self, event):
        t = event["type"]
        if t == "text_token":
            text = event.get("text", "")
            sys.stdout.write(text)
            sys.stdout.flush()
        elif t == "emotion.update":
            emotion = event.get("emotion", "")
            if self._color:
                print(f"\n[{emotion}]", end="")
        elif t == "done":
            print()  # newline after response

    async def on_error(self, error):
        print(f"\n❌ Error: {error}", file=sys.stderr)

    async def on_done(self):
        pass  # CLI 不需要额外清理

class WebAdapter(ClientAdapter):
    """Web 前端适配器（通过 WebSocket 转发）"""

    def __init__(self, websocket: WebSocket):
        self._ws = websocket

    async def on_event(self, event):
        await self._ws.send_json(event)

    async def on_error(self, error):
        await self._ws.send_json({"type": "error", "message": error})

    async def on_done(self):
        await self._ws.send_json({"type": "done"})
```

**2. CLI 重构**

```python
# cli.py（重构后）

from animate.api.adapter import CLIAdapter
from animate.api.app import create_agent

async def main():
    agent = create_agent()
    adapter = CLIAdapter()

    print("Anima Agent REPL (Ctrl+C to exit)")
    while True:
        try:
            user_input = input("\n> ").strip()
            if not user_input:
                continue

            async for event in agent.chat_stream(user_input):
                await adapter.on_event(event.to_dict())

            await adapter.on_done()

        except KeyboardInterrupt:
            print("\nBye!")
            agent.shutdown()
            break
        except Exception as e:
            await adapter.on_error(str(e))
```

**3. 共享 Agent 工厂**

```python
# animate/api/app.py（追加）

def create_agent_factory(config_path: str = "config.yaml"):
    """创建 Agent 工厂函数"""
    config = load_config(config_path)

    def factory(session_id: str = "default"):
        # 复用 Agent.create_default 逻辑
        return Agent.create_default(
            llm=create_llm(config),
            persona=load_persona(config.persona),
            vector_store=create_vs(config),
            keyword_store=create_ks(config),
            log_db=ChatLogDB(),
            memory_provider=DefaultMemoryProvider(),
            session_store=SessionStore(),
        )

    return factory
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `animate/api/adapter.py` | 新建 | ClientAdapter 抽象 + CLI/Web 实现 |
| `cli.py` | 修改 | 重构为使用 CLIAdapter |
| `animate/api/app.py` | 修改 | 新增 `create_agent_factory` |
| `tests/test_adapter_cli.py` | 新建 | CLI Adapter 测试 |

#### 测试策略

- **适配器测试**：CLIAdapter 事件输出格式验证（mock stdout）
- **回归测试**：现有 CLI REPL 手动测试（交互场景）
- **集成测试**：CLI → API → Agent 完整链路

#### 依赖关系

- 前置：8.1（FastAPI 骨架）
- 内部：cli.py 现有逻辑

#### 预估工时

| 任务 | 工时 |
|------|------|
| Adapter 抽象设计 | 0.5d |
| CLIAdapter 实现 | 1d |
| cli.py 重构 | 0.5d |
| 测试 + 回归 | 1d |
| **合计** | **3d** |

---

## Phase 9: 桌面应用

> **目标**：将 Agent + TTS + VRM 三大模块打包为独立桌面应用，用户一键安装即可使用，无需配置 Python/Node 环境。

### 9.1 Electron/Tauri 打包

#### 目标

- 评估并选择桌面打包框架
- 实现 Python 后端 + Web 前端的桌面集成
- 支持 Windows/macOS/Linux 三平台构建

#### 技术方案

**1. 框架选型对比**

| 维度 | Electron | Tauri |
|------|----------|-------|
| 安装包大小 | ~150MB（含 Chromium） | ~10MB（系统 WebView） |
| 内存占用 | ~200MB+ | ~50MB |
| 前端生态 | 完全兼容 | 完全兼容 |
| 后端集成 | child_process 调 Python | sidecar 机制调 Python |
| 原生 API | Node.js API | Rust API |
| 生态成熟度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 打包复杂度 | 中等 | 较高（需 Rust 工具链） |

**推荐方案**：Tauri 2.0 + Python sidecar

理由：安装包小、内存占用低、对 VRM 3D 渲染的 GPU 资源更友好。

**2. 架构设计**

```
┌─────────────────────────────────────┐
│         Tauri 桌面壳                │
│  ┌───────────────┐  ┌────────────┐  │
│  │  WebView      │  │  Rust      │  │
│  │  (VRM + UI)   │  │  Core      │  │
│  │  Three.js     │  │            │  │
│  └───────┬───────┘  └──────┬─────┘  │
│          │ WebSocket        │ sidecar│
│          └──────────┬───────┘        │
│                     ▼                │
│          ┌─────────────────┐         │
│          │  Python 进程     │         │
│          │  (FastAPI)       │         │
│          │  Agent + TTS     │         │
│          └─────────────────┘         │
└─────────────────────────────────────┘
```

**3. Tauri 配置**

```json
// src-tauri/tauri.conf.json
{
  "package": {
    "productName": "Anima Agent",
    "version": "0.1.0"
  },
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devPath": "http://localhost:5173",
    "distDir": "../dist"
  },
  "tauri": {
    "allowlist": {
      "shell": {
        "sidecar": true,
        "scope": [
          { "name": "python-sidecar", "cmd": "../python-sidecar", "args": [] }
        ]
      },
      "fs": { "scope": ["$APPDATA/**"] },
      "path": { "all": true }
    },
    "bundle": {
      "active": true,
      "targets": "all",
      "identifier": "com.animate.desktop",
      "icon": ["icons/32x32.png", "icons/128x128.png", "icons/icon.icns"]
    }
  }
}
```

**4. Python Sidecar 打包**

```bash
# 使用 PyInstaller 打包 Python 进程
pyinstaller \
  --name animate-server \
  --onefile \
  --add-data "config.yaml:." \
  --add-data "data/:data" \
  --add-data "prompts/:prompts" \
  --hidden-import "animate.core.agent" \
  animate/api/server.py

# 输出: dist/animate-server (Linux/macOS)
# 输出: dist/animate-server.exe (Windows)
```

**5. 三平台构建 CI**

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ['v*']

jobs:
  build:
    strategy:
      matrix:
        platform: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.platform }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }

      - name: Build Python sidecar
        run: pip install pyinstaller && pyinstaller --onefile ...

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        with:
          tagName: ${{ github.ref_name }}
          releaseName: 'Anima Agent ${{ github.ref_name }}'
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `src-tauri/tauri.conf.json` | 新建 | Tauri 配置 |
| `src-tauri/src/main.rs` | 新建 | Rust 侧 sidecar 管理 |
| `src-tauri/Cargo.toml` | 新建 | Rust 依赖 |
| `package.json` | 新建 | 前端 + Tauri 依赖 |
| `frontend/` | 新建 | 前端源码（Phase 7.2 VRM） |
| `animate/api/server.py` | 新建 | FastAPI 服务器入口 |
| `.github/workflows/release.yml` | 新建 | CI/CD 构建 |
| `scripts/build-sidecar.sh` | 新建 | PyInstaller 打包脚本 |

#### 测试策略

- **本地测试**：`cargo tauri dev` 开发模式验证
- **构建测试**：三平台 CI 绿灯
- **安装测试**：干净环境安装 + 启动 + 基本对话
- **性能测试**：启动时间 < 5s，内存 < 300MB

#### 依赖关系

- 前置：Phase 7（TTS + VRM）、Phase 8（API 接口层）
- 外部：Tauri CLI、Rust 工具链、PyInstaller
- 三平台：Windows (primary)、macOS、Linux

#### 预估工时

| 任务 | 工时 |
|------|------|
| Tauri 环境搭建 + 配置 | 2d |
| Python sidecar 打包 | 2d |
| Tauri ↔ Python IPC | 2d |
| CI/CD 构建流水线 | 2d |
| 三平台测试 + 修复 | 2d |
| **合计** | **10d** |

---

### 9.2 TTS + VRM + Agent 全链路联调

#### 目标

- 端到端验证：用户输入 → Agent 推理 → TTS 语音 → VRM 表情/动作
- 消除模块间集成问题
- 优化延迟和用户体验

#### 技术方案

**1. 全链路数据流**

```
用户输入
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI Server (Python)                                 │
│  ┌─────────┐    ┌──────────┐    ┌─────────┐             │
│  │ Agent   │───▶│ Event    │───▶│ TTS     │             │
│  │ (LLM)   │    │ Bus      │    │ Client  │──▶ 音频输出  │
│  └─────────┘    └────┬─────┘    └─────────┘             │
│                      │                                   │
└──────────────────────┼───────────────────────────────────┘
                       │ WebSocket
                       ▼
┌──────────────────────────────────────────────────────────┐
│  Tauri WebView (JavaScript)                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│  │ WebSocket│───▶│ VRM      │───▶│ Audio    │           │
│  │ Client   │    │ Controller│    │ Player   │           │
│  └──────────┘    └──────────┘    └──────────┘           │
│                      │                                   │
│                 ┌────▼────┐                              │
│                 │  Three.js│                             │
│                 │  Renderer│                             │
│                 └─────────┘                              │
└──────────────────────────────────────────────────────────┘
```

**2. 延迟优化策略**

| 环节 | 优化 | 目标延迟 |
|------|------|---------|
| Agent 推理 | 流式输出，首 token < 200ms | 200ms |
| TTS 合成 | 按句分片，首包 < 500ms | 500ms |
| VRM 表情 | WebSocket 实时推送，切换 < 50ms | 50ms |
| 口型同步 | 音频 FFT 分析，< 30ms | 30ms |
| **端到端** | 语音首包 + 表情首帧 | **< 800ms** |

**3. 联调测试场景**

```python
# tests/test_e2e_integration.py

import pytest

class TestFullPipeline:
    """全链路集成测试"""

    @pytest.mark.asyncio
    async def test_basic_conversation(self):
        """基本对话：输入 → Agent → TTS + VRM 事件"""
        async with TestClient() as client:
            events = []
            async for event in client.chat_stream("你好！"):
                events.append(event)

            # 验证事件流
            assert any(e.type == "text_token" for e in events)
            assert any(e.type == "emotion.update" for e in events)
            assert events[-1].type == "done"

    @pytest.mark.asyncio
    async def test_emotion_propagation(self):
        """情绪传播：LLM 输出 → emotion 标记 → TTS 语调 + VRM 表情"""
        async with TestClient() as client:
            tts_emotions = []
            vrm_emotions = []

            async for event in client.chat_stream("讲个笑话"):
                if event.type == "tts.emotion":
                    tts_emotions.append(event.emotion)
                if event.type == "vrm.emotion":
                    vrm_emotions.append(event.emotion)

            # 验证 TTS 和 VRM 收到相同的 emotion
            assert tts_emotions == vrm_emotions

    @pytest.mark.asyncio
    async def test_concurrent_clients(self):
        """多客户端并发"""
        async with TestClient() as client:
            tasks = [
                client.chat_stream(f"消息 {i}")
                for i in range(5)
            ]
            results = await asyncio.gather(*tasks)
            assert all(len(r) > 0 for r in results)

    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        """优雅降级：TTS 不可用时 Agent 正常工作"""
        async with TestClient(tts_enabled=False) as client:
            events = []
            async for event in client.chat_stream("你好"):
                events.append(event)
            assert any(e.type == "text_token" for e in events)
```

**4. 性能基准测试**

```python
# tests/benchmark_e2e.py

import time

async def benchmark_pipeline():
    """测量端到端延迟"""
    t0 = time.monotonic()
    first_token_time = None
    first_tts_time = None
    first_vrm_time = None

    async for event in agent.chat_stream("你好"):
        if event.type == "text_token" and first_token_time is None:
            first_token_time = time.monotonic() - t0
        elif event.type == "tts.audio" and first_tts_time is None:
            first_tts_time = time.monotonic() - t0
        elif event.type == "vrm.update" and first_vrm_time is None:
            first_vrm_time = time.monotonic() - t0

    print(f"首 Token: {first_token_time*1000:.0f}ms")
    print(f"首 TTS 包: {first_tts_time*1000:.0f}ms")
    print(f"首 VRM 帧: {first_vrm_time*1000:.0f}ms")
```

#### 文件改动

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/test_e2e_integration.py` | 新建 | 全链路集成测试 |
| `tests/benchmark_e2e.py` | 新建 | 性能基准测试 |
| `tests/conftest.py` | 修改 | 新增 TestClient fixture |
| `animate/api/app.py` | 修改 | 事件路由优化 |
| `frontend/src/vrm/vrm-controller.ts` | 修改 | WebSocket 重连 + 心跳 |
| `animate/core/tts/audio_queue.py` | 修改 | 音频缓冲优化 |

#### 测试策略

- **冒烟测试**：每轮构建自动运行 E2E 测试
- **性能基准**：首 token < 200ms，首 TTS < 800ms，VRM < 50ms
- **压力测试**：50 并发用户持续对话 10 分钟
- **兼容性测试**：Windows 10/11、macOS 13+、Ubuntu 22.04

#### 依赖关系

- 前置：Phase 7（TTS + VRM）、Phase 8（API）
- 内部：所有模块联调

#### 预估工时

| 任务 | 工时 |
|------|------|
| 联调环境搭建 | 1d |
| Agent → TTS 集成 | 2d |
| Agent → VRM 集成 | 2d |
| TTS ↔ VRM 同步 | 1d |
| 性能优化 + 延迟调优 | 2d |
| E2E 测试 + 文档 | 2d |
| **合计** | **10d** |

---

## 附录：2D/3D 角色技术选型对比

> Phase 7.2 选型 VRM 的决策依据

### 技术对比表

| 维度 | VRM | Live2D Cubism | Inochi2D |
|------|-----|---------------|----------|
| **维度** | 3D（Three.js/WebGL） | 2D 立体化 | 2D 立体化 |
| **格式** | .vrm (glTF 扩展) | .model3.json (Cubism) | .inx |
| **渲染引擎** | Three.js + @pixiv/three-vrm | Live2D Cubism SDK for Web | Inochi Creator |
| **开源协议** | MIT (VRM spec) | 商业授权 (Cubism) | MIT |
| **表情系统** | BlendShape Expression（官方标准） | Param 系统（自由度高） | Param 系统 |
| **骨骼动画** | ✅ 原生支持（Humanoid） | ❌ 不支持（2D 变形） | ⚠️ 有限支持 |
| **口型同步** | ✅ Viseme（15 个 IPA 口型） | ✅ LipSync（参数驱动） | ✅ LipSync |
| **物理模拟** | ✅ Spring Bone（头发/衣服） | ✅ Physics（2D 物理） | ✅ Physics |
| **模型制作工具** | Blender + VRM Add-on | Live2D Cubism Editor | Inochi Creator |
| **学习曲线** | 中等（需 Blender 基础） | 中等（Cubism 专用工具） | 较高（工具较少） |
| **社区生态** | ⭐⭐⭐⭐（VTuber 主流） | ⭐⭐⭐⭐⭐（日系最成熟） | ⭐⭐（小众） |
| **多角度支持** | ✅ 360° 自由视角 | ❌ 固定角度（有限变形） | ❌ 固定角度 |
| **性能开销** | 中等（3D 渲染） | 低（2D 纹理变形） | 低（2D 纹理变形） |
| **跨平台** | Web + Unity + Unreal | Web + Unity | 有限 |
| **商用案例** | VTuber（VTube Studio） | VTuber（大量日系） | 少量 |
| **表情预制件** | VRM 系统表情（标准化） | 自定义 Param（灵活） | 自定义 Param |
| **动画复用** | ✅ humanoid retarget | ❌ 不支持 | ❌ 不支持 |

### 选型决策

| 考量因素 | 说明 |
|---------|------|
| **3D 自由度** | VRM 支持 360° 视角旋转，适合沉浸式场景 |
| **骨骼动画** | Agent 的 gesture 映射需要骨骼驱动，VRM 原生支持 |
| **Viseme 标准化** | 15 个 IPA 口型标准，便于 TTS 集成 |
| **开源授权** | MIT 协议，无商业授权费用（Live2D 需付费） |
| **VTuber 生态** | VRM 是 VTuber 行业事实标准，资源丰富 |
| **表情标准化** | VRM 表情名称标准化（happy/sad/angry...），降低映射复杂度 |

**结论**：选择 VRM 是因为 3D 自由度 + 骨骼动画 + 开源授权 + 标准化表情系统的综合优势。Live2D 适合 2D 风格项目，Inochi2D 目前生态不成熟。

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| VRM 模型制作成本高 | 开发周期延长 | 使用开源 VRM 模型（VRoid Hub） |
| Three.js 性能瓶颈 | 低端设备卡顿 | LOD 优化、降级到 2D 预览 |
| Cubism 商业授权 | 如需切换到 Live2D | 架构设计时保持抽象层 |

---

## 总览：Phase 7-9 时间线

```
Week 1-2:  Phase 7.1 (TTS) ─────────────┐
Week 1-3:  Phase 7.2 (VRM) ─────────────┤
Week 3-4:  Phase 8.1 (API) ─────────────┤─── Phase 7-8 并行
Week 4:    Phase 8.2 (CLI 迁移) ─────────┤
Week 5-7:  Phase 9.1 (Desktop) ──────────┤
Week 7-8:  Phase 9.2 (E2E) ─────────────┘
                                          ▼
                              总计约 8 周 (46 工时)
```

| Phase | 工时 | 前置 |
|-------|------|------|
| 7.1 TTS 集成 | 7d | Phase 6.2 |
| 7.2 VRM 集成 | 9d | Phase 6.2 |
| 8.1 FastAPI 骨架 | 7d | Phase 6.2 |
| 8.2 CLI 迁移 | 3d | 8.1 |
| 9.1 桌面打包 | 10d | Phase 7 + 8 |
| 9.2 全链路联调 | 10d | Phase 7 + 8 |
| **合计** | **46d** | |

---

## 风险登记

| # | 风险 | 概率 | 影响 | 缓解 |
|---|------|------|------|------|
| 1 | CosyVoice 3.0 API 不稳定 | 中 | 高 | 抽象 TTSClient，支持多引擎切换 |
| 2 | VRM 模型制作耗时 | 中 | 中 | 使用 VRoid Hub 开源模型 |
| 3 | Electron/Tauri 打包兼容性 | 低 | 中 | 先 Tauri，备选 Electron |
| 4 | 端到端延迟超标 | 中 | 高 | 分段优化 + 异步流水线 |
| 5 | Python sidecar 启动慢 | 中 | 中 | PyInstaller 预编译 + 懒加载 |

---

> 下一步：完成 Phase 7-9 后，进入 Phase 10（多模态交互）和 Phase 11（云端部署）。
