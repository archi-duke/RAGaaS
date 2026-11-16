from motor.motor_asyncio import AsyncIOMotorClient
from app.models.chat_trace import ChatTrace
from beanie import init_beanie
from app.core.config import settings
from app.models.knowledge_base import KnowledgeBase
from app.models.prompt import PromptTemplate
from app.models.document import Document
from app.models.provider import CustomProvider, BuiltinProviderConfig
from app.models.schema_mapping import SchemaMappingRule, SchemaMappingProposal

# Client 인스턴스를 전역으로 유지할 수도 있음 (선택사항)
client: AsyncIOMotorClient = None

async def init_db():
    global client
    client = AsyncIOMotorClient(settings.MONGO_URI)
    
    # Beanie 초기화
    await init_beanie(
        database=client[settings.MONGO_DB],
        document_models=[
            KnowledgeBase,
            PromptTemplate,
            Document,
            CustomProvider,
            BuiltinProviderConfig,
            SchemaMappingRule,
            SchemaMappingProposal,
            ChatTrace,
        ]
    )


