"""Test concept-based entity detection for paraphrased case references."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.entity_extractor import _concept_case_entities, extract_entities

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} -- {detail}")
        failed += 1


# Test 1: Barcelona Traction via paraphrase
print("Test 1: belgium shareholders spain -> Barcelona Traction")
ents = _concept_case_entities("case about belgium shareholders in spain")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Barcelona Traction detected", any("Barcelona" in n for n in names))

# Test 2: Lotus via name
print("\nTest 2: lotus -> Lotus Case")
ents = _concept_case_entities("what is the lotus case")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Lotus Case detected", any("Lotus" in n for n in names))

# Test 3: Chorzow Factory
print("\nTest 3: chorzow factory")
ents = _concept_case_entities("tell me about chorzow factory")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Chorzow Factory detected", any("Chorzow" in n for n in names))

# Test 4: Island of Palmas
print("\nTest 4: island of palmas")
ents = _concept_case_entities("the island of palmas case")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Island of Palmas detected", any("Palmas" in n for n in names))

# Test 5: Tinoco
print("\nTest 5: tinoco arbitration")
ents = _concept_case_entities("explain the tinoco arbitration")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Tinoco detected", any("Tinoco" in n for n in names))

# Test 6: Trail Smelter via concept
print("\nTest 6: transboundary pollution -> Trail Smelter")
ents = _concept_case_entities("what about transboundary pollution")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Trail Smelter detected", any("Trail" in n for n in names))

# Test 7: Caroline via concept
print("\nTest 7: anticipatory self-defense -> Caroline Case")
ents = _concept_case_entities("is anticipatory self-defense lawful")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
test("Caroline Case detected", any("Caroline" in n for n in names))

# Test 8: Erga omnes + barcelona
print("\nTest 8: erga omnes concept")
ents = _concept_case_entities("what is erga omnes in international law")
names = [e["text"] for e in ents]
print(f"  Detected: {names}")
# erga omnes maps through synonym to barcelona traction? No, concept map doesn't have that
# But the synonym in retriever does

# Test 9: Full pipeline integration - does extract_entities find Barcelona Traction?
print("\nTest 9: Full pipeline - belgium shareholders spain")
state = {"raw_input": "case about belgium shareholders in spain", "input_class": "query"}
result = extract_entities(state)
entity_names = [e["text"] for e in result["entities"]["entities"]]
print(f"  All entities: {entity_names}")
test("Barcelona Traction in full pipeline", any("Barcelona" in n for n in entity_names))

# Test 10: Full pipeline - comparison query detection
print("\nTest 10: Comparison query: corfu channel vs lotus")
state = {"raw_input": "compare corfu channel and lotus case", "input_class": "query"}
result = extract_entities(state)
entity_names = [e["text"] for e in result["entities"]["entities"]]
intent = result.get("query_intent", {}).get("primary", [])
print(f"  Entities: {entity_names}")
print(f"  Intent: {intent}")
test("Corfu detected", any("Corfu" in n for n in entity_names))
test("Lotus detected", any("Lotus" in n for n in entity_names))
test("comparison_mode true", result.get("comparison_mode", False))

# Summary
print(f"\n{'='*60}")
print(f"RESULTS: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
