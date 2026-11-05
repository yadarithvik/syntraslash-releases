# Syntra Slashes: Architecture Specification & AI Implementation Blueprint

> **Document Type:** AI-Readable System Specification & Architecture Reference  
> **Target Audience:** Autonomous AI Agents, LLM Systems Engineers, Context Memory Architects  
> **Model Target:** Syntra-Max-Aperion (Custom 14B Parameter Architecture)  
> **Hardware Envelope:** Local Workstation (AMD Ryzen AI 7 350, NVIDIA RTX Discrete GPU, 24 GB System RAM)

---

## 1. Executive System Overview

**Syntra Slashes** is an autonomous desktop execution and cognitive agent designed to eliminate the two fundamental hardware bottlenecks of local AI execution:
1. **The Attention KV-Cache Memory Wall:** Quadratic compute ($O(N^2)$) and linear memory bloat when maintaining long raw chat context.
2. **Local Storage Proliferation:** Rapid disk exhaustion on standard SSDs (256 GB – 512 GB) caused by uncompressed multi-million-token raw conversation trees.

The architecture solves these problems through two synchronized subsystems:
* **Runtime:** *OS-Style Virtual Context Paging & Decoupled Dual-Stream Processing*
* **Post-Task:** *Retrospective Memory Consolidation & Log-Structured Markdown Compaction*

```
                              ┌────────────────────────────────────────┐
                              │          Incoming User Task            │
                              └──────────────────┬─────────────────────┘
                                                 │
                  ┌──────────────────────────────┴──────────────────────────────┐
                  ▼                                                             ▼
     [ Stream A: Active Buffer ]                                  [ Stream B: Parallel Extractor ]
  ┌──────────────────────────────┐                              ┌────────────────────────────────┐
  │  Current prompt & hot turns  │                              │  Reads Layered String Store    │
  │  (Bounded: < 2,048 tokens)   │                              │  Scans 1-line Digest Headers   │
  └──────────────┬───────────────┘                              │  Extracts strictly needed facts│
                 │                                              └───────────────┬────────────────┘
                 └──────────────────────────────┬───────────────────────────────┘
                                                ▼
                                 ┌─────────────────────────────┐
                                 │   Isolated Output Buffer    │
                                 │  (Zero-Overlap Synthesis)   │
                                 └──────────────┬──────────────┘
                                                ▼
                                 ┌─────────────────────────────┐
                                 │  User Observes Execution    │
                                 └──────────────┬──────────────┘
                                                │ (When hot buffer exceeds threshold)
                                                ▼
                                 ┌─────────────────────────────┐
                                 │  Layered Context Archiver   │
                                 │  (Serialized string store)  │
                                 └──────────────┬──────────────┘
                                                │
                                                ▼ (Session conclusion)
                                 ┌─────────────────────────────┐
                                 │ Retrospective Consolidation │
                                 │   (Compacted .md Dossier)   │
                                 └─────────────────────────────┘
```

---

## 2. Core Problem Analysis & Mathematical Formulation

### 2.1 The RAM / VRAM Wall (KV-Cache Explosion)
In standard autoregressive transformer inference, every token in the active context must calculate attention against all prior tokens. The memory required for Key and Value (KV) projections is:

$$\text{Memory}_{\text{KV}} = 2 \times n_{\text{layers}} \times n_{\text{heads}} \times d_{\text{head}} \times n_{\text{ctx}} \times \text{bytes\_per\_element}$$

For a 14-billion parameter model (e.g., 40 layers, 40 heads, head dimension 128) running 32,000 uncompressed tokens in 16-bit precision:
* $\text{KV Cache Size} \approx 2 \times 40 \times 40 \times 128 \times 32000 \times 2 \text{ bytes} \approx 26.2\text{ GB}$

**Outcome on Local Hardware:** Immediate Out-Of-Memory (OOM) crash on a 4 GB VRAM GPU / 24 GB RAM system, accompanied by exponential compute slowdown.

### 2.2 The Syntra Slashes Solution: Bounded Attention Envelope
Syntra Slashes separates *working attention memory* from *historical memory storage*:
* **Active Working Attention ($M$):** Bounded strictly to $M \le 2,048$ tokens.
* **Attention Complexity:** Reduced from unbounded $O(N^2)$ to fixed, deterministic $O(M^2)$.
* **Active KV Footprint:** Capped at $\approx 1.5\text{ GB}$, guaranteeing constant inference speed and zero OOM risks regardless of task duration.

