# 多 Agent 通信深拆 03：Mailbox / SendMessage / queued message / bridge messaging

- 仓库路径：`cc/claude_code`
- 对应总文档：`cc/cc_learn/37_multi_agent_communication_full_framework.md`
- 当前主题：**Mailbox / SendMessage / queued message / bridge messaging 深拆**

---

## 1. 这份文档聚焦什么

这里只研究：

1. agent 之间如何显式发消息
2. mailbox / queued messages 在运行时里是什么角色
3. bridge messaging 如何把消息扩展到跨进程/跨环境通信

---

## 2. 主链图

```text
agent A
  -> SendMessageTool
      │
      ▼
mailbox / queued messages
  ├── context/mailbox.tsx
  ├── context/QueuedMessageContext.tsx
  ├── utils/mailbox.ts
  └── utils/teammateMailbox.ts
      │
      ▼
hooks/useMailboxBridge.ts
      │
      ▼
bridge/bridgeMessaging.ts
      │
      ▼
agent B / teammate / remote session 收到消息
```

---

## 3. 关键文件职责

### `source/src/tools/SendMessageTool/SendMessageTool.ts`
- agent 间显式发送消息工具
- 是消息通道的业务入口

### `source/src/tools/SendMessageTool/UI.tsx`
- SendMessageTool UI

### `source/src/tools/SendMessageTool/constants.ts`
- SendMessageTool 常量

### `source/src/tools/SendMessageTool/prompt.ts`
- SendMessageTool prompt/schema

### `source/src/context/mailbox.tsx`
- mailbox 上下文
- 运行时消息通道容器

### `source/src/context/QueuedMessageContext.tsx`
- queued messages 上下文
- 支撑异步排队投递

### `source/src/utils/mailbox.ts`
- mailbox 辅助逻辑

### `source/src/utils/teammateMailbox.ts`
- teammate mailbox 辅助逻辑

### `source/src/hooks/useMailboxBridge.ts`
- 把 mailbox 与 bridge/runtime 连接起来

### `source/src/bridge/bridgeMessaging.ts`
- bridge 层消息转运
- 使消息可跨环境流动

---

## 4. 关键结论

1. **SendMessageTool 是显式 agent message passing 的顶层入口**
2. **mailbox 说明消息很多时候不是立即调用，而是事件队列/收件箱模型**
3. **queued messages 让通信天然支持异步**
4. **bridgeMessaging 把 mailbox 从本地运行时扩展到远端/跨进程场景**
5. **这条链更像 actor/message 系统，而不是同步函数调用**
