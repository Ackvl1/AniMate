# Phase 7 开发手册 · Live2D 动作标签

> 目标：让祥子的 Live2D 模型在 Unity 中随情绪、对话内容和语音节奏自动切换表情和动作——平静时优雅呼吸、愉快时微笑、冷漠时皱眉、说话时嘴型跟随。通过 EventBus 驱动 + Cubism SDK 参数控制。
>
> 这份教程**只给思路、接口和自检清单，不给完整实现**。每一步留给你自己写。
>
> **前置状态**：Phase 3 通用框架（EventBus 就绪）、Phase 5 Unity UI（Live2D 模型已渲染、基础参数控制就绪）、Phase 6 语音（TTS 音频输出就绪）。

---

## 你需要先有的认知

- **Cubism 参数系统**：Live2D 模型的每个可动部分（眼睛、嘴巴、眉毛、身体角度）对应一个参数 ID，值域 0~1（或 -1~1）。通过 Cubism SDK 的 `CubismModel.Parameters[id].Value` 设置。
- **EventBus 驱动**：Phase 3 的 `EventBus` 是粘合剂——`EmotionSkill` 在情绪变化时发 `emotion.changed` 事件，Live2D 模块订阅并按事件驱动动作。
- **随语嘴型**：TTS 播放音频时，从 `AudioSource.GetSpectrumData` 获取实时音量，映射到 `ParamMouthOpen` 参数，实现嘴型跟随语音。
- **动画状态机**：简单版——不用 Unity Animator，用协程手动控制过渡（`Mathf.Lerp`），避免 Animator 的复杂度。

如果上面任何一条你觉得模糊，先去查清楚再继续。

---

## 架构

```
EmotionSkill.run()
    → 检测到情绪 CALM → PLEASED
    → EventBus.emit("emotion.changed", old=CALM, new=PLEASED)

Python 端                                Unity 端
─────────                                ────────
EventBus ──(WebSocket)──►  Live2DController.OnEmotionChanged()
                                   │
                                   ├── MotionMapper.Map(PLEASED)
                                   │   → ["smile", "eye_sparkle"]
                                   │
                                   ├── SmoothTransition(params, 500ms)
                                   │   ParamEyeSmile: 0.0 → 0.8
                                   │   ParamMouthSmile: 0.0 → 0.6
                                   │
                                   └── PlayIdleAnimation(coroutine)
                                       眨眼、呼吸、偶尔歪头
```

---

## 总览

本轮主要是**完善 Unity 端 `Live2DController`**，Phase 5 已有基本骨架，Phase 7 把它做精细。

| 步骤 | 文件 | 干什么 |
| --- | --- | --- |
| 1 | `animate/skills/emotion_skill.py` | **修改**：情绪变化时通过 EventBus 发事件（→WebSocket→Unity） |
| 2 | `animate/server/ws_client.py` | **修改**：`send_response` 加入 motion_tags、emotion 变化事件 |
| 3 | `Live2DController.cs` | **重写**：完善情绪过渡、表情映射、随语嘴型、空闲动画 |
| 4 | `MotionMapper.cs` | **新建**：情绪 + 上下文 → 参数目标值映射 |
| 5 | `IdleAnimator.cs` | **新建**：空闲动画系统（眨眼、呼吸、身体微动） |
| 6 | 调优 | 动作平滑度、参数映射值、动画节奏 |

---

## Step 1 · `animate/skills/emotion_skill.py` — 发送情绪事件

```python
def on_register(self, agent) -> None:
    agent.set_emotion_provider(self.state_machine)
    self._event_bus = agent.event_bus

def run(self, ctx: SkillContext) -> SkillContext:
    old = self.state_machine.current
    self.state_machine.update(ctx.user_input)
    new = self.state_machine.current
    ctx.emotion = new

    if old != new and self._event_bus:
        self._event_bus.emit(EVENT_EMOTION_CHANGED, old=old, new=new)
        # UnityBridge 订阅了此事件，会自动转发到 Unity

    # ... 其余不变 ...
```

---

## Step 2 · `animate/server/ws_client.py` — 转发动作标签

在 `send_response` 中加入 `motion_tags`：

