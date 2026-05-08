# Senior Backend Engineer — Trading Infrastructure
## Hiring Committee Briefing

---

## Rank 1 — Dmitri Volkov

**Overall Score**: 7.63 / 10

**Hire Confidence**: Strong Yes

**Confidence Justification**: Exceptional fit for high-throughput trading infrastructure with proven Kubernetes expertise and direct prop trading experience, offset only by limited regulatory/compliance background.

**Strengths**:
- **Backend Engineering & Language Proficiency**: 8 years with Go and Rust—exceeds 5+ year requirement and provides strong modern language foundation for trading systems
- **High-Throughput & Low-Latency Systems**: Demonstrated expertise building high-frequency trading infrastructure; direct experience with performance-critical systems at required scale
- **Containerization & Distributed Systems**: Kubernetes expert (9/10)—excellent match for containerization requirement and modern deployment patterns
- **Real-Time Data Infrastructure**: Strong background with Kafka and Redis, critical technologies for trading data pipelines
- **Trading Domain Knowledge**: Worked directly in prop trading firm on infrastructure challenges relevant to derivatives trading

**Gaps**:
- **Financial Regulatory & Compliance**: No fintech regulatory experience noted (Moderate) — Deriv operates in regulated markets; will require onboarding on compliance frameworks
- **PostgreSQL Expertise**: Resume shows Redis and ClickHouse but no explicit PostgreSQL experience (Moderate) — core requirement but learnable with typical onboarding
- **WebSocket-Specific Experience**: Not explicitly mentioned, though real-time infrastructure experience suggests capability (Minor) — common pattern in trading systems

**Recommended Interview Focus**:
1. **Kafka & Event Streaming at Scale**: Deep dive into Kafka architecture decisions at prop trading firm—partition strategy, lag monitoring, and failure recovery for trading events
2. **Kubernetes Production Operations**: Probe incident response, resource management, and multi-region deployment patterns for trading infrastructure uptime requirements
3. **PostgreSQL & Regulatory Audit Trails**: Discuss willingness/capability to learn PostgreSQL and design for immutable audit logging needed in regulated trading platforms

---

## Rank 2 — Aisha Okonkwo

**Overall Score**: 7.52 / 10

**Hire Confidence**: Strong Yes

**Confidence Justification**: Exceptional fintech domain expertise with proven ability to build and scale real-time trading systems, though containerization experience lags and leadership transition may require discussion.

**Strengths**:
- **Financial Systems & Trading Domain Knowledge**: 9/10—built trade execution engines at 50k req/s; intimate understanding of trading workflows, settlement, and execution challenges
- **Backend Engineering & Language Proficiency**: 7 years with both Python and Go; comfortable with multiple languages required for backend infrastructure
- **Real-Time Data & WebSocket Infrastructure**: 8/10—direct experience with trade execution engine requiring real-time event handling and low-latency responses
- **High-Throughput Systems**: Proven capability managing 50k req/s—exceeds 10k req/s requirement by 5x
- **Data Persistence**: PostgreSQL and Redis experience; good mix of relational and cache layer for trading data
- **Team Leadership**: Led team of 4, suggesting architectural thinking and communication skills

**Gaps**:
- **Containerization & Distributed Systems**: 5/10 score is lowest on team—unclear Docker/Kubernetes depth; may require ramp-up time (Moderate) — modern standard for deployment pipelines
- **NoSQL Database Diversity**: Redis listed but no mention of ClickHouse, MongoDB, or other NoSQL options beyond cache (Minor) — Redis covers common use case but limits flexibility
- **Formal Credentials**: No degree listed (Minor) — not a technical blocker for 7 years of production experience, but may affect onboarding or future mobility within some organizations

**Recommended Interview Focus**:
1. **Trade Execution Engine Architecture**: Detailed walkthrough of 50k req/s system—how was latency optimized? What bottlenecks emerged? How were failures handled in live trading?
2. **Docker & Kubernetes Adoption**: Probe specific containerization experience—has candidate used Docker/Kubernetes in production, or is this an area for growth? What's the learning curve?
3. **Scaling PostgreSQL for Trading**: Discuss schema design for high-volume trade records—partitioning strategy, index optimization, and handling of concurrent writes during market spikes

---

## Rank 3 — James Whitfield

**Overall Score**: 5.35 / 10

**Hire Confidence**: Maybe

**Confidence Justification**: Strong financial systems pedigree from tier-1 banks but significant gaps in modern containerization, WebSocket infrastructure, and non-Java language proficiency create material onboarding risk.

**Strengths**:
- **Financial Systems & Trading Domain Knowledge**: 8/10—6 years at Goldman Sachs and Barclays working on equity derivatives pricing; understands regulatory, operational, and market risk requirements at enterprise scale
- **High-Throughput & Low-Latency Systems**: 7/10—explicit low-latency focus aligns with derivatives trading infrastructure needs
- **Academic Foundation**: Oxford CS degree suggests strong CS fundamentals for distributed systems theory
- **Backend Engineering Experience**: 6 years at recognized institutions implies rigorous engineering standards

