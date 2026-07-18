# ADR-001: 默认使用云端图片生成 Provider

## Status
Accepted

## Date
2026-07-18

## Context

项目原始图片生成路径强依赖本地 ComfyUI 工作流和本机 GPU。当前上线目标要求：

- 生产部署不依赖本地大模型、Ollama 或本地 ComfyUI。
- 支持 OpenAI / DashScope / 其他 OpenAI-compatible API 配置。
- 密钥必须通过 `.env` 或环境变量读取。
- 本地能力可以保留，但必须是可选 dev 模式。

## Decision

引入图片生成 Provider 分层：

- `IMAGE_PROVIDER=cloud`：生产默认，通过 `CloudImageProvider` 调用 OpenAI-compatible `images.generate`。
- `IMAGE_PROVIDER=comfyui`：开发可选，保留原 ComfyUI workflow 能力。
- 健康检查以当前 Provider 为准；云端模式下 ComfyUI 状态显示为 `optional`。
- 本地 `rembg` 抠图通过 `ENABLE_LOCAL_PREPROCESSING=true` 显式启用，生产默认关闭。

## Alternatives Considered

### 继续强依赖 ComfyUI

- 优点：保留现有工作流质量和后处理路径。
- 缺点：上线依赖 GPU、本地服务和模型文件，不满足生产云端化目标。
- 结论：拒绝作为默认生产路径。

### 完全删除 ComfyUI

- 优点：部署最简单。
- 缺点：丢失现有 workflow 调试和低成本本地开发能力。
- 结论：不删除，降级为 dev provider。

## Consequences

- 生产容器只需要 API 服务和云端密钥即可启动。
- 云端图片 API 的模型差异通过 `.env` 管理。
- 若某 OpenAI-compatible 服务不支持图片生成，需要换 `IMAGE_MODEL` 或 provider，而不是改业务编排器。
- 本地抠图、ComfyUI、U2Net 缓存不会成为上线必需组件。
