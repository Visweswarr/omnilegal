"""Quick diagnostic: verify answer modes, provider registry, and source availability.

Updated to use the new source_registry instead of the deleted source_escalator.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schemas import AnswerMode
from src.services.answer_modes import detect_answer_mode, build_mode_system_prompt, MODES
from src.pipeline.source_registry import detect_topics, _get_registry

print("=" * 60)
print("ANSWER MODE DIAGNOSTIC")
print("=" * 60)

modes = list(AnswerMode)
print(f"\nModes defined: {[m.value for m in modes]}")
print(f"MODES dict keys: {list(MODES.keys())}")

for m in modes:
    spec = MODES.get(m)
    prompt = build_mode_system_prompt(m)
    print(f"\n--- {m.value} ---")
    print(f"  Display: {spec.display_name if spec else 'MISSING'}")
    print(f"  Sections: {spec.required_sections if spec else 'MISSING'}")
    print(f"  IRAC: {spec.irac_format if spec else 'N/A'}")
    print(f"  Prompt (first 100): {prompt[:100]}...")

print("\n\nMODE DETECTION TESTS:")
test_queries = [
    ("What is diplomatic immunity?", "tourist_practical"),
    ("Explain BNS Section 69", "law_student_case_law"),
    ("Compare murder sentencing US UK India", "comparative_research"),
    ("Find all sources on diplomatic immunity", "source_discovery"),
    ("What laws apply when driving in Russia?", "tourist_practical"),
    ("Discuss the Tinoco arbitration", "law_student_case_law"),
    ("List cases on self-determination", "source_discovery"),
]

all_pass = True
for query, expected in test_queries:
    detected = detect_answer_mode(query)
    status = "PASS" if detected.value == expected else "FAIL"
    if status == "FAIL":
        all_pass = False
    print(f"  [{status}] '{query[:50]}' -> {detected.value} (expected {expected})")

print(f"\n{'ALL MODE DETECTION TESTS PASSED' if all_pass else 'SOME MODE DETECTION TESTS FAILED'}")

print("\n\nTOPIC DETECTION TESTS:")
topic_tests = [
    ("What is diplomatic immunity?", "diplomatic_immunity"),
    ("Can an Indian drive in Russia?", "driving_india_russia"),
    ("Explain BNS Section 69", "bns_69"),
    ("Compare murder sentencing", "murder_sentencing"),
    ("Tinoco arbitration", "tinoco"),
    ("Wall Advisory Opinion", "wall"),
    ("India Russia travel visa", "travel_india_russia"),
]
for query, expected in topic_tests:
    topics = detect_topics(query)
    status = "PASS" if expected in topics else "FAIL"
    print(f"  [{status}] '{query[:50]}' -> {topics} (expected {expected})")

print("\n\nSOURCE REGISTRY:")
registry = _get_registry()
for topic, tsm in sorted(registry.items()):
    print(f"  {topic}: {len(tsm.required)} required, {len(tsm.optional)} optional")
    for r in tsm.required:
        print(f"    [req] {r.role}: {r.description}")

print("\n\nPROVIDER REGISTRY:")
try:
    from src.services.provider_registry import ProviderRegistry
    reg = ProviderRegistry.get_instance()
    print(f"  Total providers: {len(reg._providers)}")
    print(f"  Available: {len(reg.all_available())}")
    for p in reg._providers.values():
        print(f"    {p.name}: model={p.model_id} quality={p.quality_score} available={p.available}")
    drafters = reg.get_drafters(3)
    print(f"  Drafters ({len(drafters)}):")
    for d in drafters:
        print(f"    {d.name}: {d.model_id}")
    critic = reg.get_best_for("critic")
    print(f"  Critic: {critic.name if critic else 'NONE'}")
    judge = reg.get_best_for("judge")
    print(f"  Judge: {judge.name if judge else 'NONE'}")
    if not drafters:
        print("  WARNING: No drafters available! Council will fail!")
    if not critic:
        print("  WARNING: No critic available! Cross-examination will be skipped!")
    if not judge:
        print("  WARNING: No judge available! Judge synthesis will be skipped!")
except Exception as exc:
    print(f"  ERROR: {exc}")

print("\n\nSYNTAX VALIDATION:")
critical_files = [
    "chainlit_app.py",
    "src/pipeline/retriever_node.py",
    "src/pipeline/source_registry.py",
    "src/pipeline/source_gate.py",
    "src/pipeline/graph.py",
    "src/services/answer_modes.py",
    "src/services/answer_format.py",
    "src/pipeline/safety_critic.py",
    "src/schemas.py",
]
import py_compile
for f in critical_files:
    try:
        py_compile.compile(str(Path(__file__).parent.parent / f), doraise=True)
        print(f"  [OK] {f}")
    except py_compile.PyCompileError as exc:
        print(f"  [FAIL] {f}: {exc}")

print("\nDONE")
