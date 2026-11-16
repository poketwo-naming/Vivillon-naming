"""Build image_bank.npz from the pictures in pokemon_images/.

Run this where the pictures are (not on the host):
    python build_image_bank.py [pokemon_images_folder] [output_file]
    python build_image_bank.py [pokemon_images_folder] [output_file] --merge-existing image_bank.npz

Per-Pokémon results are cached in .bank_cache/, so after adding or changing a
Pokémon only that one is recomputed. The merge option preserves existing
features and adds labels that are new to the existing bank.
"""

import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np

from image_match import (
    family_name,
    BANK_FILE,
    FEATURES_PER_IMAGE,
    MAX_SIDE,
    MAX_FEATURES_PER_POKEMON,
    SHARED_DISTANCE,
    compute_descriptors,
    consensus_descriptors,
    drop_duplicates,
    foreground_mask,
    reference_images,
)

import cv2


def signature(paths: list[Path]) -> str:
    digest = hashlib.sha1()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(str(path.stat().st_size).encode())
    return digest.hexdigest()


BACKGROUND_SAMPLE = 120

# Scraped pictures whose scenery is shared between pictures and would be learned
# as part of the Pokémon (Swinub's snow forest made it name every snowy spawn).
EXCLUDED_REFERENCES = {"Swinub": {"7.png", "13.png"}, "Snom": {"7.png"}}

# User-confirmed labels for identical files that appear under multiple names.
CONFIRMED_EXACT_REFERENCE_NAMES = {
    "a7a9d5a7bdc0e6ba1fb05c3a2c6d62a9beb42b095e59a11601ef5be2a8c7d2a2": "Fire Arceus",
    "a5b5ce41c65496c1fc6ced76b8a1a729893725e729ebc5ad0342e9239da7ac60": "Fire Arceus",
    "05147a992a64a1dd813d0449c7f5607e2771d9d8fac0353c8629dae2fbe6213c": "Gliding Build Koraidon",
    "91506c902788fe9770f7228496599465e6a9ffacd4abcc87069e2bdfee60150f": "Steel Silvally",
}

logger = logging.getLogger(__name__)


