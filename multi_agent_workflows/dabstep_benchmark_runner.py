"""DABstep runner wrapper for the Phase 6 multi-agent workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent_core.benchmark.benchmark_runner import run_dabstep_benchmark
from data_agent_core.llm.client import LLMClient
from multi_agent_workflows.end_to_end_data_analysis_workflow import DataAnalysisMultiAgentWorkflow


def run_dabstep_multi_agent_benchmark(
    *,
    dataset_root: str | Path,
    split: str = "dev",
    limit: int = 10,
    offset: int = 0,
    output_dir: str | Path = "outputs/dabstep_multi_agent",
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Run DABstep tasks through the Phase 6 multi-agent workflow."""

    def agent_factory(context_dir: Path) -> DataAnalysisMultiAgentWorkflow:
        return DataAnalysisMultiAgentWorkflow.from_dabstep_context(context_dir, llm_client=llm_client)

    return run_dabstep_benchmark(
        dataset_root=dataset_root,
        split=split,
        limit=limit,
        offset=offset,
        output_dir=output_dir,
        agent_factory=agent_factory,
        agent_mode="multi_agent",
    )


def main() -> None:
    """CLI entrypoint for the Phase 6 multi-agent DABstep runner."""

    parser = argparse.ArgumentParser(description="Run DABstep benchmark with Phase 6 multi-agent workflow.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--split", default="dev", choices=["dev", "all"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-dir", default="outputs/dabstep_multi_agent")
    args = parser.parse_args()
    summary = run_dabstep_multi_agent_benchmark(
        dataset_root=args.dataset_root,
        split=args.split,
        limit=args.limit,
        offset=args.offset,
        output_dir=args.output_dir,
    )
    printable = {key: value for key, value in summary.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
