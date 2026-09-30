"""Label-scheme registry: named raw-label sets and raw -> category mapping presets.

The registry lives outside the code so that a new label vocabulary (for example
the 2026-09-30 electrical E-5 set, or an optical GOOD/BAD/OPEN set) can be added
by editing a JSON file rather than the program.  The bundled
``label_schemes.json`` is the read-only default; a user file with the same shape
may add or override entries.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

EXCLUDE = "Exclude"
WILDCARD = "*"
USER_FILE_NAME = "label_schemes.json"


def normalise(value: object) -> str:
    """Case/spacing/punctuation-insensitive key shared with :mod:`core`."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", str(value)).casefold())


class SchemeError(ValueError):
    """Raised for a malformed registry file or an unknown scheme/preset id."""


@dataclass(frozen=True)
class LabelScheme:
    id: str
    labels: tuple[str, ...]
    title: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.labels:
            raise SchemeError(f"scheme {self.id!r} must list at least one label")
        seen: set[str] = set()
        for label in self.labels:
            key = normalise(label)
            if not key:
                raise SchemeError(f"scheme {self.id!r} has a blank label")
            if key in seen:
                raise SchemeError(f"scheme {self.id!r} repeats label {label!r}")
            seen.add(key)

    def canonical(self, raw: object) -> str | None:
        """Return the scheme's spelling for ``raw`` or ``None`` if unknown."""
        key = normalise(raw)
        for label in self.labels:
            if normalise(label) == key:
                return label
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "labels": list(self.labels),
            "description": self.description,
        }


@dataclass(frozen=True)
class MappingPreset:
    """A raw-label -> category table.  ``Exclude`` drops the record; ``*`` is a fallback."""

    id: str
    targets: tuple[str, ...]
    rules: Mapping[str, str]
    title: str = ""
    source: str = ""
    _lookup: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.targets:
            raise SchemeError(f"preset {self.id!r} must list target categories")
        allowed = {normalise(target): target for target in self.targets}
        allowed[normalise(EXCLUDE)] = EXCLUDE
        lookup: dict[str, str] = {}
        for raw, target in self.rules.items():
            canonical = allowed.get(normalise(target))
            if canonical is None:
                raise SchemeError(
                    f"preset {self.id!r}: {raw!r} -> {target!r} is not one of "
                    f"{', '.join(self.targets)} or {EXCLUDE}"
                )
            key = WILDCARD if str(raw).strip() == WILDCARD else normalise(raw)
            lookup[key] = canonical
        object.__setattr__(self, "_lookup", lookup)

    def map(self, raw: object) -> str | None:
        """Category for ``raw`` (``Exclude`` included) or ``None`` when unmapped."""
        return self._lookup.get(normalise(raw), self._lookup.get(WILDCARD))

    def explicit_rules(self) -> dict[str, str]:
        return {raw: target for raw, target in self.rules.items() if str(raw).strip() != WILDCARD}

    def resolved_rules(self, labels: Iterable[str]) -> dict[str, str]:
        """Expand the wildcard against a concrete label list (unmapped labels omitted)."""
        resolved: dict[str, str] = {}
        for label in labels:
            target = self.map(label)
            if target is not None:
                resolved[label] = target
        return resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "targets": list(self.targets),
            "rules": dict(self.rules),
        }


@dataclass(frozen=True)
class SchemeRegistry:
    schemes: Mapping[str, LabelScheme]
    presets: Mapping[str, MappingPreset]
    sources: tuple[str, ...] = ()

    def scheme(self, scheme_id: str) -> LabelScheme:
        try:
            return self.schemes[scheme_id]
        except KeyError as error:
            raise SchemeError(f"unknown label scheme {scheme_id!r}") from error

    def preset(self, preset_id: str) -> MappingPreset:
        try:
            return self.presets[preset_id]
        except KeyError as error:
            raise SchemeError(f"unknown mapping preset {preset_id!r}") from error

    def presets_for(self, scheme_id: str) -> tuple[MappingPreset, ...]:
        return tuple(item for item in self.presets.values() if item.source == scheme_id)

    def identify(self, raw_labels: Iterable[str]) -> tuple[str, ...]:
        """Scheme ids whose label set covers every observed raw label (most specific first)."""
        observed = {normalise(label) for label in raw_labels if str(label).strip()}
        matches = [
            scheme
            for scheme in self.schemes.values()
            if observed <= {normalise(label) for label in scheme.labels}
        ]
        matches.sort(key=lambda scheme: (len(scheme.labels), scheme.id))
        return tuple(scheme.id for scheme in matches)

    def merged(self, other: SchemeRegistry) -> SchemeRegistry:
        return SchemeRegistry(
            {**self.schemes, **other.schemes},
            {**self.presets, **other.presets},
            (*self.sources, *other.sources),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "schemes": {key: value.to_dict() for key, value in self.schemes.items()},
            "presets": {key: value.to_dict() for key, value in self.presets.items()},
        }


def registry_from_dict(data: Mapping[str, Any], source: str = "<dict>") -> SchemeRegistry:
    if not isinstance(data, Mapping):
        raise SchemeError(f"{source}: registry must be a JSON object")
    version = data.get("schema_version", 1)
    if version != 1:
        raise SchemeError(f"{source}: unsupported schema_version {version!r}")
    schemes: dict[str, LabelScheme] = {}
    for scheme_id, payload in (data.get("schemes") or {}).items():
        if not isinstance(payload, Mapping) or not isinstance(payload.get("labels"), list):
            raise SchemeError(f"{source}: scheme {scheme_id!r} needs a 'labels' list")
        schemes[str(scheme_id)] = LabelScheme(
            str(scheme_id),
            tuple(str(label) for label in payload["labels"]),
            str(payload.get("title") or scheme_id),
            str(payload.get("description") or ""),
        )
    presets: dict[str, MappingPreset] = {}
    for preset_id, payload in (data.get("presets") or {}).items():
        if not isinstance(payload, Mapping) or not isinstance(payload.get("rules"), Mapping):
            raise SchemeError(f"{source}: preset {preset_id!r} needs a 'rules' object")
        targets = payload.get("targets")
        if not isinstance(targets, list):
            raise SchemeError(f"{source}: preset {preset_id!r} needs a 'targets' list")
        presets[str(preset_id)] = MappingPreset(
            str(preset_id),
            tuple(str(target) for target in targets),
            {str(raw): str(target) for raw, target in payload["rules"].items()},
            str(payload.get("title") or preset_id),
            str(payload.get("source") or ""),
        )
    return SchemeRegistry(schemes, presets, (source,))


def load_registry_file(path: str | Path) -> SchemeRegistry:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise SchemeError(f"{source}: cannot read registry: {error}") from error
    return registry_from_dict(data, str(source))


def bundled_registry() -> SchemeRegistry:
    text = resources.files(__package__).joinpath("label_schemes.json").read_text("utf-8")
    return registry_from_dict(json.loads(text), "<bundled>")


def user_registry_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "R2R Evaluation Report Generator" / USER_FILE_NAME


def load_registry(user_path: str | Path | None = None) -> SchemeRegistry:
    """Bundled registry overlaid with the user file when it exists."""
    registry = bundled_registry()
    path = Path(user_path) if user_path else user_registry_path()
    if path.is_file():
        registry = registry.merged(load_registry_file(path))
    return registry


def save_registry(registry: SchemeRegistry, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(registry.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination
