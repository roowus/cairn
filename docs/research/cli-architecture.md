Technical Architecture and Implementation Specification for an Agentic AI OSINT Command Line Infrastructure
Modular System Architecture and Layered Infrastructure Design
Developing an enterprise-grade, Artificial Intelligence (AI) powered Open Source Intelligence (OSINT) Command Line Interface (CLI) tool requires a strict separation of concerns to ensure maintainability, operational safety, and multi-interface deployment1. A foundational principle of this design is unidirectional dependency flow: lower operational layers must remain entirely decoupled from and ignorant of the higher orchestration and presentation layers that consume them2.
The system architecture comprises three primary tiers:
The Execution Core: Stateless, asynchronous operational primitives that interface directly with external REST APIs, network sockets, system subprocesses, or scraped web endpoints1. These capabilities accept strongly typed parameter models, return validated structural data, and operate without dependency on the caller's identity or execution context1.
The Agent Orchestration Engine: The cognitive processing layer powered by Large Language Models (LLMs) and structured agent frameworks3. This engine decomposes high-level analyst intent into multi-step investigation loops, manages state across execution turns, evaluates context window limits, and dynamically invokes tools based on intermediate findings3.
The Multi-Interface Delivery Layer: The front-end adapters that expose the core capability surface to end users or upstream client software2. This layer includes an interactive Terminal User Interface (TUI)/Read-Eval-Print Loop (REPL), a native Model Context Protocol (MCP) server, an HTTP REST/OpenAPI microservice, and a direct headless CLI parser1.
To maintain long-term architectural extensibility without requiring continuous codebase refactoring, the core execution engine relies on a strict plugin contract1. Developers add new OSINT capabilities by creating isolated Python modules within a dedicated directory, inheriting from a base Plugin abstract class1.



Python
from abc import ABC, abstractmethod from typing import Any, Dict, Optional from pydantic import BaseModel  class PluginContext(BaseModel):     options: Dict[str, Any]     proxy: Optional[str] = None     timeout: int = 30  class BasePlugin(ABC):     name: str     description: str     output_schema: Dict[str, Any]      @abstractmethod     async def run(self, target: str, ctx: PluginContext) -> Dict[str, Any]:         """Execute intelligence collection logic deterministically."""         pass 
Upon package initialization, a dynamic plugin registry inspects the module space, discovers subclasses of BasePlugin, and automatically registers them across all available frontends—including the CLI parser, the MCP tool schema list, and the REST API routing table1.

Architecture Pattern
Structural Complexity
Operational Safety
Interoperability
Primary OSINT Use Case
Monolithic Scripting
Low
Low (high risk of unhandled runtime crashes)
Poor (bound exclusively to terminal stdout)
Quick ad-hoc scripts and single-purpose utilities.
Layered Engine + Plugin Registry
Medium
High (isolated error handling per plugin contract)1
Excellent (native CLI, MCP, and REST interfaces)1
Modular OSINT frameworks and extensible analyst platforms1.
Microservices Architecture
High
Very High (isolated container runtimes per tool)7
High (gRPC/HTTP message passing across services)
Scalable enterprise threat intelligence platforms7.
Intelligence Tool Integration, Sandboxing, and Scraping Infrastructure
An AI-driven OSINT CLI must synthesize intelligence across multiple technical domains, including digital identity, Domain Name Systems (DNS), infrastructure footprinting, and unstructured web content6. Rather than attempting to re-implement every intelligence technique natively, the system serves as an orchestrator around battle-tested specialized binaries, dedicated REST APIs, and modern scrapers2.
The core execution engine incorporates tools across four main investigation vectors:
Identity and Account Enumeration: Integrating utilities like holehe to check email registrations against password-recovery endpoints across hundreds of online platforms, alongside sherlock or maigret for cross-platform username profiling6.
Network and Infrastructure Footprinting: Querying passive search engine APIs such as Shodan, VirusTotal, Censys, and IP2Location to map open ports, service banners, Autonomous System Numbers (ASNs), and proxy or Tor node statuses without generating active network traffic against the target4.
Domain and Subdomain Reconnaissance: Aggregating passive DNS records, Certificate Transparency (CT) logs, and running utilities like sublist3r or subfinder to map host configurations6.
Unstructured Web Scraping: Utilizing agent-friendly crawling engines such as Crawl4AI to execute adaptive, asynchronous scraping that cleans raw HTML into LLM-optimized Markdown while evaluating site confidence scores11.
A critical architectural constraint in AI-driven security tools is preventing model hallucinations from corrupting threat intelligence6. Allowing an LLM to speculate on open ports, WHOIS records, or credential leaks destroys the utility of the system6. To achieve execution determinism, tool calls issued by the AI orchestrator must represent hard-stop invocations6. The AI model selects the tool and constructs its arguments, but local application code executes the real binary or API call, returning verified raw data to the model context6.



