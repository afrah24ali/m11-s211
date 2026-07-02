# Architecture Write-Up

This project uses a three-service microservice architecture instead of one monolithic application. The stack is split into a router service, a NER/KG service, and a RAG service. The router receives each question, classifies it, generates a request ID, and forwards the request to the correct backend. The NER/KG service handles entity-focused and knowledge-graph lookup questions, while the RAG service handles retrieval-style grounded answers.

This split gives the system clearer separation of responsibilities. Each service can be built, tested, monitored, and scaled independently. For example, if RAG becomes slower or more expensive, it can be optimized separately without changing the NER/KG service. The split also improves observability because every service exposes `/metrics`, and the same `X-Request-ID` can be traced across router and backend logs.

The cost is complexity. A monolith would be easier to run and debug because all logic would live in one process. With microservices, the stack now needs Docker Compose networking, service discovery, healthchecks, request forwarding, timeout handling, and cross-service logs. Bugs can happen not only inside a service, but also between services.

For this project, the microservice design makes sense because the goal is to practice routing, metrics, healthchecks, and cross-service correlation. In a small real product, starting with a monolith might be simpler. But for an AI system that may grow into multiple backends, the three-service split is a reasonable trade-off.
