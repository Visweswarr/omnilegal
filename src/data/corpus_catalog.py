from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from json import JSONDecodeError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from src.config import CHUNK_OVERLAP, CHUNK_SIZE, ROOT_DIR, get_available_corpus_files


COLLECTION_LABELS = {
    "core_legal_en": "Core English / Indian / International Law",
    "eu_multilingual": "EU Multilingual Law",
    "cn_legal": "Chinese Legal Retrieval",
}


class NormalizedCorpusRecord(BaseModel):
    id: str
    text: str
    title: str = ""
    source_repo: str
    source_path: str
    collection: str = "core_legal_en"
    jurisdiction: str = "mixed"
    language: str = "en"
    task_family: str = "retrieval"
    document_type: str = "mixed_legal_text"
    split: str = "runtime"
    license_note: str = ""
    labels: str = ""
    summary: str = ""
    question: str = ""
    answer: str = ""
    court: str = ""
    date: str = ""
    source_name: str = ""
    page: str | int | None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    def to_document(self) -> Document:
        metadata = {
            "record_id": self.id,
            "title": self.title,
            "source_name": self.source_name or self.source_repo,
            "source_repo": self.source_repo,
            "source_path": self.source_path,
            "collection": self.collection,
            "jurisdiction": self.jurisdiction,
            "language": self.language,
            "task_family": self.task_family,
            "document_type": self.document_type,
            "type": self.document_type,
            "split": self.split,
            "license_note": self.license_note,
            "labels": self.labels,
            "summary": self.summary,
            "question": self.question,
            "answer": self.answer,
            "court": self.court,
            "date": self.date,
            "page": self.page,
        }
        metadata.update({k: v for k, v in self.extra_metadata.items() if v is not None})
        return Document(page_content=self.text, metadata=metadata)


@dataclass(frozen=True)
class CorpusSourceSpec:
    source_id: str
    title: str
    relative_path: str
    collection: str
    parser: str
    jurisdiction: str
    language: str
    task_family: str
    document_type: str
    split: str = "runtime"
    license_note: str = "Review upstream license before redistribution."
    text_fields: tuple[str, ...] = ()
    title_fields: tuple[str, ...] = ()
    summary_fields: tuple[str, ...] = ()
    question_fields: tuple[str, ...] = ()
    answer_fields: tuple[str, ...] = ()
    label_fields: tuple[str, ...] = ()
    court_fields: tuple[str, ...] = ()
    date_fields: tuple[str, ...] = ()
    glob_pattern: str | None = None
    max_default_records: int | None = 5000


TEXT_FIELDS = (
    "text",
    "document",
    "documentContent",
    "content",
    "case_text",
    "facts",
    "judgment_reason",
    "summary",
    "q",
    "query",
    "key",
    "description",
    "question",
    "answer",
    "clause",
)

TITLE_FIELDS = ("title", "case_title", "name", "path", "id", "case_id")
MAX_RECORD_TEXT_CHARS = 12000
MAX_TEXT_FILE_CHARS = 20000