Python
async def execute_tool_safely(plugin: BasePlugin, target: str, ctx: PluginContext) -> Dict[str, Any]:     try:         result = await plugin.run(target, ctx)         return {"success": True, "data": result, "error": None}     except Exception as e:         # Capture exceptions as structured error payloads to preserve agent loop stability         return {"success": False, "data": None, "error": str(e)} 
For utilities relying on system binaries with complex native dependencies (such as phoneinfoga, subfinder, or whatweb), relying on the host operating system's $PATH introduces environment fragility. The system addresses this by implementing a containerized sidecar model using Docker. Non-Python utilities are packaged into a minimal, hardened container image (e.g., osint-tools:latest), and the Python core invokes them via the Docker Engine API or standard I/O streams, ensuring consistent execution across deployment environments.

Execution Strategy
Setup Overhead
Isolation & Security
Capabilities
Maintenance Cost
Native Host Binary
Low (requires manual PATH installation)6
Poor (direct host filesystem access)
Full operating system access
High (frequent host dependency conflicts)
Containerized (Docker) Sandbox
Medium (requires local Docker daemon)7
High (isolated container file system)7
Full binary execution within container
Low (reproducible container image builds)7
Cloud API Wrapper
Low (requires API key configuration)6
N/A (external execution)
Defined by vendor API endpoints6
Low (vendor managed)
AI Orchestration Frameworks, Type Safety, and Context Engineering
The orchestration engine governs how the agent interprets user goals, plans multi-step investigations, delegates sub-tasks, and synthesizes final reports3. Selecting the appropriate framework dictates the structural reliability and type safety of the toolchain12.
PydanticAI provides a robust foundation for building production-grade AI agents3. Unlike loose agent loops, PydanticAI integrates Pydantic's data validation capabilities directly into the LLM observation-thought-action loop3. This guarantees that parameters passed by the model into OSINT tools strictly conform to expected JSON schemas3. If a model generates malformed input (such as an invalid IP address string), PydanticAI catches the validation error and triggers an internal retry prompt requesting correction before execution occurs3.



Python
from pydantic import BaseModel, Field from pydantic_ai import Agent, RunContext  class IPInvestigationInput(BaseModel):     ip_address: str = Field(description="Target IPv4 or IPv6 address to investigate.")  class InvestigationDeps(BaseModel):     api_key_shodan: str     proxy_url: Optional[str] = None  osint_agent = Agent[InvestigationDeps, str](     'anthropic:claude-3-5-sonnet-20241022',     deps_type=InvestigationDeps,     system_prompt="You are an autonomous security analyst conducting OSINT investigations." )  @osint_agent.tool async def perform_shodan_lookup(ctx: RunContext[InvestigationDeps], params: IPInvestigationInput) -> str:     shodan_key = ctx.deps.api_key_shodan     # Execute actual Shodan lookup logic here     return f"Shodan result for {params.ip_address}: Open ports [80, 443]" 
For complex investigations, a single linear agent loop often degrades in performance due to context saturation5. The orchestrator should implement a multi-agent decomposition model, such as the pydantic-deep architecture5. In this pattern, a primary coordinator agent breaks down a high-level goal into independent tasks5. The coordinator spawns specialized sub-agents (e.g., Infrastructure Agent, Identity Agent, Leaks Agent) that run in isolated context environments5.
Managing context capacity during long-running investigations requires specific context engineering techniques:
Progressive Disclosure of Skills: Rather than inserting hundreds of lines of tool instructions into the system prompt at initialization, the agent loads light frontmatter (tool name and short description)5. Full parameter schemas are fetched dynamically only when the agent selects a specific tool path5.
Observational Summarization: When a tool returns large raw payloads (such as a 10,000-line WHOIS response or a massive JSON dump from Shodan), an intermediate summarizer compresses the output into relevant key facts before appending it to the main conversation context5.
Sub-Agent Context Isolation: Sub-agents maintain ephemeral context histories, returning only their final structured findings to the primary orchestrator5. This prevents intermediate tool outputs from polluting the parent conversation window5.
Interface Delivery Mechanisms: Terminal UI and Model Context Protocol
Security analysts require flexible deployment modes: an interactive terminal interface for manual investigations and standard protocol integrations for driving the toolchain from external agent environments2.
Terminal UI (TUI) and REPL Engineering
The CLI interface should be constructed using Rich and Textual, enabling an interactive terminal UI complete with asynchronous event handling, streaming response panels, and visual tool execution cards4. The application operates primarily as an interactive REPL with live tool-chaining visualization4.
When an analyst submits a query in the REPL (e.g., investigate target@example.com), the TUI streams the agent's reasoning and renders dedicated interface cards as tools execute in parallel via asyncio.gather()4. Session histories are serialized locally to ~/.openosint/history/ in JSON format, allowing analysts to search, reload, or export previous investigation graphs4.
Model Context Protocol (MCP) Integration
To allow external AI clients (such as Claude Code, Cursor, or Windsurf) to natively drive the toolchain, the system exposes a Model Context Protocol (MCP) server layer2. MCP establishes a standardized client-server protocol over JSON-RPC 2.0, utilizing two primary transport mechanisms: stdio for local subprocess coupling and HTTP with Server-Sent Events (SSE) for remote network deployments16.
The MCP server exposes three standard primitives16:
Tools: Executable functions exposed to the host LLM, representing core OSINT capabilities (search_email, search_shodan, search_domain) with auto-generated JSON schemas2.
Resources: Read-only contextual data, such as cached investigation session logs, system configurations, or active threat feed mappings16.
Prompts: Standardized investigation templates or playbooks (e.g., perform_email_recon, analyze_attack_surface) that guide external LLMs through systematic reconnaissance workflows16.
A key technical distinction exists between operating in CLI mode versus MCP Server mode regarding output formatting and local side effects20:



