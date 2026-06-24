# Phase 5 开发手册 · Unity UI 界面

> 目标：用 Unity 搭建桌面角色伴侣的 UI 界面——Live2D 模型渲染、聊天窗口、情绪可视化、设置面板。通过 WebSocket 与 Python 后端通信。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。
>
> **前置状态**：Phase 3 通用框架已完成，Phase 4 MCP/记忆/学习已完成。需要安装 Unity 2022.3 LTS+ + Live2D Cubism SDK for Unity。

---

## 你需要先有的认知

- **Unity + Live2D Cubism SDK**：Cubism SDK 是 Live2D 官方的 Unity 集成包。导入 SDK 后拖入模型文件即可在 Unity 中渲染和操控 Live2D 角色。
- **WebSocket 通信**：Python 后端和 Unity 之间用 WebSocket 实时通信。Unity 做 Server，Python 做 Client。消息格式为 JSON。
- **UI 布局**：Unity UI 系统（Canvas + UI GameObject）搭建聊天窗口。Live2D 模型放在独立 Camera 下渲染到 RenderTexture，嵌入 UI。
- **Cubism 参数控制**：每个可动部分对应一个参数 ID（如 `ParamEyeSmile`），通过 `model.Parameters[id].Value` 设置 0~1 值。

---

## 整体架构图

```
┌─────────────────────────────┐          WebSocket          ┌──────────────────────────┐
│       Python 后端             │◄──────────────────────────►│     Unity 前端             │
│                              │     JSON Messages          │                          │
│  cli.py --unity              │                            │  MainScene.unity         │
│       │                      │                            │       │                  │
│       ▼                      │                            │       ▼                  │
│  ┌──────────────────┐       │   "response" ←──────────  │  ┌──────────────────┐   │
│  │  UnityBridge     │◄──────┼───────────────────────────┼──│ WebSocketServer  │   │
│  │  (ws_client.py)  │       │                            │  │ (C#)             │   │
│  │                  │       │                            │  └────────┬─────────┘   │
│  │  connect()       │       │                            │           │              │
│  │  send_response() │       │                            │     ┌─────┼──────┐       │
│  │  wait_for_input()│       │                            │     │     │      │       │
│  │  send_status()   │       │                            │     ▼     ▼      ▼       │
│  └────────┬─────────┘       │                            │  ┌──────┐┌─────┐┌─────┐  │
│           │                 │                            │  │Chat  ││L2D  ││Sett-│  │
│           ▼                 │                            │  │Ctrl  ││Ctrl ││ings │  │
│  ┌──────────────────┐       │   "user_input" ──────────►│  │      ││     ││     │  │
│  │     Agent        │       │   "feedback"   ──────────►│  └──┬───┘└──┬──┘└─────┘  │
│  │  + Skills        │       │                            │     │       │              │
│  │  + ToolRegistry  │       │   ←────────── "status"     │     ▼       ▼              │
│  │  + MemoryManager │       │                            │  ┌──────────────────┐   │
│  │  + LearningCtrl  │       │                            │  │    UI Canvas     │   │
│  └──────────────────┘       │                            │  │                  │   │
│                              │                            │  │ ┌──────────────┐ │   │
│                              │                            │  │ │Live2D区域     │ │   │
│                              │                            │  │ │(RenderTexture)│ │   │
│                              │                            │  │ ├──────────────┤ │   │
│                              │                            │  │ │聊天记录       │ │   │
│                              │                            │  │ │(ScrollView)  │ │   │
│                              │                            │  │ ├──────────────┤ │   │
│                              │                            │  │ │输入框 │ [发送]│ │   │
│                              │                            │  │ │[👍][👎][⚙]  │ │   │
│                              │                            │  │ └──────────────┘ │   │
│                              │                            │  └──────────────────┘   │
│                              │                            │                          │
│                              │                            │  ┌──────────────────┐   │
│                              │                            │  │ Live2D Camera    │   │
│                              │                            │  │ (单独渲染模型)    │   │
│                              │                            │  │ Sakiko Model     │   │
│                              │                            │  │ + Cubism SDK     │   │
│                              │                            │  └──────────────────┘   │
└─────────────────────────────┘                            └──────────────────────────┘
```

**消息协议**（JSON）：

