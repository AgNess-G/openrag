"""CLI for the composable retrieval pipeline.

Commands
--------
ask <query>     Run the full retrieve → rerank → agent pipeline and print the response.
search <query>  Run retrieval only (no LLM) and print ranked document chunks.
nudges          Generate nudge suggestions from conversation history.
config          Print the active retrieval configuration.

Usage
-----
    uv run python -m pipeline.retrieval.cli ask "What is the Q3 roadmap?"
    uv run python -m pipeline.retrieval.cli search "delivery deadline"
    uv run python -m pipeline.retrieval.cli nudges --chat-id <response_id>
    uv run python -m pipeline.retrieval.cli config

Or via the installed script entry point:
    openrag-retrieve ask "What is the Q3 roadmap?"

Authentication
--------------
The retrieval pipeline uses per-user OpenSearch access control.
Pass credentials via:
  --jwt-token <token>        or  OPENRAG_JWT_TOKEN env var
  --user-id  <id>            or  OPENRAG_USER_ID env var   (default: cli-user)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Return (user_id, jwt_token) from args or env vars."""
    user_id = getattr(args, "user_id", None) or os.getenv("OPENRAG_USER_ID", "cli-user")
    jwt_token = getattr(args, "jwt_token", None) or os.getenv("OPENRAG_JWT_TOKEN", "")
    return user_id, jwt_token


def _build_pipeline(args: argparse.Namespace):
    from pipeline.retrieval.config import RetrievalConfigManager
    from pipeline.retrieval.pipeline import RetrievalPipelineBuilder
    from pipeline.retrieval.registry import get_default_registry

    config = RetrievalConfigManager(args.config).get_config()
    registry = get_default_registry()
    return RetrievalPipelineBuilder(config, registry).build(), config


def _print_sources(sources, verbose: bool = False) -> None:
    if not sources:
        print("  (no sources)")
        return
    for i, s in enumerate(sources, 1):
        preview = (s.text or "")[:120].replace("\n", " ")
        print(f"  [{i}] score={s.score:.3f}  {s.filename}  p={s.page}")
        if verbose:
            print(f"       {preview}...")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def _cmd_ask(args: argparse.Namespace) -> None:
    from pipeline.retrieval.types import RetrievalQuery

    user_id, jwt_token = _get_credentials(args)
    pipeline, _ = _build_pipeline(args)

    query = RetrievalQuery(
        text=args.query,
        user_id=user_id,
        jwt_token=jwt_token,
        filters=json.loads(args.filters) if args.filters else None,
        limit=args.limit,
        score_threshold=args.score_threshold,
    )

    print(f"Query:    {args.query}")
    print(f"Retriever: {type(pipeline.retriever).__name__}")
    print(f"Agent:     {type(pipeline.agent).__name__}")
    if args.chat_id:
        print(f"Chat ID:   {args.chat_id}")
    print()

    response = await pipeline.run(query, previous_response_id=args.chat_id)

    print("=" * 60)
    print(response.response)
    print("=" * 60)

    if response.usage:
        tokens = response.usage
        print(
            f"\nUsage: {tokens.get('input_tokens', '?')} in / "
            f"{tokens.get('output_tokens', '?')} out"
        )

    print(f"\nSources ({len(response.sources)}):")
    _print_sources(response.sources, verbose=args.verbose)

    print(f"\nChat ID: {response.response_id}")


async def _cmd_search(args: argparse.Namespace) -> None:
    from pipeline.retrieval.types import RetrievalQuery

    user_id, jwt_token = _get_credentials(args)
    pipeline, _ = _build_pipeline(args)

    query = RetrievalQuery(
        text=args.query,
        user_id=user_id,
        jwt_token=jwt_token,
        filters=json.loads(args.filters) if args.filters else None,
        limit=args.limit,
        score_threshold=args.score_threshold,
    )

    print(f"Query:     {args.query}")
    print(f"Retriever: {type(pipeline.retriever).__name__}")
    print()

    results = await pipeline.retriever.retrieve(query)

    if not results:
        print("No results found.")
        return

    if args.rerank:
        results = await pipeline.reranker.rerank(query.text, results)
        print(f"Reranker:  {type(pipeline.reranker).__name__}")
        print()

    for i, r in enumerate(results, 1):
        print(f"[{i:2d}] score={r.score:.4f}  {r.filename}  p={r.page}")
        if args.verbose:
            preview = (r.text or "")[:200].replace("\n", " ")
            print(f"      {preview}...")
        else:
            preview = (r.text or "")[:100].replace("\n", " ")
            print(f"      {preview}...")


