"""Print response shape only, never credentials, vectors, or document text."""
import asyncio
import httpx
from agentscope.app.storage import RedisStorage, EmbeddingModelConfig
from agentscope.app._service._embedding import build_embedding_model

async def main():
    async with RedisStorage(host='127.0.0.1',port=6379) as storage:
        credential = await storage.get_credential('wei','e7001a2ec3cc49cca6f51bef52b4bdd8')
        config = EmbeddingModelConfig(type='openai_credential',credential_id=credential.id,model='Qwen/Qwen3-VL-Embedding-8B',dimensions=4096,parameters={})
        model = build_embedding_model(credential,config)
        try:
            for count in (1,4,32):
                response = await model.client.embeddings.create(model=config.model,input=[f'测试条目 {i}' for i in range(count)],encoding_format='float',dimensions=4096)
                print({'inputs':count,'returned':len(response.data),'indices':[r.index for r in response.data],
                    'dimensions':[len(r.embedding or getattr(r,'dense_embedding',[]) or []) for r in response.data]})
        finally: await model.client.close()

if __name__ == '__main__': asyncio.run(main())
