"""
ComfyUI API调用服务 - 与ComfyUI后端通信

功能:
- 异步HTTP请求 (aiohttp)
- WebSocket 实时监听生成进度
- 超时处理和错误重试
"""
import json
import uuid
import logging
import asyncio
from typing import Optional, List, Dict, Any, Callable

import aiohttp

from app.config import settings

# 配置日志
logger = logging.getLogger(__name__)


class ComfyUIError(Exception):
    """ComfyUI 服务异常基类"""

    pass


class ComfyUIConnectionError(ComfyUIError):
    """连接异常"""

    pass


class ComfyUIQueueError(ComfyUIError):
    """队列提交异常"""

    pass


class ComfyUITimeoutError(ComfyUIError):
    """任务超时异常"""

    pass


class ComfyUIExecutionError(ComfyUIError):
    """任务执行失败异常（ComfyUI返回error状态）"""

    pass

class ComfyUIClient:
    """ComfyUI API 异步客户端"""

    def __init__(self, server_address: Optional[str] = None):
        """
        初始化 ComfyUI 客户端

        Args:
            server_address: ComfyUI 服务地址 (host:port)，默认从配置读取
        """
        self.server_address = server_address or settings.COMFYUI_SERVER_ADDRESS
        self.http_base = f"http://{self.server_address}"
        self.ws_base = f"ws://{self.server_address}"
        self.client_id = str(uuid.uuid4())
        self._session: Optional[aiohttp.ClientSession] = None

        logger.info(
            "ComfyUIClient initialized | server=%s | client_id=%s",
            self.server_address,
            self.client_id[:8],
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    # ==================== 连接检查 ====================

    async def check_connection(self) -> bool:
        """
        检查 ComfyUI 服务是否在线

        Returns:
            bool: True 表示服务在线
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.http_base}/system_stats",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    logger.info("ComfyUI 服务连接正常 | %s", self.server_address)
                    return True
                logger.warning("ComfyUI 返回异常状态码: %s", resp.status)
                return False
        except aiohttp.ClientError as e:
            logger.warning("ComfyUI 连接失败（非致命）: %s", str(e))
            return False
        except asyncio.TimeoutError:
            logger.warning("ComfyUI 连接超时（非致命）")
            return False

    # ==================== Prompt 提交 ====================

    async def queue_prompt(self, workflow: dict) -> str:
        """
        提交工作流到 ComfyUI 队列

        Args:
            workflow: ComfyUI 工作流字典（API格式）

        Returns:
            str: prompt_id

        Raises:
            ComfyUIQueueError: 提交失败
        """
        payload = {
            "prompt": workflow,
            "client_id": self.client_id,
        }

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.http_base}/prompt",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ComfyUIQueueError(
                        f"提交工作流失败 (HTTP {resp.status}): {error_text}"
                    )

                data = await resp.json()

                # 检查节点错误
                if "node_errors" in data and data["node_errors"]:
                    error_details = json.dumps(data["node_errors"], ensure_ascii=False)
                    raise ComfyUIQueueError(f"工作流节点错误: {error_details}")

                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    raise ComfyUIQueueError("响应中缺少 prompt_id")

                logger.info("工作流已提交 | prompt_id=%s", prompt_id)
                return prompt_id

        except ComfyUIQueueError:
            raise
        except aiohttp.ClientError as e:
            raise ComfyUIQueueError(f"HTTP 请求失败: {str(e)}") from e

    # ==================== 历史查询 ====================

    async def get_history(self, prompt_id: str) -> dict:
        """
        获取 prompt 执行历史

        Args:
            prompt_id: prompt ID

        Returns:
            dict: 执行历史数据
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.http_base}/history/{prompt_id}",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("获取历史失败 (HTTP %s) | prompt_id=%s", resp.status, prompt_id)
                    return {}

                data = await resp.json()
                return data.get(prompt_id, {})

        except aiohttp.ClientError as e:
            logger.error("获取历史异常: %s", str(e))
            return {}

    # ==================== 图片获取 ====================

    async def get_image(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> bytes:
        """
        获取生成的图片

        Args:
            filename: 文件名
            subfolder: 子目录
            folder_type: 文件夹类型 (output / input / temp)

        Returns:
            bytes: 图片二进制数据

        Raises:
            ComfyUIError: 获取失败
        """
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }

        try:
            session = await self._get_session()
            async with session.get(
                f"{self.http_base}/view",
                params=params,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    raise ComfyUIError(
                        f"获取图片失败 (HTTP {resp.status}): filename={filename}"
                    )

                image_data = await resp.read()
                logger.info("图片下载成功 | filename=%s | size=%d bytes", filename, len(image_data))
                return image_data

        except ComfyUIError:
            raise
        except aiohttp.ClientError as e:
            raise ComfyUIError(f"下载图片异常: {str(e)}") from e

    # ==================== 等待完成 ====================

    async def wait_for_completion(
        self,
        prompt_id: str,
        timeout: int = 300,
        poll_interval: float = 1.0,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> dict:
        """
        等待 prompt 执行完成

        使用 WebSocket 监听实时进度，同时轮询 history 作为兜底。

        Args:
            prompt_id: prompt ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）
            on_progress: 进度回调 (current, total)

        Returns:
            dict: 执行完成后的 history 数据

        Raises:
            ComfyUITimeoutError: 任务超时
            ComfyUIError: 执行失败
        """
        logger.info("等待任务完成 | prompt_id=%s | timeout=%ds", prompt_id, timeout)

        # 启动 WebSocket 监听（非阻塞）
        ws_task = asyncio.create_task(
            self._listen_ws(prompt_id, on_progress)
        )

        try:
            start_time = asyncio.get_event_loop().time()

            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    ws_task.cancel()
                    raise ComfyUITimeoutError(
                        f"任务超时: prompt_id={prompt_id}, timeout={timeout}s"
                    )

                # 查询执行状态
                history = await self.get_history(prompt_id)

                if history:
                    status = history.get("status", {})
                    status_str = status.get("status_str", "")
                    completed = status.get("completed", True)

                    # 检测执行错误状态（"error"），避免死等
                    if status_str == "error":
                        ws_task.cancel()
                        try:
                            await ws_task
                        except asyncio.CancelledError:
                            pass
                        error_msg = "未知执行错误"
                        try:
                            messages = status.get("messages", [])
                            if messages:
                                last_msg = messages[-1]
                                if isinstance(last_msg, list) and len(last_msg) > 1:
                                    error_msg = str(last_msg[1])
                        except Exception:
                            pass
                        raise ComfyUIExecutionError(
                            f"ComfyUI执行失败: prompt_id={prompt_id}, error={error_msg}"
                        )

                    if completed:
                        logger.info(
                            "任务执行完成 | prompt_id=%s | status=%s",
                            prompt_id,
                            status_str,
                        )

                        # 取消 WS 监听
                        ws_task.cancel()
                        try:
                            await ws_task
                        except asyncio.CancelledError:
                            pass

                        return history

                await asyncio.sleep(poll_interval)

        except ComfyUITimeoutError:
            raise
        except Exception as e:
            ws_task.cancel()
            raise ComfyUIError(f"等待任务异常: {str(e)}") from e

    async def _listen_ws(
        self,
        prompt_id: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """
        WebSocket 监听生成进度

        Args:
            prompt_id: 要监听的 prompt ID
            on_progress: 进度回调
        """
        ws_url = f"{self.ws_base}/ws?clientId={self.client_id}"

        try:
            session = await self._get_session()
            async with session.ws_connect(
                ws_url,
                timeout=aiohttp.ClientWSTimeout(ws_receive=10),
            ) as ws:
                logger.debug("WebSocket 已连接 | prompt_id=%s", prompt_id)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            msg_type = data.get("type", "")

                            if msg_type == "progress":
                                value = data.get("data", {}).get("value", 0)
                                max_val = data.get("data", {}).get("max", 0)
                                logger.debug(
                                    "生成进度 | prompt_id=%s | %d/%d",
                                    prompt_id, value, max_val,
                                )
                                if on_progress:
                                    on_progress(value, max_val)

                            elif msg_type == "executing":
                                node = data.get("data", {}).get("node")
                                prompt = data.get("data", {}).get("prompt_id")
                                if node is None and prompt == prompt_id:
                                    logger.debug(
                                        "执行完成信号 | prompt_id=%s", prompt_id
                                    )
                                    return

                            elif msg_type == "executed":
                                exec_prompt = data.get("data", {}).get("prompt_id")
                                if exec_prompt == prompt_id:
                                    logger.debug(
                                        "节点执行完成 | prompt_id=%s", prompt_id
                                    )

                        except json.JSONDecodeError:
                            logger.warning("WS 消息解析失败: %s", msg.data[:200])

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error("WebSocket 错误: %s", ws.exception())
                        break

        except asyncio.CancelledError:
            logger.debug("WebSocket 监听已取消 | prompt_id=%s", prompt_id)
        except aiohttp.ClientError as e:
            logger.warning("WebSocket 连接异常: %s", str(e))
        except Exception as e:
            logger.warning("WebSocket 监听异常: %s", str(e))

    # ==================== 图片上传 ====================

    async def upload_image(self, image_bytes: bytes, filename: str) -> dict:
        """
        上传参考图到 ComfyUI input 目录

        Args:
            image_bytes: 图片二进制数据
            filename: 文件名（如 "reference.png"）

        Returns:
            dict: 上传结果，如 {"name": "reference.png", "subfolder": "", "type": "input"}

        Raises:
            ComfyUIError: 上传失败
        """
        try:
            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field(
                "image",
                image_bytes,
                filename=filename,
                content_type="image/png" if filename.lower().endswith(".png") else "image/jpeg",
            )

            # 尝试 overwrite 参数
            params = {"overwrite": "true"}

            async with session.post(
                f"{self.http_base}/upload/image",
                params=params,
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise ComfyUIError(
                        f"上传图片失败 (HTTP {resp.status}): {error_text}"
                    )

                result = await resp.json()
                logger.info("图片上传成功 | filename=%s | name=%s", filename, result.get("name"))
                return result

        except ComfyUIError:
            raise
        except aiohttp.ClientError as e:
            raise ComfyUIError(f"上传图片异常: {str(e)}") from e

    # ==================== 节点信息 ====================

    async def get_object_info(self) -> dict:
        """
        获取 ComfyUI 节点信息（用于调试）

        Returns:
            dict: 节点信息
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.http_base}/object_info",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}
        except Exception as e:
            logger.warning("获取节点信息失败: %s", str(e))
            return {}

    # ==================== 中断执行 ====================

    async def interrupt(self) -> bool:
        """
        中断当前执行队列

        Returns:
            bool: 是否成功
        """
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.http_base}/interrupt",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    logger.info("已发送中断信号")
                    return True
                return False
        except Exception as e:
            logger.error("发送中断信号失败: %s", str(e))
            return False

    # ==================== 资源管理 ====================

    async def close(self) -> None:
        """关闭客户端，释放资源"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("ComfyUIClient 已关闭")
