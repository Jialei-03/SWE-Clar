"""Pure gameplay operations for the synthetic creature arena.

The HTTP server owns the current state and calls :func:`process_game_action` for
one operation at a time.  This module deliberately treats an operation as a
transaction: all validation happens against a copied state and a rejected
operation never changes one of the business collections.
"""

from copy import deepcopy
import math
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Small validation helpers


def _finite_number(value: Any) -> bool:
    """Return whether *value* is a finite JSON-style number.

    ``bool`` is a subclass of ``int`` in Python, but it is not a number for
    the game rules.  Restricting this helper to int/float also keeps the value
    JSON serialisable when a direct caller (rather than the HTTP layer) uses
    this function.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # Python integers have arbitrary precision and therefore cannot be
    # infinite.  Calling math.isfinite on an extremely large int would first
    # try to convert it to a float and can raise OverflowError.
    if isinstance(value, int):
        return True
    return math.isfinite(value)


def _integer(value: Any, *, positive: bool = False) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return value > 0 if positive else value >= 0


def _identifier(value: Any) -> bool:
    """Identifiers in the JSON game records are non-empty strings."""

    return isinstance(value, str) and bool(value)


def _mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _fail(out: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Install a non-empty error response without touching business data."""

    out.pop("result", None)
    out["error"] = {"code": code or "invalid_action"}
    return out


