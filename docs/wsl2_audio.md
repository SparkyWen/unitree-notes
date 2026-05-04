# WSL2 音频修复记录（va-demo / sounddevice / PortAudio）

> 2026-05-04 修复了在 WSL2 + conda env (`agi`) 下跑 `va-demo` 时麦克风/扬声器完全打不开的问题。
> 这份文档记录了**完整的根因链 + 实际修复步骤 + 验证方法 + 后续维护**，方便以后任何 `sounddevice`/`pyaudio`/PortAudio 程序撞同样的错时直接定位。

---

## 0. 现象

```
$ conda activate agi
$ cd ~/unitree/unitree-notes/va-demo
$ set -a; source .env; set +a
$ python -m va_demo.main --mode confirm
...
  File ".../va_demo/audio_io.py", line 68, in start
    self._stream = self._sd.RawInputStream(...)
  File ".../sounddevice.py", line 2750, in _get_stream_parameters
    info = query_devices(device)
  File ".../sounddevice.py", line 577, in query_devices
    raise PortAudioError(f'Error querying device {device}')
sounddevice.PortAudioError: Error querying device -1
```

关键信号：**device 索引是 `-1`**。这是 PortAudio "没有默认设备"的哨兵值。

环境：

| | |
|---|---|
| OS | WSL2 (Linux 6.6.87.2-microsoft-standard-WSL2) on Windows |
| Python | conda env `agi`，Python 3.11，`~/miniforge3/envs/agi/` |
| sounddevice | 0.5.5（pip wheel，pure Python wrapper，加载 ctypes） |
| portaudio | conda-forge `19.7.0` (`~/miniforge3/envs/agi/lib/libportaudio.so`) |
| WSLg PulseAudio | 已运行，socket = `/mnt/wslg/PulseServer` |

---

## 1. 根因分析（逐层剥洋葱）

### 1.1 第一层：va-demo 没指定设备

`va-demo/configs/va_demo.yaml`:

```yaml
audio:
  input_device: null
  output_device: null
```

`null` → `MicStream(device=None)` → `RawInputStream(device=None)` → sounddevice 用 `sd.default.device`。问题就出在 default。

### 1.2 第二层：sounddevice 报告"零设备"

```python
>>> import sounddevice as sd
>>> sd.default.device
[-1, -1]                    # 没有默认输入也没有默认输出
>>> sd.query_hostapis()
[{'name': 'ALSA', 'default_input_device': -1, 'default_output_device': -1, ...}]
>>> sd.query_devices()
                            # 空列表，一个设备都没有
```

PortAudio 只列出 ALSA 一个 host API，且枚举不到任何设备。

### 1.3 第三层：WSLg PulseAudio 本身是健康的

```bash
$ pactl info | head -3
Server String: unix:/mnt/wslg/PulseServer
Library Protocol Version: 35
Server Protocol Version: 35

$ pactl list short sources
1   RDPSink.monitor   module-rdp-sink.c     s16le 2ch 44100Hz   SUSPENDED
2   RDPSource         module-rdp-source.c   s16le 1ch 44100Hz   SUSPENDED   ← 麦克风桥到 Windows

$ pactl list short sinks
1   RDPSink           module-rdp-sink.c     s16le 2ch 44100Hz   SUSPENDED   ← 扬声器桥到 Windows
```

WSLg 已经把 Windows 音频通过 RDP 桥到 Linux 端的 PulseAudio。**所以 Linux 端不是没有音频，而是 PortAudio 找不到路径**。

### 1.4 第四层：ALSA 在 WSL2 里看不到任何硬件

```bash
$ aplay -l
aplay: device_list:277: no soundcards found...
$ arecord -l
arecord: device_list:277: no soundcards found...
```

WSL2 不通过 ALSA 暴露硬件声卡，**WSLg 只通过 PulseAudio 暴露**。所以 PortAudio 的 ALSA 后端去找 `hw:0,0` 这种硬件设备一定是空的。

### 1.5 第五层（关键）：conda 的 PortAudio 没有 PulseAudio 后端

```bash
$ ldd ~/miniforge3/envs/agi/lib/libportaudio.so | grep -E 'pulse|asound|jack'
    libasound.so.2 => ...    # 只链了 ALSA，没有 pulse / jack
```

PortAudio v19.7 的官方源码 **根本没有** PulseAudio host API：

```bash
$ ls ~/src/portaudio/src/hostapi/
alsa  asihpi  asio  coreaudio  dsound  jack  oss  skeleton  wasapi  wdmks  wmme
$ ./configure --help | grep -i pulse
(empty)
```