def exact_reference_index(
    groups: dict[str, list[Path]], names: list[str], *, include_all: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    indices = {name: index for index, name in enumerate(names)}
    owners: dict[str, str] = {}
    conflicts: set[str] = set()
    confirmed: set[str] = set()
    for name, paths in groups.items():
        for path in paths:
            if not include_all and not path.name.startswith("user-reference-"):
                continue
            data = path.read_bytes()
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError(f"Cannot decode exact reference image {path}")
            digest = hashlib.sha256(data).hexdigest()
            if CONFIRMED_EXACT_REFERENCE_NAMES.get(digest) == name:
                confirmed.add(digest)
            previous = owners.get(digest)
            if previous is not None and previous != name:
                conflicts.add(digest)
            else:
                owners[digest] = name
    for digest in conflicts:
        if digest in confirmed:
            owners[digest] = CONFIRMED_EXACT_REFERENCE_NAMES[digest]
        else:
            del owners[digest]
    unresolved = len(conflicts - confirmed)
    if unresolved:
        logger.warning("Excluded %d exact references with conflicting names", unresolved)
    if conflicts & confirmed:
        logger.info("Resolved %d exact references using confirmed labels", len(conflicts & confirmed))
    hashes = sorted(owners)
    return (
        np.array(hashes, dtype="U64"),
        np.array([indices[owners[digest]] for digest in hashes], dtype=np.int32),
    )


def background_pool(folder: Path, exclude: set[str]):
    """Raw features of many other Pokémon's pictures, mostly scenery."""
    numbered = sorted(
        path
        for path in folder.rglob("*.png")
        if path.stem.isdigit() and path.parent.name not in exclude
    )
    step = max(1, len(numbered) // BACKGROUND_SAMPLE)
    sets = [
        found
        for found in (compute_descriptors(p.read_bytes()) for p in numbered[::step])
        if found is not None
    ]
    return np.vstack(sets).astype(np.float32)


def remove_background(descriptors, pool):
    matcher = cv2.BFMatcher()
    keep = np.ones(len(descriptors), bool)
    for position, pair in enumerate(matcher.knnMatch(descriptors, pool, k=1)):
        if pair and pair[0].distance < SHARED_DISTANCE:
            keep[position] = False
    return descriptors[keep]


def pokemon_features(
    name: str,
    paths: list[Path],
    cache: Path,
    pool=None,
):
    cache_file = cache / f"{hashlib.sha1(name.encode()).hexdigest()}.npz"
    wanted = (
        f"{signature(paths)}-{FEATURES_PER_IMAGE}-{MAX_SIDE}-fg2"
    )
    if cache_file.is_file():
        with np.load(cache_file) as data:
            if str(data["signature"]) == wanted:
                return data["descriptors"]
    sets = []
    extra = []
    for path in paths:
        data = path.read_bytes()
        found = compute_descriptors(
            data,
            mask=None if path.stem.isdigit() else foreground_mask(data),
        )
        if found is None or len(found) < 2:
            found = None
        if found is None:
            continue
        # Hand-added pictures (not the numbered scraped ones) are a different
        # render, so they can't pass the repeat check; keep all their features.
        if path.stem.isdigit():
            sets.append(found)
        else:
            extra.append(remove_background(found, pool) if pool is not None else found)
    parts = ([consensus_descriptors(sets)] if sets else [])
    parts.extend(extra)
    if not parts:
        return np.zeros((0, 128), np.float32)
    descriptors = drop_duplicates(np.vstack(parts))
    np.savez(cache_file, signature=wanted, descriptors=descriptors)
    return descriptors


def assemble_bank(names: list[str], per_pokemon: dict):
    """Combine per-Pokémon features into (descriptors uint8, labels)."""
    # Features that look the same in other Pokémon are background, so drop them.
    compact = {
        name: descriptors[
            np.linspace(0, len(descriptors) - 1, MAX_FEATURES_PER_POKEMON).astype(int)
        ] if len(descriptors) > MAX_FEATURES_PER_POKEMON else descriptors
        for name, descriptors in list(per_pokemon.items())
    }
    per_pokemon.clear()
    everything = np.vstack(list(compact.values())).astype(np.float32)
    owner = np.concatenate(
        [np.full(len(compact[name]), i) for i, name in enumerate(names)]
    )
    cv2.setRNGSeed(0)
    matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=32))
    matcher.add([everything])
    matcher.train()
    families = [family_name(name) for name in names]
    kept_descriptors, kept_labels = [], []
    for index, name in enumerate(names):
        features = compact[name].astype(np.float32)
        if len(features) == 0:
            continue
        keep = np.ones(len(features), bool)
        for position, neighbours in enumerate(matcher.knnMatch(features, k=6)):
            for neighbour in neighbours:
                if (
                    families[owner[neighbour.trainIdx]] != families[index]
                    and neighbour.distance < SHARED_DISTANCE
                ):
                    keep[position] = False
                    break
        features = features[keep]
        if len(features) > MAX_FEATURES_PER_POKEMON:
            chosen = np.linspace(0, len(features) - 1, MAX_FEATURES_PER_POKEMON).astype(int)
            features = features[chosen]
        kept_descriptors.append(features)
        kept_labels.append(np.full(len(features), index))

    descriptors = np.vstack(kept_descriptors)
    return (
        np.clip(np.rint(descriptors), 0, 255).astype(np.uint8),
        np.concatenate(kept_labels).astype(np.int32),
    )


