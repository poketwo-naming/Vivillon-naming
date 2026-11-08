"""HTTP API that lets the org bot manage reserves in Vivillon."""

import hmac
import json
import logging
import unicodedata
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

logger = logging.getLogger(__name__)


class OrgError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path}") from error


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(path)


def fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).replace("’", "'").casefold().strip()


class OrgReserves:
    """Org reserve list, kept separate from Vivillon's saved reservations."""

    def __init__(
        self,
        path: Path,
        restrictions_path: Path,
        known_names: list[str],
    ) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = load_json(path, [])
        restriction_data = load_json(restrictions_path, {})
        slots = restriction_data.get("slots", {})
        if isinstance(slots, list):
            shared_rule = restriction_data.get("shared", {})
            self.restrictions: dict[str, dict[str, list[str]]] = {
                slot: shared_rule for slot in slots
            }
        else:
            self.restrictions = slots
        self.names: dict[str, str] = {}
        for name in known_names:
            current = self.names.get(fold(name))
            if current is None or current == current.lower():
                self.names[fold(name)] = name

    def canonical_name(self, pokemon: str) -> tuple[str, bool]:
        """Return (display name, all_forms). Raises OrgError if unknown."""
        text = unicodedata.normalize("NFC", pokemon).strip()
        all_forms = False
        if text.casefold().startswith("all "):
            all_forms = True
            text = text[4:].strip()
        canonical = self.names.get(fold(text))
        if canonical is None:
            raise OrgError(404, f"Pokémon not found: {pokemon}")
        return canonical, all_forms

    def check_restriction(self, name: str, slot: str | None) -> None:
        if slot is None:
            return
        rule = self.restrictions.get(slot)
        if rule is None:
            return
        allowed = rule.get("allowed")
        blocked = rule.get("blocked", [])
        if allowed is not None and fold(name) not in {fold(n) for n in allowed}:
            raise OrgError(403, f"{name} is not allowed in slot {slot}")
        if fold(name) in {fold(n) for n in blocked}:
            raise OrgError(403, f"{name} is blocked in slot {slot}")

    def validate(self, pokemon: str, slot: str | None) -> tuple[str, bool]:
        name, all_forms = self.canonical_name(pokemon)
        self.check_restriction(name, slot)
        return name, all_forms

    def add(self, name: str, user_id: int, slot: str | None) -> bool:
        if self.category_owner_for(name, user_id) is not None:
            raise OrgError(409, f"{name} is reserved by another category claim")
        for entry in self.entries:
            if (
                fold(entry["pokemon"]) == fold(name)
                and entry["userId"] == str(user_id)
                and entry.get("slot") == slot
            ):
                return False
        self.entries.append({"pokemon": name, "userId": str(user_id), "slot": slot})
        save_json(self.path, self.entries)
        return True

    def category_owner_for(self, name: str, user_id: int) -> str | None:
        for entry in self.entries:
            if (
                fold(entry["pokemon"]) == fold(name)
                and entry.get("type") == "category"
                and entry["userId"] != str(user_id)
            ):
                return entry["userId"]
        return None

    def has_reservation(self, name: str, user_id: int) -> bool:
        return any(
            fold(entry["pokemon"]) == fold(name)
            and entry["userId"] == str(user_id)
            for entry in self.entries
        )

    def remove(self, name: str, user_id: int, slot: str | None = None) -> bool:
        kept = [
            entry
            for entry in self.entries
            if not (
                fold(entry["pokemon"]) == fold(name)
                and entry["userId"] == str(user_id)
                and entry.get("slot") == slot
                and entry.get("type", "individual") == "individual"
            )
        ]
        removed = len(kept) != len(self.entries)
        if removed:
            self.entries = kept
            save_json(self.path, self.entries)
        return removed

    def reset(self) -> int:
        count = len(self.entries)
        self.entries = []
        save_json(self.path, self.entries)
        return count