> 这不是 conda-forge 的问题。**Debian/Ubuntu 的 `libportaudio2` 也是 ALSA-only**（apt show 显示 `Depends: libasound2t64, libjack-jackd2-0`，没有 libpulse）。这是 PortAudio 项目长期未合并的 PR。
>
> **结论：在 Linux 上不要试图编译"带 pulse 后端"的 PortAudio**——官方源码就没这个东西。

那 Linux 上的 PortAudio 程序怎么用 PulseAudio？答案是**通过 ALSA 的 `pulse` PCM 插件间接桥接**：

```
sounddevice → PortAudio (ALSA host API) → libasound → ALSA pcm_pulse plugin → PulseAudio
```

`pulse` plugin 来自 apt 包 `libasound2-plugins`（提供 `libasound_module_pcm_pulse.so`）。

### 1.6 第六层（真正的根因）：conda 的 libasound 找不到插件目录

```bash
$ strings ~/miniforge3/envs/agi/lib/libasound.so.2 | grep alsa-lib
%s/alsa-lib
/home/helios/miniforge3/envs/agi/lib/alsa-lib    ← 编译时硬编码的插件搜索路径

$ ls ~/miniforge3/envs/agi/lib/alsa-lib
ls: cannot access '...': No such file or directory   ← 这个目录根本不存在
```

conda 的 `libasound.so.2` 把它的插件路径 **硬编码** 到 `$CONDA_PREFIX/lib/alsa-lib/`，而 conda 又没装任何 ALSA 插件，所以这个目录是空的（实际上不存在）。

**最终因果链：**

```
conda libasound 没有插件目录
  → 解析 ALSA "default" PCM 时找不到 pcm_pulse 插件
    → ALSA 拒绝打开 default
      → PortAudio 的 ALSA 后端在枚举时看不到 default
        → sounddevice.query_devices() 返回空
          → sd.default.device 是 [-1, -1]
            → RawInputStream(device=None) 解析到设备 -1
              → query_devices(-1) 报错
```

**验证假设**：用系统的 `libasound.so.2`（它知道去 `/usr/lib/x86_64-linux-gnu/alsa-lib/` 找插件）替换试试：

```bash
$ LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasound.so.2 \
    conda run -n agi python -c "import sounddevice as sd; print(sd.query_devices())"
  0 pulse, ALSA (32 in, 32 out)
* 1 default, ALSA (32 in, 32 out)
```

立刻通了，确认根因。

---

## 2. 实际修复步骤

### Step 1：装系统侧的 ALSA → PulseAudio 桥接组件

```bash
sudo apt-get update
sudo apt-get install -y \
    libasound2-plugins \
    build-essential libpulse-dev libasound2-dev libjack-jackd2-dev \
    wget pkg-config
```

| 包 | 作用 |
|---|---|
| `libasound2-plugins` | 提供 `libasound_module_pcm_pulse.so` —— **唯一必装的关键包**，让 ALSA 能桥接到 PulseAudio |
| 其余 | 构建工具 + ALSA/Pulse/JACK 开发头文件。本次最终没用上（不需要重编 portaudio），但留着方便日后真要编译音频库 |

> 实际上**只需要 `libasound2-plugins`** 就足够。其它包是当初尝试方案 A（编译带 pulse 的 portaudio）装的，事后发现 PortAudio 官方就没 pulse 后端，编译路线无效。这些包留下来无副作用，也很小。

确认 pulse 插件存在：
```bash
$ ls /usr/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_pulse.so
/usr/lib/x86_64-linux-gnu/alsa-lib/libasound_module_pcm_pulse.so   ✓
```

### Step 2：写 `~/.asoundrc`，把 ALSA `default` 路由到 PulseAudio

```bash
cat > ~/.asoundrc <<'EOF'
# Route ALSA "default" through PulseAudio so apps that only speak ALSA
# (e.g. conda-forge libportaudio.so, which has no PulseAudio host API)
# can reach WSLg's PulseAudio at /mnt/wslg/PulseServer.
#
# To revert: delete this file. To diagnose: `aplay -L | head` should list
# "pulse" and "default" pointing at the pulse plugin.

pcm.!default {
    type pulse
    fallback "sysdefault"
    hint {
        show on
        description "Default ALSA Output (PulseAudio via WSLg)"
    }
}

ctl.!default {
    type pulse
    fallback "sysdefault"
}

pcm.pulse { type pulse }
ctl.pulse { type pulse }
EOF
```