async def _cmd_nudges(args: argparse.Namespace) -> None:
    from pipeline.retrieval.types import RetrievalQuery

    user_id, jwt_token = _get_credentials(args)
    pipeline, _ = _build_pipeline(args)

    query = RetrievalQuery(
        text="",
        user_id=user_id,
        jwt_token=jwt_token,
        filters=json.loads(args.filters) if args.filters else None,
        limit=args.limit,
        score_threshold=0.0,
    )

    print(f"Nudges generator: {type(pipeline.nudges_generator).__name__}")
    if args.chat_id:
        print(f"Chat ID: {args.chat_id}")
    print()

    suggestions = await pipeline.generate_nudges(query, previous_response_id=args.chat_id)

    if not suggestions:
        print("No nudges generated.")
        return

    print("Suggested follow-up questions:")
    for i, s in enumerate(suggestions, 1):
        print(f"  {i}. {s}")


def _cmd_config(args: argparse.Namespace) -> None:
    from pipeline.retrieval.config import RetrievalConfigManager

    config = RetrievalConfigManager(args.config).get_config()

    print("Retrieval Configuration")
    print("=" * 40)
    print(f"Retriever:  {config.retriever.type}")
    print(f"  semantic_weight: {config.retriever.semantic_weight}")
    print(f"  keyword_weight:  {config.retriever.keyword_weight}")
    print(f"  limit:           {config.retriever.limit}")
    print(f"  score_threshold: {config.retriever.score_threshold}")
    print()
    print(f"Reranker:   {config.reranker.type}")
    if config.reranker.type != "none":
        print(f"  top_k: {config.reranker.top_k}")
    print()
    print(f"Agent:      {config.agent.type}")
    print(f"  model:          {config.agent.model}")
    print(f"  temperature:    {config.agent.temperature}")
    print(f"  max_tokens:     {config.agent.max_tokens}")
    print(f"  max_iterations: {config.agent.max_iterations}")
    print(f"  tools:          {config.agent.tools}")
    print()
    print(f"Nudges:     {config.nudges.type}  (enabled={config.nudges.enabled})")
    if config.nudges.enabled:
        print(f"  model:           {config.nudges.model}")
        print(f"  max_suggestions: {config.nudges.max_suggestions}")
    print()
    print(f"Conversation rolling_window: {config.conversation.rolling_window}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="openrag-retrieve",
        description="OpenRAG Composable Retrieval Pipeline CLI",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Retrieval config file (default: pipeline/presets/retrieval/retrieval.yaml)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")

    # Shared auth args added to relevant subcommands
    auth_parent = argparse.ArgumentParser(add_help=False)
    auth_parent.add_argument("--user-id", default=None, help="User ID (or OPENRAG_USER_ID env)")
    auth_parent.add_argument("--jwt-token", default=None, help="JWT token (or OPENRAG_JWT_TOKEN env)")

    # Shared search args
    search_parent = argparse.ArgumentParser(add_help=False)
    search_parent.add_argument("--limit", type=int, default=10, help="Max documents to retrieve")
    search_parent.add_argument("--score-threshold", type=float, default=0.0)
    search_parent.add_argument(
        "--filters",
        default=None,
        help='Filters as JSON string, e.g. \'{"data_sources": ["wiki"]}\'',
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ask
    p_ask = sub.add_parser(
        "ask",
        parents=[auth_parent, search_parent],
        help="Run the full retrieve → rerank → agent pipeline",
    )
    p_ask.add_argument("query", help="Natural language question")
    p_ask.add_argument("--chat-id", default=None, help="Continue a previous conversation")

    # search
    p_search = sub.add_parser(
        "search",
        parents=[auth_parent, search_parent],
        help="Retrieve document chunks without running the LLM agent",
    )
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "--rerank",
        action="store_true",
        help="Apply the configured reranker to results",
    )

    # nudges
    p_nudges = sub.add_parser(
        "nudges",
        parents=[auth_parent, search_parent],
        help="Generate follow-up question suggestions",
    )
    p_nudges.add_argument(
        "--chat-id",
        default=None,
        help="Base nudges on a previous conversation",
    )

    # config
    sub.add_parser("config", help="Print the active retrieval configuration")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if args.command == "config":
        _cmd_config(args)
        return

    cmd_map = {
        "ask": _cmd_ask,
        "search": _cmd_search,
        "nudges": _cmd_nudges,
    }

    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()
