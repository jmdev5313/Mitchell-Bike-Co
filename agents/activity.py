"""The Agent's activity log: which MCP server each tool call went to, and what came back.

Summaries are written here from the tool results, in plain code. No model is
involved, so the log shows what actually happened, including every refusal.
"""

import json
from typing import Any

# Which shop MCP server offers each tool. tests/test_activity.py checks this
# against the servers themselves.
TOOL_SERVERS = {
    **dict.fromkeys(
        ["find_customer", "get_bike", "check_fit", "list_fitting_parts", "stock_status", "list_services"],
        "catalog",
    ),
    **dict.fromkeys(
        ["open_work_order", "get_work_order", "record_diagnosis", "add_part", "add_service",
         "lock_quote", "draft_customer_message", "list_customer_messages"],
        "work orders",
    ),
    **dict.fromkeys(["supplier_options", "estimate_ready_date", "plan_order", "create_purchase_order"], "procurement"),
}


def server_for(tool: str) -> str:
    return TOOL_SERVERS.get(tool, "unknown")


def describe(tool: str, arguments: dict[str, Any] | None, result: str, is_error: bool) -> str:
    """One short line for the activity log."""
    if is_error:
        return "Refused: " + _clean_error(tool, result)
    data = _parse(result)
    try:
        return _SUMMARIES.get(tool, _generic)(arguments or {}, data)
    except (KeyError, TypeError, IndexError, ValueError):
        return _generic(arguments or {}, data)


def entry(tool: str, arguments: dict[str, Any] | None, result: str, is_error: bool) -> dict[str, Any]:
    out = {
        "name": tool,
        "server": server_for(tool),
        "is_error": is_error,
        "summary": describe(tool, arguments, result, is_error),
    }
    if tool == "draft_customer_message" and not is_error:
        # Which message the Agent drafted, so the workshop can show it in the chat as a card.
        message = _parse(result)
        if isinstance(message, dict) and isinstance(message.get("id"), int):
            out["message_id"] = message["id"]
    return out


def _clean_error(tool: str, text: str) -> str:
    prefix = f"Error executing tool {tool}: "
    return text[len(prefix):] if text.startswith(prefix) else text


def _parse(text: str) -> Any:
    """A tool result as JSON. List results arrive as several objects one after another."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value["result"] if isinstance(value, dict) and set(value) == {"result"} else value
    except json.JSONDecodeError:
        pass
    decoder, items, i = json.JSONDecoder(), [], 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            value, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            return text
        items.append(value)
    return items


def _as_list(data: Any) -> list:
    if data is None:
        return []
    return data if isinstance(data, list) else [data]


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def _short_date(iso: str) -> str:
    from datetime import date

    d = date.fromisoformat(iso)
    return f"{d:%a}, {d:%b} {d.day}"


def _generic(arguments: dict, data: Any) -> str:
    return "Done"


def _find_customer(arguments: dict, data: Any) -> str:
    people = _as_list(data)
    if not people:
        return f"No customer matches “{arguments.get('query', '')}”"
    names = ", ".join(p["name"] for p in people[:3])
    bikes = sum(len(p.get("bikes", [])) for p in people)
    return f"{names} ({bikes} bike{'s' if bikes != 1 else ''})"


def _get_bike(arguments: dict, data: Any) -> str:
    diffs = data.get("differs_from_catalog_model") or []
    head = f"{data['model']}"
    if diffs:
        changed = "; ".join(f"{d['kind']} {d['this_bike']} (catalog: {d['catalog_model']})" for d in diffs)
        return f"{head}. Differs from catalog: {changed}"
    return f"{head}. Matches its catalog model"


def _check_fit(arguments: dict, data: Any) -> str:
    if data["fits"]:
        notes = data.get("notes") or []
        return f"{data['sku']} fits" + (f", {notes[0].split(': ', 1)[-1]}" if notes else "")
    return f"{data['sku']} doesn't fit: {'; '.join(data['problems'])}"


def _list_fitting_parts(arguments: dict, data: Any) -> str:
    parts = _as_list(data)
    fitting = [p for p in parts if p["fits"]]
    category = arguments.get("category", "part")
    if not fitting:
        return f"No {category} fits ({len(parts)} checked)"
    shown = ", ".join(
        f"{p['sku']} ({p['stock_qty']} in stock)" if p["stock_qty"] else f"{p['sku']} (out of stock)"
        for p in fitting
    )
    return f"{len(fitting)} of {len(parts)} {category}s fit: {shown}"


def _stock_status(arguments: dict, data: Any) -> str:
    return f"{data['sku']}: {data['stock_qty']} in stock" if data["stock_qty"] else f"{data['sku']}: out of stock"


def _list_services(arguments: dict, data: Any) -> str:
    return f"{len(_as_list(data))} labor services"


def _work_order(verb: str):
    def summarize(arguments: dict, data: Any) -> str:
        return f"Work order #{data['work_order_id']} {verb}"
    return summarize


def _add_part(arguments: dict, data: Any) -> str:
    qty = arguments.get("qty", 1)
    return f"{arguments.get('sku')}{f' × {qty}' if qty != 1 else ''} added. Total {_dollars(data['total_cents'])}"


def _add_service(arguments: dict, data: Any) -> str:
    return f"{arguments.get('service_name')} added. Total {_dollars(data['total_cents'])}"


def _lock_quote(arguments: dict, data: Any) -> str:
    return f"Quote locked at {_dollars(data['quoted_total_cents'])}"


def _draft(arguments: dict, data: Any) -> str:
    if data.get("quoted_total_cents") is not None:
        return f"Draft to the Customer, carrying the {_dollars(data['quoted_total_cents'])} quote. Waiting for the Mechanic to send"
    return "Draft to the Customer. Waiting for the Mechanic to send"


def _list_messages(arguments: dict, data: Any) -> str:
    messages = _as_list(data)
    replies = sum(m["direction"] == "from_customer" for m in messages)
    return f"{len(messages)} message{'s' if len(messages) != 1 else ''}, {replies} from the Customer"


def _supplier_options(arguments: dict, data: Any) -> str:
    options = _as_list(data)
    if not options:
        return f"No supplier has {arguments.get('qty', 1)} × {arguments.get('sku')}"
    return " · ".join(
        f"{o['supplier_name']} {_dollars(o['total_cents'])}, {o['lead_time_days']} days" for o in options
    )


def _estimate(arguments: dict, data: Any) -> str:
    suppliers = data.get("suppliers") or []
    via = f" via {', '.join(suppliers)}" if suppliers else ""
    lead = data["lead_time_days"]
    return f"Ready {_short_date(data['ready_date'])}{via} ({lead}-day lead time + 1 repair day)" if lead else \
        f"Ready {_short_date(data['ready_date'])}, parts in stock"


def _plan_order(arguments: dict, data: Any) -> str:
    lines = data.get("lines") or []
    if not lines:
        return "Nothing to order: every part is in stock"
    parts = "; ".join(f"{l['sku']} from {l['supplier']} ({l['lead_time_days']} days, {_dollars(l['total_cents'])})" for l in lines)
    promised = f". Promise: ready {_short_date(data['promised_ready_on'])}" if data.get("promised_ready_on") else ""
    return f"Plan: {parts}{promised}. The shop orders it on approval"


def _purchase_order(arguments: dict, data: Any) -> str:
    supplier = data.get("supplier_name") or f"supplier {data['supplier_id']}"
    return f"Ordered from {supplier}: {_dollars(data['total_cents'])}"


_SUMMARIES = {
    "find_customer": _find_customer,
    "get_bike": _get_bike,
    "check_fit": _check_fit,
    "list_fitting_parts": _list_fitting_parts,
    "stock_status": _stock_status,
    "list_services": _list_services,
    "open_work_order": _work_order("opened"),
    "get_work_order": lambda a, d: f"Work order #{d['work_order_id']}: {d['status'].replace('_', ' ')}",
    "record_diagnosis": _work_order("diagnosis recorded"),
    "add_part": _add_part,
    "add_service": _add_service,
    "lock_quote": _lock_quote,
    "draft_customer_message": _draft,
    "list_customer_messages": _list_messages,
    "supplier_options": _supplier_options,
    "estimate_ready_date": _estimate,
    "plan_order": _plan_order,
    "create_purchase_order": _purchase_order,
}