| Metric | Traditional Monolithic Chatbot | Syntra Slashes Virtual Architecture |
| :--- | :--- | :--- |
| **Active KV-Cache Memory** | Grows linearly: $15\text{ GB} - 30+\text{ GB}$ | **Fixed & constant: $\approx 1.5\text{ GB}$** |
| **Max Conversation Lifespan** | Hard-capped at 8k–16k tokens | **Virtually infinite (disk-backed)** |
| **Attention Compute Complexity** | $O(N^2)$ (Drastically slows down over time) | **$O(M^2)$ (Consistently fast indefinitely)** |
| **Token Ingestion Cost** | Multiplies with history depth | **Constant per step** |

---

## 3. Subsystem Architecture 1: Virtual Context Paging (Runtime)

### 3.1 Part 1: Rolling Serialization into Layered Strings (The "Cold Store")
When conversation turns in active memory exceed the hot threshold ($T_{\text{hot}} = 10\text{ turns}$ or $\approx 2,048\text{ tokens}$):
1. The oldest turns are evicted from the active transformer attention context.
2. The evicted turns are serialized into plain-text **Cold String Layers** and persisted to fast local storage (SQLite WAL or atomic JSON buffer).
3. Active VRAM/RAM consumption for those historical turns immediately drops to **zero**.

### 3.2 Part 2: The Decoupled Parallel Extractor
When a prompt references earlier context, the engine does **not** dump old layers back into active context. Instead, a decoupled extraction pass queries the cold store:
* It reads **only** the layer store.
* It filters and extracts **only** the exact parameters, credentials, paths, or code entities required.
* It isolates the extracted facts as structured metadata.

### 3.3 Part 3: Layer Indexing & Fast Digest Headers (Latency Elimination)
* **The Engineering Constraint:** Sequentially re-reading 100,000 words across 100 raw layers using a 14B model would require 15–30 seconds of compute before generating a response token.
* **The Optimization:** When each layer is archived, a lightweight **Digest Header** (a 1-line semantic index tag) is pre-computed:
  ```json
  {
    "layer_id": "layer_004",
    "digest": "User configured SQLite WAL database path at %LOCALAPPDATA%/SyntraSlashes/memory/syntra.db",
    "timestamp": 1729801200
  }
  ```
* **Routing Speed:**
  1. The parallel extractor scans **only the 1-line digest headers** ($\approx 100\text{ lines} \ll 1\text{ KB}$, processed in $< 50\text{ ms}$).
  2. Pinpoints the exact targeted layer (e.g., Layer 4).
  3. Sells only Layer 4 for fact extraction ($< 1.5\text{ seconds}$).
  4. Returns isolated facts to Stream C.

### 3.4 Part 4: Isolated Output Buffer (Zero-Overlap Synthesis)
The generation prompt delivered to the model is assembled as an isolated synthesis frame without historical chatter:
```
[RECALLED SYSTEM FACTS]:
- Database: SQLite WAL at %LOCALAPPDATA%/SyntraSlashes/memory/syntra.db
- Workspace: C:\Users\rithvik yada\Desktop\PY-HACKATHON

[CURRENT ACTIVE CONTEXT]:
User: Create the billing database table according to our previous schema.
Syntra:
```

---

## 4. Subsystem Architecture 2: Retrospective Memory Consolidation (Post-Task)

### 4.1 The Storage Problem on Local SSDs
An uncompressed session running thousands of tool actions, stdout/stderr streams, file contents, and reasoning steps can generate hundreds of megabytes of raw text. Storing raw session transcripts across months of continuous development exhausts laptop storage.

### 4.2 Retrospective Consolidation Mechanism
Upon session completion, the system transitions from **active recording** to **retrospective consolidation** (analogous to REM sleep consolidation in mammalian biology):