def merge_existing_bank(
    descriptors: np.ndarray,
    labels: np.ndarray,
    names: list[str],
    exact_hashes: np.ndarray,
    exact_labels: np.ndarray,
    existing_bank: Path,
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray, np.ndarray]:
    with np.load(existing_bank) as bank:
        old_descriptors = bank["descriptors"].copy()
        old_labels = bank["labels"].copy()
        old_names = bank["names"].tolist()
        old_exact_hashes = bank["exact_hashes"].copy()
        old_exact_labels = bank["exact_labels"].copy()

    rebuilt_indices = {name: index for index, name in enumerate(names)}
    old_names_set = set(old_names)
    merged_names = old_names + [name for name in names if name not in old_names_set]
    merged_name_indices = {name: index for index, name in enumerate(merged_names)}
    feature_parts = []
    label_parts = []

    for index in range(len(old_names)):
        features = old_descriptors[old_labels == index]
        feature_parts.append(features)
        label_parts.append(np.full(len(features), index, dtype=np.int32))

    for name in merged_names[len(old_names) :]:
        rebuilt_index = rebuilt_indices[name]
        features = descriptors[labels == rebuilt_index]
        feature_parts.append(features)
        label_parts.append(
            np.full(len(features), merged_name_indices[name], dtype=np.int32)
        )

    merged_descriptors = np.vstack(feature_parts)
    merged_labels = np.concatenate(label_parts)

    owners: dict[str, str | None] = {}
    for bank_names, hashes, indices in (
        (old_names, old_exact_hashes, old_exact_labels),
        (names, exact_hashes, exact_labels),
    ):
        for digest, index in zip(hashes.tolist(), indices.tolist()):
            name = bank_names[int(index)]
            if digest not in owners:
                owners[digest] = name
            elif owners[digest] != name:
                owners[digest] = None

    valid_exact_references = sorted(
        (digest, name) for digest, name in owners.items() if name is not None
    )
    merged_hashes = [digest for digest, _ in valid_exact_references]
    return (
        merged_descriptors,
        merged_labels,
        merged_names,
        np.array(merged_hashes, dtype="U64"),
        np.array(
            [merged_name_indices[name] for _, name in valid_exact_references],
            dtype=np.int32,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default="pokemon_images")
    parser.add_argument("output", nargs="?", default=BANK_FILE)
    parser.add_argument(
        "--merge-existing",
        type=Path,
        metavar="BANK",
        help="preserve BANK's features and add only newly encountered Pokémon labels",
    )
    parser.add_argument(
        "--index-all-references",
        action="store_true",
        help="index every labelled reference image for exact-byte matching",
    )
    args = parser.parse_args()
    folder = Path(args.folder)
    output = Path(args.output)
    cache = Path(".bank_cache")
    cache.mkdir(exist_ok=True)

    groups = reference_images(folder)
    if not groups:
        sys.exit(f"No pictures found in {folder}")
    pool = None
    if any(not path.stem.isdigit() for paths in groups.values() for path in paths):
        print("Building background pool for hand-added pictures...", flush=True)
        pool = background_pool(folder, set())
    for name, excluded in EXCLUDED_REFERENCES.items():
        if name in groups:
            groups[name] = [p for p in groups[name] if p.name not in excluded]
    names = sorted(groups)
    per_pokemon = {}
    for number, name in enumerate(names, 1):
        per_pokemon[name] = pokemon_features(
            name,
            [path for path in groups[name] if not path.name.startswith("user-reference-")],
            cache,
            pool,
        )
        if number == 1 or number % 25 == 0 or number == len(names):
            print(f"[{number}/{len(names)}] {name}: {len(per_pokemon[name])} features", flush=True)

    descriptors, labels = assemble_bank(names, per_pokemon)
    exact_hashes, exact_labels = exact_reference_index(
        groups, names, include_all=args.index_all_references
    )
    if args.merge_existing is not None:
        reference_names = names
        reference_hashes = exact_hashes
        reference_labels = exact_labels
        descriptors, labels, names, exact_hashes, exact_labels = merge_existing_bank(
            descriptors,
            labels,
            names,
            exact_hashes,
            exact_labels,
            args.merge_existing,
        )
        if args.index_all_references:
            merged_indices = {name: index for index, name in enumerate(names)}
            exact_hashes = reference_hashes
            exact_labels = np.array(
                [merged_indices[reference_names[index]] for index in reference_labels],
                dtype=np.int32,
            )
    np.savez_compressed(
        output,
        descriptors=descriptors,
        labels=labels,
        names=np.array(names),
        exact_hashes=exact_hashes,
        exact_labels=exact_labels,
    )
    print(f"Wrote {output}: {len(names)} Pokémon, {len(descriptors)} features")


if __name__ == "__main__":
    main()