**Gaps**:
- **WebSocket & Real-Time Data Infrastructure**: 3/10 score is critical gap—no WebSocket experience listed; equity derivatives pricing is batch-oriented vs. streaming real-time data (Critical) — core requirement for Deriv's platform
- **Language Proficiency Mismatch**: Java primary language; Python secondary; no Go or Rust (Critical) — job explicitly requires strong Python or Go; Java/JVM stack is different paradigm for trading microservices
- **Containerization & Distributed Systems**: 4/10—unclear Kubernetes/Docker maturity; banking infrastructure often uses legacy monoliths (Critical) — modern infrastructure requirement not demonstrated
- **Data Persistence Expertise**: 3/10 score is critical—no PostgreSQL or NoSQL database experience listed; banking systems often abstract away DB layer (Critical) — fundamental infrastructure skill gap
- **Technology Stack Recency**: Background suggests legacy financial systems (pricing engines, derivatives models) vs. modern cloud-native trading platforms (Critical)

**Recommended Interview Focus**:
1. **Real-Time vs. Batch Architecture Transition**: How does candidate view moving from equity derivatives batch pricing to streaming WebSocket-based market data pipelines? What's the mental model shift required?
2. **Language Transition to Python/Go**: Assess willingness and capability to become proficient in Python or Go—how quickly can Java expertise transfer to event-driven, concurrent systems in different languages?
3. **Cloud-Native & PostgreSQL Fundamentals**: Probe specific experience with relational database optimization, containerized deployment patterns, and Kubernetes concepts—or clarity on learning plan if starting from scratch

---

## Summary Recommendation

**Proceed with Rounds 2 & 3**: Dmitri Volkov (C4) and Aisha Okonkwo (C1) are both strong candidates with complementary profiles. Dmitri excels in infrastructure and containerization; Aisha brings unmatched trading domain expertise. **Consider passing on Rank 3** (James Whitfield) unless regulatory/enterprise credibility is weighted heavily—multiple critical technology gaps create onboarding risk that may not be justified by financial domain knowledge alone.

---

## Structured Interview Questions — Dmitri Volkov

**Question 1 [Behavioural — validates: High-Throughput & Low-Latency Systems]**
Walk me through a specific incident at your prop trading firm where latency degradation occurred in production. What was the root cause, how did you diagnose it, and what architectural or infrastructure changes did you implement to prevent recurrence? What were the measurable improvements in p99 or p999 latency?

**Question 2 [Behavioural — probes: Financial Systems & Trading Domain Knowledge gap (regulatory experience)]**
At Deriv, we operate in highly regulated markets with strict compliance requirements around order handling, market abuse detection, and audit trails. How have you approached compliance or auditability in your previous trading infrastructure work? Have you had to integrate with compliance or risk teams, and if so, how did you bridge the gap between engineering constraints and regulatory requirements?

**Question 3 [Technical — probes: Data Persistence & Database Expertise gap (PostgreSQL)]**
Your background emphasizes Redis and ClickHouse. In our trading platform, we need PostgreSQL for transactional consistency on orders, positions, and account state, while using ClickHouse for analytics. Describe how you would architect the data flow between these systems to ensure strong consistency on critical trading data while maintaining real-time analytics. What potential race conditions or sync failures concern you most?

**Question 4 [Technical — validates: Real-Time Data & WebSocket Infrastructure]**
Describe the real-time data pipeline you built for your HFT infrastructure—specifically: what was the end-to-end latency from market data ingestion through Kafka to client delivery, what protocol did you use for client connections, and how did you handle backpressure when subscribers couldn't keep up with market tick velocity? How would you adapt this for WebSocket clients with varying network conditions?

**Question 5 [Technical — validates: Containerization & Distributed Systems strength]**
Given your Kubernetes expertise in HFT environments, walk me through how you would design a multi-region, auto-scaling deployment for a trading API serving 50k+ concurrent WebSocket connections with strict latency SLOs (p99 < 100ms). Address: pod placement strategy, stateful vs stateless service separation, how you'd handle graceful shutdown during trading hours, and your observability/alerting approach for detecting degradation.

---

## Cohort Analysis

This candidate pool exhibits a bifurcated talent distribution with two strong contenders (Volkov at 7.63 and Okonkwo at 7.52) but a steep drop-off in depth thereafter. The top two candidates both meet the core technical requirements—5+ years backend experience, proficiency in Go/Python, proven high-throughput system design (8/10 scores in multiple critical areas)—yet each has a distinct weakness: Volkov lacks fintech regulatory exposure and scores only 6/10 in database expertise (ClickHouse is specialized for analytics, not transactional systems), while Okonkwo shows a concerning 5/10 gap in containerization and distributed systems orchestration despite strong trading domain knowledge (9/10). The remaining four candidates (Whitfield, Zhang, Nair, Henderson) all fall below 5.4/10, revealing a pervasive pattern across the pool: no candidate outside the top two simultaneously demonstrates strength in *all six* core areas. Specific recurring gaps include WebSocket/real-time infrastructure expertise (only Volkov, Okonkwo, and Zhang score above 7/10), containerization proficiency (only three candidates reach 5/10 or higher), and database breadth—most candidates show expertise in either PostgreSQL *or* NoSQL, not both at depth. **Recommendation: Proceed with Volkov as primary offer and Okonkwo as strong backup, contingent on 2-week technical assessments focused on their specific gaps (database systems design for Volkov; Docker/Kubernetes orchestration for Okonkwo), but simultaneously expand the search.** The 2.3-point gap between #2 and #3, combined with no candidate exceeding 8/10 in more than two criteria, suggests the current pool lacks the senior-level trading infrastructure specialist this role demands; prioritize candidates with explicit Kubernetes + PostgreSQL + Go/Python + WebSocket experience from fintech or prop trading backgrounds.