Python
async def format_tool_response(data: Dict[str, Any], is_mcp_mode: bool, output_path: str) -> Dict[str, Any]:     if is_mcp_mode:         # MCP Mode: Return raw structured JSON directly to the host client context         return {             "content": [{"type": "text", "text": json.dumps(data)}],             "isError": False         }     else:         # CLI Mode: Render formatted output to terminal and save reports to disk         save_report_to_disk(data, output_path)         return {"data": data, "saved_to": output_path} 

Operational Dimension
Interactive Terminal UI (TUI/REPL)
Native MCP Server
Headless Direct CLI
Primary Consumer
Human Security Analyst6
External AI Host (Claude Code, Cursor)2
Automated CI/CD Pipelines and Scripts6
Transport Protocol
Standard IO / Terminal Rendering4
JSON-RPC over stdio or HTTP/SSE
[cite: 16, 17, 18]
System Shell Execution6
State Persistence
Local session history (~/.openosint/)4
Session-managed via JSON-RPC context19
Ephemeral per-command execution6
Output Delivery
Visual Markdown, tables, streaming cards4
In-memory structured JSON payloads20
Raw stdout, JSON strings, or files20
Threat Intelligence Data Modeling via STIX 2.1 Standard
To ensure that findings collected by the AI OSINT tool can be ingested into enterprise Threat Intelligence Platforms (TIPs) like OpenCTI or MISP, the system translates unstructured results into Structured Threat Information eXpression (STIX 2.1) objects21.
Using the stix2 Python library, raw key-value pairs returned by OSINT plugins are mapped into STIX Cyber-observable Objects (SCOs), STIX Domain Objects (SDOs), and STIX Relationship Objects (SROs)21.



Python
from stix2 import IPv4Address, DomainName, Relationship, Bundle  def build_stix_graph(domain_str: str, ip_str: str) -> Bundle:     # 1. Instantiate Cyber-observable Objects (SCOs)     # SCOs use deterministic UUIDv5 generation based on ID Contributing Properties     ip_sco = IPv4Address(value=ip_str)     domain_sco = DomainName(value=domain_str, resolves_to_refs=[ip_sco.id])      # 2. Instantiate STIX Relationship Objects (SROs)     rel_sro = Relationship(         relationship_type="resolves-to",         source_ref=domain_sco.id,         target_ref=ip_sco.id     )      # 3. Bundle objects into a valid STIX 2.1 JSON container     return Bundle(objects=[ip_sco, domain_sco, rel_sro]) 
Understanding ID generation mechanics is essential when building STIX pipelines to prevent object duplication across investigation runs23:
STIX Domain Objects (SDOs) and Relationships (SROs): Utilize random UUIDv4 generation by default23. Every instance of an Indicator or Threat Actor SDO is treated as a distinct observation unless explicitly updated via versioning properties23.
STIX Cyber-observable Objects (SCOs): Utilize deterministic UUIDv5 generation based on an OASIS-defined namespace (00abedb4-aa42-466c-9c01-fed23315a9b7) and ID Contributing Properties (e.g., the value string of an IPv4 or Domain object)23. This ensures that querying an IP address across different agent runs yields the exact same STIX ID, allowing automatic object deduplication and graph stitching within downstream databases23.

