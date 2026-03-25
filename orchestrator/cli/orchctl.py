#!/usr/bin/env python3
"""
orchctl — Command-line interface for the CMAOP platform.

Manage and introspect your multi-agent trading orchestrator
from the terminal. No GUI required.

Commands:
    run        Run a full analysis session
    agents     List all registered agents
    tools      List all registered tools
    memory     Search or display long-term memory
    token-usage Show token spending summary
    status     Print platform health/circuit status

Usage:
    python -m orchestrator.cli.orchctl run --ticker BTCUSDT
    python -m orchestrator.cli.orchctl agents list
    python -m orchestrator.cli.orchctl memory search "bitcoin bullish"
    python -m orchestrator.cli.orchctl token-usage --session abc123
    python -m orchestrator.cli.orchctl status
"""

import argparse
import json
import sys
import textwrap
from typing import Optional


# ── ANSI Colors ───────────────────────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    RED    = "\033[31m"
    BLUE   = "\033[34m"
    GREY   = "\033[90m"

def _header(text: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}{'─' * 55}{C.RESET}")
    print(f"  {C.BOLD}{text}{C.RESET}")
    print(f"{C.CYAN}{'─' * 55}{C.RESET}")

def _ok(msg: str) -> None:
    print(f"  {C.GREEN}✅{C.RESET} {msg}")

def _warn(msg: str) -> None:
    print(f"  {C.YELLOW}⚠️ {C.RESET} {msg}")

def _err(msg: str) -> None:
    print(f"  {C.RED}❌{C.RESET} {msg}", file=sys.stderr)

def _row(label: str, value: str, width: int = 22) -> None:
    print(f"  {C.GREY}{label:<{width}}{C.RESET} {value}")


# ── Command: run ──────────────────────────────────────────────────────────────

def cmd_run(args) -> None:
    """Run a trading analysis session."""
    from orchestrator.sdk.presets import create_trading_orchestrator
    import asyncio

    _header(f"CMAOP — Running Analysis: {args.ticker}")
    _row("Ticker",   args.ticker)
    _row("Topology", args.topology)
    _row("Budget",   f"${args.budget:.2f}")
    _row("Dry-run",  str(args.dry_run))
    print()

    orch = create_trading_orchestrator(
        ticker=args.ticker,
        topology=args.topology,
        budget_usd=args.budget,
    )

    if len(orch.router._agents) == 0:
        _warn("No agents registered. Add agents with @agent decorator before running.")
        _warn("Try: python -m orchestrator.example  (for a demo run)")
        return

    result = asyncio.run(orch.run())
    _print_run_result(result)


def _print_run_result(result) -> None:
    _header("Session Result")
    _row("Session ID",    result.session_id)
    _row("Ticker",        result.ticker)
    _row("Topology",      result.topology)
    _row("Agents Run",    str(len(result.run_results)))
    _row("Success Rate",  f"{result.success_rate:.0%}")
    _row("Total Duration",f"{result.total_duration:.2f}s")

    if result.final_decision:
        d = result.final_decision
        action = d.get("action", "?")
        conf   = d.get("confidence", 0)
        color  = C.GREEN if action == "BUY" else (C.RED if action == "SELL" else C.YELLOW)
        print(f"\n  {C.BOLD}Final Decision:{C.RESET}  {color}{C.BOLD}{action}{C.RESET}  "
              f"(confidence: {conf:.0%})")
        reason = d.get("reason", "")
        if reason:
            print(f"  {C.GREY}Reason:{C.RESET} {textwrap.shorten(reason, width=60)}")
    else:
        _warn("No decision produced.")

    failed = [r.agent_id for r in result.run_results if not r.success]
    if failed:
        _err(f"Failed agents: {', '.join(failed)}")
    print()


# ── Command: agents ───────────────────────────────────────────────────────────

def cmd_agents(args) -> None:
    """List registered agents."""
    from orchestrator.sdk.agent_builder import list_agents

    agents = list_agents()
    _header("Registered Agents")
    if not agents:
        _warn("No agents registered yet. Use @agent decorator to register some.")
        return

    for a in agents:
        priority_badge = f"{C.GREY}p{a['priority']}{C.RESET}"
        deps = ", ".join(a["depends_on"]) if a["depends_on"] else C.GREY + "none" + C.RESET
        print(f"  {C.BOLD}{C.CYAN}{a['agent_id']:<22}{C.RESET} "
              f"{C.BLUE}{a['role']:<25}{C.RESET} {priority_badge}")
        if a["description"]:
            print(f"    {C.GREY}{textwrap.shorten(a['description'], width=60)}{C.RESET}")
        print(f"    depends_on: {deps}")
    print()