CURATED_SOURCE_SPECS: list[CorpusSourceSpec] = [
    CorpusSourceSpec(
        source_id="indian_bail_judgments",
        title="IndianBailJudgments-1200 structured cases",
        relative_path="IndianBailJudgments-1200/indian_bail_judgments.json",
        collection="core_legal_en",
        parser="json",
        jurisdiction="indian",
        language="en",
        task_family="bail_prediction",
        document_type="case_law",
        split="runtime_training_eval",
        license_note="CC BY 4.0; cite dataset authors.",
        text_fields=("facts", "legal_issues", "judgment_reason", "summary", "legal_principles_discussed"),
        title_fields=("case_title", "case_id"),
        summary_fields=("summary",),
        label_fields=("bail_outcome", "crime_type", "ipc_sections", "special_laws"),
        court_fields=("court",),
        date_fields=("date",),
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="cail2022_train",
        title="CAIL2022 legal case retrieval train records",
        relative_path="CAIL2022/cail2022_train.json",
        collection="cn_legal",
        parser="json",
        jurisdiction="chinese",
        language="zh",
        task_family="case_retrieval",
        document_type="case_law",
        split="train",
        text_fields=("query", "key"),
        title_fields=("title",),
        question_fields=("query",),
        answer_fields=("key",),
    ),
    CorpusSourceSpec(
        source_id="cail2022_stage2_queries",
        title="CAIL2022 stage 2 queries",
        relative_path="CAIL2022/stage2/query_stage2.json",
        collection="cn_legal",
        parser="json",
        jurisdiction="chinese",
        language="zh",
        task_family="case_retrieval",
        document_type="case_law",
        split="query",
        text_fields=("q", "crime"),
        title_fields=("path", "ridx"),
        question_fields=("q",),
        label_fields=("crime",),
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="lecard_queries",
        title="LeCaRD query records",
        relative_path="LeCaRD/data/query/query.json",
        collection="cn_legal",
        parser="json",
        jurisdiction="chinese",
        language="zh",
        task_family="case_retrieval",
        document_type="case_law",
        split="query",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        question_fields=TEXT_FIELDS,
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="lecard_corpus_common_charge",
        title="LeCaRD common charge corpus",
        relative_path="LeCaRD/data/corpus/common_charge.json",
        collection="cn_legal",
        parser="json",
        jurisdiction="chinese",
        language="zh",
        task_family="case_retrieval",
        document_type="case_law",
        split="corpus",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
    ),
    CorpusSourceSpec(
        source_id="eur_lex_sum_single_reference",
        title="EUR-Lex-Sum single-reference subset metadata",
        relative_path="eur-lex-sum/Analysis/Insights/single_reference_subset.json",
        collection="eu_multilingual",
        parser="json",
        jurisdiction="eu",
        language="multi",
        task_family="summarization",
        document_type="statutory_law",
        split="analysis_subset",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        summary_fields=("summary", "summaryContent", "reference"),
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="eur_lex_sum_final_stats",
        title="EUR-Lex-Sum analysis statistics",
        relative_path="eur-lex-sum/Analysis/Insights/final_stats.txt",
        collection="eu_multilingual",
        parser="txt",
        jurisdiction="eu",
        language="multi",
        task_family="summarization",
        document_type="statutory_law",
        split="analysis_stats",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="multi_eurlex_eurovoc_descriptors",
        title="MultiEURLEX EuroVoc descriptors",
        relative_path="multi-eurlex/data/eurovoc_descriptors.json",
        collection="eu_multilingual",
        parser="json",
        jurisdiction="eu",
        language="multi",
        task_family="classification",
        document_type="statutory_law",
        split="labels",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        label_fields=TEXT_FIELDS,
    ),
    CorpusSourceSpec(
        source_id="multi_eurlex_eurovoc_concepts",
        title="MultiEURLEX EuroVoc concepts",
        relative_path="multi-eurlex/data/eurovoc_concepts.json",
        collection="eu_multilingual",
        parser="json",
        jurisdiction="eu",
        language="multi",
        task_family="classification",
        document_type="reference_dataset",
        split="labels",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        label_fields=TEXT_FIELDS,
    ),
    CorpusSourceSpec(
        source_id="privacy_qa_train",
        title="PrivacyQA train records",
        relative_path="PrivacyQA_EMNLP/data/policy_train_data.csv",
        collection="core_legal_en",
        parser="csv",
        jurisdiction="us",
        language="en",
        task_family="qa",
        document_type="privacy_policy",
        split="train",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        question_fields=("question", "Query", "query"),
        answer_fields=("answer", "Answer", "segment_text", "policy_segment"),
    ),
    CorpusSourceSpec(
        source_id="privacy_qa_test",
        title="PrivacyQA test records",
        relative_path="PrivacyQA_EMNLP/data/policy_test_data.csv",
        collection="core_legal_en",
        parser="csv",
        jurisdiction="us",
        language="en",
        task_family="qa",
        document_type="privacy_policy",
        split="test",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        question_fields=("question", "Query", "query"),
        answer_fields=("answer", "Answer", "segment_text", "policy_segment"),
    ),
    CorpusSourceSpec(
        source_id="cuad_category_descriptions",
        title="CUAD category descriptions",
        relative_path="cuad/category_descriptions.csv",
        collection="core_legal_en",
        parser="csv",
        jurisdiction="us",
        language="en",
        task_family="contract_qa",
        document_type="contract",
        split="labels",
        text_fields=TEXT_FIELDS,
        title_fields=TITLE_FIELDS,
        label_fields=TEXT_FIELDS,
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="bva_sample_cases",
        title="BVA summarization sample cases",
        relative_path="bva-summarization/summarization/single_issue_PTSD_sample",
        collection="core_legal_en",
        parser="txt_dir",
        jurisdiction="us",
        language="en",
        task_family="summarization",
        document_type="case_law",
        split="sample",
        glob_pattern="*.txt",
    ),
    CorpusSourceSpec(
        source_id="bva_annotated_cases",
        title="BVA annotated case text",
        relative_path="bva-summarization/annotated_casetext",
        collection="core_legal_en",
        parser="txt_dir",
        jurisdiction="us",
        language="en",
        task_family="summarization",
        document_type="case_law",
        split="annotated",
        glob_pattern="*.txt",
    ),
]


