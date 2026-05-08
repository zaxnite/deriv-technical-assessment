# Senior Backend Engineer — Trading Infrastructure
## Hiring Committee Briefing Document

---

## Rank 1 — Aisha Okonkwo

**Overall Score**: 8.34 / 10

**Hire Confidence**: Strong Yes

**Confidence Justification**: Exceeds all core requirements with proven production experience at scale in trading systems, strong domain expertise, and demonstrated technical leadership.

**Strengths**:
- **Backend Engineering Depth & Seniority**: 7 years of backend engineering with team leadership experience (led 4-person team)
- **High-Throughput Systems**: Direct experience building real-time trade execution engine handling 50k req/s, exceeding the 10k req/s requirement by 5x
- **Financial Systems Domain**: Strong fintech background with trading platform expertise at Lagos fintech startup
- **Language Proficiency**: Fluent in both Python and Go
- **Real-Time Architecture**: Proven ability with Kafka for event streaming and Redis for caching in high-performance contexts
- **Data Persistence**: PostgreSQL expertise demonstrated in production fintech environment

**Gaps**:
- **Formal Education**: No degree listed (Minor) — Does not impact technical capability but may affect some corporate hiring policies
- **Containerization Stack**: Score of 7/10 suggests Docker/Kubernetes experience may be less comprehensive than preferred (Moderate) — May require onboarding on current orchestration practices
- **NoSQL Breadth**: Only Redis mentioned; no evidence of other NoSQL databases like MongoDB or DynamoDB (Minor) — Easily addressed through on-the-job learning

**Recommended Interview Focus**:
1. **Trade Execution Engine Architecture**: Deep dive into how the 50k req/s system handled order routing, latency optimization, and failure scenarios—probe for understanding of bottlenecks and scaling decisions
2. **Kafka Streaming Patterns**: Explore specific use cases for Kafka in the trading engine, consumer group management, and how backpressure was handled in real-time contexts
3. **Team Leadership & Async Culture Fit**: Discuss experience leading distributed teams, code review practices, and how they structured async decision-making—critical for distributed team requirement

---

## Rank 2 — Dmitri Volkov

**Overall Score**: 8.18 / 10

**Hire Confidence**: Yes

**Confidence Justification**: Exceptional infrastructure and containerization expertise with proven high-frequency trading experience, though with slightly lower domain depth and a language proficiency trade-off (Rust instead of Python).

**Strengths**:
- **Backend Engineering Depth & Seniority**: 8 years of backend engineering experience
- **High-Throughput Systems**: Direct high-frequency trading infrastructure expertise, demonstrating mastery of sub-millisecond latency requirements
- **Containerization Stack**: Kubernetes expert with score of 9/10—exceptional fit for modern infrastructure requirements
- **Real-Time Data Architecture**: Kafka and Redis experience with ClickHouse indicating sophisticated data pipeline knowledge
- **Financial Systems Domain**: High-frequency trading firm background shows understanding of regulatory constraints and risk management in finance
- **Go Proficiency**: Strong Go experience aligned with job requirements

**Gaps**:
- **Python Proficiency**: Only Go and Rust listed; no Python mentioned (Moderate) — Python is explicitly preferred; may reduce ability to work across the full codebase immediately
- **Fintech Regulatory Experience**: Not mentioned in resume summary (Moderate) — Prop trading HFT differs from regulated fintech; may lack understanding of compliance and licensing requirements relevant to Deriv
- **Financial Systems Breadth**: HFT background is specialized; less evidence of broader payment processing or trading platform operations (Moderate) — May need ramp-up on non-HFT trading scenarios

**Recommended Interview Focus**:
1. **Python Acquisition Timeline & Capability**: Assess ability to quickly upskill in Python given Go expertise; discuss previous polyglot programming experience and learning velocity
2. **Regulatory & Operational Differences**: Probe understanding of how HFT infrastructure differs from regulated retail/B2B trading platforms regarding compliance, audit trails, and risk controls
3. **ClickHouse & Analytics Pipeline Design**: Explore rationale for ClickHouse selection, real-time analytics architecture, and how this integrates with order execution systems—assesses thinking on data platform diversity

---

## Rank 3 — Mei-Lin Zhang

**Overall Score**: 6.60 / 10

**Hire Confidence**: Maybe

**Confidence Justification**: Strong foundational skills and Python expertise with legitimate trading domain exposure, but falls short of the 5+ years requirement and lacks demonstrated high-throughput production experience at required scale.

**Strengths**:
- **Python Proficiency**: Expert-level Python skills (8/10) with demonstrated depth through open-source trading library contributions
- **Real-Time Data Architecture**: WebSocket pipeline experience directly relevant to job requirements, with score of 8/10
- **Financial Systems Knowledge**: Legitimate trading domain exposure through open-source contributions and crypto exchange work
- **Data Persistence**: PostgreSQL and MongoDB experience covers both relational and NoSQL databases
- **Domain Passion**: Open-source contributions suggest intrinsic interest in trading systems beyond just employment

**Gaps**:
- **Years of Experience**: Only 4 years versus required 5+ years (Critical) — Does not meet minimum seniority threshold; lacks depth in system design for large-scale production
- **High-Throughput System Experience**: Score of 6/10 indicates limited exposure to systems handling >10k req/s (Critical) — No evidence of working at required performance scale in production
- **Backend Engineering Depth**: Score of 5/10 suggests relative junior status; may lack experience with large distributed systems, operational concerns, and production troubleshooting (Critical)
- **Containerization Stack**: Score of 6/10; Docker/Kubernetes experience not clearly demonstrated (Moderate) — May require significant onboarding on orchestration
- **Current Role Context**: Early-stage startup background may not have exposed to enterprise-scale infrastructure or distributed team practices (Moderate)

