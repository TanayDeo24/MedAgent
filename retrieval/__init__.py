"""RAG retrieval layer: corpus building, chunking, embedding, FAISS indexing.

Public interface for downstream consumers (agent nodes, in a later pass):

    from retrieval.retriever import retrieve
    results = retrieve("EGFR inhibitors in NSCLC", k=5)
"""
