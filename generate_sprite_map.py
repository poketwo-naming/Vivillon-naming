"""Build pokemon_sprites.json: Poketwo name -> PokeAPI pokemon id (for thumbnails)."""

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

import numpy as np

API = "https://pokeapi.co/api/v2/{}?limit=3000"
PREFIX_SUFFIXES = {
    "mega-x": "mega-x",
    "mega-y": "mega-y",
    "mega": "mega",
    "gmax": "gmax",
    "alolan": "alola",
    "galarian": "galar",
    "hisuian": "hisui",
    "paldean": "paldea",
    "primal": "primal",
}
SPRITE_OVERRIDES = {
    "Gmax Toxtricity": 10219,
    "Low-Key Toxtricity": 10184,
    "Pau Oricorio": 10124,
    "Roaming Gimmighoul": 10263,
    "Zygarde": 10118,
}


def fetch_ids(endpoint: str) -> dict[str, int]:
    request = urllib.request.Request(
        API.format(endpoint), headers={"User-Agent": "vivillon-sprite-map"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)["results"]
    return {r["name"]: int(r["url"].rstrip("/").split("/")[-1]) for r in results}


def slug(name: str) -> str:
    name = name.replace("♂", "-m").replace("♀", "-f")
    name = name.replace("’", "").replace("'", "").replace(".", "").replace(":", "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def resolve(name: str, pokemon: dict[str, int], species: dict[str, int]) -> int | None:
    full = slug(name)
    if full in pokemon:
        return pokemon[full]
    words = name.split()
    prefix = slug(words[0])
    rest = slug(" ".join(words[1:]))
    if prefix in PREFIX_SUFFIXES and rest:
        candidate = f"{rest}-{PREFIX_SUFFIXES[prefix]}"
        if candidate in pokemon:
            return pokemon[candidate]
    # Other forms: fall back to the base species, which is named by one word.
    for word in reversed(re.split(r"\s+", name)):
        if slug(word) in species:
            return species[slug(word)]
    return None


def main() -> None:
    root = Path(__file__).parent
    pokemon = fetch_ids("pokemon")
    species = fetch_ids("pokemon-species")
    names = [str(n) for n in np.load(root / "image_bank.npz")["names"]]
    names += json.loads((root / "data" / "pokemon_names.json").read_text(encoding="utf-8"))
    mapping: dict[str, int] = {}
    for name in sorted(set(names)):
        sprite_id = SPRITE_OVERRIDES.get(name)
        if sprite_id is None:
            sprite_id = resolve(name, pokemon, species)
        if sprite_id is None:
            print(f"No sprite for {name}")
        else:
            mapping[name] = sprite_id
    mapping["Gmax Low-Key Toxtricity"] = pokemon["toxtricity-low-key-gmax"]
    (root / "data" / "pokemon_sprites.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=0) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(mapping)} entries")


if __name__ == "__main__":
    main()