**Recommended Interview Focus**:
1. **Scaling the WebSocket Pipeline**: Ask about the crypto exchange pipeline—what throughput did it handle, what bottlenecks were encountered, and how would they architect for 50x higher volume
2. **Production System Maturity & Operations**: Probe open-source contributions for depth—did they own deployment, monitoring, incident response, or only core feature development; assess understanding of production readiness
3. **Career Trajectory & Role Expectations**: Understand whether this role is intended as a career step up or lateral move; explore learning plan for closing the 1+ year experience gap and high-throughput system knowledge

---

## Cohort Analysis

The candidate pool demonstrates **strong overall quality** with the top two candidates clearly exceeding requirements and presenting minimal risk. Both C1 and C4 bring proven production experience in trading systems at scale (50k and HFT respectively), with complementary strengths: C1 offers depth in financial domain and Python/Go balance, while C4 provides superior infrastructure and containerization expertise. The cohort's **primary common gap** is lack of demonstrated expertise across the full stack—C1 shows moderate containerization depth, C4 lacks Python, and both could benefit from broader NoSQL exposure. C3 represents a **junior outlier** who falls short of the 5+ year requirement, though shows promising potential if the role can accommodate a mid-level engineer. **Recommendation: Proceed with confidence into detailed interviews with C1 and C4 as primary tracks**, with C1 as the preferred option given balanced proficiency across all stated requirements. C3 should be **deprioritized unless C1 and C4 decline**; if the business has flexibility to hire a junior engineer with growth potential, C3 merits consideration but should not occupy a senior role slot. Expanding the search is **not necessary** given the strength of the top two candidates.

---

## Structured Interview Questions — Aisha Okonkwo

**Question 1 [Behavioural — validates: Leadership & Team Scaling]**
You led a team of 4 engineers while building the trade execution engine at your Lagos fintech startup. Walk us through a specific technical decision or architectural change you championed as a leader that initially faced resistance from your team. How did you handle the disagreement, and what was the outcome in terms of system performance or team capability?

**Question 2 [Behavioural — validates: Ownership in High-Stakes Financial Systems]**
Trading infrastructure requires extreme reliability—a bug in order execution or settlement logic can cost the company significant money. Describe a production incident in your trade execution engine where something went wrong. What was your role in diagnosing and fixing it, and what safeguards did you implement afterward to prevent recurrence?

**Question 3 [Technical — probes: WebSocket & Real-Time Data Pipeline Gap]**
Your trade execution engine handled 50k req/s through Kafka. At Deriv, we stream live market data and trade updates to thousands of concurrent traders via WebSocket connections. Your resume doesn't mention WebSocket experience. Walk us through how you would architect the real-time data path from market feed → server → connected clients, and explain where you'd use WebSocket versus your Kafka-based approach, and why.

**Question 4 [Technical — probes: Containerisation & Orchestration Gap]**
You've demonstrated strong experience with PostgreSQL, Redis, and Kafka in production, but Docker and Kubernetes aren't mentioned. Describe a scenario where your trade execution engine needed to scale horizontally during peak market hours. How did you manage deployment, service discovery, and state consistency across instances? If you didn't use containers, what would you need to learn to containerize and orchestrate a similar system for Deriv?

**Question 5 [Technical — validates: High-Throughput Optimization Under Constraints]**
Your trade execution engine achieved 50k req/s—impressive for a Lagos-based startup. Walk us through the specific bottlenecks you encountered as throughput scaled (e.g., database connection pooling, message broker partitioning, network I/O). Pick one critical optimization you implemented and explain your trade-offs in latency, consistency, and operational complexity. How would your approach differ if you needed to handle 500k req/s at Deriv?

---

## Cohort Analysis

This candidate pool demonstrates strong senior-level talent with two genuinely excellent fits (Aisha at 8.34/10 and Dmitri at 8.18/10) who both exceed the 5+ years requirement and score 8-9/10 across high-throughput, low-latency, and financial domain criteria—however, a sharp quality cliff emerges at rank three, where Mei-Lin (6.60/10) falls below the seniority bar at only 4 years experience despite solid technical skills, and the remaining three candidates (James, Tom, Priya) all score below 6/10 due to compounding gaps: James lacks both Go/Python proficiency (5/10) and async architecture experience (4/10), Tom is severely deficient in financial systems knowledge (2/10) and real-time architecture (5/10), and Priya's payments background doesn't translate to trading-grade throughput (5/10 high-throughput score) or async systems (3/10). The systemic pattern across ranks 3-6 is a critical mismatch between general backend seniority and the *specific* intersection of financial domain expertise, real-time/async architecture, and Python/Go proficiency required for trading infrastructure—these gaps cannot be easily trained in the role. **Recommendation: Proceed immediately with first-round interviews for Aisha and Dmitri (both clear hires pending cultural fit), but expand the search rather than proceeding with ranks 3-6.** The drop-off is too severe; Mei-Lin's under-4-years experience disqualifies her regardless of potential, and candidates 4-6 each lack 2-3 critical technical pillars that are difficult to backfill during onboarding. A focused re-recruitment targeting backend engineers with 5+ years at fintech/crypto/prop trading firms or those with demonstrable real-time async systems experience will yield higher probability of advancing candidates to offer stage.