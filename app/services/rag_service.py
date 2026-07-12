"""
RAG知识库服务 - 基于 llama-index 和 chromadb 实现的知识检索服务

功能:
- 使用 SimpleDirectoryReader 读取 knowledge_base/ 目录下所有 .md 文件
- 使用 OpenAI text-embedding-ada-002 作为 embedding 模型
- 使用 ChromaDB 作为向量存储，支持持久化到 knowledge_base_index/ 目录
- 支持按平台名称进行精准查询
"""
import os
import logging
from pathlib import Path
from typing import List, Optional

from llama_index import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    ServiceContext,
    StorageContext,
)
from llama_index.embeddings import OpenAIEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

from app.config import settings

# 配置日志
logger = logging.getLogger(__name__)


class RAGService:
    """RAG知识库服务，用于管理和检索平台规则知识"""

    def __init__(self):
        """初始化RAG服务"""
        # 使用绝对路径确保路径正确
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.persist_dir = str(base_dir / settings.RAG_PERSIST_DIR)
        self.knowledge_base_dir = str(base_dir / settings.KNOWLEDGE_BASE_DIR)
        self.embedding_model_name = settings.EMBEDDING_MODEL
        self.collection_name = "platform_rules"

        # 初始化 ChromaDB 客户端
        self.chroma_client = chromadb.PersistentClient(path=self.persist_dir)

        # 确保持久化目录存在
        os.makedirs(self.persist_dir, exist_ok=True)

        # 平台列表
        self.platforms = {
            "amazon": "Amazon",
            "aliexpress": "AliExpress（速卖通）",
            "taobao": "淘宝/天猫",
            "shopee": "Shopee",
        }

        logger.info(
            "RAGService initialized | persist_dir=%s | knowledge_base_dir=%s | embedding_model=%s",
            self.persist_dir,
            self.knowledge_base_dir,
            self.embedding_model_name,
        )

    def _create_embedding_model(self) -> OpenAIEmbedding:
        """创建 embedding 模型实例
        
        兼容阿里云百炼等非 OpenAI 原生模型名（如 text-embedding-v3）。
        llama-index 0.9.27 会校验模型名，因此先用已知模型名初始化，
        再覆盖 model_name 为实际使用的模型名。
        """
        try:
            return OpenAIEmbedding(
                model=self.embedding_model_name,
                api_key=settings.OPENAI_API_KEY,
                api_base=settings.OPENAI_BASE_URL,
            )
        except (ValueError, TypeError):
            pass

        # 使用默认模型名绕过枚举校验，再覆盖实际模型名
        embed_model = OpenAIEmbedding(
            model="text-embedding-ada-002",
            api_key=settings.OPENAI_API_KEY,
            api_base=settings.OPENAI_BASE_URL,
        )
        embed_model.model_name = self.embedding_model_name
        # 同时覆盖内部引擎，确保 API 调用使用正确的模型名
        embed_model._query_engine = self.embedding_model_name
        embed_model._text_engine = self.embedding_model_name
        logger.info(
            "Embedding 模型名已覆盖: ada-002 → %s",
            self.embedding_model_name,
        )
        return embed_model

    def _create_service_context(self) -> ServiceContext:
        """创建 ServiceContext"""
        embed_model = self._create_embedding_model()
        return ServiceContext.from_defaults(
            embed_model=embed_model,
            chunk_size=1024,
            chunk_overlap=200,
        )

    def _get_chroma_collection(self):
        """获取或创建 ChromaDB collection"""
        collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug("ChromaDB collection '%s' loaded", self.collection_name)
        return collection

    def build_index(self) -> VectorStoreIndex:
        """
        构建新索引 - 从 knowledge_base/ 读取所有 .md 文件并创建向量索引

        Returns:
            VectorStoreIndex: 构建完成的索引
        """
        logger.info("开始构建 RAG 索引...")

        # 检查知识库目录
        kb_path = Path(self.knowledge_base_dir)
        if not kb_path.exists() or not kb_path.is_dir():
            raise FileNotFoundError(f"知识库目录不存在: {self.knowledge_base_dir}")

        # 列出可用的 .md 文件
        md_files = list(kb_path.glob("*.md"))
        if not md_files:
            raise FileNotFoundError(f"知识库目录中没有 .md 文件: {self.knowledge_base_dir}")

        logger.info("找到 %d 个规则文件: %s", len(md_files), [f.name for f in md_files])

        # 使用 SimpleDirectoryReader 加载文档
        documents = SimpleDirectoryReader(
            input_dir=self.knowledge_base_dir,
            required_exts=[".md"],
            recursive=False,
        ).load_data()

        logger.info("成功加载 %d 个文档", len(documents))

        # 创建 ServiceContext
        service_context = self._create_service_context()

        # 删除已有的 collection（如果存在），确保全新构建
        try:
            self.chroma_client.delete_collection(name=self.collection_name)
            logger.info("已删除旧的 collection")
        except Exception:
            logger.info("不存在旧的 collection，直接创建")

        # 创建新的 collection（复用 self.chroma_client）
        collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 构建索引（insert_batch_size=10 适配阿里云 text-embedding-v3 限制）
        index = VectorStoreIndex.from_documents(
            documents,
            service_context=service_context,
            storage_context=storage_context,
            insert_batch_size=10,
        )

        # 持久化索引
        index.storage_context.persist(persist_dir=self.persist_dir)

        logger.info(
            "RAG 索引构建完成 | 文档数=%d | 持久化目录=%s",
            len(documents),
            self.persist_dir,
        )
        return index

    def load_index(self) -> Optional[VectorStoreIndex]:
        """
        加载已有索引 - 从 knowledge_base_index/ 加载已持久化的向量索引

        Returns:
            Optional[VectorStoreIndex]: 已加载的索引，如果不存在则返回 None
        """
        logger.info("尝试加载已有 RAG 索引...")

        persist_path = Path(self.persist_dir)

        # 检查持久化目录是否存在
        if not persist_path.exists():
            logger.warning("持久化目录不存在: %s", self.persist_dir)
            return None

        # 检查 ChromaDB 数据是否存在
        chroma_db_files = list(persist_path.glob("chroma.sqlite3"))
        if not chroma_db_files:
            logger.warning("未找到 ChromaDB 数据文件")
            return None

        try:
            chroma_client = chromadb.PersistentClient(path=self.persist_dir)

            # 检查 collection 是否存在
            collection_names = chroma_client.list_collections()
            if not any(c.name == self.collection_name for c in collection_names):
                logger.warning("未找到 collection '%s'", self.collection_name)
                return None

            collection = chroma_client.get_collection(name=self.collection_name)
            count = collection.count()
            if count == 0:
                logger.warning("collection 为空，请重新构建索引")
                return None

            logger.info("找到已有索引，collection包含 %d 条记录", count)

            vector_store = ChromaVectorStore(chroma_collection=collection)
            service_context = self._create_service_context()

            index = VectorStoreIndex.from_vector_store(
                vector_store,
                service_context=service_context,
            )

            logger.info("RAG 索引加载成功")
            return index

        except Exception as e:
            logger.error("加载索引失败: %s", str(e))
            return None

    def get_or_create_index(self) -> VectorStoreIndex:
        """
        智能判断：优先加载已有索引，若不存在则构建新索引

        Returns:
            VectorStoreIndex: 可用的索引
        """
        index = self.load_index()
        if index is not None:
            return index

        logger.info("未找到可用索引，开始构建新索引...")
        return self.build_index()

    def _get_index(self) -> VectorStoreIndex:
        """
        内部方法：获取索引（优先加载已有索引）

        Returns:
            VectorStoreIndex: 可用的索引
        """
        index = self.load_index()
        if index is None:
            raise RuntimeError(
                "索引尚未构建。请先调用 build_index() 或 get_or_create_index()"
            )
        return index

    def query_rules(self, platform: str, query: str, top_k: int = 5) -> str:
        """
        根据平台和问题查询相关规则

        Args:
            platform: 平台名称 (amazon/aliexpress/taobao/shopee)
            query: 查询问题文本
            top_k: 返回的文档片段数量，默认 5

        Returns:
            str: 检索到的规则文本（合并后）
        """
        # 规范化平台名称
        platform_lower = platform.lower().strip()
        platform_display = self.platforms.get(platform_lower, platform)

        # 将平台名称融入查询以提高检索精度
        enhanced_query = f"【{platform_display}】平台的规则: {query}"

        logger.info(
            "查询规则 | platform=%s | enhanced_query=%s | top_k=%d",
            platform_display,
            query,
            top_k,
        )

        index = self._get_index()

        # 创建查询引擎
        query_engine = index.as_query_engine(
            similarity_top_k=top_k,
            response_mode="no_text",  # 只返回检索到的文档片段，不生成回复
        )

        # 执行查询
        response = query_engine.query(enhanced_query)

        # 提取检索到的文本内容
        result_texts = []
        if hasattr(response, "source_nodes"):
            for i, node in enumerate(response.source_nodes):
                score = node.score if hasattr(node, "score") else "N/A"
                text = node.node.text if hasattr(node.node, "text") else str(node.node)
                result_texts.append(f"--- 片段 {i+1} (相关度: {score:.4f}) ---\n{text}")

        if not result_texts:
            return f"未找到与 '{query}' 相关的 {platform_display} 平台规则。"

        result = "\n\n".join(result_texts)
        logger.info("查询完成 | 返回 %d 个片段", len(result_texts))
        return result

    def get_all_rules_for_platform(self, platform: str) -> str:
        """
        获取某平台的所有规则内容

        Args:
            platform: 平台名称 (amazon/aliexpress/taobao/shopee)

        Returns:
            str: 该平台的完整规则文本
        """
        platform_lower = platform.lower().strip()

        # 构建预期的文件名
        platform_file_map = {
            "amazon": "amazon_rules.md",
            "aliexpress": "aliexpress_rules.md",
            "taobao": "taobao_rules.md",
            "shopee": "shopee_rules.md",
        }

        filename = platform_file_map.get(platform_lower)
        if not filename:
            return f"不支持的平台: {platform}。支持的平台: {', '.join(self.platforms.keys())}"

        file_path = Path(self.knowledge_base_dir) / filename
        if not file_path.exists():
            return f"平台 '{platform}' 的规则文件不存在: {file_path}"

        logger.info("读取平台完整规则 | platform=%s | file=%s", platform, filename)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            logger.info("读取完成 | 共 %d 字符", len(content))
            return content
        except Exception as e:
            logger.error("读取规则文件失败: %s", str(e))
            return f"读取规则文件失败: {str(e)}"

    async def build_index_async(self) -> VectorStoreIndex:
        """
        异步构建索引（在事件循环中运行同步构建操作）

        Returns:
            VectorStoreIndex: 构建完成的索引
        """
        import asyncio
        return await asyncio.to_thread(self.build_index)

    async def query_rules_async(self, platform: str, query: str, top_k: int = 5) -> str:
        """
        异步查询规则

        Args:
            platform: 平台名称
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            str: 检索到的规则文本
        """
        import asyncio
        return await asyncio.to_thread(self.query_rules, platform, query, top_k)

    async def add_document(self, file_path: str) -> None:
        """
        向知识库添加新文档并重建索引

        Args:
            file_path: 文档路径
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"文档不存在: {file_path}")

        dst = Path(self.knowledge_base_dir) / src.name
        import shutil
        shutil.copy2(src, dst)
        logger.info("文档已复制到知识库: %s -> %s", src, dst)

        # 重建索引以包含新文档
        logger.info("添加新文档后重建索引...")
        self.build_index()

    async def delete_document(self, filename: str) -> None:
        """
        从知识库删除文档并重建索引

        Args:
            filename: 要删除的文件名（不含路径，如 "amazon_rules.md"）
        """
        target = Path(self.knowledge_base_dir) / filename
        if target.exists():
            target.unlink()
            logger.info("文档已删除: %s", target)
        else:
            logger.warning("文档不存在，无需删除: %s", target)

        # 重建索引
        logger.info("删除文档后重建索引...")
        self.build_index()
