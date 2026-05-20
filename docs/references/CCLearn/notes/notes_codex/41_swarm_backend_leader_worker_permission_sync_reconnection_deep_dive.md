# 多 Agent 通信深拆 04：Swarm backend / leader-worker / permission sync / reconnection

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/37_multi_agent_communication_full_framework.md`
- 当前主题：**Swarm backend / leader-worker / permission sync / reconnection 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. 多 agent/swarm 的执行后端是怎么组织的
2. leader 与 worker 如何做权限同步
3. 多 agent 环境下如何做 reconnect / layout / mode snapshot

---

## 2. 主链图

```text
leader agent
      │
      ▼
utils/swarm/backends/registry.ts
  - 选择 backend
      │
      ├── InProcessBackend
      ├── TmuxBackend
      ├── ITermBackend
      └── PaneBackendExecutor
      │
      ▼
spawnInProcess / inProcessRunner / spawnUtils
      │
      ▼
leaderPermissionBridge / permissionSync
      │
      ▼
worker agents 执行
      │
      ▼
reconnection / teammateLayoutManager / teammateModeSnapshot
```

---

## 3. 关键文件职责

### `source/src/utils/swarm/backends/registry.ts`
- 注册/选择 swarm backend

### `source/src/utils/swarm/backends/InProcessBackend.ts`
- in-process backend 实现

### `source/src/utils/swarm/backends/TmuxBackend.ts`
- tmux backend 实现

### `source/src/utils/swarm/backends/ITermBackend.ts`
- iTerm backend 实现

### `source/src/utils/swarm/backends/PaneBackendExecutor.ts`
- pane 执行器 backend

### `source/src/utils/swarm/backends/detection.ts`
- backend 环境检测

### `source/src/utils/swarm/backends/it2Setup.ts`
- iTerm2 setup 逻辑

### `source/src/utils/swarm/backends/teammateModeSnapshot.ts`
- teammate mode snapshot

### `source/src/utils/swarm/backends/types.ts`
- backend 类型定义

### `source/src/utils/swarm/constants.ts`
- swarm 常量 |

### `source/src/utils/swarm/inProcessRunner.ts`
- in-process runner 主逻辑 |

### `source/src/utils/swarm/spawnInProcess.ts`
- in-process spawn |

### `source/src/utils/swarm/spawnUtils.ts`
- spawn 辅助 |

### `source/src/utils/swarm/leaderPermissionBridge.ts`
- leader -> worker 权限桥 |

### `source/src/utils/swarm/permissionSync.ts`
- swarm 权限同步 |

### `source/src/utils/swarm/reconnection.ts`
- swarm reconnection 逻辑 |

### `source/src/utils/swarm/teamHelpers.ts`
- team/swarm 辅助 |

### `source/src/utils/swarm/teammateInit.ts`
- teammate 初始化 |

### `source/src/utils/swarm/teammateLayoutManager.ts`
- teammate 布局管理 |

### `source/src/utils/swarm/teammateModel.ts`
- teammate model 辅助 |

### `source/src/utils/swarm/teammatePromptAddendum.ts`
- teammate prompt 补充 |

### `source/src/hooks/toolPermission/handlers/swarmWorkerHandler.ts`
- swarm worker 权限处理 |

---

## 4. 关键结论

1. **swarm 是有真实后端执行层的，不只是逻辑上的多个 agent**
2. **backend 可切换：in-process / tmux / iTerm / pane executor**
3. **leader-worker 权限同步是多 agent 执行环境的一条独立通信链**
4. **reconnection / mode snapshot / layout manager 说明 swarm 是长生命周期协作环境**
5. **这层通信不仅传消息，还传执行环境、权限、布局和状态**
