"""LLM root-cause agent: LangGraph tool-calling loop with citation verification.

    START → [ml_prior] → agent ⇄ tools
                           ↓ submit_report
                         verify ──(invalid citations, retries left)──→ agent
                           ↓
                          END

In hybrid mode the ml_prior node runs the trained ranker first and hands its
ranking to the agent, which must confirm or overturn it with telemetry.

The agent investigates one incident through telemetry tools, then calls
submit_report. The verify node rejects reports that cite evidence IDs the
agent never retrieved, or services that do not exist, and sends the errors
back so the agent can correct itself.
"""
import json
import random
import re
import time
from functools import lru_cache
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from openai import RateLimitError

from app.llm import default_deployment, estimate_cost, get_client
from app.ranker import ml_ranking
from app.telemetry import CaseTelemetry, baro_ranking

MAX_STEPS = 14
MAX_VERIFY_RETRIES = 2
MAX_RATE_LIMIT_WAITS = 30
# Azure's rate limiter reserves prompt + max output tokens per request, so an
# explicit cap (reports are ~700 tokens) keeps throughput near the real usage.
MAX_OUTPUT_TOKENS = 2000
EVIDENCE_ID = re.compile(r"^(MET|LOG|TRC):")
EMPTY_USAGE = {"prompt_tokens" : 0, "completion_tokens" : 0, "cached_tokens" : 0}
FAULT_TYPES = ["cpu", "mem", "disk", "socket", "delay", "loss", "code", "unknown"]

SYSTEM_PROMPT = """You are a senior site-reliability engineer performing root-cause analysis \
on a microservice system. A fault was injected into exactly one service at the alert time. \
Your job is to find that service.

Method:
1. Start with get_top_anomalies to see which metrics changed most after the alert.
2. Inspect the strongest candidates with get_service_metrics, get_service_logs and \
get_service_traces. Faults propagate: callers of a faulty service often show higher latency \
or errors too. Use get_dependencies to tell the origin of a fault from its downstream symptoms. \
A service whose own resource metrics (cpu, mem, disk, socket) or own logs changed is a stronger \
candidate than one that only shows latency inherited from a dependency.
3. Use search_runbooks to find remediation guidance for the fault you identify.
4. Call submit_report. Rank exactly 5 candidate services (or all, if fewer exist), most likely first. Cite only evidence \
IDs (MET:..., LOG:..., TRC:...) and runbook IDs (RB-...) that tools actually returned to you.

Fault types and their usual signatures:
- cpu: the service's own cpu metric jumps.
- mem: the service's own memory metric climbs.
- disk: the service's own diskio metric jumps.
- socket: the service's own socket count changes sharply.
- delay: injected network latency. The service's latency rises (and its callers' latency \
follows) while its cpu/mem barely change.
- loss: packet loss. Errors, timeouts and retries rise for calls to the service, often with \
lower throughput, without resource saturation.
- code: application defect. New exception types or error log templates, error responses, \
or the process shutting down/restarting.
- unknown: none of the above fits.
Be efficient: aim for 4-8 tool calls before submitting."""