副作用：用户级 dotfile，影响所有 ALSA-aware 程序的"default"设备走向。**对系统其它部分零干扰**（系统上根本没有别的 ALSA 设备，不存在被覆盖的问题）。

### Step 3（**关键的关键**）：把 conda env 的 ALSA 插件路径 symlink 到系统目录

```bash
ln -sfn /usr/lib/x86_64-linux-gnu/alsa-lib \
        ~/miniforge3/envs/agi/lib/alsa-lib
```

这一步是真正解决问题的核心。Step 1 + Step 2 让系统的 ALSA 能桥到 PulseAudio，但 conda env 里的 `libasound` 仍然只看 `$CONDA_PREFIX/lib/alsa-lib/`。symlink 把这个空目录指到系统的 alsa-lib 目录，conda 的 ALSA 立刻就拿到了 `pulse` 等所有插件。

副作用：

- 只新增 1 个 symlink，**不替换/不修改任何二进制**。
- ABI 兼容性：conda 的 libasound 是 1.2.x，系统的 ALSA 插件是 1.2.11，主版本号一致，二进制兼容。
- 隔离性：只影响 `agi` 这一个 conda env，其它 env / 系统 Python 不受影响。
- 可逆：`rm ~/miniforge3/envs/agi/lib/alsa-lib` 即可还原。

### Step 4：清掉 sudo 凭证缓存

```bash
sudo -k
```

纯粹的安全卫生 —— 防止后续命令意外以 root 权限运行。

---

## 3. 验证

### 3.1 sounddevice 看到设备了

```bash
$ conda run -n agi python -c "
import sounddevice as sd
print('default device:', sd.default.device)
print('host APIs:')
for i, h in enumerate(sd.query_hostapis()):
    print(f'  [{i}] {h[\"name\"]} default_in={h[\"default_input_device\"]} default_out={h[\"default_output_device\"]}')
print('devices:')
print(sd.query_devices())
"
default device: [1, 1]
host APIs:
  [0] ALSA default_in=1 default_out=1
devices:
  0 pulse, ALSA (32 in, 32 out)
* 1 default, ALSA (32 in, 32 out)
```

对照修复前：`default device: [-1, -1]`，devices 列表为空。

### 3.2 端到端录音测试（用 va-demo 完全相同的参数）

```python
import sounddevice as sd, numpy as np, time, queue
q = queue.Queue()
def cb(indata, frames, t, status): q.put(bytes(indata))
with sd.RawInputStream(samplerate=24000, blocksize=1200,
                       dtype='int16', channels=1, callback=cb):
    time.sleep(1.0)
buf = b''.join([q.get() for _ in range(q.qsize())])
arr = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
print(f'captured {len(buf)} bytes, RMS={np.sqrt(np.mean(arr*arr)):.1f}')
# captured 50400 bytes, RMS=17.5     ← 真实环境音；如果是静音 RMS<5
```

### 3.3 端到端播放测试

```python
import sounddevice as sd, numpy as np, time
sr = 24000
t = np.linspace(0, 0.3, int(sr*0.3), endpoint=False)
tone = (0.2 * np.sin(2*np.pi*440*t) * 32767).astype(np.int16).tobytes()
with sd.RawOutputStream(samplerate=sr, blocksize=0,
                        dtype='int16', channels=1) as s:
    s.write(tone); time.sleep(0.4)
# 应该能从 Windows 扬声器听到 0.3s 的 440Hz 蜂鸣
```

### 3.4 跑 va-demo

```bash
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
conda activate agi
python -m va_demo.main --mode confirm
```

不再在 `mic.start()` 报 device -1 错误。

---

## 4. 整体架构图（修复后的音频路径）

