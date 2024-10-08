from fs.memoryfs import MemoryFS
from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders.merge import MergedDataLoader
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.retrievers import ContextualCompressionRetriever
from langchain.schema import Document
from os import getenv

base_url = getenv("OLLAMA_HOST")
if base_url == None:
    base_url = "localhost:11434"

base_url = "http://"+base_url

from .in_memory_loader import InMemoryLoader

RAG_TEMPLATE = """
        <|system|>
        You are a supportive AI Assistant in a Retrieval Augmentation Generator (RAG).\
        You should follow instructions extremely well, help the user clarify doubts,\
        and provide insightful, truthful, and direct answers based on the context.\
        Do not retrieve HTML-like answers. Make sure your answer is based on the CONTEXT.

        If the user's query/ question is not in CONTEXT, please say, "I don't know; this is not clearly in the context."
        </section>

        <section>
        CONTEXT:
        <context>
        {context}
        </context>
        </section>

        <section>
        <|user|>
        {query}
        </section>

        <|assistant|>
        """

K_search = 5

class RAGTemplate:
    def __init__(self, web_urls, yt_transcript, mem_fs, llm_name="gpt-4o-mini"):
                #  llm_name="phi3.5"):
        self.docs = self.data_loaders(web_urls, yt_transcript, mem_fs)
        self.vector_store, self.split_documents = self.vector_db(self.docs)
        self.retriever, self.simple_retriever = self.retrieval(self.vector_store, self.split_documents)
        self.llm = Ollama(
            base_url = base_url,
            model="phi3.5",
            temperature=0.0)
        # import os
        # os.environ["OPENAI_API_KEY"] = "API-KEY"
        # self.llm = ChatOpenAI(model=llm_name, temperature=0.0)
    
    def data_loaders(self, web_urls, yt_transcript, mem_fs):
        # Loaders
        web_loader = WebBaseLoader(web_urls)
        web_loader.requests_per_second = 1
        yt_loader = InMemoryLoader(mem_fs, yt_transcript)
        loader_all = MergedDataLoader(loaders=[web_loader, yt_loader])
        docs_all = loader_all.load()

        return docs_all

    def vector_db(self, docs):
        text_splitter = RecursiveCharacterTextSplitter()
        split_documents = text_splitter.split_documents(docs)

        embeddings = OllamaEmbeddings(
            # model="nomic-embed-text"
            base_url = base_url,
            model="mxbai-embed-large"
            )
        vector_store = FAISS.from_documents(split_documents, embeddings)
        return vector_store, split_documents

    def retrieval(self, vector_store, split_documents):
        # Simple vector search + retrieval
        retriever_vectordb = vector_store.as_retriever()
        return retriever_vectordb, retriever_vectordb
        
    def augment_generate(self, query):
        # Augmentation and Generation
        prompt = ChatPromptTemplate.from_template(RAG_TEMPLATE)
        output_parser = StrOutputParser()

        chain = (
            {"context": self.retriever, "query": RunnablePassthrough()}
            | prompt
            | self.llm
            | output_parser
        )

        response = chain.invoke(query)
        return response
    
class SimpleRAGVectorSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        # Simple vector search + retrieval
        retriever_vectordb = vector_store.as_retriever()
        return retriever_vectordb, retriever_vectordb

class RerankRAGVectorSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        # Simple vector search + retrieval
        K = K_search
        retriever_vectordb = vector_store.as_retriever(search_kwargs={"k": K})
        # Implementing Re-ranking
        compressor = FlashrankRerank()
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=retriever_vectordb
        )
        return compression_retriever, retriever_vectordb

class SimpleRAGKeywordSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        # Simple keyword search + retrieval
        keyword_retriever = BM25Retriever.from_documents(split_documents)
        return keyword_retriever, keyword_retriever

class RerankRAGKeywordSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        K = K_search
        # Simple keyword search + retrieval
        keyword_retriever = BM25Retriever.from_documents(split_documents)
        keyword_retriever.k =  K

        # Implementing Re-ranking
        compressor = FlashrankRerank()
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=keyword_retriever
        )
        return compression_retriever, keyword_retriever

class SimpleRAGEnsembleVectorKeywordSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        # Vector Search + Keyword search
        retriever_vectordb = vector_store.as_retriever()
        keyword_retriever = BM25Retriever.from_documents(split_documents)

        ensemble_retriever = EnsembleRetriever(retrievers=
                                            [retriever_vectordb,keyword_retriever],
                                            weights=[0.5, 0.5])        
        return ensemble_retriever, keyword_retriever

class RerankRAGEnsembleVectorKeywordSearch(RAGTemplate):
    def retrieval(self, vector_store, split_documents):
        # Hybrid search + ensemble retrieval
        K = K_search
        retriever_vectordb = vector_store.as_retriever(search_kwargs={"k": K})

        keyword_retriever = BM25Retriever.from_documents(split_documents)
        keyword_retriever.k =  K

        ensemble_retriever = EnsembleRetriever(retrievers=
                                            [retriever_vectordb,keyword_retriever],
                                            weights=[0.5, 0.5])
                   
        # Implementing Re-ranking
        compressor = FlashrankRerank()
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=ensemble_retriever
        )
        return compression_retriever, ensemble_retriever