TOOLS = [
    {"name" : "list_services",
     "description" : "List all services in the system and which telemetry (logs, traces) is available.",
     "parameters" : {"type" : "object", "properties" : {}, "required" : [], "additionalProperties" : False}},
    {"name" : "get_top_anomalies",
     "description" : "Metrics with the largest robust z-score change after the alert, across all services.",
     "parameters" : {"type" : "object", "properties" : {
         "limit" : {"type" : "integer", "description" : "How many metrics to return (max 30)."}},
         "required" : ["limit"], "additionalProperties" : False}},
    {"name" : "get_service_metrics",
     "description" : "All metric changes for one service (cpu, mem, diskio, socket, workload, error, latency).",
     "parameters" : {"type" : "object", "properties" : {"service" : {"type" : "string"}},
                     "required" : ["service"], "additionalProperties" : False}},
    {"name" : "get_service_logs",
     "description" : "Log volume change, error-rate change and never-seen-before log templates for one service.",
     "parameters" : {"type" : "object", "properties" : {"service" : {"type" : "string"}},
                     "required" : ["service"], "additionalProperties" : False}},
    {"name" : "get_service_traces",
     "description" : "Trace error rate and p90 latency for calls to one service, before vs. after the alert.",
     "parameters" : {"type" : "object", "properties" : {"service" : {"type" : "string"}},
                     "required" : ["service"], "additionalProperties" : False}},
    {"name" : "get_dependencies",
     "description" : "Services this service calls and services that call it.",
     "parameters" : {"type" : "object", "properties" : {"service" : {"type" : "string"}},
                     "required" : ["service"], "additionalProperties" : False}},
    {"name" : "search_runbooks",
     "description" : "Hybrid (BM25 + embedding) search over the runbook library.",
     "parameters" : {"type" : "object", "properties" : {"query" : {"type" : "string"}},
                     "required" : ["query"], "additionalProperties" : False}},
]

ML_PRIOR_PROMPT = (
    "Before you investigate, here is the ranking from a LightGBM model trained on past incidents "
    "(held-out top-1 accuracy about 86%). Treat it as a strong prior. Verify the top candidate "
    "against its own metrics, logs and traces; overturn it only if the telemetry clearly points "
    "elsewhere (for example, the candidate's anomalies are only latency inherited from a "
    "dependency that shows its own resource or error anomaly)."
)

ML_TOOL = {
    "name" : "get_ml_ranking",
    "description" : (
        "Ranking from a LightGBM model trained on past incidents. Strong prior, but it can be "
        "wrong; confirm it against the telemetry before accepting it."
    ),
    "parameters" : {"type" : "object", "properties" : {}, "required" : [], "additionalProperties" : False},
}

SUBMIT_TOOL = {
    "name" : "submit_report",
    "description" : "Submit the final root-cause report. Ends the investigation.",
    "strict" : True,
    "parameters" : {
        "type" : "object",
        "properties" : {
            "ranked_services" : {
                "type" : "array",
                "description" : "Exactly 5 candidate root-cause services, most likely first.",
                "items" : {
                    "type" : "object",
                    "properties" : {
                        "service" : {"type" : "string"},
                        "likelihood" : {"type" : "number", "description" : "0 to 1"},
                        "rationale" : {"type" : "string"},
                        "evidence_ids" : {"type" : "array", "items" : {"type" : "string"}},
                    },
                    "required" : ["service", "likelihood", "rationale", "evidence_ids"],
                    "additionalProperties" : False,
                },
            },
            "fault_type" : {"type" : "string", "enum" : FAULT_TYPES},
            "summary" : {"type" : "string", "description" : "2-4 sentence explanation of the root cause."},
            "remediation" : {"type" : "string"},
            "runbook_ids" : {"type" : "array", "items" : {"type" : "string"}},
        },
        "required" : ["ranked_services", "fault_type", "summary", "remediation", "runbook_ids"],
        "additionalProperties" : False,
    },
}

class AgentState(TypedDict, total = False):
    messages : list[dict]
    seen_evidence : list[str]
    seen_runbooks : list[str]
    trace : list[dict]
    steps : int
    verify_retries : int
    pending_calls : list[dict]
    report : dict
    verification : dict
    usage : dict

@lru_cache(maxsize = 1)
def runbook_retriever():
    from app.database import SessionLocal
    from app.retrieval import HybridRetriever, build_documents
    with SessionLocal() as db:
        documents = [d for d in build_documents(db) if d["type"] == "runbook"]
    return HybridRetriever(documents) if documents else None

