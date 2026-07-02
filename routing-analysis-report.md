# Routing Analysis Report

## Routing Accuracy

- Total fixture questions: 15
- Correct routing decisions: 12
- Routing accuracy: 0.800

| Question | Expected | Routed Target | Request ID |
|---|---:|---:|---|
| Extract the company names mentioned in this earnings report. | ner-kg | ner-kg | `096f4e21-b7ea-4719-a713-a1099776fe73` |
| List all people and organizations in this article. | ner-kg | rag | `30bea6d7-7b8a-42e5-aab7-a900d3390dd2` |
| What entities appear in the following text? | ner-kg | ner-kg | `8670a5a8-679d-4288-8484-29558865583a` |
| Find every product mentioned in this paragraph. | ner-kg | rag | `b034cfc0-ef3d-4321-87be-a83aa1750919` |
| Which companies has Microsoft acquired since 2020? | ner-kg | rag | `1a0a18b6-9fd1-4b21-9195-c7bdf0e74560` |
| Who are the suppliers of TSMC according to the knowledge graph? | ner-kg | ner-kg | `275229b9-91d0-4dd5-8833-7d212467c7c5` |
| What is the parent company of Anthropic? | ner-kg | ner-kg | `530aef66-06c4-4171-98ff-7921233bf89f` |
| Return the entities of type ORGANIZATION in this passage. | ner-kg | ner-kg | `e9b2f678-8522-48c6-8abe-434d51dfb3a5` |
| Summarize how transformer attention works. | rag | rag | `e244b2f5-432f-44ae-bf5e-d1617db2aa28` |
| Explain the trade-off between micro and macro F1. | rag | rag | `83b54a71-2aad-48eb-b302-ec8d80194a36` |
| How should I think about latency-vs-load profiling for an inference service? | rag | rag | `f220c5a7-51cb-4245-9047-fe83ca850fc8` |
| Why does prometheus prefer histograms over summaries for latency? | rag | rag | `f45b6706-19ff-4f40-a145-72c64c201af6` |
| What is the role of a router in a multi-agent system? | rag | rag | `40b1f66d-2f88-4f7f-8499-c860d687f523` |
| Walk me through how RAG grounding rate is computed. | rag | rag | `7eb2e842-e036-40e0-bd6a-bdb79ce432a2` |
| Describe the difference between vector and keyword retrieval. | rag | rag | `9dc9edd4-3cf3-47f1-89f4-73f6176bec26` |

## Per-Service Metrics

| Service | Request Volume | Estimated p95 Latency |
|---|---:|---:|
| router | 447 | 0.005s |
| ner-kg | 426 | 0.005s |
| rag | 438 | 0.005s |

## Routing Pattern

- 10/15 questions (66.7%) were routed to `rag`.
- `ner-kg` received 5 decisions (33.3%).
- `rag` received 10 decisions (66.7%).

## Cross-Service Correlation

The router produced request IDs for 15 out of 15 routing decisions. 0 decisions were missing request IDs. The same request ID is forwarded through the `X-Request-ID` header, so a single request can be traced from the router log to the selected backend log.

Manual verification command:

```bash
docker compose -f docker-compose-stretch.yml logs | grep <request-id>
```
