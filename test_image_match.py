import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import TypeVar
from unittest.mock import Mock, patch

import image_match
from image_match import ImageMatcher, compute_descriptors, reference_images


T = TypeVar("T")


def require_match(value: T | None) -> T:
    if value is None:
        raise AssertionError("Expected the image matcher to return a result")
    return value


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class ImageMatcherTests(unittest.TestCase):
    def test_exact_reference_does_not_match_another_image(self) -> None:
        np = image_match.np
        image = b"trusted reference bytes"
        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=np.random.default_rng(42).random((8, 128), dtype=np.float32),
                labels=np.zeros(8, dtype=np.int32),
                names=np.array(["Pikachu"]),
                exact_hashes=np.array([hashlib.sha256(image).hexdigest()]),
                exact_labels=np.array([0], dtype=np.int32),
            )
            matcher = ImageMatcher(bank_path)
            with patch.object(matcher, "_transparency_mask", return_value=None):
                with patch("image_match.compute_descriptors", return_value=None):
                    with patch("image_match.foreground_mask", return_value=None):
                        self.assertEqual(matcher.match(image), ("Pikachu", 0))
                        self.assertIsNone(matcher.match(b"different image bytes"))

    def test_conflicting_exact_references_are_not_indexed(self) -> None:
        from build_image_bank import exact_reference_index

        cv2 = image_match.cv2
        np = image_match.np
        encoded = cv2.imencode(".png", np.zeros((16, 16, 3), dtype=np.uint8))[1].tobytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "Pikachu" / "user-reference-one.png"
            second = root / "Eevee" / "user-reference-two.png"
            for path in (first, second):
                path.parent.mkdir()
                path.write_bytes(encoded)
            hashes, labels = exact_reference_index(
                {"Pikachu": [first], "Eevee": [second]},
                ["Pikachu", "Eevee"],
            )
        self.assertEqual(len(hashes), 0)
        self.assertEqual(len(labels), 0)

    def test_shared_screenshot_species_use_lower_vote_floor(self) -> None:
        for name in (
            "White-Plumage Squawkabilly",
            "Wiglett",
            "Lotad",
            "Dreepy",
            "Ditto",
        ):
            with self.subTest(name=name):
                self.assertEqual(image_match.minimum_votes_for(name), 4)

    def test_normal_deoxys_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "deoxys-normal" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Deoxys"])

    def test_ordinary_keldeo_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "keldeo-ordinary" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Keldeo"])

    def test_land_shaymin_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "shaymin-land" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Shaymin"])

    def test_gastrodon_east_sea_folder_uses_east_sea_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("Gastrodon East sea", "East Sea Gastrodon"):
                image_path = root / folder / "image.png"
                image_path.parent.mkdir()
                image_path.write_bytes(b"")

            groups = reference_images(root)

        self.assertEqual(list(groups), ["East Sea Gastrodon"])
        self.assertEqual(len(groups["East Sea Gastrodon"]), 2)

    def test_kilowattrel_artwork_matches_common_image_variations(self) -> None:
        root = Path(__file__).with_name("pokemon_images") / "Kilowattrel"
        image = image_match.cv2.imread(
            str(root / "spawn-reference-2026-11-13.png"),
            image_match.cv2.IMREAD_UNCHANGED,
        )
        self.assertIsNotNone(image)
        variations = (
            (".png", image_match.cv2.flip(image, 1)),
            (".png", image_match.cv2.resize(image, None, fx=0.75, fy=0.75)),
            (".jpg", image_match.cv2.cvtColor(image, image_match.cv2.COLOR_BGRA2BGR)),
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for extension, variation in variations:
            with self.subTest(extension=extension, shape=variation.shape):
                success, encoded = image_match.cv2.imencode(extension, variation)
                self.assertTrue(success)
                result = require_match(matcher.match(encoded.tobytes()))
                self.assertEqual(result[0], "Kilowattrel")

    def test_nidoran_gendered_reference_names_stay_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in (
                "nidoran-f",
                "nidoran-m",
                "nidoran-female",
                "nidoran-male",
                "Nidoran♀",
                "Nidoran♂",
                "nidoran-valentine",
            ):
                image_path = root / folder / "1.png"
                image_path.parent.mkdir()
                image_path.write_bytes(b"")

            groups = reference_images(root)

        self.assertEqual(len(groups["Nidoran♀"]), 3)
        self.assertEqual(len(groups["Nidoran♂"]), 3)
        self.assertNotIn("Nidoran-Valentine", groups)

    def test_archived_nidoran_genders_match_their_own_references(self) -> None:
        root = Path(__file__).with_name("pokemon_images")
        groups = reference_images(root)
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        for name, folder in (("Nidoran♀", "nidoran-f"), ("Nidoran♂", "nidoran-m")):
            with self.subTest(name=name):
                references = [path for path in groups[name] if path.parent.name == folder]
                self.assertTrue(references)
                result = matcher.match(references[0].read_bytes())
                result = require_match(result)
                self.assertEqual(result[0], name)

    def test_user_east_shellos_reference_matches_as_east_shellos(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "East Shellos"
            / "spawn-reference.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "East Shellos")

    def test_bonsly_recent_spawn_matches_in_both_orientations(self) -> None:
        import cv2

        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Bonsly"
            / "actual-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Bonsly")

    def test_trubbish_mislabeled_as_bonsly_matches_in_both_orientations(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        root = Path(__file__).with_name("pokemon_images") / "Trubbish"
        for filename in ("spawn-reference.png", "spawn-screenshot-2026-11-13.png"):
            image = image_match.cv2.imread(str(root / filename))
            image = require_match(image)
            for candidate in (image, image_match.cv2.flip(image, 1)):
                with self.subTest(filename=filename, mirrored=candidate is not image):
                    success, buffer = image_match.cv2.imencode(".png", candidate)
                    self.assertTrue(success)
                    result = require_match(matcher.match(buffer.tobytes()))
                    self.assertEqual(result[0], "Trubbish")

    def test_hippopotas_recent_spawn_matches_in_both_orientations(self) -> None:
        import cv2

        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Hippopotas"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Hippopotas")

    def test_wiglett_spawn_reference_matches_as_wiglett(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Wiglett"
            / "spawn-reference.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Wiglett")

    def test_wiglett_user_screenshot_matches_as_wiglett(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Wiglett"
            / "spawn-reference-2.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Wiglett")

    def test_wiglett_unnamed_spawn_matches_as_wiglett(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Wiglett"
            / "spawn-reference-3.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Wiglett")

    def test_wiglett_recent_spawn_matches_in_both_orientations(self) -> None:
        import cv2

        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Wiglett"
            / "spawn-reference-4.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Wiglett")

    def test_sunkern_spawn_reference_matches_as_sunkern(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Sunkern"
            / "spawn-reference.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Sunkern")

    def test_shroodle_spawn_reference_matches_as_shroodle(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Shroodle"
            / "spawn-reference.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Shroodle")

    def test_sandygast_spawn_reference_matches_as_sandygast(self) -> None:
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Sandygast"
            / "spawn-reference.png"
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))

        result = matcher.match(image_path.read_bytes())

        result = require_match(result)
        self.assertEqual(result[0], "Sandygast")

    def test_rapid_strike_urshifu_reference_uses_spaced_form_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "urshifu-rapid-strike" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Rapid Strike Urshifu"])

    def test_confined_hoopa_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "hoopa" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Hoopa"])

    def test_koraidon_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for folder in ("Koraidon", "Koraidon Build"):
                image_path = Path(directory) / folder / "image.png"
                image_path.parent.mkdir()
                image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Koraidon"])
        self.assertEqual(len(groups["Koraidon"]), 2)

    def test_pumpkaboo_size_and_costume_references_use_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in (
                "Pumpkaboo",
                "pumpkaboo-average",
                "pumpkaboo-small",
                "pumpkaboo-large",
                "pumpkaboo-super",
                "pumpkaboo-autumn",
            ):
                image_path = root / folder / "1.png"
                image_path.parent.mkdir()
                image_path.write_bytes(b"")

            groups = reference_images(root)

        self.assertEqual(list(groups), ["Pumpkaboo"])
        self.assertEqual(len(groups["Pumpkaboo"]), 6)

    def test_power_construct_zygarde_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "zygarde-10-power-construct" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Zygarde"])

    def test_incarnate_tornadus_reference_uses_species_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "tornadus-incarnate" / "1.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"")

            groups = reference_images(Path(directory))

        self.assertEqual(list(groups), ["Tornadus"])

    def test_paldean_tauros_match_is_reported_as_tauros(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(5).integers(0, 256, (256, 256), dtype=np.uint8)
        encoded = require_match(cv2.imencode(".png", image)[1])
        descriptors = require_match(compute_descriptors(encoded.tobytes()))

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Paldean Tauros"]),
            )
            result = require_match(ImageMatcher(bank_path).match(encoded.tobytes()))

        self.assertEqual(result[0], "Tauros")

    def test_mimikyu_and_morpeko_forms_are_reported_by_species_name(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(6).integers(0, 256, (256, 256), dtype=np.uint8)
        encoded = cv2.imencode(".png", image)[1].tobytes()
        descriptors = require_match(compute_descriptors(encoded))

        for form_name in (
            "Busted Mimikyu",
            "Disguised Mimikyu",
            "Totem-Busted Mimikyu",
            "Totem-Disguised Mimikyu",
            "Full-Belly Morpeko",
        ):
            with self.subTest(form_name=form_name), tempfile.TemporaryDirectory() as directory:
                bank_path = Path(directory) / "image_bank.npz"
                np.savez(
                    bank_path,
                    descriptors=descriptors,
                    labels=np.zeros(len(descriptors), dtype=np.int32),
                    names=np.array([form_name]),
                )
                result = require_match(ImageMatcher(bank_path).match(encoded))

            self.assertEqual(result[0], form_name.split()[-1])

    def test_matches_reference_when_spawn_image_is_flipped(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.random.default_rng(17).integers(0, 256, (256, 256), dtype=np.uint8)
        encoded = cv2.imencode(".png", image)[1].tobytes()
        flipped = cv2.imencode(".png", cv2.flip(image, 1))[1].tobytes()
        descriptors = compute_descriptors(encoded)
        descriptors = require_match(descriptors)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Pikachu"]),
            )
            matcher = ImageMatcher(bank_path)

            result = matcher.match(flipped)
            result = require_match(result)
            self.assertEqual(result[0], "Pikachu")

    def test_small_known_spawn_images_match_in_both_orientations(self) -> None:
        cv2 = image_match.cv2
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        root = Path(__file__).with_name("pokemon_images")
        for name, filename in (
            ("Oddish", "spawn-screenshot-2026-11-07.png"),
            ("Wiglett", "bulbasaur-example-6.png"),
            ("Spheal", "bulbasaur-example-big-3.png"),
        ):
            image = require_match(cv2.imread(str(root / name / filename)))
            height, width = image.shape[:2]
            scale = 240 / max(height, width)
            image = cv2.resize(
                image, (round(width * scale), round(height * scale)),
                interpolation=cv2.INTER_AREA,
            )
            for mirror in (False, True):
                with self.subTest(pokemon=name, mirrored=mirror):
                    candidate = cv2.flip(image, 1) if mirror else image
                    success, encoded = cv2.imencode(".png", candidate)
                    self.assertTrue(success)
                    result = require_match(matcher.match(encoded.tobytes()))
                    self.assertEqual(result[0], name)

    def test_reduced_exact_reference_is_not_a_different_clear_match(self) -> None:
        cv2 = image_match.cv2
        path = (
            Path(__file__).with_name("pokemon_images")
            / "Toedscool"
            / "user-reference-2026-11-07.png"
        )
        image = require_match(cv2.imread(str(path)))
        height, width = image.shape[:2]
        scale = 240 / max(height, width)
        image = cv2.resize(
            image, (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for mirror in (False, True):
            with self.subTest(mirrored=mirror):
                candidate = cv2.flip(image, 1) if mirror else image
                success, encoded = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(encoded.tobytes())
                if result is not None:
                    self.assertEqual(result[0], "Toedscool")

    def test_small_image_retry_preserves_vote_thresholds(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.zeros((120, 240, 3), dtype=np.uint8)
        encoded = cv2.imencode(".png", image)[1].tobytes()
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        with patch.object(matcher, "_match", return_value=None) as vote_match:
            self.assertIsNone(matcher.match(encoded))

        self.assertTrue(vote_match.called)
        self.assertTrue(all(not call.kwargs.get("allow_weak") for call in vote_match.call_args_list))

    def test_foreground_retry_cannot_reclassify_boldore_or_milcery(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(23).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Milcery", "Boldore"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(
                    matcher,
                    "_match",
                    side_effect=[("Milcery", 46), None],
                ),
                patch("image_match.foreground_mask") as mask,
            ):
                result = matcher.match(b"spawn image")

        self.assertEqual(result, ("Milcery", 46))
        mask.assert_not_called()

    def test_opaque_png_uses_foreground_segmentation(self) -> None:
        cv2 = image_match.cv2
        np = image_match.np
        image = np.zeros((256, 256, 4), dtype=np.uint8)
        image[..., :3] = (30, 180, 30)
        image[..., 3] = 255
        cv2.rectangle(image, (80, 60), (175, 205), (30, 30, 220, 255), -1)
        encoded = cv2.imencode(".png", image)[1].tobytes()

        mask = image_match.foreground_mask(encoded)

        mask = require_match(mask)
        self.assertTrue(np.any(mask == 0))
        self.assertTrue(np.any(mask == 255))

    def test_relaxed_match_rejects_weak_shellos_false_positive(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(25).random((2, 128), dtype=np.float32)
        neighbours = [
            [Mock(trainIdx=0, distance=10), Mock(trainIdx=1, distance=20)]
            for _ in range(5)
        ]

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.array([0, 1], dtype=np.int32),
                names=np.array(["Shellos", "Bellossom"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch(
                    "image_match.compute_descriptors",
                    return_value=np.zeros((5, 128), dtype=np.float32),
                ),
                patch.object(matcher, "matcher", Mock()) as image_matcher,
            ):
                image_matcher.knnMatch.return_value = neighbours
                result = matcher._match(b"spawn image", False, relaxed=True)
                fallback = matcher.best_guess(b"spawn image")

        self.assertIsNone(result)
        self.assertEqual(fallback, ("Shellos", 5))

    def test_shellos_requires_more_votes_than_a_weak_goomy_lookalike(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(26).random((2, 128), dtype=np.float32)
        neighbours = [
            [Mock(trainIdx=0, distance=10), Mock(trainIdx=1, distance=20)]
            for _ in range(6)
        ]

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.array([0, 1], dtype=np.int32),
                names=np.array(["Shellos", "Goomy"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch(
                    "image_match.compute_descriptors",
                    return_value=np.zeros((6, 128), dtype=np.float32),
                ),
                patch.object(matcher, "matcher", Mock()) as image_matcher,
            ):
                image_matcher.knnMatch.return_value = neighbours
                results = [
                    matcher._match(b"spawn image", False, relaxed=relaxed)
                    for relaxed in (False, True)
                ]

        self.assertEqual(results, [None, None])

    def test_palafin_finizen_match_is_kept_when_patch_is_not_detected(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(24).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Finizen", "Palafin"]),
            )
            matcher = ImageMatcher(bank_path)

            for name in ("Finizen", "Palafin"):
                with (
                    self.subTest(name=name),
                    patch.object(
                        matcher,
                        "_match",
                        side_effect=[(name, 20), (name, 18)],
                    ),
                    patch(
                        "image_match.has_belly_patch",
                        return_value=name == "Palafin",
                    ),
                ):
                    result = matcher.match(b"spawn image")
                self.assertEqual(result, (name, 20))

    def test_finizen_spawn_reference_matches_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        path = (
            Path(__file__).with_name("pokemon_images")
            / "Finizen"
            / "bulbasaur-example-1.png"
        )
        image = cv2.imread(str(path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, encoded = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(encoded.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Finizen")

    def test_palafin_spawn_reference_matches_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        path = (
            Path(__file__).with_name("pokemon_images")
            / "Palafin"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, encoded = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(encoded.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Palafin")

    def test_vivillon_match_requires_a_valid_pattern_alignment(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(24).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Vivillon"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(matcher, "_match", side_effect=[("Vivillon", 20), None]),
                patch("image_match.vivillon_form_by_pattern", return_value=None),
            ):
                result = matcher.match(b"unrelated spawn image")

        self.assertIsNone(result)

    def test_invalid_vivillon_match_does_not_hide_a_second_species_match(self) -> None:
        np = image_match.np
        descriptors = np.random.default_rng(25).random((8, 128), dtype=np.float32)

        with tempfile.TemporaryDirectory() as directory:
            bank_path = Path(directory) / "image_bank.npz"
            np.savez(
                bank_path,
                descriptors=descriptors,
                labels=np.zeros(len(descriptors), dtype=np.int32),
                names=np.array(["Vivillon", "Milcery"]),
            )
            matcher = ImageMatcher(bank_path)

            with (
                patch.object(
                    matcher,
                    "_match",
                    side_effect=[("Vivillon", 20), ("Milcery", 16)],
                ),
                patch("image_match.vivillon_form_by_pattern", return_value=None),
            ):
                result = matcher.match(b"milcery spawn image")

        self.assertEqual(result, ("Milcery", 16))


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class SilvallyTests(unittest.TestCase):
    def test_folders_keep_their_type_names(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.SILVALLY_FORMS:
            self.assertIn(form, groups)

    def test_type_forms_are_reported_as_silvally(self) -> None:
        self.assertEqual(image_match.species_display_name("Bug Silvally"), "Silvally")
        self.assertEqual(image_match.family_name("Fairy Silvally"), "Silvally")

    def test_type_is_chosen_by_colour(self) -> None:
        for form in ("Silvally", "Bug Silvally", "Fire Silvally", "Water Silvally"):
            path = image_match.silvally_thumbnail_path(form)
            self.assertEqual(
                image_match.silvally_form_by_color(path.read_bytes()), form
            )


class VivillonTests(unittest.TestCase):
    def test_every_pattern_has_a_folder_and_thumbnail(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.VIVILLON_FORMS:
            self.assertIn(form, groups)
            self.assertTrue(image_match.form_thumbnail_path(form).is_file(), form)

    def test_patterns_are_reported_as_vivillon(self) -> None:
        self.assertEqual(image_match.species_display_name("Polar Vivillon"), "Vivillon")
        self.assertEqual(image_match.family_name("Fancy Vivillon"), "Vivillon")

    def test_custom_reference_forms_resolve_to_their_species(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        forms = {
            "Partner Pikachu": "Pikachu",
            "Partner Eevee": "Eevee",
            "Enchanted Applin": "Applin",
            "Rotten Applin": "Applin",
            "Oracle Meowscarada": "Meowscarada",
            "Witch Meowscarada": "Meowscarada",
            "Medusa Simipour": "Simipour",
            "Statue Simipour": "Simipour",
            "Elixir Reuniclus": "Reuniclus",
            "Cauldron Reuniclus": "Reuniclus",
            "Gliding Build Koraidon": "Koraidon",
            "Zenith Marshadow": "Marshadow",
            "Galarian Zen Darmanitan": "Darmanitan",
            "Zygarde Cell": "Zygarde",
            "Zygarde Core": "Zygarde",
            "Combat Breed Tauros": "Tauros",
            "Blaze Breed Tauros": "Tauros",
            "Aqua Breed Tauros": "Tauros",
            "Heart Trim Furfrou": "Furfrou",
            "Matron Trim Furfrou": "Furfrou",
            "Debutante Trim Furfrou": "Furfrou",
            "Trash Burmy": "Burmy",
            "High-speed Flight Configuration Genesect": "Genesect",
            "Green-Plumage Squawkabilly": "Squawkabilly",
            "White-Plumage Squawkabilly": "Squawkabilly",
            "Yellow-Plumage Squawkabilly": "Squawkabilly",
        }
        for form, species in forms.items():
            with self.subTest(form=form):
                self.assertIn(form, groups)
                self.assertEqual(image_match.species_display_name(form), species)
                self.assertEqual(image_match.family_name(form), species)
                if form not in {"Green-Plumage Squawkabilly", "Zygarde Core"}:
                    self.assertIsNotNone(bot.custom_thumbnail_path(form), form)

    def test_pattern_is_chosen_by_appearance_even_mirrored(self) -> None:
        import cv2

        for form in image_match.VIVILLON_FORMS:
            data = image_match.form_thumbnail_path(form).read_bytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(data), form)
            source = require_match(
                cv2.imread(str(image_match.form_thumbnail_path(form)))
            )
            image = cv2.flip(source, 1)
            mirrored = cv2.imencode(".png", image)[1].tobytes()
            self.assertEqual(image_match.vivillon_form_by_pattern(mirrored), form)


@unittest.skipIf(image_match.cv2 is None, "OpenCV is not installed")
class CustomFormRecognitionTests(unittest.TestCase):
    def test_sealeo_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Sealeo"
            / "bulbasaur-example-big-1.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Sealeo")

    def test_yamask_spawn_reference_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Yamask"
            / "reference-002.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Yamask")

    def test_enchanted_applin_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Enchanted Applin"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Enchanted Applin")

    def test_applin_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Applin"
            / "spawn-reference-002.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Applin")

    def test_flamigo_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Flamigo"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Flamigo")

    def test_ditto_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Ditto"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Ditto")

    def test_squawkabilly_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Green-Plumage Squawkabilly"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Green-Plumage Squawkabilly")

    def test_yellow_squawkabilly_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Yellow-Plumage Squawkabilly"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Yellow-Plumage Squawkabilly")

    def test_oddish_spawn_is_recognized_when_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Oddish"
            / "spawn-reference.png"
        )
        image = cv2.imread(str(image_path))
        image = require_match(image)
        if image is None:
            return

        for candidate in (image, cv2.flip(image, 1)):
            with self.subTest(mirrored=candidate is not image):
                success, buffer = cv2.imencode(".png", candidate)
                self.assertTrue(success)
                result = matcher.match(buffer.tobytes())
                result = require_match(result)
                self.assertEqual(result[0], "Oddish")

    def test_oddish_accepts_four_distinctive_votes(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        oddish_label = matcher.names.index("Oddish")
        rival_label = matcher.names.index("Nymble")
        oddish_train_index = int(
            image_match.np.flatnonzero(matcher.labels == oddish_label)[0]
        )
        rival_train_index = int(
            image_match.np.flatnonzero(matcher.labels == rival_label)[0]
        )
        matches = [
            [
                cv2.DMatch(index, oddish_train_index, 10.0),
                cv2.DMatch(index, rival_train_index, 20.0),
            ]
            for index in range(4)
        ]
        matches.append(
            [
                cv2.DMatch(4, rival_train_index, 10.0),
                cv2.DMatch(4, oddish_train_index, 20.0),
            ]
        )
        matcher.matcher = Mock()
        matcher.matcher.knnMatch.return_value = matches

        with patch(
            "image_match.compute_descriptors",
            return_value=image_match.np.zeros((5, 128), dtype=image_match.np.float32),
        ):
            result = matcher._match(b"", False)

        self.assertEqual(result, ("Oddish", 4))

    def test_enchanted_applin_accepts_four_clear_votes(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        form_label = matcher.names.index("Enchanted Applin")
        rival_label = matcher.names.index("Pikachu")
        form_train_index = int(
            image_match.np.flatnonzero(matcher.labels == form_label)[0]
        )
        rival_train_index = int(
            image_match.np.flatnonzero(matcher.labels == rival_label)[0]
        )
        matches = [
            [
                cv2.DMatch(index, form_train_index, 10.0),
                cv2.DMatch(index, rival_train_index, 100.0),
            ]
            for index in range(4)
        ]
        matcher.matcher = Mock()
        matcher.matcher.knnMatch.return_value = matches

        with patch(
            "image_match.compute_descriptors",
            return_value=image_match.np.zeros((4, 128), dtype=image_match.np.float32),
        ):
            result = matcher._match(b"", False)

        self.assertEqual(result, ("Enchanted Applin", 4))

    def test_supplied_form_images_match_their_named_forms(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        forms = (
            "Partner Pikachu",
            "Partner Eevee",
            "Enchanted Applin",
            "Rotten Applin",
            "Oracle Meowscarada",
            "Witch Meowscarada",
            "Medusa Simipour",
            "Statue Simipour",
            "Elixir Reuniclus",
            "Cauldron Reuniclus",
            "Gliding Build Koraidon",
            "Zenith Marshadow",
            "Galarian Zen Darmanitan",
            "Zygarde Cell",
            "Combat Breed Tauros",
            "Blaze Breed Tauros",
            "Aqua Breed Tauros",
            "Heart Trim Furfrou",
            "Matron Trim Furfrou",
            "Trash Burmy",
            "High-speed Flight Configuration Genesect",
            "Yellow-Plumage Squawkabilly",
        )
        for form in forms:
            with self.subTest(form=form):
                image_path = (
                    Path(__file__).with_name("pokemon_images")
                    / form
                    / "image.png"
                )
                result = matcher.match(image_path.read_bytes())

                result = require_match(result)
                self.assertEqual(result[0], form)

    def test_low_vote_user_crops_match_their_folder_species(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        examples = (
            ("Gulpin", "bulbasaur-example-3.png"),
            ("Gulpin", "bulbasaur-example-tight-c44n.png"),
            ("Salandit", "bulbasaur-example-tight-c7n.png"),
            ("Spheal", "bulbasaur-example-3.png"),
            ("Spheal", "bulbasaur-example-6.png"),
            ("Spheal", "bulbasaur-example-tight-c28n.png"),
            ("Yamask", "bulbasaur-example-tight-c33n.png"),
        )
        for expected, filename in examples:
            with self.subTest(pokemon=expected, filename=filename):
                image_path = (
                    Path(__file__).with_name("pokemon_images")
                    / expected
                    / filename
                )
                result = matcher.match(image_path.read_bytes())

                result = require_match(result)
                self.assertEqual(result[0], expected)

    def test_saved_goomy_spawn_scene_matches_as_goomy(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Goomy"
            / "bulbasaur-example-1.png"
        )

        result = require_match(matcher.match(image_path.read_bytes()))

        self.assertEqual(result[0], "Goomy")

    def test_user_reported_spawn_crops_are_recognized(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        examples = (
            ("Applin", "user-example.png"),
            ("Ditto", "user-example.png"),
            ("Dreepy", "user-example-2.png"),
            ("Gulpin", "user-example-8.png"),
            ("Dreepy", "user-example.png"),
            ("Lotad", "user-example.png"),
            ("Snorunt", "user-example.png"),
            ("Snom", "user-example-5.png"),
            ("Toedscool", "user-example-2.png"),
            ("Wiglett", "user-example-4.png"),
            ("Wiglett", "user-example-6.png"),
            ("White-Plumage Squawkabilly", "user-example.png"),
            ("White-Plumage Squawkabilly", "user-example-2.png"),
            ("Wingull", "user-example.png"),
            ("Rotten Applin", "user-example-2.png"),
            ("Wiglett", "user-example-5.png"),
            ("Wiglett", "user-example-2.png"),
            ("Unown Variant 26", "user-example.png"),
            ("Debutante Trim Furfrou", "user-example.png"),
            ("Toedscool", "user-example.png"),
            ("Spheal", "user-example.png"),
            ("Unfezant", "user-example.png"),
            ("Swalot", "user-example.png"),
            ("Wiglett", "user-example-3.png"),
            ("Pumpkaboo", "user-example.png"),
            ("Duskull", "user-example.png"),
            ("Milcery", "user-example-1.png"),
            ("Unown Variant 2", "user-example-3.png"),
            (
                "High-speed Flight Configuration Genesect",
                "user-example-5.png",
            ),
            ("Trash Burmy", "user-example.png"),
            ("Green-Plumage Squawkabilly", "user-example-6.png"),
            ("Smoliv", "user-example-1.png"),
            ("Bellsprout", "user-example-2.png"),
            ("Matron Trim Furfrou", "user-example-3.png"),
            ("Oracle Meowscarada", "user-example-5.png"),
            ("Gourgeist", "user-example-6.png"),
            ("Gulpin", "user-example-7.png"),
            ("Enchanted Applin", "user-example-8.png"),
            ("Mimikyu", "user-example-9.png"),
            ("Bellsprout", "user-example-9.png"),
            ("Litwick", "user-example-18.png"),
            ("Enchanted Applin", "user-example-15.png"),
        )
        for expected, filename in examples:
            with self.subTest(filename=filename):
                image_path = (
                    Path(__file__).with_name("pokemon_images")
                    / expected
                    / filename
                )
                result = matcher.match(image_path.read_bytes())

                result = require_match(result)
                self.assertEqual(result[0], expected)
                if expected == "Unown Variant 2":
                    import bot

                    self.assertEqual(bot.display_pokemon_name(result[0]), "Unown B")
                if expected == "Unown Variant 26":
                    import bot

                    self.assertEqual(bot.display_pokemon_name(result[0]), "Unown Z")

    def test_custom_forms_are_recognized_when_flipped(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        forms = (
            "Partner Eevee",
            "Blaze Breed Tauros",
            "Aqua Breed Tauros",
        )
        for form in forms:
            with self.subTest(form=form):
                image_path = (
                    Path(__file__).with_name("pokemon_images")
                    / form
                    / "image.png"
                )
                image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
                image = require_match(image)
                if image is None:
                    continue
                success, buffer = cv2.imencode(".png", cv2.flip(image, 1))
                self.assertTrue(success)

                result = matcher.match(buffer.tobytes())

                result = require_match(result)
                self.assertEqual(result[0], form)

    def test_zenith_marshadow_is_recognized_when_flipped(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Zenith Marshadow"
            / "image.png"
        )
        image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        image = require_match(image)
        if image is None:
            return
        success, buffer = cv2.imencode(".png", cv2.flip(image, 1))
        self.assertTrue(success)

        result = matcher.match(buffer.tobytes())

        result = require_match(result)
        self.assertEqual(result[0], "Zenith Marshadow")

    def test_all_vivillon_forms_match_their_reference_images(self) -> None:
        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.VIVILLON_FORMS:
            with self.subTest(form=form):
                result = matcher.match(groups[form][0].read_bytes())

                result = require_match(result)
                self.assertEqual(result[0], form)

    def test_zygarde_cell_matches_when_rendered_in_a_scene(self) -> None:
        import cv2
        import numpy as np

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        image_path = (
            Path(__file__).with_name("pokemon_images")
            / "Zygarde Cell"
            / "image.png"
        )
        source = require_match(cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED))
        canvas = np.full((420, 420, 3), (70, 105, 45), dtype=np.uint8)
        pokemon = cv2.resize(source, (250, 250))
        alpha = pokemon[..., 3:4] / 255.0
        region = canvas[85:335, 85:335]
        canvas[85:335, 85:335] = (
            pokemon[..., :3] * alpha + region * (1 - alpha)
        ).astype(np.uint8)
        data = cv2.imencode(".png", canvas)[1].tobytes()

        result = matcher.match(data)

        result = require_match(result)
        self.assertEqual(result[0], "Zygarde Cell")


class ArceusTests(unittest.TestCase):
    def test_every_type_has_a_folder_and_thumbnail(self) -> None:
        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in image_match.ARCEUS_FORMS:
            self.assertIn(form, groups)
            self.assertTrue(image_match.form_thumbnail_path(form).is_file(), form)

    def test_types_are_reported_as_arceus(self) -> None:
        self.assertEqual(image_match.species_display_name("Fire Arceus"), "Arceus")
        self.assertEqual(image_match.family_name("Fairy Arceus"), "Arceus")

    def test_type_is_chosen_by_colour_even_mirrored(self) -> None:
        import cv2

        for form in image_match.ARCEUS_FORMS:
            path = image_match.form_thumbnail_path(form)
            self.assertEqual(image_match.arceus_form_by_color(path.read_bytes()), form)
            source = require_match(cv2.imread(str(path)))
            mirrored_buffer = require_match(
                cv2.imencode(".png", cv2.flip(source, 1))[1]
            )
            mirrored = mirrored_buffer.tobytes()
            self.assertEqual(image_match.arceus_form_by_color(mirrored), form)


class RotomTests(unittest.TestCase):
    FORMS = (
        "Rotom", "Heat Rotom", "Wash Rotom", "Frost Rotom", "Fan Rotom", "Mow Rotom",
        "DJ Rotom", "Rotom Pokédex", "Rotom Phone", "Rotom Drone",
    )

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)


class DeoxysTests(unittest.TestCase):
    FORMS = ("Deoxys", "Attack Deoxys", "Defense Deoxys", "Speed Deoxys")

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)

    def test_each_form_is_recognised_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for form in self.FORMS:
            folder = Path(__file__).with_name("pokemon_images") / form
            for name in ("image.png", "image_mirrored.png"):
                img = require_match(
                    cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
                )
                bg = cv2.resize(img[..., :3], (500, 400)) // 2 + 60
                x, y = 60, 20
                roi = bg[y:y + 360, x:x + 360]
                small = cv2.resize(img, (360, 360))
                al = small[..., 3:4] / 255.0
                bg[y:y + 360, x:x + 360] = (small[..., :3] * al + roi * (1 - al)).astype(bg.dtype)
                ok, buf = cv2.imencode(".png", bg)
                self.assertTrue(ok)
                buf = require_match(buf)
                result = require_match(matcher.match(buf.tobytes()))
                self.assertEqual(result[0], form, name)


class PichuTests(unittest.TestCase):
    FORMS = ("Pichu", "Spiky-Eared Pichu")

    def test_every_form_has_a_folder_and_thumbnail(self) -> None:
        import bot

        groups = reference_images(Path(__file__).with_name("pokemon_images"))
        for form in self.FORMS:
            self.assertIn(form, groups)
            self.assertIsNotNone(bot.custom_thumbnail_path(form), form)

    def test_each_form_is_recognised_normal_and_mirrored(self) -> None:
        import cv2

        matcher = ImageMatcher(Path(__file__).with_name("image_bank.npz"))
        for form in self.FORMS:
            folder = Path(__file__).with_name("pokemon_images") / form
            for name in ("image.png", "image_mirrored.png"):
                img = require_match(
                    cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
                )
                bg = cv2.resize(img[..., :3], (500, 400)) // 2 + 60
                x, y = 60, 20
                roi = bg[y:y + 360, x:x + 360]
                small = cv2.resize(img, (360, 360))
                al = small[..., 3:4] / 255.0
                bg[y:y + 360, x:x + 360] = (small[..., :3] * al + roi * (1 - al)).astype(bg.dtype)
                ok, buf = cv2.imencode(".png", bg)
                self.assertTrue(ok)
                buf = require_match(buf)
                result = require_match(matcher.match(buf.tobytes()))
                self.assertEqual(result[0], form, name)


if __name__ == "__main__":
    unittest.main()