def collect_ids(value, found):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "id" and isinstance(item, str):
                found.add(item)
            else:
                collect_ids(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_ids(item, found)
    return found

class ToolBox:
    def __init__(self, telemetry, use_ml):
        self.telemetry = telemetry
        self.use_ml = use_ml

    def specs(self):
        tools = TOOLS + ([ML_TOOL] if self.use_ml else []) + [SUBMIT_TOOL]
        return [{"type" : "function", "function" : tool} for tool in tools]

    def _service(self, name):
        if name not in self.telemetry.services:
            raise ValueError(f"Unknown service '{name}'. Call list_services for valid names.")
        return name

    def run(self, name, args):
        t = self.telemetry
        if name == "list_services":
            return {"services" : [
                {"service" : s, "has_logs" : s in t.logs, "has_traces" : s in t.traces}
                for s in t.services
            ]}
        if name == "get_top_anomalies":
            return {"anomalies" : t.top_anomalies(min(max(int(args.get("limit", 15)), 1), 30))}
        if name == "get_service_metrics":
            return {"service" : args["service"], "metrics" : t.service_metrics(self._service(args["service"]))}
        if name == "get_service_logs":
            return {"service" : args["service"], **t.service_logs(self._service(args["service"]))}
        if name == "get_service_traces":
            return {"service" : args["service"], **t.service_traces(self._service(args["service"]))}
        if name == "get_dependencies":
            return {"service" : args["service"], **t.neighbors(self._service(args["service"]))}
        if name == "search_runbooks":
            retriever = runbook_retriever()
            if retriever is None:
                return {"runbooks" : []}
            hits = retriever.search(args["query"], top_k = 3)["documents"]
            return {"runbooks" : [
                {"id" : d["id"], "title" : d["title"], "snippet" : d["snippet"][:200]} for d in hits
            ]}
        if name == "get_ml_ranking" and self.use_ml:
            return {"ranking" : ml_ranking(t)}
        raise ValueError(f"Unknown tool '{name}'")

def complete(client, **kwargs):
    """Chat completion that waits out Azure tokens-per-minute limits."""
    for _ in range(MAX_RATE_LIMIT_WAITS):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as error:
            headers = getattr(error.response, "headers", {}) or {}
            wait = float(headers.get("retry-after") or headers.get("x-ratelimit-reset-tokens") or 20)
            time.sleep(wait + random.uniform(1, 5))
    raise RuntimeError("Azure OpenAI rate limit: gave up after repeated waits")

def build_agent(toolbox, deployment):
    client = get_client()
    tool_specs = toolbox.specs()

    def agent(state):
        steps = state.get("steps", 0) + 1
        force_submit = steps >= MAX_STEPS
        response = complete(
            client,
            model = deployment,
            messages = state["messages"],
            tools = tool_specs,
            tool_choice = (
                {"type" : "function", "function" : {"name" : "submit_report"}}
                if force_submit else "auto"
            ),
            parallel_tool_calls = True,
            max_completion_tokens = MAX_OUTPUT_TOKENS,
        )
        message = response.choices[0].message
        usage = dict(state.get("usage", EMPTY_USAGE))
        usage["prompt_tokens"] += response.usage.prompt_tokens
        usage["completion_tokens"] += response.usage.completion_tokens
        details = getattr(response.usage, "prompt_tokens_details", None)
        usage["cached_tokens"] += (getattr(details, "cached_tokens", 0) or 0) if details else 0

        calls = [
            {"id" : call.id, "name" : call.function.name, "arguments" : call.function.arguments}
            for call in (message.tool_calls or [])
        ]
        assistant = {"role" : "assistant", "content" : message.content or ""}
        if calls:
            assistant["tool_calls"] = [
                {"id" : c["id"], "type" : "function",
                 "function" : {"name" : c["name"], "arguments" : c["arguments"]}}
                for c in calls
            ]
        messages = state["messages"] + [assistant]
        if not calls:
            messages.append({"role" : "user", "content" : "Continue the investigation, then call submit_report."})
        return {"messages" : messages, "pending_calls" : calls, "steps" : steps, "usage" : usage}

    def route_agent(state):
        calls = state.get("pending_calls", [])
        if any(c["name"] == "submit_report" for c in calls):
            return "verify"
        if calls:
            return "tools"
        return "agent"

    def tools(state):
        messages = list(state["messages"])
        seen_evidence = set(state.get("seen_evidence", []))
        seen_runbooks = set(state.get("seen_runbooks", []))
        trace = list(state.get("trace", []))
        for call in state["pending_calls"]:
            started = time.perf_counter()
            try:
                args = json.loads(call["arguments"] or "{}")
                result = toolbox.run(call["name"], args)
                ids = collect_ids(result, set())
                seen_evidence.update(i for i in ids if EVIDENCE_ID.match(i))
                seen_runbooks.update(i for i in ids if i.startswith("RB-"))
                ok = True
            except Exception as error:
                args, result, ok = {}, {"error" : str(error)}, False
            content = json.dumps(result, default = str, separators = (",", ":"))
            messages.append({"role" : "tool", "tool_call_id" : call["id"], "content" : content})
            trace.append({
                "tool" : call["name"], "arguments" : args, "ok" : ok,
                "result_chars" : len(content),
                "ms" : round((time.perf_counter() - started) * 1000, 1),
            })
        return {
            "messages" : messages, "seen_evidence" : sorted(seen_evidence),
            "seen_runbooks" : sorted(seen_runbooks), "trace" : trace,
        }

    def verify(state):
        call = next(c for c in state["pending_calls"] if c["name"] == "submit_report")
        messages = list(state["messages"])
        # Other calls made in the same turn still need tool responses.
        for other in state["pending_calls"]:
            if other is not call:
                messages.append({"role" : "tool", "tool_call_id" : other["id"],
                                 "content" : json.dumps({"error" : "Ignored: report submitted in the same turn."})})
        try:
            report = json.loads(call["arguments"])
        except json.JSONDecodeError:
            report = {"ranked_services" : [], "fault_type" : "unknown", "summary" : "",
                      "remediation" : "", "runbook_ids" : []}

        seen_evidence = set(state.get("seen_evidence", []))
        seen_runbooks = set(state.get("seen_runbooks", []))
        services = set(toolbox.telemetry.services)
        cited = [i for item in report.get("ranked_services", []) for i in item.get("evidence_ids", [])]
        invalid_evidence = sorted({i for i in cited if i not in seen_evidence})
        invalid_runbooks = sorted({i for i in report.get("runbook_ids", []) if i not in seen_runbooks})
        invalid_services = sorted({
            item["service"] for item in report.get("ranked_services", []) if item["service"] not in services
        })
        problems = []
        if invalid_evidence:
            problems.append(f"cited evidence never returned by a tool: {invalid_evidence}")
        if invalid_runbooks:
            problems.append(f"cited runbooks never returned by search_runbooks: {invalid_runbooks}")
        if invalid_services:
            problems.append(f"unknown services: {invalid_services}")
        if not report.get("ranked_services"):
            problems.append("ranked_services is empty")

        retries = state.get("verify_retries", 0)
        verification = {
            "cited" : len(cited) + len(report.get("runbook_ids", [])),
            "invalid" : len(invalid_evidence) + len(invalid_runbooks),
            "invalid_services" : invalid_services,
            "problems" : problems,
            "retries" : retries,
            "grounded" : not problems,
        }
        trace = list(state.get("trace", [])) + [{
            "tool" : "submit_report", "arguments" : {}, "ok" : not problems,
            "result_chars" : 0, "ms" : 0.0, "problems" : problems,
        }]
        if problems and retries < MAX_VERIFY_RETRIES:
            messages.append({"role" : "tool", "tool_call_id" : call["id"], "content" : json.dumps({
                "status" : "rejected",
                "errors" : problems,
                "instruction" : "Fix the report: cite only IDs returned by tools and valid service names, then call submit_report again.",
            })})
            return {"messages" : messages, "verify_retries" : retries + 1,
                    "verification" : verification, "trace" : trace, "pending_calls" : []}
        messages.append({"role" : "tool", "tool_call_id" : call["id"], "content" : json.dumps({"status" : "accepted"})})
        return {"messages" : messages, "report" : report, "verification" : verification,
                "trace" : trace, "pending_calls" : []}

    def ml_prior(state):
        result = toolbox.run("get_ml_ranking", {})
        call_id = "call_ml_prior"
        return {
            "messages" : state["messages"] + [
                {"role" : "user", "content" : ML_PRIOR_PROMPT},
                {"role" : "assistant", "content" : "", "tool_calls" : [
                    {"id" : call_id, "type" : "function",
                     "function" : {"name" : "get_ml_ranking", "arguments" : "{}"}}]},
                {"role" : "tool", "tool_call_id" : call_id,
                 "content" : json.dumps(result, separators = (",", ":"))},
            ],
            "trace" : [{"tool" : "get_ml_ranking", "arguments" : {}, "ok" : True,
                        "result_chars" : 0, "ms" : 0.0}],
        }

    def route_verify(state):
        return END if state.get("report") is not None else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("verify", verify)
    if toolbox.use_ml:
        graph.add_node("ml_prior", ml_prior)
        graph.add_edge(START, "ml_prior")
        graph.add_edge("ml_prior", "agent")
    else:
        graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_agent, {"tools" : "tools", "verify" : "verify", "agent" : "agent"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("verify", route_verify, {"agent" : "agent", END : END})
    return graph.compile()

def alert_message(telemetry):
    meta = telemetry.meta
    started = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(meta["inject_time"])))
    return (
        f"ALERT at {started}: service degradation detected in the {meta['system_name']} "
        f"microservice system ({len(telemetry.services)} services). Users report slow and failing "
        "requests. Identify the root-cause service and fault type."
    )