REPOSITORY_SUMMARY_SPECS: list[CorpusSourceSpec] = [
    CorpusSourceSpec(
        source_id="legal_ml_datasets_readme",
        title="legal-ml-datasets repository summary",
        relative_path="legal-ml-datasets/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="mixed",
        language="en",
        task_family="dataset_summary",
        document_type="reference_dataset",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="fairlex_readme",
        title="FairLex repository summary",
        relative_path="fairlex/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="mixed",
        language="en",
        task_family="dataset_summary",
        document_type="reference_dataset",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="fairlex_placeholder_dataset",
        title="FairLex placeholder dataset note",
        relative_path="fairlex/data/datasets/placeholder.txt",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="mixed",
        language="en",
        task_family="dataset_summary",
        document_type="reference_dataset",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="multi_eurlex_readme",
        title="MultiEURLEX repository summary",
        relative_path="multi-eurlex/README.md",
        collection="eu_multilingual",
        parser="txt",
        jurisdiction="eu",
        language="multi",
        task_family="dataset_summary",
        document_type="reference_dataset",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="billsum_readme",
        title="BillSum repository summary",
        relative_path="BillSum/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="us",
        language="en",
        task_family="dataset_summary",
        document_type="legislation",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="casehold_readme",
        title="CaseHOLD repository summary",
        relative_path="casehold/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="us",
        language="en",
        task_family="dataset_summary",
        document_type="case_law",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="clerc_readme",
        title="CLERC repository summary",
        relative_path="CLERC/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="us",
        language="en",
        task_family="dataset_summary",
        document_type="case_law",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="bsard_readme",
        title="BSARD repository summary",
        relative_path="bsard/README.md",
        collection="eu_multilingual",
        parser="txt",
        jurisdiction="belgian",
        language="fr",
        task_family="dataset_summary",
        document_type="statutory_law",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="lleqa_readme",
        title="LLeQA repository summary",
        relative_path="lleqa/README.md",
        collection="eu_multilingual",
        parser="txt",
        jurisdiction="belgian",
        language="fr",
        task_family="dataset_summary",
        document_type="statutory_law",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="eur_lex_sum_readme",
        title="EUR-Lex-Sum repository summary",
        relative_path="eur-lex-sum/README.md",
        collection="eu_multilingual",
        parser="txt",
        jurisdiction="eu",
        language="multi",
        task_family="dataset_summary",
        document_type="statutory_law",
        split="reference",
        max_default_records=None,
    ),
    CorpusSourceSpec(
        source_id="legal_summarization_readme",
        title="TLDRLegal summarization repository summary",
        relative_path="legal_summarization/README.md",
        collection="core_legal_en",
        parser="txt",
        jurisdiction="mixed",
        language="en",
        task_family="dataset_summary",
        document_type="terms_of_service",
        split="reference",
        max_default_records=None,
    ),
]