```json
// Python → Unity
{"type": "response", "text": "...", "emotion": "PLEASED", "motion_tags": ["smile"]}
{"type": "status", "state": "listening"|"thinking"|"speaking"|"idle"}

// Unity → Python
{"type": "user_input", "text": "你今天心情怎么样？"}
{"type": "feedback", "rating": 1, "correction": ""}
{"type": "command", "command": "reset"|"reindex"|"exit"}
```

---

## 总览：你要新建 / 修改的组件

### Python 端

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| P1 | `animate/server/__init__.py` | **新建**：server 包入口 |
| P2 | `animate/server/ws_client.py` | **新建**：WebSocket 客户端 `UnityBridge` |
| P3 | `cli.py` | **修改**：新增 `--unity` 模式 |

### Unity 端

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| U1 | `AniMateUnity/` 工程 | **新建**：Unity 项目 + 导入 Cubism SDK + 模型 |
| U2 | `WebSocketServer.cs` | **新建**：WebSocket 服务端 |
| U3 | `ChatController.cs` | **新建**：聊天 UI 逻辑 |
| U4 | `Live2DController.cs` | **新建**：Live2D 模型渲染与基础参数控制 |
| U5 | `SettingsManager.cs` | **新建**：设置面板 |
| U6 | `MainScene.unity` | **新建**：主场景组装 |
| U7 | 联调 | Python ↔ Unity 端到端跑通 |

---

## Python 端

---

### Step P1 · `animate/server/__init__.py`

空文件。

---

### Step P2 · `animate/server/ws_client.py` — UnityBridge

```python
import json, threading
from websocket import WebSocketApp

class UnityBridge:
    """Python ↔ Unity WebSocket 通信桥。"""

    def __init__(self, host="localhost", port=8765): ...
    def connect(self) -> bool: ...

    def send_response(self, response: AgentResponse) -> None:
        """发送 Agent 回复到 Unity。含 text, emotion, motion_tags。"""

    def send_status(self, state: str) -> None:
        """state: "idle" | "listening" | "thinking" | "speaking" 。"""

    def wait_for_input(self, timeout=None) -> str | None:
        """阻塞等待 Unity 用户输入。超时返回 None。"""

    def wait_for_feedback(self, timeout=1.0) -> dict | None:
        """非阻塞检查 👍/👎 反馈。"""

    def close(self) -> None: ...
```

**关键决策**：
- `wait_for_input` 阻塞式——替代了 Phase 3 的 `ConsoleInput` 角色。`--unity` 模式下不再用 ConsoleInput/ConsoleOutput
- `wait_for_feedback` 非阻塞——每轮后快速检查反馈，不阻塞下一轮
- 用 `threading.Event` 实现阻塞，不用 asyncio（保持全同步风格）

**自检**：Unity 空工程运行 → `UnityBridge().connect()` 成功。

---

### Step P3 · `cli.py` — Unity 模式

```python
if args.unity:
    bridge = UnityBridge()
    if not bridge.connect():
        print("无法连接 Unity"); return

    agent = Agent.create_with_mcp(...)

    while True:
        bridge.send_status("idle")
        user_input = bridge.wait_for_input()
        if user_input is None: continue

        if user_input.strip() == "/reset":
            agent.reset(); continue
        if user_input in {"exit", "quit"}: break

        bridge.send_status("thinking")
        response = agent.chat(user_input)

        bridge.send_status("speaking")
        bridge.send_response(response)

        # 检查反馈
        feedback = bridge.wait_for_feedback(timeout=0.5)
        if feedback:
            if feedback.get("rating"):
                agent.record_feedback(feedback["rating"])
            if feedback.get("correction"):
                agent.handle_correction(feedback["correction"])
else:
    # Console 模式不变
    ...
```

---

## Unity 端

---

### Step U1 · 创建项目 + 导入 Cubism SDK