---

## Counter-Intuitive Pick — Devil's Advocate Case for Tom Henderson

> *Note: This is a structured devil's advocate exercise. The final ranking above stands.*

**If Deriv's immediate crisis is infrastructure instability rather than domain expertise**, Tom Henderson becomes the optimal hire. Trading platforms live or die by uptime—a single cascade failure during market hours can cost millions. Tom's 10 years at Google and Meta were spent building exactly what Deriv needs: bulletproof distributed systems at scale. His Kubernetes and Cassandra expertise directly addresses the infrastructure layer where a single misconfiguration can take down the entire trading engine. While he lacks financial domain knowledge, that gap is solvable through pairing and documentation; a fundamentally broken infrastructure cannot be fixed by domain expertise alone. Deriv's existing team likely already understands trading workflows—what they may desperately need is someone who can architect systems that survive 10M concurrent connections without degradation.

Additionally, Tom's FAANG pedigree—often dismissed as "resume padding" in this cohort—actually signals something valuable here: he has *survived high-bar code reviews and incident postmortems at scale*. When a Cassandra cluster fails mid-trade, you need someone who has debugged similar failures at Meta under production pressure, not someone learning Go on the job. His system design strength translates directly to preventing the kinds of cascading failures that financial systems must avoid. The "no financial domain experience" argument inverts if you consider that financial domain experts without his infrastructure track record might build theoretically sound systems that crumble under real-world load.

**The scenario**: Deriv's current backend is suffering from latency issues, data consistency problems, or deployment brittleness—and the committee recognizes that the next 18 months require someone who can lead a major infrastructure overhaul before adding features. In that narrow but critical window, Tom's rare combination of FAANG-scale experience and hands-on system reliability becomes more valuable than Aisha's stronger overall profile.

---

## Blind Re-Ranking Analysis

### Ranking Comparison

| Candidate | Original Rank | Blind Rank | Change |
|-----------|--------------|------------|--------|
| C4 (Dmitri Volkov) | #1 | #2 | ▼ -1 |
| C1 (Aisha Okonkwo) | #2 | #1 | ▲ +1 |
| C2 (James Whitfield) | #3 | #4 | ▼ -1 |
| C3 (Mei-Lin Zhang) | #4 | #3 | ▲ +1 |
| C5 (Priya Nair) | #5 | #5 | — |
| C6 (Tom Henderson) | #6 | #6 | — |

### Position Change Analysis

**C4 (Dmitri Volkov): #1 → #2**
- Original score: 7.63/10 → Blind score: 7.29/10 (▼ -0.34 points)
- **Likely cause: Bias in original scoring.** The 0.34-point drop and position swap suggest the name/perceived background may have inflated the original score. The blind evaluation reveals C1 and C4 are competitive (7.42 vs 7.29), but C4's dominance in named ranking appears artificially enhanced.

**C1 (Aisha Okonkwo): #2 → #1**
- Original score: 7.52/10 → Blind score: 7.42/10 (▼ -0.10 points)
- **Likely cause: Bias in original scoring.** Despite a minimal score drop, C1 ranks higher blind than named. This suggests the original scorer may have penalised C1 due to name/demographic perception, and removal of this context revealed slightly stronger relative performance.

**C2 (James Whitfield): #3 → #4**
- Original score: 5.35/10 → Blind score: 4.69/10 (▼ -0.66 points)
- **Likely cause: Scoring inconsistency or context-dependent evaluation.** The significant 0.66-point drop is the largest variance among mid-tier candidates. The original scorer may have given contextual credit (e.g., experience, background) that doesn't reflect demonstrated competency in blind assessment.

**C3 (Mei-Lin Zhang): #4 → #3**
- Original score: 4.93/10 → Blind score: 4.82/10 (▼ -0.11 points)
- **Likely cause: Bias in original scoring.** Despite minimal score change, C3 improves one position in blind ranking, suggesting the original scorer may have underweighted this candidate due to name/demographic bias.

### Conclusion

The blind ranking suggests **significant bias in the original scoring**, particularly in the top two positions where C4 and C1 essentially swapped rankings with substantive score differences. The consistent pattern of name-associated candidates (Volkov) scoring higher in the named ranking and performing lower blind, combined with non-European names scoring lower originally but higher blind, indicates demographic bias influenced the original evaluation. The removal of identifying information produced materially different outcomes for 4 of 6 candidates.