```
       ┌─────────────────────────────────────────────────────────┐
       │  Windows 11 主机                                         │
       │     麦克风  ←─────────RDP─────────→  扬声器             │
       └──────────────────────┬──────────────────────────────────┘
                              │
       ┌──────────────────────┴──────────────────────────────────┐
       │  WSL2 (Ubuntu 24.04) — WSLg subsystem                   │
       │                                                          │
       │     PulseAudio (WSLg-managed, /mnt/wslg/PulseServer)     │
       │       ├── RDPSource (从 Windows 麦克风拿数据)             │
       │       └── RDPSink   (推数据到 Windows 扬声器)             │
       │                ▲                                          │
       │                │  unix socket                              │
       │                │                                          │
       │     /usr/lib/x86_64-linux-gnu/alsa-lib/                  │
       │       └── libasound_module_pcm_pulse.so                  │
       │                ▲                                          │
       │                │ dlopen()                                  │
       │                │                                          │
       │     ~/.asoundrc:  pcm.!default { type pulse }            │
       │                ▲                                          │
       │                │ snd_pcm_open("default")                  │
       │                │                                          │
       │     ~/miniforge3/envs/agi/lib/                           │
       │       ├── libasound.so.2  (conda)                        │
       │       │     └─ 找插件时去 lib/alsa-lib/                    │
       │       └── alsa-lib  ──symlink──▶  /usr/lib/.../alsa-lib  │ ← Step 3
       │                ▲                                          │
       │                │                                          │
       │     libportaudio.so  (conda, ALSA-only host API)         │
       │                ▲                                          │
       │                │ ctypes                                    │
       │                │                                          │
       │     sounddevice.py (pip)                                 │
       │                ▲                                          │
       │                │                                          │
       │     va_demo/audio_io.py                                  │
       │                                                          │
       └─────────────────────────────────────────────────────────┘
```

绿色路径全程贯通后，va-demo 的 `RawInputStream` / `RawOutputStream` 才能成功打开。

---

## 5. 后续维护

### 5.1 新建 conda env 想用音频时

每个新 env 都要重新做一次 symlink（asoundrc 是用户级，不用重做）：

```bash
ln -sfn /usr/lib/x86_64-linux-gnu/alsa-lib $CONDA_PREFIX/lib/alsa-lib
```

可以塞进 env 的 activate hook 自动化（可选）：

```bash
mkdir -p $CONDA_PREFIX/etc/conda/activate.d
cat > $CONDA_PREFIX/etc/conda/activate.d/alsa_plugin_dir.sh <<'EOF'
[ -e "$CONDA_PREFIX/lib/alsa-lib" ] || \
    ln -sfn /usr/lib/x86_64-linux-gnu/alsa-lib "$CONDA_PREFIX/lib/alsa-lib"
EOF
```

### 5.2 conda upgrade / 包重装可能破坏 symlink

如果 `conda install` 重装 `alsa-lib` 包（conda-forge 有这个包），可能会把这个 symlink 替换成它自带的（多半是空的）目录。届时只需重做：

```bash
rm -rf $CONDA_PREFIX/lib/alsa-lib
ln -sfn /usr/lib/x86_64-linux-gnu/alsa-lib $CONDA_PREFIX/lib/alsa-lib
```

### 5.3 不要尝试的弯路

| 想法 | 为什么不要 |
|---|---|
| 编译带 PulseAudio 的 portaudio | PortAudio v19.7 官方源码**没有** pulse host API，`./configure --with-pulseaudio` 这个 flag 不存在 |
| `apt install libportaudio2` 然后让 conda 用系统的 | 系统 portaudio 也只编了 ALSA，对解决问题完全没帮助 |
| 直接给 va-demo 配 `input_device: 0` 之类的索引 | 修复前 `query_devices()` 是空的，根本没有任何索引可填 |
| 把 conda 的 `libasound.so.2` 替换为系统的 | 风险大，可能破坏其它 conda 包；本质上 conda 的 libasound 没坏，只是缺插件目录 |

### 5.4 故障排查清单

如果将来音频又坏了，按这个顺序查：

```bash
# 1. WSLg pulse 还在吗？
pactl info | head -3                       # 应该看到 Server String: unix:/mnt/wslg/PulseServer
ls -la /mnt/wslg/PulseServer               # socket 文件应该存在

# 2. ALSA 能解析 default → pulse 吗？
aplay -L | grep -A1 -E '^default|^pulse'   # 应该列出 default 和 pulse

# 3. asoundrc 还在吗？
ls -la ~/.asoundrc

# 4. conda env 的插件目录 symlink 还在吗？
ls -la $CONDA_PREFIX/lib/alsa-lib          # 应该是 symlink → /usr/lib/.../alsa-lib

# 5. sounddevice 能看到设备吗？
python -c "import sounddevice as sd; print(sd.query_devices())"
# 应该看到 pulse 和 default 两个设备
```

任何一步异常 → 回到本文档对应的 step 修复。

---

## 6. 一句话总结

> **WSL2 没有 ALSA 硬件，只有 WSLg PulseAudio。Linux 上的 PortAudio 没有 pulse 后端，必须靠 ALSA 的 pulse 插件桥接。conda env 自带的 libasound 因为插件路径硬编码到了空目录而完全失明 —— 一个 symlink 把它指向系统的 ALSA 插件目录，整条链立刻打通。**
