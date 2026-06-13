from prometheus_client import Counter, Gauge, Histogram

requests_total = Counter(
    "gateway_requests_total",
    "Total requests processed",
    ["source"],  # cache / local / external
)

request_duration = Histogram(
    "gateway_request_duration_seconds",
    "Request duration in seconds",
    ["source"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

cache_hit_ratio = Gauge(
    "gateway_cache_hit_ratio",
    "Cache hit ratio (rolling)",
)

knowledge_entries_total = Gauge(
    "gateway_knowledge_entries_total",
    "Total entries in Knowledge Store",
)

external_tokens_total = Counter(
    "gateway_external_tokens_total",
    "Total tokens consumed from external LLMs",
    ["provider"],
)

finetuning_runs_total = Counter(
    "gateway_finetuning_runs_total",
    "Total fine-tuning runs",
    ["status"],  # success / failure
)

local_model_accuracy = Gauge(
    "gateway_local_model_accuracy",
    "Latest local model benchmark accuracy",
)
