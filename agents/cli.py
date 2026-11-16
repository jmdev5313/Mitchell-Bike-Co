"""Chat with the Agent as the Mechanic, in the terminal.

Commands act out what the Agent cannot do itself:
  /photo PATH     attach a photo to your next message
  /drafts         show the work order's messages to the Customer
  /send [ID]      (Mechanic) send a draft; defaults to the latest draft
  /approve        (Customer) approve the latest sent quote
  /decline        (Customer) decline the latest sent quote
  /reply TEXT     (Customer) reply to the shop
  /usage          tokens used in this conversation
  /quit           leave; the conversation can be resumed with --conversation ID

Run: make agent   (or: uv run python -m agents.cli [--conversation ID])
"""

import argparse
import asyncio
import sys
from pathlib import Path

from agents import config, conversations
from agents.runtime import RUNTIMES, TurnResult, open_agent
from shop import db, messages
from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation


class Session:
    """The non-Agent side of the chat: the Mechanic's and Customer's actions."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.photos: list[Path] = []
        self.notes: list[str] = []  # shop updates the Agent hears about with the next message

    def work_order_id(self, conn) -> int:
        work_order_id = conversations.get(conn, self.conversation_id).work_order_id
        if work_order_id is None:
            raise RuleViolation("no work order yet in this conversation")
        return work_order_id

    def handle(self, line: str) -> str:
        """Run a slash command and return what to print."""
        command, _, arg = line.partition(" ")
        arg = arg.strip()
        if command == "/photo":
            path = Path(arg).expanduser()
            if not path.is_file():
                return f"No file at {path}"
            self.photos.append(path)
            return f"Attached {path.name} to your next message."
        conn = db.connect()
        try:
            if command == "/drafts":
                thread = messages.list_messages(conn, self.work_order_id(conn))
                return "\n".join(_describe(m) for m in thread) or "No messages yet."
            if command == "/send":
                thread = messages.list_messages(conn, self.work_order_id(conn))
                drafts = [m for m in thread if m.status == "draft"]
                target = int(arg) if arg else (drafts[-1].id if drafts else None)
                if target is None:
                    return "No drafts to send."
                sent = messages.send_draft(conn, target)
                self.notes.append(f"The mechanic sent message {sent.id} to the customer.")
                return f"Sent message {sent.id} to the Customer."
            if command in ("/approve", "/decline"):
                thread = messages.list_messages(conn, self.work_order_id(conn))
                quotes = [m for m in thread if m.status == "sent" and m.quoted_total_cents is not None]
                if not quotes:
                    return "No sent quote to answer."
                status = wo.record_customer_decision(conn, quotes[-1].id, approved=command == "/approve")
                self.notes.append(f"The customer {status} the quote in message {quotes[-1].id}.")
                return f"The Customer {status} the ${quotes[-1].quoted_total_cents / 100:.2f} quote."
            if command == "/reply":
                if not arg:
                    return "Usage: /reply TEXT"
                msg = messages.receive_message(conn, self.work_order_id(conn), arg)
                self.notes.append(f"The customer replied (message {msg.id}).")
                return "The Customer's reply is in the thread."
            if command == "/usage":
                totals = conversations.usage_totals(conn, self.conversation_id)
                return ", ".join(f"{k}: {v:,}" for k, v in totals.items()) or "No usage yet."
            return f"Unknown command {command}. Commands: " + ", ".join(
                ("/photo", "/drafts", "/send", "/approve", "/decline", "/reply", "/usage", "/quit")
            )
        except (NotFound, RuleViolation, ValueError) as e:
            return f"Refused: {e}"
        finally:
            conn.close()

    def take_message(self, text: str) -> tuple[str, list[Path]]:
        """The Mechanic's message with any pending shop updates, and the photos to attach."""
        if self.notes:
            text = "(Shop update: " + " ".join(self.notes) + ")\n\n" + text
        photos, self.photos, self.notes = self.photos, [], []
        return text, photos


def _describe(m) -> str:
    quote = f" [quote ${m.quoted_total_cents / 100:.2f}]" if m.quoted_total_cents is not None else ""
    who = "to Customer" if m.direction == "to_customer" else "from Customer"
    return f"#{m.id} {m.status} {who}{quote}: {m.body}"


def render(result: TurnResult) -> str:
    lines = [f"  · {note}" for note in result.progress]
    for call in result.tool_calls:
        lines.append(f"  → {call.name}" + (f"  REFUSED: {call.result}" if call.is_error else ""))
    lines.append("")
    lines.append(result.reply)
    return "\n".join(lines)


async def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Chat with the Agent as the Mechanic.")
    parser.add_argument("--runtime", default="anthropic", choices=RUNTIMES)
    parser.add_argument("--conversation", help="resume a conversation by id")
    args = parser.parse_args(argv)
    config.load_env()

    async with open_agent(args.runtime, args.conversation) as agent:
        session = Session(agent.conversation_id)
        print(f"Agent ready ({agent.name}, conversation {agent.conversation_id}). Type /quit to leave.")
        while True:
            try:
                line = (await asyncio.to_thread(input, "\nMechanic> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line == "/quit":
                break
            if line.startswith("/"):
                print(session.handle(line))
                continue
            text, photos = session.take_message(line)
            result = await agent.send(text, photos)
            print(render(result))
        print(f"\nResume with: make agent ARGS='--conversation {agent.conversation_id}'")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