# ── Command: tools ────────────────────────────────────────────────────────────

def cmd_tools(args) -> None:
    """List registered tools."""
    from orchestrator.sdk.agent_builder import list_tools

    tools = list_tools()
    _header("Registered Tools")
    if not tools:
        _warn("No tools registered yet. Use @tool decorator to register some.")
        return

    for t in tools:
        print(f"  {C.BOLD}{C.GREEN}{t['name']:<25}{C.RESET} "
              f"{C.GREY}[{t['category']}]{C.RESET}")
        if t["description"]:
            print(f"    {C.GREY}{textwrap.shorten(t['description'], width=60)}{C.RESET}")
    print()


# ── Command: memory ───────────────────────────────────────────────────────────

def cmd_memory(args) -> None:
    """Interact with long-term memory and reasoning bank."""
    if args.memory_cmd == "search":
        _cmd_memory_search(args.query, args.top_k)
    elif args.memory_cmd == "list":
        _cmd_memory_list(args.limit)
    elif args.memory_cmd == "stats":
        _cmd_memory_stats()
    else:
        _err(f"Unknown memory subcommand: {args.memory_cmd}")


def _cmd_memory_search(query: str, top_k: int) -> None:
    from orchestrator.memory.reasoning_bank import ReasoningBank

    bank = ReasoningBank()
    _header(f"Memory Search: '{query}'")
    results = bank.suggest(query, top_k=top_k, min_score=0.0)
    if not results:
        _warn("No matching patterns found.")
        return
    for r in results:
        print(f"  {C.BOLD}{r.task[:60]}{C.RESET}  {C.GREY}score={r.score:.2f}{C.RESET}")
        print(f"    {C.GREY}{r.outcome[:80]}{C.RESET}")
    print()


def _cmd_memory_list(limit: int) -> None:
    from orchestrator.memory.long_term_memory import LongTermMemory

    ltm = LongTermMemory()
    _header(f"Long-Term Memory (last {limit})")
    memories = ltm.recall_recent(limit=limit)
    if not memories:
        _warn("Memory bank is empty.")
        return
    for m in memories:
        action_color = C.GREEN if m.action == "BUY" else (C.RED if m.action == "SELL" else C.YELLOW)
        pnl_str = f"${m.outcome_pnl:+.2f}" if m.outcome_pnl is not None else "open"
        print(f"  {C.GREY}{m.memory_id[:8]}{C.RESET}  "
              f"{action_color}{m.action:<6}{C.RESET}  "
              f"{m.ticker:<12}  "
              f"@ ${m.entry_price:>10,.2f}  "
              f"PnL: {pnl_str:<10}  "
              f"{C.GREY}{m.created_at.strftime('%Y-%m-%d %H:%M')}{C.RESET}")
    print()


def _cmd_memory_stats() -> None:
    from orchestrator.memory.long_term_memory import LongTermMemory
    from orchestrator.memory.reasoning_bank import ReasoningBank

    ltm  = LongTermMemory()
    bank = ReasoningBank()
    _header("Memory Statistics")
    pnl = ltm.get_pnl_summary()
    _row("Total Trades",   str(pnl["trades"]))
    _row("Total PnL",      f"${pnl['total_pnl']:+,.4f}")
    _row("Average PnL",    f"${pnl['avg_pnl']:+,.4f}")
    stats = bank.stats()
    _row("Trajectories",   str(stats["total_trajectories"]))
    _row("Avg Quality",    f"{stats['avg_score']:.2f}")
    _row("Max Quality",    f"{stats['max_score']:.2f}")
    _row("Distilled",      str(stats["distilled_patterns"]))
    print()


# ── Command: token-usage ──────────────────────────────────────────────────────

