"""Print the JSON Schema of every event, for TypeScript generation.

The frontend runs this through `npm run gen:types`; don't call it by hand
unless you're debugging the schema.
"""

import json

from pydantic.json_schema import GenerateJsonSchema

from pipeline.events import tenor_event_adapter


class _NoFieldTitles(GenerateJsonSchema):
    """Drop per-field titles; json2ts would turn each into a type alias (Ts1, Type2, ...)."""

    def field_title_should_be_set(self, schema) -> bool:
        return False


def event_schema() -> dict:
    schema = tenor_event_adapter.json_schema(mode="serialization", schema_generator=_NoFieldTitles)
    schema["title"] = "TenorEvent"
    return schema


if __name__ == "__main__":
    print(json.dumps(event_schema(), indent=2))