def investigate_case(case_id, use_ml = True, deployment = None):
    """Run the agent on one RCAEval case. Returns the report plus run metadata."""
    deployment = deployment or default_deployment()
    telemetry = CaseTelemetry(case_id)
    toolbox = ToolBox(telemetry, use_ml)
    graph = build_agent(toolbox, deployment)
    started = time.perf_counter()
    state = graph.invoke(
        {"messages" : [
            {"role" : "system", "content" : SYSTEM_PROMPT},
            {"role" : "user", "content" : alert_message(telemetry)},
        ]},
        {"recursion_limit" : 4 * (MAX_STEPS + MAX_VERIFY_RETRIES) + 10},
    )
    usage = state.get("usage", EMPTY_USAGE)
    report = state.get("report", {})
    # The LLM decides the top positions; any it leaves empty are completed
    # from the ML ranking (hybrid) or the statistical baseline (agent).
    fallback = [r["service"] for r in ml_ranking(telemetry, k = 100)] if use_ml else baro_ranking(telemetry)
    llm_ranking = [s["service"] for s in report.get("ranked_services", [])]
    final_ranking = list(dict.fromkeys(llm_ranking + [s for s in fallback if s not in llm_ranking]))
    return {
        "case_id" : case_id,
        "method" : "hybrid" if use_ml else "agent",
        "deployment" : deployment,
        "report" : report,
        "final_ranking" : final_ranking[:5],
        "verification" : state.get("verification", {}),
        "trace" : state.get("trace", []),
        "usage" : {
            **usage,
            "llm_calls" : state.get("steps", 0),
            "tool_calls" : sum(1 for t in state.get("trace", []) if t["tool"] != "submit_report"),
            "cost_usd" : estimate_cost(
                deployment, usage["prompt_tokens"], usage["completion_tokens"], usage["cached_tokens"]
            ),
            "latency_s" : round(time.perf_counter() - started, 2),
        },
    }