OSINT Intelligence Finding
STIX 2.1 Family
Target STIX Object Type
ID Generation Scheme
Key Standard Properties
Target IP Address
SCO
ipv4-addr / ipv6-addr
UUIDv5 (Deterministic)
value, belongs_to_refs
[cite: 21, 24]
Discovered Subdomain
SCO
domain-name
UUIDv5 (Deterministic)
value, resolves_to_refs
[cite: 21, 25]
User Profile / Handle
SCO
user-account
UUIDv5 (Deterministic)
user_id, account_login, account_type
[cite: 24]
Breach Exposure
SDO
indicator
UUIDv4 (Random)
pattern, pattern_type, valid_from
[cite: 26]
Linkage (Domain to IP)
SRO
relationship
UUIDv4 (Random)
relationship_type, source_ref, target_ref
[cite: 21]
Hardening, Security Controls, and Threat Mitigation
Deploying an autonomous agent that parses untrusted external web data and executes system binaries introduces security attack vectors16. System design must account for both local execution risks and remote protocol vulnerabilities16.
Security architecture enforces risk mitigation across four primary operational boundaries:
Indirect Prompt Injection Defense
When the tool fetches external content—such as scraping target websites via Crawl4AI, retrieving WHOIS records, or fetching Pastebin dumps—attackers can plant malicious prompt injection payloads inside HTML tags or text fields6. If raw scraped content is passed directly into the model context, these hidden instructions can hijack the agent loop, forcing it to exfiltrate API keys, execute destructive local tools, or bypass safety rules18.
Mitigation requires treating all external tool outputs as untrusted data strings. The system applies HTML entity encoding, strips instruction-override tokens (e.g., <|im_start|>), and truncates payload lengths prior to LLM context ingestion18.



