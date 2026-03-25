"""Tests for Phase 2 Memory Layer components."""

import asyncio
import pytest

from orchestrator.memory.vector_memory import VectorMemory
from orchestrator.memory.short_term_memory import ShortTermMemory
from orchestrator.memory.long_term_memory import LongTermMemory
from orchestrator.memory.reasoning_bank import ReasoningBank


# ── VectorMemory Tests ────────────────────────────────────────────────────────

class TestVectorMemory:
    def setup_method(self):
        self.mem = VectorMemory(db_path=":memory:", dimensions=4)

    def test_store_and_count(self):
        self.mem.store("entry_a", [0.1, 0.2, 0.3, 0.4], {"ticker": "BTC"})
        self.mem.store("entry_b", [0.9, 0.8, 0.7, 0.6], {"ticker": "ETH"})
        assert self.mem.count() == 2

    def test_search_returns_results(self):
        self.mem.store("btc_buy", [1.0, 0.0, 0.0, 0.0], {"action": "BUY"})
        self.mem.store("eth_sell", [0.0, 1.0, 0.0, 0.0], {"action": "SELL"})
        results = self.mem.search([1.0, 0.0, 0.0, 0.0], top_k=1)
        assert len(results) >= 1
        # The most similar should be the BUY entry
        assert results[0].label == "btc_buy"

    def test_delete(self):
        eid = self.mem.store("to_delete", [0.5, 0.5, 0.5, 0.5])
        assert self.mem.count() == 1
        self.mem.delete(eid)
        assert self.mem.count() == 0

    def test_list_all(self):
        self.mem.store("a", [1.0, 0.0, 0.0, 0.0])
        self.mem.store("b", [0.0, 1.0, 0.0, 0.0])
        entries = self.mem.list_all()
        assert len(entries) == 2

    def test_dimension_mismatch(self):
        with pytest.raises(ValueError):
            self.mem.store("bad", [1.0, 2.0])  # wrong dimensions


# ── ShortTermMemory Tests ────────────────────────────────────────────────────

class TestShortTermMemory:
    def setup_method(self):
        self.stm = ShortTermMemory(ttl_seconds=3600)

    def test_set_and_get(self):
        self.stm.set("price", 65_000.0)
        assert self.stm.get("price") == 65_000.0

    def test_default_value(self):
        assert self.stm.get("missing", default="fallback") == "fallback"

    def test_exists(self):
        self.stm.set("key", "value")
        assert self.stm.exists("key")
        assert not self.stm.exists("nonexistent")

    def test_delete(self):
        self.stm.set("temp", 42)
        self.stm.delete("temp")
        assert not self.stm.exists("temp")

    def test_conversation_history(self):
        self.stm.push_message("user", "What is BTC price?")
        self.stm.push_message("agent", "Current BTC is $65,000")
        history = self.stm.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_context_variables(self):
        self.stm.set_context("session_id", "abc-123")
        assert self.stm.get_context("session_id") == "abc-123"


# ── LongTermMemory Tests ──────────────────────────────────────────────────────

class TestLongTermMemory:
    def setup_method(self):
        self.ltm = LongTermMemory(db_path=":memory:")

    def test_store_and_recall(self):
        self.ltm.store_trade_memory(
            ticker="BTCUSDT",
            action="BUY",
            entry_price=65_000,
            conditions={"rsi": 38},
            confidence=0.85,
        )
        memories = self.ltm.recall_by_ticker("BTCUSDT")
        assert len(memories) == 1
        assert memories[0].action == "BUY"

    def test_update_outcome(self):
        mid = self.ltm.store_trade_memory("ETHUSDT", "SELL", 3200)
        self.ltm.update_outcome(mid, outcome_pnl=120.5)
        memories = self.ltm.recall_by_ticker("ETHUSDT")
        assert memories[0].outcome_pnl == 120.5

    def test_recall_by_action(self):
        self.ltm.store_trade_memory("BTCUSDT", "BUY", 65000)
        self.ltm.store_trade_memory("BTCUSDT", "SELL", 66000)
        buys = self.ltm.recall_by_action("BUY")
        assert all(m.action == "BUY" for m in buys)

    def test_pnl_summary(self):
        mid1 = self.ltm.store_trade_memory("BTCUSDT", "BUY", 65000)
        mid2 = self.ltm.store_trade_memory("BTCUSDT", "SELL", 66000)
        self.ltm.update_outcome(mid1, 200.0)
        self.ltm.update_outcome(mid2, -50.0)
        summary = self.ltm.get_pnl_summary("BTCUSDT")
        assert summary["trades"] == 2
        assert summary["total_pnl"] == pytest.approx(150.0)


# ── ReasoningBank Tests ───────────────────────────────────────────────────────

class TestReasoningBank:
    def setup_method(self):
        self.bank = ReasoningBank(db_path=":memory:")

    def test_start_and_finalize(self):
        tid = self.bank.start_trajectory("Analyze BTCUSDT RSI oversold")
        self.bank.add_step(tid, "observation", "RSI is 38")
        self.bank.add_step(tid, "reasoning", "Oversold → likely bounce")
        result = self.bank.finalize(tid, score=0.9, outcome="Trade +$320 PnL")
        assert result is True
        assert self.bank.stats()["total_trajectories"] == 1

    def test_suggest_by_keyword(self):
        tid = self.bank.start_trajectory("BTCUSDT RSI oversold BUY signal")
        self.bank.add_step(tid, "observation", "RSI 38, MACD crossover")
        self.bank.finalize(tid, score=0.88, outcome="Profitable")

        suggestions = self.bank.suggest("BTCUSDT RSI oversold", top_k=3)
        assert len(suggestions) == 1
        assert "RSI" in suggestions[0].task

    def test_suggest_as_prompt(self):
        tid = self.bank.start_trajectory("ETHUSDT bearish divergence SELL")
        self.bank.add_step(tid, "observation", "Bearish divergence on 4h chart")
        self.bank.finalize(tid, score=0.75, outcome="Avoided -5% drawdown")

        prompt = self.bank.suggest_as_prompt("ETHUSDT bearish signal")
        assert "PAST REASONING PATTERNS" in prompt
        assert "Bearish" in prompt

    def test_distill_patterns(self):
        # Create 3 similar trajectories with high score
        for i in range(3):
            tid = self.bank.start_trajectory("BTCUSDT RSI signal analysis")
            self.bank.finalize(tid, score=0.85, outcome=f"Trade {i} success")
        count = self.bank.distill(min_count=3, min_score=0.7)
        assert count >= 1

    def test_stats(self):
        tid = self.bank.start_trajectory("Test trajectory")
        self.bank.finalize(tid, score=0.6)
        stats = self.bank.stats()
        assert stats["total_trajectories"] == 1
        assert stats["avg_score"] == pytest.approx(0.6)