```
[ Active Session Stream ]
           │
           ▼
[ Raw Scratch Layers (100 MB - 1.2 GB) ] ──▶ Task marked Complete / User closes session
                                                            │
                                                            ▼
                                             ┌─────────────────────────────┐
                                             │  Compaction Filter Engine   │
                                             └──────────────┬──────────────┘
                                                            │
                     ┌──────────────────────────────────────┴──────────────────────────────────────┐
                     ▼                                                                             ▼
           [ PURGE (Discarded Noise) ]                                                   [ DISTILL (Permanent Knowledge) ]
           • Repetitive intermediate tool polling                                        • Architectural & schema decisions
           • Transient error traces that were repaired                                   • Verified code snippets & diffs
           • Terminal formatting & control characters                                    • Canonical absolute filesystem paths
           • Ephemeral conversational back-and-forth                                     • Core outcomes & active follow-ups
                     │                                                                             │
                     ▼                                                                             ▼
           [ Permanently Deleted ]                                                       [ Structured Markdown Dossier ]
           (Immediate SSD space reclamation)                                             (e.g., memory/compacted_sessions/s12.md)
                                                                                                   │
                                                                                                   ▼
                                                                                         [ Permanent Archive ]
                                                                                         (Average size: 40 KB - 200 KB)
```

### 4.3 Standard Markdown Dossier Specification

Every compacted session produces a durable, machine-readable `.md` file adhering strictly to this schema:

```markdown
# Session Dossier: [Project Name / Primary Objective]
**Session ID:** [uuid] | **Date:** YYYY-MM-DD | **Original Turns:** [count] | **Compacted Size:** [KB]

## 1. Executive Summary
- Concise 3-line summary of what was requested, investigated, and verified.

## 2. Verified Architectural Decisions & Schemas
- Explicit records of schemas, API contracts, protocols, and ports established.

## 3. Artifacts, Code Changes & File References
- Absolute paths to created or modified files.
- Summary of line additions/deletions and verified tool outputs.

## 4. Execution State & Verified Outcomes
- Exact command lines executed and verified exit codes (`exit 0`).
- Verification outputs (e.g., numeric totals, UI state confirmations).

## 5. Extracted Persistent Facts (High-Priority Retrieval Index)
- `[FACT_KEY]`: Value for cross-session semantic search.
```

---

## 5. Reference Implementation: Python Core Engine

The following standalone engine implements the Virtual Context Pager, Digest Router, and Retrospective Compactor:

```python
"""
Syntra Virtual Context & Memory Consolidation Engine
Implements OS-style virtual context paging and retrospective compaction.
"""
import os
import json
import time
from pathlib import Path
import urllib.request

class SyntraVirtualContextEngine:
    def __init__(self, model_url="http://127.0.0.1:11434", model_name="syntra-max-aperion", max_hot_tokens=2048):
        self.model_url = model_url
        self.model_name = model_name
        self.max_hot_tokens = max_hot_tokens
        
        self.hot_buffer = []      # Stream A: Active short-term dialogue turns
        self.cold_layers = []     # Stream B: Persistent layered string store with digest headers
        self.memory_dir = Path("memory/compacted_sessions")
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _call_model(self, prompt, system_instruction=None):
        """Invoke local 14B model without external service dependencies."""
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": self.max_hot_tokens, "temperature": 0.2}
        }
        
        req = urllib.request.Request(
            f"{self.model_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
            return data.get("message", {}).get("content", "").strip()

    def append_turn(self, role, content):
        """Record turn into hot buffer and trigger paging when budget threshold is met."""
        self.hot_buffer.append({"role": role, "content": content, "timestamp": time.time()})
        self._page_out_if_needed()

    def _page_out_if_needed(self):
        """OS-Style Context Paging: Archive older turns to cold string layers."""
        if len(self.hot_buffer) > 10:  # Hot threshold met
            # Evict turns 0 through -2 (keep the last 2 turns in hot attention)
            evicted = self.hot_buffer[:-2]
            self.hot_buffer = self.hot_buffer[-2:]
            
            layer_text = "\n".join([f"{t['role'].upper()}: {t['content']}" for t in evicted])
            
            # Compute 1-line digest header for fast routing
            digest_prompt = f"Summarize the technical facts and decisions in this conversation snippet in ONE short sentence:\n{layer_text}"
            digest_header = self._call_model(digest_prompt)
            
            layer_entry = {
                "layer_id": f"layer_{len(self.cold_layers) + 1:03d}",
                "digest": digest_header,
                "data": layer_text,
                "timestamp": time.time()
            }
            self.cold_layers.append(layer_entry)

    def extract_relevant_facts(self, query):
        """Decoupled Parallel Extractor: Route via digest headers and pull isolated facts."""
        if not self.cold_layers:
            return ""

        # Step 1: Scan only digest headers (low compute overhead)
        headers_index = "\n".join([f"[{l['layer_id']}] {l['digest']}" for l in self.cold_layers])
        routing_prompt = f"""Given the user task: "{query}"
Identify which layer IDs contain required facts or schemas. Output only the IDs separated by commas, or NONE:
{headers_index}"""
        
        selected_ids = self._call_model(routing_prompt)
        if "NONE" in selected_ids.upper():
            return ""

        # Step 2: Extract strictly relevant facts from targeted layers
        extracted_facts = []
        for layer in self.cold_layers:
            if layer["layer_id"] in selected_ids:
                extract_prompt = f"""Extract ONLY specific facts, paths, code definitions, or constraints relevant to: "{query}"
Source Text:
{layer['data']}"""
                facts = self._call_model(extract_prompt)
                if facts:
                    extracted_facts.append(facts)

        return "\n".join(extracted_facts)

    def build_isolated_prompt(self, user_prompt):
        """Assemble Stream C: Isolated Output Frame."""
        recalled_facts = self.extract_relevant_facts(user_prompt)
        
        clean_context = []
        if recalled_facts:
            clean_context.append(f"[RECALLED HISTORICAL FACTS]:\n{recalled_facts}\n")
            
        clean_context.append("[ACTIVE DIALOGUE]:")
        for turn in self.hot_buffer:
            clean_context.append(f"{turn['role'].upper()}: {turn['content']}")
        clean_context.append(f"USER: {user_prompt}\nASSISTANT:")
        
        return "\n".join(clean_context)

    def consolidate_and_close_session(self, session_id):
        """Retrospective Consolidation: Purge raw chatter, generate structured .md dossier."""
        all_text = []
        for l in self.cold_layers:
            all_text.append(l["data"])
        for h in self.hot_buffer:
            all_text.append(f"{h['role'].upper()}: {h['content']}")
        full_transcript = "\n".join(all_text)

        compaction_prompt = f"""You are the Retrospective Memory Consolidation Engine.
Analyze the complete raw session text below. Discard conversational filler, greetings, and resolved errors.
Produce a clean, highly structured Markdown dossier with these exact sections:
1. Executive Summary
2. Verified Architectural Decisions & Schemas
3. Artifacts & File Modifications (with full paths)
4. Execution State & Verified Results
5. Extracted Persistent Facts

Raw Session Data:
{full_transcript}"""

        dossier_content = self._call_model(compaction_prompt)
        
        # Persist compacted Markdown file
        dossier_path = self.memory_dir / f"{session_id}.md"
        with open(dossier_path, "w", encoding="utf-8") as f:
            f.write(f"# Compacted Session Dossier: {session_id}\n")
            f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')} | **Layers:** {len(self.cold_layers)}\n\n")
            f.write(dossier_content)

        # Purge in-memory scratch buffers immediately
        self.cold_layers.clear()
        self.hot_buffer.clear()
        
        return dossier_path
```

---

## 6. Integration Rules for Downstream AI Agents

When interacting with or extending the Syntra Slashes codebase, external agents must follow these operational guidelines:

1. **Do Not Re-Inject Full History:** Never dump serialized raw logs or archived turns into `messages[]`. Always use the decoupled extractor to pull isolated facts.
2. **Preserve Native Tool Invocation:** Emit actions using structured native tool definitions (`find_folder`, `run_python`, `write_file`, `mouse_move`, `mouse_click`, `complete_task`). Never write pseudo-JSON blocks into prose.
3. **Uphold Coherent Desktop Leases:** Any multi-step UI automation sequence (`switch_window` $\to$ `inspect_ui` $\to$ `mouse_move` $\to$ `type_text`) must execute under an exclusive desktop lease to prevent focus interruption.
4. **Enforce Monotonic Event Correlation:** Every tool invocation must propagate a unique `call_id`, linking `action_start` and `observation` events without path or argument loss.
5. **Durable Compaction Trigger:** When a multi-step task completes and verification succeeds via `complete_task`, invoke retrospective memory consolidation to persist the `.md` dossier and clear ephemeral execution buffers.