Python
import re from html import escape  def sanitize_untrusted_text(raw_text: str) -> str:     sanitized = escape(raw_text)     sanitized = re.sub(r'(?i)<\|im_start\|>|<\|im_end\|>|system:', '[REDACTED_TOKEN]', sanitized)     return sanitized[:8000] 
Command Injection Prevention
Tools that execute system binaries must never concatenate raw LLM strings directly into system command lines16. Invoking commands via shell string formatting allows arbitrary command execution if parameter strings contain shell meta-characters18. All subprocess execution must pass through asyncio.create_subprocess_exec() using array-based argument passing, completely bypassing shell evaluation engines16.
Access Control and Authentication
When running as a network-accessible MCP server over HTTP/SSE, authorization must be strictly enforced. Unauthenticated MCP endpoints allow unauthorized clients to trigger internal tools or exfiltrate intelligence data.
The server implements the OAuth 2.1 authorization flow specified in the MCP standard18. Incoming HTTP requests must present valid Bearer tokens obtained via OAuth authorization endpoints18. Requests lacking valid tokens receive immediate HTTP 401 Unauthorized rejections18. Furthermore, Role-Based Access Control (RBAC) restricts sensitive tools to authorized roles16.
Comprehensive Audit Logging
Every execution step, tool invocation, input argument, and response payload size is recorded in an immutable audit log16. Audit entries capture the invoking model identity, tool name, execution parameters, timestamp, and result status, establishing full forensic traceability for security compliance16.
Strategic Implementation Roadmap
Building a production-ready AI OSINT CLI tool requires balancing agentic autonomy with execution safety3. By establishing a decoupled architecture, developers ensure that tool primitives remain stateless, deterministic, and modular1. Utilizing PydanticAI enforces strict type validation across the agent loop, eliminating malformed tool calls and structuring investigation outputs3.
Concurrently, implementing dual interface endpoints—an interactive TUI/REPL for human analysts and an MCP server for AI coding hosts—maximizes tool utility across operational workflows2. Normalizing raw findings into standard STIX 2.1 JSON bundles ensures integration into downstream threat intelligence pipelines, enabling automated graph construction and cross-investigation deduplication via deterministic UUIDv5 mapping21.
Development should proceed through four sequential implementation phases:
Phase 1: Execution Core & Base Plugins: Implement the stateless plugin abstract contract and core asynchronous OSINT tools (holehe, sherlock, Shodan API, WHOIS)1. Validate output serialization using Pydantic schemas3.
Phase 2: Agent Orchestration Engine: Build the PydanticAI agent runner, incorporating tool registration, system prompts, hard-stop tool execution rules, and sub-agent task delegation patterns3.
Phase 3: Delivery Interfaces: Construct the terminal interface using Textual and Rich for live tool execution streaming4. Wrap the execution engine with an MCP server supporting stdio and HTTP/SSE transports2.
Phase 4: STIX 2.1 Pipeline & Security Hardening: Integrate stix2 serialization to generate standard threat bundles22. Enforce input sanitization, OAuth 2.1 authorization, containerized sidecar execution, and audit logging controls across all operational layers7.
Works cited
AGENTS.md - soxoj/osint-cli-tool-skeleton - GitHub, https://github.com/soxoj/osint-cli-tool-skeleton/blob/main/AGENTS.md
I built an MCP-native OSINT framework that lets AI agents investigate from your terminal, https://dev.to/sonotommy/i-built-an-mcp-native-osint-framework-that-lets-ai-agents-investigate-from-your-terminal-4768
PydanticAI Agents: Build Reliable AI Decision Systems - ADaSci, https://adasci.org/blog/a-practioners-guide-to-pydanticai-agents
OpenOSINT - AI Agents on GitHub (1.2k ) | SkillsLLM, https://skillsllm.com/skill/openosint
We Built a Batteries-Included AI Agent Framework on PydanticAI. Here's the Architecture. | by Kacperwlodarczyk | Medium, https://medium.com/@kacperwlodarczyk/we-built-a-batteries-included-ai-agent-framework-on-pydanticai-heres-the-architecture-53f228d673b6
GitHub - OpenOSINT/OpenOSINT: AI-powered OSINT agent with interactive REPL, MCP server, and CLI. 16 tools. Works with Claude, GPT-4, or local models. For authorized security research only., https://github.com/OpenOSINT/OpenOSINT
GitHub - dazzyddos/OSINT_AI_Agent: A Simple Offensive AI OSINT Agent built using LangGraph, https://github.com/dazzyddos/OSINT_AI_Agent
Top Python Libraries of 2025 - Edge AI and Vision Alliance, https://www.edge-ai-vision.com/2026/01/top-python-libraries-of-2025/
osint-tools · GitHub Topics, https://github.com/topics/osint-tools
Model Context Protocol Servers - Augment Code, https://www.augmentcode.com/mcp
Quick Start - Crawl4AI Documentation (v0.9.x), https://docs.crawl4ai.com/core/quickstart/
Type-safe LLM agents with PydanticAI - Paul Simmering, https://simmering.dev/blog/pydantic-ai/
Choosing an agent framework: LangChain vs LangGraph vs CrewAI vs PydanticAI vs Mastra vs Vercel AI SDK - Speakeasy, https://www.speakeasy.com/blog/ai-agent-framework-comparison/
TUI Primitives | Indusagi Documentation, https://www.indusagi.com/python/ui/tui
CLI-Anything: Making ALL Software Agent-Native - GitHub, https://github.com/HKUDS/CLI-Anything
Model Context Protocol (MCP): A hands on guide - IntelligenceX Cybersecurity Blog, https://blog.intelligencex.org/model-context-protocol-mcp-a-hands-on-guide
Better Safe Than Sorry: Model Context Protocol - IOActive, https://www.ioactive.com/better-safe-than-sorry-model-context-protocol/
Exploring Model Context Protocol (MCP): A Pen Tester's Perspective | by Dom Whewell, https://medium.com/@domwhewell/exploring-model-context-protocol-mcp-bca7175347fd
A Survey on Model Context Protocol: Architecture, State-of-the-art, Challenges and Future Directions - TechRxiv, https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.174495492.22752319/v1
artl-mcp · PyPI, https://pypi.org/project/artl-mcp/
Understanding STIX 2.1 Objects: A Foundation for Structured Threat Intelligence - dogesec, https://www.dogesec.com/blog/beginners_guide_stix_objects/
From Unstructured Threat Intelligence to STIX 2.1 Bundles with Generative AI - Medium, https://medium.com/@antonio.formato/from-unstructured-threat-intelligence-to-stix-2-1-bundles-with-generative-ai-1065ce399e63
Your First STIX Objects: A Developer's Guide to STIX 2.1 with Python | dogesec, https://www.dogesec.com/blog/your_first_stix_object_a_developer_guide_to_stix_with_python/
cti-python-stix2/observables.py at ... - Open Cloud Git, https://eugit.opencloud.lu/MISP/cti-python-stix2/src/commit/3dda25e97615b76b5f325198b8a78aa6c8d84850/stix2/v21/observables.py
cti-python-stix2/stix2/v21/observables.py at master - GitHub, https://github.com/oasis-open/cti-python-stix2/blob/master/stix2/v21/observables.py
STIX 2.1 Indicator Patterning and Detection Development | Filigran Blog, https://filigran.io/blog/stix-2-1-indicator-patterning-and-detection-development/
