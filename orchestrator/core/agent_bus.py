"""
AgentBus — Central message bus for inter-agent communication.

Every agent registers with the bus, publishes messages to topics,
and subscribes to topics it wants to listen to. Supports fan-out
(broadcast) and direct (point-to-point) messaging patterns.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A message sent between agents on the bus."""

    topic: str
    sender: str
    payload: Any
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.utcnow)
    session_id: Optional[str] = None
    reply_to: Optional[str] = None  # message_id of original if this is a reply

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "topic": self.topic,
            "sender": self.sender,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "reply_to": self.reply_to,
        }


class AgentBus:
    """
    Central nervous system of the orchestration platform.

    Agents publish and subscribe to named topics. Supports both
    synchronous callbacks and async coroutines as handlers.

    Usage:
        bus = AgentBus()

        # Subscribe
        bus.subscribe("analysis.technical", my_handler)

        # Publish
        await bus.publish(Message(
            topic="analysis.technical",
            sender="quant_analyst",
            payload={"signal": "BUY", "confidence": 0.85},
        ))
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self._subscribers: Dict[str, List[Callable]] = {}
        self._message_log: List[Message] = []
        self._registered_agents: Dict[str, str] = {}  # agent_id -> role

    # ── Registration ──────────────────────────────────────────────────

    def register_agent(self, agent_id: str, role: str) -> None:
        """Register an agent with the bus."""
        self._registered_agents[agent_id] = role
        logger.info("[AgentBus] Registered agent '%s' as '%s'", agent_id, role)

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister an agent from the bus."""
        self._registered_agents.pop(agent_id, None)
        logger.info("[AgentBus] Unregistered agent '%s'", agent_id)

    @property
    def active_agents(self) -> Dict[str, str]:
        """Return currently registered agents."""
        return dict(self._registered_agents)

    # ── Pub/Sub ───────────────────────────────────────────────────────

    def subscribe(self, topic: str, handler: Callable) -> None:
        """Subscribe a handler to a topic.

        Handler signature: handler(message: Message) -> None | Awaitable
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(handler)
        logger.debug("[AgentBus] '%s' subscribed to topic '%s'", handler.__name__, topic)

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        """Remove a handler from a topic."""
        if topic in self._subscribers:
            self._subscribers[topic] = [
                h for h in self._subscribers[topic] if h != handler
            ]

    async def publish(self, message: Message) -> int:
        """Publish a message to all subscribers of its topic.

        Returns the number of handlers notified.
        """
        message.session_id = message.session_id or self.session_id
        self._message_log.append(message)

        handlers = self._subscribers.get(message.topic, [])

        # Also deliver to wildcard subscribers (topic="*")
        handlers += self._subscribers.get("*", [])

        notified = 0
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
                notified += 1
            except Exception as exc:
                logger.error(
                    "[AgentBus] Handler '%s' failed for topic '%s': %s",
                    handler.__name__, message.topic, exc,
                )

        logger.debug(
            "[AgentBus] Published '%s' from '%s' → %d handlers notified",
            message.topic, message.sender, notified,
        )
        return notified

    def publish_sync(self, message: Message) -> int:
        """Synchronous wrapper for publish (runs in new event loop if needed)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If inside an existing event loop, schedule as task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.publish(message))
                    return future.result()
            else:
                return loop.run_until_complete(self.publish(message))
        except RuntimeError:
            return asyncio.run(self.publish(message))

    # ── Message Log ───────────────────────────────────────────────────

    def get_messages(
        self,
        topic: Optional[str] = None,
        sender: Optional[str] = None,
        last_n: Optional[int] = None,
    ) -> List[Message]:
        """Retrieve logged messages with optional filters."""
        msgs = self._message_log
        if topic:
            msgs = [m for m in msgs if m.topic == topic]
        if sender:
            msgs = [m for m in msgs if m.sender == sender]
        if last_n:
            msgs = msgs[-last_n:]
        return msgs

    def get_conversation_thread(self, topic: str) -> List[dict]:
        """Return all messages for a topic as readable dicts."""
        return [m.to_dict() for m in self.get_messages(topic=topic)]

    def clear_log(self) -> None:
        """Clear the in-memory message log."""
        self._message_log.clear()

    def summary(self) -> dict:
        """Return a brief summary of bus activity."""
        return {
            "session_id": self.session_id,
            "registered_agents": len(self._registered_agents),
            "topics": len(self._subscribers),
            "total_messages": len(self._message_log),
            "agents": self._registered_agents,
        }