def cmd_token_usage(args) -> None:
    """Show token spending for a session."""
    from orchestrator.guards.token_meter import TokenMeter

    sid = args.session or "demo-session"
    meter = TokenMeter(session_id=sid, db_path=":memory:")
    # For demo purposes create a sample record
    if args.demo:
        meter.record("market_analyst", 1200, 350)
        meter.record("risk_manager",    800, 200)
        meter.record("trader",          400, 150)

    _header(f"Token Usage — Session: {sid}")
    s = meter.summary()
    _row("Session ID",    s["session_id"])
    _row("Total Cost",    s["total_cost_usd"])
    _row("Budget",        s["budget_usd"])
    _row("Budget Used",   s["budget_used_pct"])
    _row("Input Tokens",  str(s["input_tokens"]))
    _row("Output Tokens", str(s["output_tokens"]))
    _row("Total Tokens",  str(s["total_tokens"]))
    print()


# ── Command: status ───────────────────────────────────────────────────────────

def cmd_status(args) -> None:
    """Show platform health and circuit breaker status."""
    from orchestrator.guards.circuit_breaker import CircuitBreaker, CircuitState
    from orchestrator.sdk.agent_builder import get_registered_agents, get_registered_tools

    _header("CMAOP Platform Status")
    agents = get_registered_agents()
    tools  = get_registered_tools()
    _ok(f"Platform: HEALTHY")
    _row("Registered Agents", str(len(agents)))
    _row("Registered Tools",  str(len(tools)))

    cb = CircuitBreaker()
    _row("Kill Switch",  C.GREEN + "OFF" + C.RESET if not cb._kill_switch else C.RED + "ON" + C.RESET)

    all_stats = cb.all_stats()
    if all_stats:
        print(f"\n  {C.BOLD}Circuit States:{C.RESET}")
        for name, stat in all_stats.items():
            state_color = C.GREEN if stat["state"] == "CLOSED" else C.RED
            print(f"    {name:<25} {state_color}{stat['state']}{C.RESET}  "
                  f"(fails={stat['failures']}, calls={stat['total_calls']})")
    else:
        _row("Circuits", "No active circuits")
    print()


# ── Parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchctl",
        description="CMAOP — Custom Multi-Agent Orchestration Platform CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
          Examples:
            python -m orchestrator.cli.orchctl run --ticker BTCUSDT
            python -m orchestrator.cli.orchctl agents
            python -m orchestrator.cli.orchctl tools
            python -m orchestrator.cli.orchctl memory search "bitcoin oversold"
            python -m orchestrator.cli.orchctl memory list --limit 10
            python -m orchestrator.cli.orchctl memory stats
            python -m orchestrator.cli.orchctl token-usage --demo
            python -m orchestrator.cli.orchctl status
        """),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── run ──
    p_run = sub.add_parser("run", help="Run a trading analysis session")
    p_run.add_argument("--ticker",   default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    p_run.add_argument("--topology", default="pipeline",
                       choices=["pipeline", "hierarchical", "mesh"])
    p_run.add_argument("--budget",   type=float, default=1.00,
                       help="Max LLM budget in USD (default: 1.00)")
    p_run.add_argument("--dry-run",  action="store_true",
                       help="Simulate without touching real money")

    # ── agents ──
    sub.add_parser("agents", help="List all registered agents")

    # ── tools ──
    sub.add_parser("tools", help="List all registered tools")

    # ── memory ──
    p_mem = sub.add_parser("memory", help="Interact with memory stores")
    mem_sub = p_mem.add_subparsers(dest="memory_cmd", required=True)
    p_search = mem_sub.add_parser("search", help="Search reasoning bank")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--top-k", type=int, default=3, dest="top_k")
    p_list = mem_sub.add_parser("list", help="List recent trade memories")
    p_list.add_argument("--limit", type=int, default=10)
    mem_sub.add_parser("stats", help="Show memory statistics")

    # ── token-usage ──
    p_tok = sub.add_parser("token-usage", help="Show token spending")
    p_tok.add_argument("--session", help="Session ID to query")
    p_tok.add_argument("--demo",    action="store_true", help="Inject demo data")

    # ── status ──
    sub.add_parser("status", help="Show platform health")

    return parser


def main(argv=None) -> None:
    """Entry point for orchctl."""
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "run":         cmd_run,
        "agents":      cmd_agents,
        "tools":       cmd_tools,
        "memory":      cmd_memory,
        "token-usage": cmd_token_usage,
        "status":      cmd_status,
    }

    handler = dispatch.get(args.command)
    if handler:
        try:
            handler(args)
        except KeyboardInterrupt:
            print(f"\n{C.YELLOW}Interrupted by user.{C.RESET}")
            sys.exit(0)
        except Exception as exc:
            _err(f"Command failed: {exc}")
            raise
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
