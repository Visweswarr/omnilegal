from src.services.entity_intake import analyze_text


def extract_entities(text: str):
    result = analyze_text(text)
    return [entity.model_dump() for entity in result.entities]


def get_displacy_html(text: str):
    result = analyze_text(text)
    return result.html or "<p>No entity markup available.</p>"