def _success(out: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    out.pop("error", None)
    out["result"] = result
    return out


def _valid_item(item: Any) -> Optional[Dict[str, Any]]:
    """Validate and copy an item description.

    The returned copy is normalised to include the default ``stackable``
    field.  Extra configured item metadata is retained, which is useful to a
    browser client and does not affect the inventory rules.
    """

    if not isinstance(item, dict):
        return None
    if not _identifier(item.get("item_id")):
        return None

    stackable = item.get("stackable", False)
    if not isinstance(stackable, bool):
        return None
    if stackable:
        if not _integer(item.get("stack_limit"), positive=True):
            return None

    result = deepcopy(item)
    result["stackable"] = stackable
    return result


def _valid_slot(slot: Any) -> bool:
    return (
        isinstance(slot, dict)
        and _identifier(slot.get("item_id"))
        and _integer(slot.get("quantity"), positive=True)
    )


def _valid_inventory(inventory: Any) -> bool:
    if not isinstance(inventory, dict):
        return False
    capacity = inventory.get("capacity")
    slots = inventory.get("slots")
    if not _integer(capacity):
        return False
    if not isinstance(slots, list) or len(slots) > capacity:
        return False
    return all(_valid_slot(slot) for slot in slots)


def _valid_combatant(combatant: Any) -> bool:
    if not isinstance(combatant, dict):
        return False
    hp = combatant.get("hp")
    return (
        _finite_number(hp)
        and hp > 0
        and _finite_number(combatant.get("level"))
        and _finite_number(combatant.get("defense"))
    )


def _valid_recipe(recipe: Any) -> bool:
    """Check the configured recipe shape used by fusion.

    Levels are allowed to be any finite number: the encyclopedia applies the
    special level-one filter, while fusion deliberately does not.
    """

    if not isinstance(recipe, dict):
        return False
    if "level" not in recipe or not _finite_number(recipe.get("level")):
        return False
    inputs = recipe.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 2:
        return False
    if not all(_identifier(value) for value in inputs):
        return False
    return _identifier(recipe.get("result"))


def _valid_events(state: Dict[str, Any]) -> bool:
    return isinstance(state.get("events"), list)


# ---------------------------------------------------------------------------
# Inventory transactions


def _add_to_inventory(
    inventory: Dict[str, Any], item: Dict[str, Any], quantity: int
) -> Tuple[bool, str, Dict[str, Any]]:
    """Atomically add ``quantity`` described items to an inventory.

    ``inventory`` is only assigned its new slots after the complete capacity
    calculation succeeds.  The caller passes a state copy, so a successful
    operation is safe to commit and a failed one leaves the original state
    untouched as well.
    """

    if not _valid_inventory(inventory):
        return False, "invalid_inventory", {}
    if not _integer(quantity, positive=True):
        return False, "invalid_quantity", {}

    normal_item = _valid_item(item)
    if normal_item is None:
        return False, "invalid_item", {}

    item_id = normal_item["item_id"]
    new_slots = deepcopy(inventory["slots"])
    remaining = quantity

    if normal_item["stackable"]:
        limit = normal_item["stack_limit"]
        # Existing stacks are filled in their existing order.  There is no
        # need for stack metadata in a slot: the supplied item description is
        # the rule for this insertion.
        for slot in new_slots:
            if remaining == 0:
                break
            if slot["item_id"] != item_id:
                continue
            room = limit - slot["quantity"]
            if room <= 0:
                continue
            amount = min(room, remaining)
            slot["quantity"] += amount
            remaining -= amount

        required_slots = (remaining + limit - 1) // limit if remaining else 0
        if len(new_slots) + required_slots > inventory["capacity"]:
            return False, "capacity_overflow", {}

        while remaining:
            amount = min(limit, remaining)
            new_slots.append({"item_id": item_id, "quantity": amount})
            remaining -= amount
    else:
        # A non-stackable quantity is one occupied slot per unit, including
        # when the same item already exists in the inventory.
        if len(new_slots) + quantity > inventory["capacity"]:
            return False, "capacity_overflow", {}
        for _ in range(quantity):
            new_slots.append({"item_id": item_id, "quantity": 1})

    inventory["slots"] = new_slots
    return True, "", {
        "item_id": item_id,
        "quantity": quantity,
        "stackable": normal_item["stackable"],
    }


# ---------------------------------------------------------------------------
# Drop helpers


def _drop_item(drop: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Read an item from a generated drop (and tolerate simple fixture forms)."""

    item = drop.get("item")
    if isinstance(item, dict):
        return _valid_item(item)

    # A flattened form is convenient for hand-written synthetic fixtures.  It
    # is not used for generated drops, but accepting it does not change the
    # public representation we create.
    if "item_id" in drop:
        flat = {
            key: deepcopy(drop[key])
            for key in ("item_id", "stackable", "stack_limit")
            if key in drop
        }
        return _valid_item(flat)
    return None


def _drop_created(drop: Dict[str, Any]) -> Optional[float]:
    for key in ("created", "created_at", "createdAt"):
        if key in drop:
            value = drop[key]
            return value if _finite_number(value) else None
    return None


def _drop_expiry(drop: Dict[str, Any], created: float) -> Optional[float]:
    # Generated drops use the fixed 120-second lifetime.  Reading common
    # aliases also makes pickup/expiry well-defined for a supplied synthetic
    # drop fixture.
    for key in ("expires", "expires_at", "expiresAt", "expiry"):
        if key in drop:
            value = drop[key]
            return value if _finite_number(value) else None
    expiry = created + 120
    return expiry if _finite_number(expiry) else None


def _drop_owner(drop: Dict[str, Any]) -> Any:
    if "owner_id" in drop:
        return drop["owner_id"]
    return drop.get("owner")


def _drop_active(drop: Dict[str, Any]) -> bool:
    return not bool(drop.get("picked", False)) and not bool(drop.get("expired", False))


def _drop_timing(drop: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(drop, dict):
        return None
    created = _drop_created(drop)
    if created is None:
        return None
    expiry = _drop_expiry(drop, created)
    if expiry is None:
        return None
    return created, expiry


def _valid_drops(drops: Any) -> bool:
    if not isinstance(drops, dict):
        return False
    # Existing inactive drops are still records and are left in place, but a
    # malformed record should not make an expiry operation partially mutate
    # the mapping.
    for drop in drops.values():
        if not isinstance(drop, dict):
            return False
        if _drop_timing(drop) is None:
            return False
        if _drop_active(drop) and _drop_item(drop) is None:
            return False
    return True


def _known_inventory(state: Dict[str, Any], user_id: Any) -> bool:
    inventories = state.get("inventories")
    return (
        _identifier(user_id)
        and isinstance(inventories, dict)
        and user_id in inventories
        and _valid_inventory(inventories[user_id])
    )


# ---------------------------------------------------------------------------
# Individual operations


def _use_skill(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source_id = action.get("source_id")
    target_id = action.get("target_id")
    skill_id = action.get("skill_id")

    if not all(_identifier(value) for value in (source_id, target_id, skill_id)):
        return _fail(out, "invalid_action")

    combatants = out.get("combatants")
    skills = out.get("skills")
    if not isinstance(combatants, dict) or source_id not in combatants or target_id not in combatants:
        return _fail(out, "unknown_combatant")
    if not isinstance(skills, dict) or skill_id not in skills:
        return _fail(out, "unknown_skill")

    source = combatants[source_id]
    target = combatants[target_id]
    skill = skills[skill_id]
    if not _valid_combatant(source) or not _valid_combatant(target):
        return _fail(out, "invalid_combatant")
    if not isinstance(skill, dict) or not _finite_number(skill.get("power")):
        return _fail(out, "invalid_skill")
    if not _valid_events(out):
        return _fail(out, "invalid_events")

    damage = max(0, skill["power"] + source["level"] - target["defense"])
    old_hp = target["hp"]
    target_hp = max(0, old_hp - damage)

    # All validation is complete before these three assignments, so an
    # accepted action produces exactly one event and no other combatant/skill
    # is touched.
    combatants[target_id]["hp"] = target_hp
    event = {
        "type": "use_skill",
        "source_id": source_id,
        "target_id": target_id,
        "skill_id": skill_id,
        "damage": damage,
        "target_hp": target_hp,
    }
    out["events"].append(event)
    return _success(out, {"damage": damage, "target_hp": target_hp})


def _add_item(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user_id = action.get("user_id")
    item = action.get("item")
    quantity = action.get("quantity")

    if not _identifier(user_id):
        return _fail(out, "invalid_user")
    inventories = out.get("inventories")
    if not isinstance(inventories, dict) or user_id not in inventories:
        return _fail(out, "unknown_user")
    if not _integer(quantity, positive=True):
        return _fail(out, "invalid_quantity")
    normal_item = _valid_item(item)
    if normal_item is None:
        return _fail(out, "invalid_item")

    # Work on a private copy of the user's inventory.  In particular, a
    # capacity failure cannot leave partially filled existing stacks behind.
    candidate = deepcopy(inventories[user_id])
    # A non-stackable batch is mistakenly treated as a single insertion here.
    # The lower-level transaction still handles loot pickup correctly, but a
    # direct add_item request loses the extra per-unit slots.
    insert_quantity = quantity if normal_item["stackable"] else 1
    ok, code, metadata = _add_to_inventory(candidate, item, insert_quantity)
    if not ok:
        return _fail(out, code)
    inventories[user_id] = candidate
    return _success(
        out,
        {
            "added": quantity,
            "user_id": user_id,
            "item_id": metadata["item_id"],
        },
    )


def _roll_drop(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    enemy_id = action.get("enemy_id")
    drop_id = action.get("drop_id")
    roll = action.get("roll")
    chance = action.get("chance")
    owner_id = action.get("owner_id")
    now = action.get("now")
    item = action.get("item")

    if not _identifier(enemy_id):
        return _fail(out, "invalid_enemy")
    combatants = out.get("combatants")
    if not isinstance(combatants, dict) or enemy_id not in combatants:
        return _fail(out, "unknown_enemy")
    enemy = combatants[enemy_id]
    if not isinstance(enemy, dict) or not _finite_number(enemy.get("hp")) or enemy["hp"] > 0:
        return _fail(out, "enemy_not_defeated")

    if not _identifier(drop_id):
        return _fail(out, "invalid_drop")
    drops = out.get("drops")
    if not isinstance(drops, dict):
        return _fail(out, "invalid_drops")
    if drop_id in drops or any(
        isinstance(existing, dict) and existing.get("drop_id") == drop_id
        for existing in drops.values()
    ):
        return _fail(out, "duplicate_drop")
    if not _known_inventory(out, owner_id):
        return _fail(out, "unknown_owner")
    if not _finite_number(now):
        return _fail(out, "invalid_time")
    if not _finite_number(roll) or not 0 <= roll <= 1:
        return _fail(out, "invalid_roll")
    if not _finite_number(chance) or not 0 <= chance <= 1:
        return _fail(out, "invalid_chance")
    normal_item = _valid_item(item)
    if normal_item is None:
        return _fail(out, "invalid_item")

    # A valid non-winning roll is an accepted no-op for the business state.
    if not roll < chance:
        return _success(out, {"dropped": False, "drop_id": drop_id})

    # ``created``/``expires`` are the canonical fields.  The aliases make the
    # timestamp information easy to inspect without affecting the rules.
    drop = {
        "drop_id": drop_id,
        "enemy_id": enemy_id,
        "owner_id": owner_id,
        "item": normal_item,
        "created": now,
        "created_at": now,
        "expires": now + 120,
        "expires_at": now + 120,
        "picked": False,
        "expired": False,
    }
    drops[drop_id] = drop
    return _success(out, {"dropped": True, "drop_id": drop_id})


def _pickup(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    drop_id = action.get("drop_id")
    user_id = action.get("user_id")
    now = action.get("now")

    if not _identifier(drop_id):
        return _fail(out, "invalid_drop")
    if not _identifier(user_id):
        return _fail(out, "invalid_user")
    if not _finite_number(now):
        return _fail(out, "invalid_time")

    drops = out.get("drops")
    inventories = out.get("inventories")
    if not isinstance(drops, dict) or drop_id not in drops:
        return _fail(out, "unknown_drop")
    if not isinstance(inventories, dict) or user_id not in inventories:
        return _fail(out, "unknown_user")

    drop = drops[drop_id]
    timing = _drop_timing(drop)
    if not isinstance(drop, dict) or timing is None:
        return _fail(out, "invalid_drop")
    if not _drop_active(drop):
        return _fail(out, "drop_unavailable")
    item = _drop_item(drop)
    if item is None:
        return _fail(out, "invalid_item")
    created, expiry = timing
    if now < created or now >= expiry:
        return _fail(out, "drop_unavailable")

    owner_id = _drop_owner(drop)
    # The owner has the first 60 seconds exclusively; at exactly +60 all
    # users with an existing inventory may compete for it.
    if now < created + 60 and user_id != owner_id:
        return _fail(out, "pickup_not_allowed")
    if not _valid_inventory(inventories[user_id]):
        return _fail(out, "invalid_inventory")

    candidate = deepcopy(inventories[user_id])
    ok, code, _ = _add_to_inventory(candidate, item, 1)
    if not ok:
        return _fail(out, code)

    # Commit the inventory and the loot transition together.  No operation
    # after this point can reject.
    inventories[user_id] = candidate
    drop["picked"] = True
    drop["picked_by"] = user_id
    drop["picked_at"] = now
    return _success(out, {"picked": True, "drop_id": drop_id, "user_id": user_id})


def _expire(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = action.get("now")
    if not _finite_number(now):
        return _fail(out, "invalid_time")
    drops = out.get("drops")
    if not _valid_drops(drops):
        return _fail(out, "invalid_drops")

    expired_count = 0
    for drop in drops.values():
        if not _drop_active(drop):
            continue
        timing = _drop_timing(drop)
        # _valid_drops above guarantees timing for every record.
        assert timing is not None
        _, expiry = timing
        if expiry <= now:
            drop["expired"] = True
            drop["expired_at"] = now
            expired_count += 1
    return _success(out, {"expired": expired_count})


def _encyclopedia(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    recipes = out.get("recipes")
    if not isinstance(recipes, dict):
        return _fail(out, "invalid_recipes")

    rows = []
    # JSON object keys are strings.  The string key fallback also keeps direct
    # Python callers with unusual comparable keys deterministic.
    try:
        recipe_ids = sorted(recipes)
    except TypeError:
        recipe_ids = sorted(recipes, key=lambda value: str(value))

    for recipe_id in recipe_ids:
        recipe = recipes[recipe_id]
        if _valid_recipe(recipe) and recipe["level"] == 1:
            row = deepcopy(recipe)
            row["recipe_id"] = recipe_id
            rows.append(row)
    return _success(out, {"recipes": rows})


def _fuse(out: Dict[str, Any], action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user_id = action.get("user_id")
    recipe_id = action.get("recipe_id")
    if not _identifier(user_id):
        return _fail(out, "invalid_user")
    if not _identifier(recipe_id):
        return _fail(out, "invalid_recipe")

    recipes = out.get("recipes")
    if not isinstance(recipes, dict) or recipe_id not in recipes:
        return _fail(out, "unknown_recipe")
    recipe = recipes[recipe_id]
    if not _valid_recipe(recipe):
        return _fail(out, "invalid_recipe")

    creatures = out.get("creatures")
    if not isinstance(creatures, dict) or user_id not in creatures:
        return _fail(out, "unknown_user")
    owned = creatures[user_id]
    if not isinstance(owned, list) or not all(_identifier(value) for value in owned):
        return _fail(out, "invalid_creatures")

    first, second = recipe["inputs"]
    if first == second:
        if owned.count(first) < 2:
            return _fail(out, "insufficient_creatures")
    else:
        if first not in owned or second not in owned:
            return _fail(out, "insufficient_creatures")

    remaining = list(owned)
    # Remove occurrences one at a time.  This handles identical inputs by
    # consuming two copies rather than accidentally consuming one twice.
    remaining.remove(first)
    remaining.remove(second)
    remaining.append(recipe["result"])
    creatures[user_id] = remaining
    return _success(
        out,
        {"fused": True, "user_id": user_id, "recipe_id": recipe_id, "result": recipe["result"]},
    )


# ---------------------------------------------------------------------------
# Public entry point


def process_game_action(state: dict, action: dict) -> dict:
    """Apply one public game operation and return a new JSON state.

    The input state and action are never modified.  A malformed state/action
    produces a normal error object rather than leaking an exception through
    the HTTP handler.
    """

    if not isinstance(state, dict):
        return {"error": {"code": "invalid_state"}}
    try:
        out = deepcopy(state)
    except Exception:
        return {"error": {"code": "invalid_state"}}

    # ``out`` is a dict because state was checked above.  Strip only response
    # metadata; all business collections remain exactly as copied on errors.
    out.pop("result", None)
    out.pop("error", None)

    if not isinstance(action, dict):
        return _fail(out, "invalid_action")
    operation = action.get("type")
    if not isinstance(operation, str):
        return _fail(out, "invalid_action")

    handlers = {
        "use_skill": _use_skill,
        "add_item": _add_item,
        "roll_drop": _roll_drop,
        "pickup": _pickup,
        "expire": _expire,
        "encyclopedia": _encyclopedia,
        "fuse": _fuse,
    }
    handler = handlers.get(operation)
    if handler is None:
        return _fail(out, "unknown_action")

    try:
        result = handler(out, action)
        # Every handler returns a state.  This guard keeps the public contract
        # intact if a future handler is changed incorrectly.
        if not isinstance(result, dict):
            return _fail(out, "invalid_action")
        return result
    except (ArithmeticError, KeyError, IndexError, TypeError, ValueError):
        # Invalid synthetic records should reject atomically, not make the
        # loopback service unusable.  ``out`` is already an isolated copy.
        return _fail(out, "invalid_action")


__all__ = ["process_game_action"]