```python
def send_response(self, response: AgentResponse) -> None:
    msg = {
        "type": "response",
        "text": response.text,
        "emotion": response.emotion.value,
        "motion_tags": response.motion_tags,
    }
    self._send_json(msg)
```

新增方法：当 EventBus 收到 `emotion.changed` 事件时转发：

```python
def send_emotion_change(self, old_emotion, new_emotion) -> None:
    self._send_json({
        "type": "emotion_changed",
        "old": old_emotion.value,
        "new": new_emotion.value,
    })
```

---

## Step 3 · `Live2DController.cs` — 完善控制器

```csharp
using Live2D.Cubism.Core;
using UnityEngine;
using System.Collections;
using System.Collections.Generic;

public class Live2DController : MonoBehaviour
{
    [SerializeField] private CubismModel model;
    [SerializeField] private MotionMapper motionMapper;
    [SerializeField] private IdleAnimator idleAnimator;
    [SerializeField] private float transitionDuration = 0.5f;

    private string _currentEmotion = "CALM";
    private Dictionary<string, Coroutine> _activeTransitions = new();

    // ── 情绪切换 ──
    public void OnEmotionChanged(string oldEmotion, string newEmotion)
    {
        _currentEmotion = newEmotion;
        var targets = motionMapper.MapEmotion(newEmotion, oldEmotion);
        SmoothTransition(targets, transitionDuration);
        idleAnimator.SetEmotion(newEmotion);
    }

    // ── 随语动作 ──
    public void OnTalkingStarted()
    {
        // 说话开始时略微张嘴 + 睁眼
        var talkParams = motionMapper.MapTalking(_currentEmotion);
        SmoothTransition(talkParams, 0.1f);
    }

    public void OnTalkingStopped()
    {
        // 说话结束回到当前情绪的默认表情
        var idleParams = motionMapper.MapEmotion(_currentEmotion);
        SmoothTransition(idleParams, 0.3f);
    }

    // ── 嘴型跟随音频 ──
    public void UpdateLipSync(float volume)
    {
        // volume: AudioSource.GetSpectrumData 归一化后的音量 0~1
        float mouthOpen = Mathf.Lerp(0.05f, 0.4f, volume);
        model.Parameters["ParamMouthOpen"].Value = mouthOpen;
    }

    // ── 平滑过渡 ──
    private void SmoothTransition(Dictionary<string, float> targets, float duration)
    {
        foreach (var (paramId, targetValue) in targets)
        {
            if (_activeTransitions.ContainsKey(paramId))
                StopCoroutine(_activeTransitions[paramId]);

            var coroutine = StartCoroutine(TransitionCoroutine(paramId, targetValue, duration));
            _activeTransitions[paramId] = coroutine;
        }
    }

    private IEnumerator TransitionCoroutine(string paramId, float target, float duration)
    {
        float start = model.Parameters[paramId].Value;
        float elapsed = 0f;

        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / duration;
            // 缓入缓出
            t = t * t * (3f - 2f * t);
            model.Parameters[paramId].Value = Mathf.Lerp(start, target, t);
            yield return null;
        }

        model.Parameters[paramId].Value = target;
        _activeTransitions.Remove(paramId);
    }
}
```

---

## Step 4 · `MotionMapper.cs` — 动作映射

```csharp
using UnityEngine;
using System.Collections.Generic;

[CreateAssetMenu(menuName = "Anima Agent/MotionMapper")]
public class MotionMapper : ScriptableObject
{
    // ── 情绪映射 ──
    [System.Serializable]
    public class EmotionMapping
    {
        public string emotion;  // "CALM" / "PLEASED" / "COLD"
        public List<ParameterTarget> parameters;
    }

    [System.Serializable]
    public class ParameterTarget
    {
        public string paramId;   // 如 "ParamEyeSmile"
        public float value;      // 0.0 ~ 1.0
    }

    [SerializeField] private List<EmotionMapping> emotionMappings;
    [SerializeField] private List<ParameterTarget> talkingOverrides; // 说话时的通用覆盖

    public Dictionary<string, float> MapEmotion(string emotion,
                                                  string previousEmotion = null)
    {
        // 从 emotionMappings 中找到对应情绪的参数列表 → Dictionary<string, float>
    }

    public Dictionary<string, float> MapTalking(string emotion)
    {
        // 当前情绪参数 + talkingOverrides 叠加
    }
}
```