REFERENCE_DATASET_SOURCE_IDS = {
    "legal_ml_datasets_readme",
    "fairlex_readme",
    "fairlex_placeholder_dataset",
    "multi_eurlex_readme",
    "multi_eurlex_eurovoc_concepts",
    "multi_eurlex_eurovoc_descriptors",
}


def collection_catalog() -> dict[str, dict[str, Any]]:
    return {
        name: {"collection": name, "label": label}
        for name, label in COLLECTION_LABELS.items()
    }


def curated_source_specs(include_summaries: bool = True) -> list[CorpusSourceSpec]:
    specs = list(CURATED_SOURCE_SPECS)
    if include_summaries:
        specs.extend(REPOSITORY_SUMMARY_SPECS)
    return specs


def reference_dataset_source_specs() -> list[CorpusSourceSpec]:
    return [
        spec
        for spec in curated_source_specs(include_summaries=True)
        if spec.source_id in REFERENCE_DATASET_SOURCE_IDS
    ]


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _safe_source_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _compact(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    return " ".join(str(value).split())


def _first_value(row: dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        if field in row and row[field] not in (None, ""):
            return _compact(row[field])
    return ""


def _combine_fields(row: dict[str, Any], fields: Iterable[str]) -> str:
    parts = []
    for field in fields:
        value = _first_value(row, (field,))
        if value:
            parts.append(f"{field}: {value}")
    if parts:
        return "\n".join(parts)
    fallback = []
    for key, value in row.items():
        compact = _compact(value)
        if compact and len(compact) > 20:
            fallback.append(f"{key}: {compact}")
        if len(fallback) >= 6:
            break
    return "\n".join(fallback)


def _record_from_row(spec: CorpusSourceSpec, path: Path, index: int, row: dict[str, Any]) -> NormalizedCorpusRecord | None:
    text = _combine_fields(row, spec.text_fields or TEXT_FIELDS)
    if len(text.strip()) < 20:
        return None
    if len(text) > MAX_RECORD_TEXT_CHARS:
        text = text[:MAX_RECORD_TEXT_CHARS]

    title = _first_value(row, spec.title_fields or TITLE_FIELDS) or f"{spec.title} #{index + 1}"
    labels = _combine_fields(row, spec.label_fields) if spec.label_fields else ""
    source_path = _safe_source_path(path)
    return NormalizedCorpusRecord(
        id=f"{spec.source_id}:{_stable_id(source_path, index, title, text[:120])}",
        text=text,
        title=title,
        source_repo=spec.source_id,
        source_path=source_path,
        collection=spec.collection,
        jurisdiction=spec.jurisdiction,
        language=spec.language,
        task_family=spec.task_family,
        document_type=spec.document_type,
        split=spec.split,
        license_note=spec.license_note,
        labels=labels,
        summary=_first_value(row, spec.summary_fields),
        question=_first_value(row, spec.question_fields),
        answer=_first_value(row, spec.answer_fields),
        court=_first_value(row, spec.court_fields),
        date=_first_value(row, spec.date_fields),
        source_name=spec.source_id,
        extra_metadata={"dataset_title": spec.title},
    )


def _iter_json_rows(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
            else:
                yield {"value": item}
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                yield item
            else:
                yield {"id": key, "value": value}


def _iter_json_records(spec: CorpusSourceSpec, path: Path, limit: int | None) -> Iterable[NormalizedCorpusRecord]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        rows = list(_iter_json_rows(json.loads(text)))
    except JSONDecodeError:
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"value": item})
    for index, row in enumerate(rows):
        if limit is not None and index >= limit:
            break
        record = _record_from_row(spec, path, index, row)
        if record:
            yield record


def _iter_csv_records(spec: CorpusSourceSpec, path: Path, limit: int | None) -> Iterable[NormalizedCorpusRecord]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                break
            record = _record_from_row(spec, path, index, row)
            if record:
                yield record


def _xlsx_column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    if not letters:
        return 0
    index = 0
    for letter in letters.upper():
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def _xlsx_cell_text(cell, shared_strings: list[str]) -> str:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline_string = cell.find(f"{ns}is")
        if inline_string is None:
            return ""
        return "".join(text.text or "" for text in inline_string.iter(f"{ns}t"))

    value = cell.find(f"{ns}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (IndexError, ValueError):
            return ""
    return value.text


def _iter_xlsx_rows(path: Path) -> Iterable[dict[str, Any]]:
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as workbook:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            for item in shared_root.iter(f"{ns}si"):
                shared_strings.append("".join(text.text or "" for text in item.iter(f"{ns}t")))

        worksheet_paths = sorted(
            name for name in workbook.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not worksheet_paths:
            return

        sheet_root = ET.fromstring(workbook.read(worksheet_paths[0]))
        rows: list[list[str]] = []
        for row in sheet_root.iter(f"{ns}row"):
            values: list[str] = []
            for position, cell in enumerate(row.findall(f"{ns}c")):
                column_index = _xlsx_column_index(cell.attrib.get("r", "")) if cell.attrib.get("r") else position
                while len(values) <= column_index:
                    values.append("")
                values[column_index] = _xlsx_cell_text(cell, shared_strings)
            if any(value.strip() for value in values):
                rows.append(values)

    if not rows:
        return
    headers = [header.strip() or f"column_{index + 1}" for index, header in enumerate(rows[0])]
    for values in rows[1:]:
        yield {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
        }


def _iter_xlsx_records(spec: CorpusSourceSpec, path: Path, limit: int | None) -> Iterable[NormalizedCorpusRecord]:
    for index, row in enumerate(_iter_xlsx_rows(path)):
        if limit is not None and index >= limit:
            break
        record = _record_from_row(spec, path, index, row)
        if record:
            yield record


def _iter_txt_record(spec: CorpusSourceSpec, path: Path) -> Iterable[NormalizedCorpusRecord]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) < 20:
        return
    if len(text) > MAX_TEXT_FILE_CHARS:
        text = text[:MAX_TEXT_FILE_CHARS]
    source_path = _safe_source_path(path)
    yield NormalizedCorpusRecord(
        id=f"{spec.source_id}:{_stable_id(source_path, text[:120])}",
        text=text,
        title=spec.title if path.is_file() else path.name,
        source_repo=spec.source_id,
        source_path=source_path,
        collection=spec.collection,
        jurisdiction=spec.jurisdiction,
        language=spec.language,
        task_family=spec.task_family,
        document_type=spec.document_type,
        split=spec.split,
        license_note=spec.license_note,
        source_name=spec.source_id,
        extra_metadata={"dataset_title": spec.title},
    )


def _iter_txt_dir_records(spec: CorpusSourceSpec, base_path: Path, limit: int | None) -> Iterable[NormalizedCorpusRecord]:
    pattern = spec.glob_pattern or "*.txt"
    for index, path in enumerate(sorted(base_path.glob(pattern))):
        if limit is not None and index >= limit:
            break
        yield from _iter_txt_record(spec, path)


def iter_source_records(
    spec: CorpusSourceSpec,
    *,
    sample_limit_per_source: int | None = None,
) -> Iterable[NormalizedCorpusRecord]:
    path = ROOT_DIR / spec.relative_path
    if not path.exists():
        return []
    limit = sample_limit_per_source
    if limit is None:
        limit = spec.max_default_records
    if spec.parser == "json":
        return _iter_json_records(spec, path, limit)
    if spec.parser == "csv":
        return _iter_csv_records(spec, path, limit)
    if spec.parser == "xlsx":
        return _iter_xlsx_records(spec, path, limit)
    if spec.parser == "txt":
        return _iter_txt_record(spec, path)
    if spec.parser == "txt_dir":
        return _iter_txt_dir_records(spec, path, limit)
    return []


def iter_normalized_records(
    *,
    collections: list[str] | None = None,
    sample_limit_per_source: int | None = None,
    include_summaries: bool = True,
) -> Iterable[NormalizedCorpusRecord]:
    selected = set(collections or COLLECTION_LABELS.keys())
    for spec in curated_source_specs(include_summaries=include_summaries):
        if spec.collection not in selected:
            continue
        yield from iter_source_records(spec, sample_limit_per_source=sample_limit_per_source)


def iter_reference_dataset_records(
    *,
    sample_limit_per_source: int | None = 50,
) -> Iterable[NormalizedCorpusRecord]:
    for spec in reference_dataset_source_specs():
        yield from iter_source_records(spec, sample_limit_per_source=sample_limit_per_source)


def _pdf_metadata_map(key: str) -> dict[str, str]:
    return {
        "indian_constitution": {
            "jurisdiction": "indian",
            "type": "constitutional_text",
            "document_type": "constitutional_text",
            "language": "en",
            "task_family": "retrieval",
            "collection": "core_legal_en",
        },
        "un_charter": {
            "jurisdiction": "international",
            "type": "treaty",
            "document_type": "treaty",
            "language": "en",
            "task_family": "retrieval",
            "collection": "core_legal_en",
        },
        "iccpr": {
            "jurisdiction": "international",
            "type": "treaty",
            "document_type": "treaty",
            "language": "en",
            "task_family": "retrieval",
            "collection": "core_legal_en",
        },
        "icescr": {
            "jurisdiction": "international",
            "type": "treaty",
            "document_type": "treaty",
            "language": "en",
            "task_family": "retrieval",
            "collection": "core_legal_en",
        },
        "malcolm_shaw": {
            "jurisdiction": "international",
            "type": "commentary",
            "document_type": "commentary",
            "language": "en",
            "task_family": "retrieval",
            "collection": "core_legal_en",
        },
    }.get(key, {})


def load_project_pdf_documents() -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader

    docs: list[Document] = []
    for key, path in get_available_corpus_files().items():
        loader = PyPDFLoader(str(path))
        try:
            loaded = loader.load()
        except Exception as exc:
            print(f"Error loading {key}: {exc}")
            continue
        base_metadata = _pdf_metadata_map(key)
        for doc in loaded:
            doc.metadata["source_name"] = key
            doc.metadata["source_repo"] = "project_local_corpus"
            doc.metadata["source_path"] = str(path.relative_to(ROOT_DIR))
            doc.metadata["record_id"] = f"{key}:{doc.metadata.get('page', '?')}"
            doc.metadata["collection"] = base_metadata.get("collection", "core_legal_en")
            doc.metadata["license_note"] = "Verify redistribution rights for bundled PDFs before external release."
            doc.metadata.update(base_metadata)
            docs.append(doc)
    return docs


def build_collection_documents(
    *,
    collections: list[str] | None = None,
    sample_limit_per_source: int | None = None,
    include_summaries: bool = True,
    include_project_pdfs: bool = True,
) -> dict[str, list[Document]]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    selected = set(collections or COLLECTION_LABELS.keys())
    grouped: dict[str, list[Document]] = {collection: [] for collection in selected}

    if include_project_pdfs and "core_legal_en" in selected:
        grouped.setdefault("core_legal_en", []).extend(load_project_pdf_documents())

    for record in iter_normalized_records(
        collections=list(selected),
        sample_limit_per_source=sample_limit_per_source,
        include_summaries=include_summaries,
    ):
        grouped.setdefault(record.collection, []).append(record.to_document())

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    return {
        collection: splitter.split_documents(documents) if documents else []
        for collection, documents in grouped.items()
    }


def corpus_inventory(sample_limit_per_source: int | None = 5) -> dict[str, Any]:
    counts: dict[str, int] = {}
    collections: dict[str, int] = {}
    missing: list[str] = []
    for spec in curated_source_specs(include_summaries=True):
        path = ROOT_DIR / spec.relative_path
        if not path.exists():
            missing.append(spec.relative_path)
            continue
        records = list(iter_source_records(spec, sample_limit_per_source=sample_limit_per_source))
        counts[spec.source_id] = len(records)
        collections[spec.collection] = collections.get(spec.collection, 0) + len(records)
    pdf_count = len(get_available_corpus_files())
    counts["project_local_corpus_pdfs"] = pdf_count
    collections["core_legal_en"] = collections.get("core_legal_en", 0) + pdf_count
    return {
        "sources": counts,
        "collections": collections,
        "missing": missing,
        "collection_catalog": collection_catalog(),
    }
