"""Workflow schema loader and model definitions."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def normalize_header(raw_header: str) -> str:
    """
    Normalise a header per specification:
    'lower-case it, trim it, and replace every run of _ or whitespace with a single space.'
    """
    if not raw_header:
        return ""
    cleaned = raw_header.strip().lower()
    return re.sub(r"[\s_]+", " ", cleaned)


@dataclass(frozen=True)
class FieldSchema:
    """Specification of a single schema field."""

    name: str
    type: str  # 'string', 'phone', 'date', 'decimal', 'enum'
    required: bool = False
    pii: bool = False
    reference: bool = False
    default: Optional[Any] = None
    values: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()

    def matches_header(self, normalized_hdr: str) -> bool:
        """Check if a normalized CSV header matches this field's name or any alias."""
        if normalize_header(self.name) == normalized_hdr:
            return True
        for alias in self.aliases:
            if normalize_header(alias) == normalized_hdr:
                return True
        return False


@dataclass(frozen=True)
class WorkflowSchema:
    """Complete schema for a workflow."""

    workflow_id: str
    description: str
    fields: List[FieldSchema]

    @property
    def reference_field(self) -> Optional[FieldSchema]:
        """Return the schema field marked as reference=True."""
        for f in self.fields:
            if f.reference:
                return f
        return None

    def map_headers(self, raw_headers: List[str]) -> Dict[str, FieldSchema]:
        """
        Map CSV column names to schema FieldSchema instances.
        Columns that match nothing are omitted (ignored).
        """
        mapping: Dict[str, FieldSchema] = {}
        for raw_hdr in raw_headers:
            norm = normalize_header(raw_hdr)
            for f in self.fields:
                if f.matches_header(norm):
                    mapping[raw_hdr] = f
                    break
        return mapping


def load_workflow_schemas(schemas_dir: Path) -> Dict[str, WorkflowSchema]:
    """Load all JSON workflow schemas from the specified directory."""
    schemas: Dict[str, WorkflowSchema] = {}
    for json_file in schemas_dir.glob("*.json"):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            wf_id = data["workflow_id"]
            fields: List[FieldSchema] = []
            for f in data.get("fields", []):
                fields.append(
                    FieldSchema(
                        name=f["name"],
                        type=f["type"],
                        required=f.get("required", False),
                        pii=f.get("pii", False),
                        reference=f.get("reference", False),
                        default=f.get("default"),
                        values=tuple(f.get("values", [])),
                        aliases=tuple(f.get("aliases", [])),
                    )
                )
            schemas[wf_id] = WorkflowSchema(
                workflow_id=wf_id,
                description=data.get("description", ""),
                fields=fields,
            )
    return schemas