def create_app(
    api_key: str,
    org: OrgReserves,
    guild_id: int,
    add_to_vivillon: Callable[[str, int], None],
    remove_from_vivillon: Callable[[str, int], bool],
    categories: Callable[[], dict[str, dict[str, list[str]]]] | None = None,
    add_category_to_vivillon: Callable[[list[str], int], None] | None = None,
    clear_reserves_from_vivillon: Callable[[int], int] | None = None,
    matches_all_forms: Callable[[str, str], bool] | None = None,
) -> web.Application:
    @web.middleware
    async def guard(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path == "/api/org/health":
            return await handler(request)
        # Public static pages (the music Activity) live outside /api/.
        if request.method == "GET" and not request.path.startswith("/api/"):
            return await handler(request)
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {api_key}".encode()):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )
        try:
            return await handler(request)
        except OrgError as error:
            return web.json_response(
                {"success": False, "error": error.message}, status=error.status
            )
        except ValueError as error:
            logger.exception("Org API storage error")
            return web.json_response(
                {"success": False, "error": str(error)}, status=500
            )

    async def body(request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict):
            raise OrgError(400, "Invalid request")
        return data

    def parse_user(data: dict[str, Any]) -> int:
        user_id = data.get("userId")
        if not isinstance(user_id, str) or not user_id.isdigit():
            raise OrgError(400, "Invalid request: userId must be a Discord ID string")
        return int(user_id)

    def parse_pokemon(data: dict[str, Any]) -> str:
        pokemon = data.get("pokemon")
        if not isinstance(pokemon, str) or not pokemon.strip():
            raise OrgError(400, "Invalid request: pokemon must be a string")
        return pokemon

    def parse_slot(data: dict[str, Any]) -> str | None:
        slot = data.get("slot")
        if slot is None:
            return None
        if not isinstance(slot, str):
            raise OrgError(400, "Invalid request: slot must be a string")
        return slot

    def parse_category(data: dict[str, Any]) -> str:
        category = data.get("category")
        if not isinstance(category, str) or not category.strip():
            raise OrgError(400, "Invalid request: category must be a string")
        return category

    def current_categories() -> dict[str, list[str]]:
        if categories is None:
            return {}
        return categories().get(str(guild_id), {})

    async def reserves(request: web.Request) -> web.Response:
        data = await body(request)
        action = data.get("action")
        if action not in {"add", "remove"}:
            raise OrgError(400, "Invalid request: action must be add or remove")
        user_id = parse_user(data)
        slot = parse_slot(data)
        pokemon = parse_pokemon(data)
        if action == "remove" and "slot" not in data:
            raise OrgError(400, "Invalid request: slot is required for removal")
        if action == "add":
            name, all_forms = org.validate(pokemon, slot)
        else:
            name, all_forms = org.canonical_name(pokemon)
        stored = f"All {name}" if all_forms else name
        if action == "add":
            for category_pokemon in current_categories().values():
                for category_name in category_pokemon:
                    category_key = fold(category_name)
                    category_all_forms = category_key.startswith("all ")
                    if category_all_forms:
                        category_key = category_key[4:].strip()
                    if (
                        fold(name) == category_key
                        or (
                            matches_all_forms is not None
                            and (
                                (all_forms and matches_all_forms(category_key, name))
                                or (
                                    category_all_forms
                                    and matches_all_forms(name, category_key)
                                )
                            )
                        )
                    ):
                        raise OrgError(
                            409, f"{stored} belongs to a category and cannot be individually reserved"
                        )
            created = org.add(stored, user_id, slot)
            add_to_vivillon(stored, user_id)
            changed = created
        else:
            changed = org.remove(stored, user_id, slot)
            if not changed:
                raise OrgError(404, f"{stored} is not reserved in that slot for that user")
            if not org.has_reservation(stored, user_id):
                remove_from_vivillon(stored, user_id)
        return web.json_response(
            {
                "success": True,
                "action": action,
                "pokemon": stored,
                "userId": str(user_id),
                "slot": slot,
                "changed": changed,
            }
        )

    async def validate(request: web.Request) -> web.Response:
        data = await body(request)
        name, all_forms = org.validate(parse_pokemon(data), parse_slot(data))
        return web.json_response(
            {
                "success": True,
                "valid": True,
                "pokemon": f"All {name}" if all_forms else name,
            }
        )

    async def list_reserves(request: web.Request) -> web.Response:
        del request
        entries = [
            {
                **entry,
                "slot": entry.get("slot"),
                "type": entry.get("type", "individual"),
            }
            for entry in org.entries
        ]
        return web.json_response(
            {"success": True, "count": len(entries), "reserves": entries}
        )

    async def list_categories(request: web.Request) -> web.Response:
        del request
        available = [
            {"name": name, "pokemon": pokemon, "count": len(pokemon)}
            for name, pokemon in sorted(current_categories().items())
        ]
        return web.json_response(
            {"success": True, "count": len(available), "categories": available}
        )

    async def reserve_category(request: web.Request) -> web.Response:
        data = await body(request)
        category_name = parse_category(data)
        user_id = parse_user(data)
        category_key = fold(category_name)
        category_data = current_categories()
        category_pokemon = next(
            (
                pokemon
                for name, pokemon in category_data.items()
                if fold(name) == category_key
            ),
            None,
        )
        if category_pokemon is None:
            raise OrgError(404, f"Category not found: {category_name}")
        if not category_pokemon:
            raise OrgError(409, f"Category is empty: {category_key}")
        if add_category_to_vivillon is None:
            raise OrgError(503, "Category reservations are not configured")

        names: list[str] = []
        seen_names: set[str] = set()
        for pokemon in category_pokemon:
            name, all_forms = org.canonical_name(pokemon)
            stored = f"All {name}" if all_forms else name
            key = fold(stored)
            if key not in seen_names:
                names.append(stored)
                seen_names.add(key)

        user_key = str(user_id)
        for name in names:
            for entry in org.entries:
                if fold(entry["pokemon"]) != fold(name):
                    continue
                if entry["userId"] != user_key:
                    raise OrgError(409, f"{name} is already reserved by another user")
                if entry.get("type") == "category" and entry.get("category") != category_key:
                    raise OrgError(409, f"{name} is already assigned to another category")

        previous_entries = [dict(entry) for entry in org.entries]
        updated_entries = [dict(entry) for entry in org.entries]
        changed = False
        for name in names:
            existing = next(
                (
                    entry
                    for entry in updated_entries
                    if fold(entry["pokemon"]) == fold(name)
                    and entry["userId"] == user_key
                ),
                None,
            )
            if existing is None:
                updated_entries.append(
                    {
                        "pokemon": name,
                        "userId": user_key,
                        "slot": None,
                        "type": "category",
                        "category": category_key,
                    }
                )
                changed = True
            elif existing.get("type") != "category":
                existing["type"] = "category"
                existing["category"] = category_key
                changed = True

        if changed:
            save_json(org.path, updated_entries)
            try:
                add_category_to_vivillon(names, user_id)
            except Exception:
                try:
                    save_json(org.path, previous_entries)
                except Exception as rollback_error:
                    logger.exception("Could not roll back failed category reservation")
                    raise ValueError(
                        "Category reservation failed and the org reserve list "
                        "could not be rolled back"
                    ) from rollback_error
                raise
            org.entries = updated_entries

        return web.json_response(
            {
                "success": True,
                "category": category_key,
                "userId": user_key,
                "count": len(names),
                "pokemon": names,
                "changed": changed,
            }
        )

    async def reset(request: web.Request) -> web.Response:
        del request
        previous_entries = [dict(entry) for entry in org.entries]
        try:
            cleared_org = org.reset()
        except Exception as error:
            logger.exception("Could not clear Org reserve list")
            raise ValueError("Could not clear Org reserve list") from error
        try:
            cleared_vivillon = (
                clear_reserves_from_vivillon(guild_id)
                if clear_reserves_from_vivillon is not None
                else 0
            )
        except Exception as error:
            try:
                save_json(org.path, previous_entries)
            except Exception as rollback_error:
                logger.exception("Could not roll back failed Org reserve reset")
                raise ValueError(
                    "Reset failed and the Org reserve list could not be restored"
                ) from rollback_error
            org.entries = previous_entries
            logger.exception("Could not clear Vivillon reserve list")
            raise ValueError("Could not clear Vivillon reserve list") from error
        return web.json_response(
            {
                "success": True,
                "cleared": cleared_org,
                "clearedVivillon": cleared_vivillon,
            }
        )

    async def health(request: web.Request) -> web.Response:
        del request
        return web.json_response({"success": True, "status": "ok"})

    app = web.Application(middlewares=[guard])
    app.router.add_get("/api/org/health", health)
    app.router.add_post("/api/org/reserves", reserves)
    app.router.add_post("/api/org/reserves/category", reserve_category)
    app.router.add_post("/api/org/validate", validate)
    app.router.add_get("/api/org/reserves", list_reserves)
    app.router.add_get("/api/org/categories", list_categories)
    app.router.add_post("/api/org/reset", reset)
    app["guild_id"] = guild_id
    return app