1. Unity Hub → 新建 2D 项目 `AniMateUnity`，放仓库根目录
2. 下载 [Cubism SDK for Unity](https://www.live2d.com/download/cubism-sdk/)，导入项目
3. 祥子模型文件（`.model3.json` + 贴图 + `.moc3`）放入 `Assets/Live2D/Sakiko/`
4. 拖入 Scene → 确认能显示和呼吸动画

---

### Step U2 · `WebSocketServer.cs`

```csharp
using UnityEngine;
using System.Net.WebSockets;
using System.Collections.Concurrent;

public class WebSocketServer : MonoBehaviour
{
    [SerializeField] private int port = 8765;
    public event Action<string> OnMessageReceived;

    public async Task StartServer() { ... }
    public async Task SendMessage(string json) { ... }
    public bool IsConnected { get; private set; }
}
```

**注意**：WebSocket 操作在后台线程，更新 UI 需要回主线程（`UnityMainThreadDispatcher` 或类似机制）。

**自检**：Python `UnityBridge().connect()` → 连接成功。

---

### Step U3 · `ChatController.cs` — 聊天 UI

```csharp
public class ChatController : MonoBehaviour
{
    [SerializeField] private Transform messageContainer;
    [SerializeField] private GameObject userMessagePrefab, sakiMessagePrefab;
    [SerializeField] private InputField inputField;
    [SerializeField] private Button sendButton, likeButton, dislikeButton;
    [SerializeField] private Text emotionText;

    public event Action<string> OnUserSend;
    public event Action<int, string> OnFeedback;

    public void AddMessage(string sender, string text, string emotion = "") { ... }
    public void SetEmotion(string emotion, string icon) { ... }
    public void SetStatus(string status) { ... }
}
```

**UI 布局**：详见架构图中的 UI Canvas 部分——Live2D 区域在上、聊天 ScrollView 在中、输入框+按钮在下。

---

### Step U4 · `Live2DController.cs` — Live2D 基础控制

```csharp
using Live2D.Cubism.Core;

public class Live2DController : MonoBehaviour
{
    [SerializeField] private CubismModel model;

    // 基础情绪映射（Phase 7 会完善为 MotionMapper ScriptableObject）
    private Dictionary<string, Dictionary<string, float>> emotionMap = new()
    {
        ["CALM"] = new() { ["ParamEyeSmile"]=0f, ["ParamMouthSmile"]=0f, ["ParamBrowY"]=0f },
        ["PLEASED"] = new() { ["ParamEyeSmile"]=0.8f, ["ParamMouthSmile"]=0.6f, ["ParamBrowY"]=0.1f },
        ["COLD"] = new() { ["ParamEyeSmile"]=0f, ["ParamMouthSmile"]=0f, ["ParamBrowY"]=-0.5f, ["ParamEyeOpen"]=0.7f },
    };

    public void SetEmotion(string emotion)
    {
        if (!emotionMap.ContainsKey(emotion)) return;
        // 平滑过渡（Lerp），duration 500ms
        StartCoroutine(SmoothTransition(emotionMap[emotion], 0.5f));
    }
}
```

**自检**：`SetEmotion("PLEASED")` → 模型 0.5 秒内平滑微笑。

---

### Step U5 · `SettingsManager.cs`

设置面板（API Key、模型名、语音开关等），存 `PlayerPrefs`（非敏感项）或回写 Python `.env`（敏感项）。

---

### Step U6 · `MainScene.unity` 场景结构

```
MainScene
├── Main Camera + EventSystem
├── Canvas (Screen Space - Overlay)
│   ├── Panel_Live2D → RawImage (RenderTexture)
│   ├── Panel_Chat → ScrollView → Content (消息气泡)
│   ├── InputArea → InputField + Buttons
│   ├── StatusBar + EmotionText
│   └── SettingsPanel (默认隐藏)
├── Live2D Camera (Culling Mask = Live2D Layer)
│   └── Sakiko_Model (CubismModel + Live2DController)
└── Managers
    ├── WebSocketServer
    ├── ChatController
    ├── Live2DController
    ├── SettingsManager
    └── AppController (总控)
```

---

### Step U7 · 联调

1. Unity 运行 → WebSocket Server 监听 localhost:8765
2. `python cli.py --unity` → 连接
3. Unity 输入框输入 → 发送 → Python Agent 处理 → 返回 → Unity 显示回复
4. 情绪变化 → Live2D 模型表情变化
5. 👍/👎 → Python 收到反馈

---

## 跑通后会想做的事

1. **消息气泡美化**：Saki 气泡 + 头像、用户气泡不同风格
2. **过渡动画**：状态切换淡入淡出、消息滑入效果
3. **系统托盘**：最小化到托盘，像真正的桌面宠物
4. **打包发布**：Unity Build Standalone + PyInstaller 打包 Python 后端
5. **多分辨率适配**：Canvas Scaler

---

## 完成 Phase 5 的判定

- [ ] Unity 运行 → Python 连接 → 端到端对话跑通
- [ ] 聊天窗口正确显示用户和 Saki 消息
- [ ] 情绪变化 → Live2D 模型三种表情可区分
- [ ] 👍/👎 按钮 → Python 收到反馈
- [ ] Python 退出 → Unity 不崩溃