**做成 ScriptableObject 的好处**：参数映射可以从 Unity Editor 直接编辑，不需要改代码。非程序员也能调表情。

**默认映射参考值**（具体参数名以你的模型为准）：

| 情绪 | ParamEyeSmile | ParamMouthSmile | ParamBrowY | ParamEyeOpen |
|------|:---:|:---:|:---:|:---:|
| CALM | 0.0 | 0.0 | 0.0 | 1.0 |
| PLEASED | 0.8 | 0.6 | 0.1 | 1.0 |
| COLD | 0.0 | 0.0 | -0.5 | 0.7 |

---

## Step 5 · `IdleAnimator.cs` — 空闲动画系统

```csharp
using UnityEngine;
using System.Collections;

public class IdleAnimator : MonoBehaviour
{
    [SerializeField] private CubismModel model;
    [SerializeField] private float blinkInterval = 4.0f;    // 平均眨眼间隔
    [SerializeField] private float blinkDuration = 0.15f;   // 一次眨眼时长
    [SerializeField] private float breathAmplitude = 0.05f; // 呼吸幅度

    private string _emotion = "CALM";

    public void SetEmotion(string emotion) => _emotion = emotion;

    private void Start()
    {
        StartCoroutine(BlinkLoop());
        StartCoroutine(BreathLoop());
        StartCoroutine(BodySwayLoop());
    }

    private IEnumerator BlinkLoop()
    {
        while (true)
        {
            float wait = Random.Range(blinkInterval * 0.5f, blinkInterval * 1.5f);
            yield return new WaitForSeconds(wait);

            // 闭眼
            model.Parameters["ParamEyeOpen"].Value = 0.0f;
            yield return new WaitForSeconds(blinkDuration);

            // 睁眼（不同情绪的睁眼幅度不同）
            float openValue = _emotion == "COLD" ? 0.7f : 1.0f;
            model.Parameters["ParamEyeOpen"].Value = openValue;
        }
    }

    private IEnumerator BreathLoop()
    {
        while (true)
        {
            // 用 sin 波模拟呼吸
            float time = 0f;
            while (time < 4.0f)
            {
                time += Time.deltaTime;
                float breath = Mathf.Sin(time * Mathf.PI * 0.5f) * breathAmplitude;
                model.Parameters["ParamBodyAngleY"].Value = breath;
                yield return null;
            }
        }
    }

    private IEnumerator BodySwayLoop()
    {
        while (true)
        {
            // 5~10 秒随机一次轻微歪头
            float wait = Random.Range(5f, 10f);
            yield return new WaitForSeconds(wait);

            float sway = Random.Range(-0.05f, 0.05f);
            // 平滑过渡到歪头位置再回来...
        }
    }
}
```

**自检**：
- Unity 运行 → 祥子每隔几秒自然眨眼
- 身体有轻微呼吸起伏
- 切换到 PLEASED → 呼吸节奏不变，表情更新

---

## Step 6 · 跑通后会想做的事

1. **参数校准**：对照实际模型在 Unity Inspector 中逐个参数调试，找到最自然的取值范围
2. **丰富动作库**：不只表情，还可控制头发飘动（`ParamHairSwing`）、耳朵摆动（如有）
3. **动作序列**：特定触发词 → 播放预定义动作序列（如被夸时害羞扭头）
4. **物理模拟**：利用 Cubism Physics 组件，让头发/裙摆随角色动作自然飘动
5. **粒子特效**：PLEASED 时身边飘花粒子、COLD 时身边飘冰晶（用 Unity Particle System）

---

## 完成 Phase 7 的判定

- [ ] 情绪变化时，Live2D 模型表情在 0.5 秒内平滑过渡
- [ ] CALM / PLEASED / COLD 三种情绪有视觉上明显的表情差异
- [ ] 说话时嘴型跟随音频音量变化（有 TTS 输出时生效）
- [ ] 空闲状态有自然眨眼和呼吸动画
- [ ] 情绪切换多次不卡顿、不闪烁
